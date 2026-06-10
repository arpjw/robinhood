from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from oracle.models import OrderRecord, SignalRecord

logger = logging.getLogger(__name__)

DEFAULT_THRESHOLDS = [0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50]


@dataclass
class ThresholdResult:
    connector_slug: str
    contract_category: str | None
    tested_thresholds: list[float]
    win_rates: list[float]
    avg_pnls: list[float]
    sharpes: list[float | None]
    trade_counts: list[int]
    current_threshold: float
    optimal_threshold: float
    optimal_sharpe: float | None
    current_sharpe: float | None
    recommendation: str
    computed_at: datetime


def _stdev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(variance)


def _sharpe_from_pnls(pnls: list[float]) -> float | None:
    if not pnls:
        return None
    mean = sum(pnls) / len(pnls)
    std = _stdev(pnls)
    if std == 0:
        return None
    return mean / std * math.sqrt(252)


def _category(contract_slug: str) -> str:
    return contract_slug.split("-")[0] if "-" in contract_slug else contract_slug


class ThresholdTuner:
    def __init__(
        self,
        tested_thresholds: list[float] = DEFAULT_THRESHOLDS,
        min_trades_for_threshold: int = 5,
    ) -> None:
        self._thresholds = tested_thresholds
        self._min_trades = min_trades_for_threshold

    def _current_threshold(self) -> float:
        return float(os.getenv("VELOCITY_THRESHOLD", "0.15"))

    def _compute_result(
        self,
        joined: list[tuple[SignalRecord, OrderRecord | None]],
        connector_slug: str,
        contract_category: str | None,
    ) -> ThresholdResult:
        current = self._current_threshold()
        now = datetime.now(tz=timezone.utc)

        win_rates: list[float] = []
        avg_pnls: list[float] = []
        sharpes: list[float | None] = []
        trade_counts: list[int] = []

        for threshold in self._thresholds:
            eligible = [
                ord_
                for sig, ord_ in joined
                if abs(sig.velocity) >= threshold
                and ord_ is not None
                and ord_.pnl_usd is not None
            ]
            count = len(eligible)
            trade_counts.append(count)

            if count == 0:
                win_rates.append(0.0)
                avg_pnls.append(0.0)
                sharpes.append(None)
                continue

            pnls = [o.pnl_usd for o in eligible]  # type: ignore[misc]
            wins = sum(1 for p in pnls if p > 0)
            win_rates.append(wins / count)
            avg_pnls.append(sum(pnls) / count)

            if count < self._min_trades:
                sharpes.append(None)
            else:
                sharpes.append(_sharpe_from_pnls(pnls))

        valid_sharpes = [
            (i, s) for i, (s, c) in enumerate(zip(sharpes, trade_counts))
            if s is not None and c >= self._min_trades
        ]
        if valid_sharpes:
            best_idx, best_sharpe = max(valid_sharpes, key=lambda x: x[1])
            optimal_threshold = self._thresholds[best_idx]
            optimal_sharpe: float | None = best_sharpe
        else:
            optimal_threshold = current
            optimal_sharpe = None

        current_sharpe: float | None = None
        for i, t in enumerate(self._thresholds):
            if abs(t - current) < 1e-9:
                current_sharpe = sharpes[i]
                break

        return ThresholdResult(
            connector_slug=connector_slug,
            contract_category=contract_category,
            tested_thresholds=list(self._thresholds),
            win_rates=win_rates,
            avg_pnls=avg_pnls,
            sharpes=sharpes,
            trade_counts=trade_counts,
            current_threshold=current,
            optimal_threshold=optimal_threshold,
            optimal_sharpe=optimal_sharpe,
            current_sharpe=current_sharpe,
            recommendation=self.format_recommendation_data(
                contract_category, current, optimal_threshold, optimal_sharpe, current_sharpe,
                valid_sharpes, trade_counts,
            ),
            computed_at=now,
        )

    def tune(
        self,
        joined: list[tuple[SignalRecord, OrderRecord | None]],
        connector_slug: str,
    ) -> list[ThresholdResult]:
        results: list[ThresholdResult] = []
        results.append(self._compute_result(joined, connector_slug, None))

        by_category: dict[str, list[tuple[SignalRecord, OrderRecord | None]]] = {}
        for sig, ord_ in joined:
            cat = _category(sig.contract_slug)
            by_category.setdefault(cat, []).append((sig, ord_))

        for cat, cat_joined in by_category.items():
            results.append(self._compute_result(cat_joined, connector_slug, cat))

        return results

    def format_recommendation_data(
        self,
        contract_category: str | None,
        current: float,
        optimal: float,
        optimal_sharpe: float | None,
        current_sharpe: float | None,
        valid_sharpes: list[tuple[int, float]],
        trade_counts: list[int],
    ) -> str:
        cat = contract_category or "aggregate"
        max_trades = max(trade_counts) if trade_counts else 0

        if not valid_sharpes:
            total = sum(
                c for c, t in zip(trade_counts, self._thresholds)
                if abs(t - current) < 1e-9
            )
            return (
                f"Insufficient data for {cat} ({max_trades} trades). "
                f"Need at least {self._min_trades} trades per threshold."
            )

        if abs(optimal - current) < 1e-9:
            return f"Current threshold {current:.2f} is optimal for {cat} — no improvement found across tested range."

        opt_sharpe_str = f"{optimal_sharpe:.2f}" if optimal_sharpe is not None else "n/a"
        cur_sharpe_str = f"{current_sharpe:.2f}" if current_sharpe is not None else "n/a"
        opt_trades = trade_counts[self._thresholds.index(optimal)] if optimal in self._thresholds else 0

        if optimal > current:
            return (
                f"Raise threshold for {cat} from {current:.2f} to {optimal:.2f} — "
                f"Sharpe improves from {cur_sharpe_str} to {opt_sharpe_str} ({opt_trades} trades)."
            )
        return (
            f"Lower threshold for {cat} from {current:.2f} to {optimal:.2f} — "
            f"Sharpe improves from {cur_sharpe_str} to {opt_sharpe_str} ({opt_trades} trades)."
        )

    def format_recommendation(self, result: ThresholdResult) -> str:
        return result.recommendation
