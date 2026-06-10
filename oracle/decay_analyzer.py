from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable

from oracle.models import OrderRecord, SignalRecord

logger = logging.getLogger(__name__)


@dataclass
class DecayPoint:
    minutes: int
    avg_pnl_usd: float
    avg_return_pct: float
    n_observations: int
    std_pnl_usd: float
    sharpe_at_exit: float | None


@dataclass
class DecayCurve:
    connector_slug: str
    contract_category: str | None
    computed_at: datetime
    points: list[DecayPoint]
    optimal_exit_minutes: int
    current_exit_minutes: int
    recommendation: str | None


def _stdev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(variance)


def _annualized_sharpe(avg_return: float, std_return: float, hold_minutes: int) -> float | None:
    if std_return == 0 or hold_minutes <= 0:
        return None
    periods_per_year = 252 * 6.5 * 60 / hold_minutes
    return (avg_return / std_return) * math.sqrt(periods_per_year)


def _category(contract_slug: str) -> str:
    return contract_slug.split("-")[0] if "-" in contract_slug else contract_slug


class DecayAnalyzer:
    def __init__(
        self,
        equity_fetcher: Callable[[str, datetime, datetime], float | None],
        bucket_minutes: int = 15,
        max_minutes: int = 240,
    ) -> None:
        self._equity_fetcher = equity_fetcher
        self._bucket_minutes = bucket_minutes
        self._max_minutes = max_minutes

    def _current_exit_minutes(self) -> int:
        exit_hours = float(os.getenv("EXIT_HOURS", "2.0"))
        return int(exit_hours * 60)

    def _compute_curve(
        self,
        trades: list[tuple[SignalRecord, OrderRecord]],
        connector_slug: str,
        contract_category: str | None,
    ) -> DecayCurve:
        points: list[DecayPoint] = []
        buckets = range(self._bucket_minutes, self._max_minutes + 1, self._bucket_minutes)

        for minutes in buckets:
            pnls: list[float] = []
            returns: list[float] = []

            for sig, ord_ in trades:
                if ord_.entry_price is None:
                    continue
                fetch_time = ord_.timestamp + timedelta(minutes=minutes)
                price = self._equity_fetcher(
                    ord_.ticker, fetch_time, fetch_time + timedelta(hours=1)
                )
                if price is None:
                    continue
                direction_sign = 1.0 if ord_.side == "buy" else -1.0
                ret = (price - ord_.entry_price) / ord_.entry_price * direction_sign
                size_shares = ord_.size_usd / ord_.entry_price if ord_.entry_price > 0 else 0
                pnl = ret * ord_.entry_price * size_shares
                pnls.append(pnl)
                returns.append(ret)

            if not pnls:
                points.append(DecayPoint(
                    minutes=minutes,
                    avg_pnl_usd=0.0,
                    avg_return_pct=0.0,
                    n_observations=0,
                    std_pnl_usd=0.0,
                    sharpe_at_exit=None,
                ))
                continue

            avg_pnl = sum(pnls) / len(pnls)
            avg_ret = sum(returns) / len(returns)
            std_pnl = _stdev(pnls)
            std_ret = _stdev(returns)
            sharpe = _annualized_sharpe(avg_ret, std_ret, minutes)

            points.append(DecayPoint(
                minutes=minutes,
                avg_pnl_usd=avg_pnl,
                avg_return_pct=avg_ret * 100,
                n_observations=len(pnls),
                std_pnl_usd=std_pnl,
                sharpe_at_exit=sharpe,
            ))

        best_point = max(
            (p for p in points if p.sharpe_at_exit is not None),
            key=lambda p: p.sharpe_at_exit,  # type: ignore[arg-type]
            default=points[0] if points else None,
        )
        optimal = best_point.minutes if best_point else self._bucket_minutes
        current = self._current_exit_minutes()

        return DecayCurve(
            connector_slug=connector_slug,
            contract_category=contract_category,
            computed_at=datetime.now(tz=timezone.utc),
            points=points,
            optimal_exit_minutes=optimal,
            current_exit_minutes=current,
            recommendation=self._make_recommendation(optimal, current, points),
        )

    def _make_recommendation(
        self,
        optimal: int,
        current: int,
        points: list[DecayPoint],
    ) -> str | None:
        sharpe_at_optimal = next(
            (p.sharpe_at_exit for p in points if p.minutes == optimal), None
        )
        sharpe_at_current = next(
            (p.sharpe_at_exit for p in points if p.minutes == current), None
        )
        if abs(optimal - current) <= self._bucket_minutes:
            diff = abs((sharpe_at_optimal or 0) - (sharpe_at_current or 0))
            return f"current is optimal (Sharpe difference: {diff:.2f})"
        if optimal < current:
            return f"reduce to {optimal}m"
        return f"extend to {optimal}m"

    def analyze(
        self,
        joined: list[tuple[SignalRecord, OrderRecord | None]],
        connector_slug: str,
    ) -> list[DecayCurve]:
        trades = [(sig, ord_) for sig, ord_ in joined if ord_ is not None]
        if not trades:
            return []

        curves: list[DecayCurve] = []
        curves.append(self._compute_curve(trades, connector_slug, None))

        by_category: dict[str, list[tuple[SignalRecord, OrderRecord]]] = {}
        for sig, ord_ in trades:
            cat = _category(sig.contract_slug)
            by_category.setdefault(cat, []).append((sig, ord_))

        for cat, cat_trades in by_category.items():
            curves.append(self._compute_curve(cat_trades, connector_slug, cat))

        return curves

    def format_recommendation(self, curve: DecayCurve) -> str:
        cat_str = curve.contract_category or "all"
        sharpe_at_optimal = next(
            (p.sharpe_at_exit for p in curve.points if p.minutes == curve.optimal_exit_minutes),
            None,
        )
        sharpe_at_current = next(
            (p.sharpe_at_exit for p in curve.points if p.minutes == curve.current_exit_minutes),
            None,
        )

        if abs(curve.optimal_exit_minutes - curve.current_exit_minutes) <= self._bucket_minutes:
            diff = abs((sharpe_at_optimal or 0.0) - (sharpe_at_current or 0.0))
            return (
                f"Current {curve.current_exit_minutes}m exit is near-optimal for {cat_str} signals "
                f"(optimal: {curve.optimal_exit_minutes}m, Sharpe difference: {diff:.2f})."
            )

        sharpe_opt_str = f"{sharpe_at_optimal:.2f}" if sharpe_at_optimal is not None else "n/a"
        sharpe_cur_str = f"{sharpe_at_current:.2f}" if sharpe_at_current is not None else "n/a"

        if curve.optimal_exit_minutes < curve.current_exit_minutes:
            return (
                f"Optimal exit for {cat_str} signals is {curve.optimal_exit_minutes}m "
                f"(current: {curve.current_exit_minutes}m). "
                f"Sharpe at {curve.optimal_exit_minutes}m: {sharpe_opt_str} vs "
                f"{sharpe_cur_str} at {curve.current_exit_minutes}m."
            )
        return (
            f"Extend exit window for {cat_str} signals from {curve.current_exit_minutes}m "
            f"to {curve.optimal_exit_minutes}m. "
            f"Sharpe at {curve.optimal_exit_minutes}m: {sharpe_opt_str} vs "
            f"{sharpe_cur_str} at {curve.current_exit_minutes}m."
        )
