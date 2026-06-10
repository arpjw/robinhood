from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable

from oracle.models import OrderRecord, SignalRecord

logger = logging.getLogger(__name__)


@dataclass
class ICResult:
    connector_slug: str
    contract_category: str | None
    n_observations: int
    ic: float
    ic_pvalue: float
    ic_significant: bool
    lookback_hours: float
    computed_at: datetime
    velocity_series: list[float] = field(default_factory=list)
    return_series: list[float] = field(default_factory=list)


def _category(contract_slug: str) -> str:
    parts = contract_slug.split("-")
    return parts[0] if parts else contract_slug


def _compute_spearman(xs: list[float], ys: list[float]) -> tuple[float, float]:
    try:
        from scipy import stats
        result = stats.spearmanr(xs, ys)
        return float(result.statistic), float(result.pvalue)
    except Exception:
        return 0.0, 1.0


def _build_ic_result(
    connector_slug: str,
    contract_category: str | None,
    velocities: list[float],
    returns: list[float],
    lookback_hours: float,
    min_observations: int,
) -> ICResult:
    n = len(velocities)
    now = datetime.now(tz=timezone.utc)
    if n < min_observations:
        return ICResult(
            connector_slug=connector_slug,
            contract_category=contract_category,
            n_observations=n,
            ic=0.0,
            ic_pvalue=1.0,
            ic_significant=False,
            lookback_hours=lookback_hours,
            computed_at=now,
            velocity_series=velocities,
            return_series=returns,
        )
    ic, pvalue = _compute_spearman(velocities, returns)
    significant = pvalue < 0.05 and n >= 10
    return ICResult(
        connector_slug=connector_slug,
        contract_category=contract_category,
        n_observations=n,
        ic=ic,
        ic_pvalue=pvalue,
        ic_significant=significant,
        lookback_hours=lookback_hours,
        computed_at=now,
        velocity_series=velocities,
        return_series=returns,
    )


class ICCalculator:
    def __init__(
        self,
        equity_fetcher: Callable[[str, datetime, datetime], float | None],
        lookback_hours: float = 2.0,
        min_observations: int = 10,
    ) -> None:
        self._equity_fetcher = equity_fetcher
        self._lookback_hours = lookback_hours
        self._min_observations = min_observations

    def _realized_return(
        self,
        signal: SignalRecord,
        order: OrderRecord,
    ) -> float | None:
        if order.entry_price is None or order.exit_price is None:
            return None
        direction_sign = 1.0 if order.side == "buy" else -1.0
        return (order.exit_price - order.entry_price) / order.entry_price * direction_sign

    def compute(
        self,
        joined: list[tuple[SignalRecord, OrderRecord | None]],
        connector_slug: str,
    ) -> list[ICResult]:
        usable = [
            (sig, ord_)
            for sig, ord_ in joined
            if ord_ is not None and ord_.entry_price is not None and ord_.exit_price is not None
        ]

        all_velocities: list[float] = []
        all_returns: list[float] = []
        by_category: dict[str, tuple[list[float], list[float]]] = {}

        for sig, ord_ in usable:
            ret = self._realized_return(sig, ord_)
            if ret is None:
                continue
            all_velocities.append(abs(sig.velocity))
            all_returns.append(ret)
            cat = _category(sig.contract_slug)
            vels, rets = by_category.setdefault(cat, ([], []))
            vels.append(abs(sig.velocity))
            rets.append(ret)

        results: list[ICResult] = []
        results.append(
            _build_ic_result(
                connector_slug, None, all_velocities, all_returns,
                self._lookback_hours, self._min_observations,
            )
        )

        for cat, (vels, rets) in by_category.items():
            if len(vels) >= self._min_observations:
                results.append(
                    _build_ic_result(
                        connector_slug, cat, vels, rets,
                        self._lookback_hours, self._min_observations,
                    )
                )

        return results

    def compute_rolling(
        self,
        joined: list[tuple[SignalRecord, OrderRecord | None]],
        connector_slug: str,
        window_size: int = 20,
    ) -> list[tuple[datetime, float]]:
        usable = [
            (sig, ord_)
            for sig, ord_ in joined
            if ord_ is not None and ord_.entry_price is not None and ord_.exit_price is not None
        ]
        usable.sort(key=lambda p: p[0].timestamp)

        results: list[tuple[datetime, float]] = []
        for i in range(window_size, len(usable) + 1):
            window = usable[i - window_size:i]
            vels = [abs(s.velocity) for s, _ in window]
            rets = [
                self._realized_return(s, o) or 0.0
                for s, o in window
            ]
            ic, _ = _compute_spearman(vels, rets)
            results.append((window[-1][0].timestamp, ic))

        return results

    def ic_decay(
        self,
        joined: list[tuple[SignalRecord, OrderRecord | None]],
        connector_slug: str,
        max_hours: float = 4.0,
        bucket_minutes: int = 15,
    ) -> dict[int, ICResult]:
        usable = [
            (sig, ord_)
            for sig, ord_ in joined
            if ord_ is not None and ord_.entry_price is not None
        ]

        results: dict[int, ICResult] = {}
        max_bucket = int(max_hours * 60)

        for minutes in range(bucket_minutes, max_bucket + 1, bucket_minutes):
            velocities: list[float] = []
            returns: list[float] = []
            lookback = minutes / 60.0

            for sig, ord_ in usable:
                entry_time = ord_.exit_timestamp or (
                    ord_.timestamp + timedelta(minutes=minutes)
                )
                fetch_time = ord_.timestamp + timedelta(minutes=minutes)
                price = self._equity_fetcher(ord_.ticker, fetch_time, fetch_time + timedelta(hours=1))
                if price is None or ord_.entry_price is None:
                    continue
                direction_sign = 1.0 if ord_.side == "buy" else -1.0
                ret = (price - ord_.entry_price) / ord_.entry_price * direction_sign
                velocities.append(abs(sig.velocity))
                returns.append(ret)

            results[minutes] = _build_ic_result(
                connector_slug, None, velocities, returns,
                lookback, self._min_observations,
            )

        return results
