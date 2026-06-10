from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

import pytest

from oracle.ic_calculator import ICCalculator, ICResult
from oracle.models import OrderRecord, SignalRecord


def _utc(hours_ago: float = 0) -> datetime:
    return datetime.now(tz=timezone.utc) - timedelta(hours=hours_ago)


def _make_signal(
    velocity: float = 0.3,
    contract_slug: str = "KXFED-APR27",
    source: str = "kalshi_fed",
    hours_ago: float = 0,
) -> SignalRecord:
    ts = _utc(hours_ago)
    return SignalRecord(
        signal_id=f"sig_{abs(hash(ts.isoformat()))}",
        timestamp=ts,
        contract_slug=contract_slug,
        velocity=velocity,
        direction="up",
        source=source,
        basket=["JPM"],
        sector="financials",
        macro_factors=["rates"],
        confidence=0.9,
        fired=True,
    )


def _make_order(
    signal: SignalRecord,
    entry_price: float = 100.0,
    exit_price: float = 101.0,
    pnl_usd: float = 1.0,
    side: str = "buy",
) -> OrderRecord:
    return OrderRecord(
        order_id=f"ord_{abs(hash(signal.signal_id))}",
        signal_id=signal.signal_id,
        timestamp=signal.timestamp,
        mode="mock",
        ticker="JPM",
        side=side,
        size_usd=100.0,
        entry_price=entry_price,
        exit_price=exit_price,
        exit_reason="time_decay",
        exit_timestamp=signal.timestamp + timedelta(hours=2),
        pnl_usd=pnl_usd,
        source=signal.source,
        contract_slug=signal.contract_slug,
        velocity=signal.velocity,
    )


def _null_fetcher(ticker: str, start: datetime, end: datetime) -> float | None:
    return None


class TestICResultDataclass:
    def test_ic_result_fields(self) -> None:
        result = ICResult(
            connector_slug="kalshi_fed",
            contract_category=None,
            n_observations=15,
            ic=0.12,
            ic_pvalue=0.03,
            ic_significant=True,
            lookback_hours=2.0,
            computed_at=_utc(),
        )
        assert result.connector_slug == "kalshi_fed"
        assert result.n_observations == 15
        assert result.ic == 0.12
        assert result.ic_significant is True


class TestICCalculatorCompute:
    def test_correct_n_observations(self) -> None:
        calc = ICCalculator(equity_fetcher=_null_fetcher, min_observations=5)
        signals = [_make_signal(velocity=0.1 * (i + 1), hours_ago=float(i)) for i in range(10)]
        joined = [
            (sig, _make_order(sig, exit_price=100.0 + sig.velocity * 10))
            for sig in signals
        ]
        results = calc.compute(joined, "kalshi_fed")
        agg = next(r for r in results if r.contract_category is None)
        assert agg.n_observations == 10

    def test_ic_near_zero_for_random_data(self) -> None:
        random.seed(42)
        calc = ICCalculator(equity_fetcher=_null_fetcher, min_observations=5)
        signals = [_make_signal(velocity=random.uniform(0.1, 0.5), hours_ago=float(i)) for i in range(20)]
        joined = [
            (sig, _make_order(sig, exit_price=100.0 + random.uniform(-2, 2)))
            for sig in signals
        ]
        results = calc.compute(joined, "kalshi_fed")
        agg = next(r for r in results if r.contract_category is None)
        assert abs(agg.ic) < 0.8

    def test_ic_positive_for_correlated_data(self) -> None:
        calc = ICCalculator(equity_fetcher=_null_fetcher, min_observations=5)
        velocities = [0.1 * (i + 1) for i in range(15)]
        signals = [_make_signal(velocity=v, hours_ago=float(i)) for i, v in enumerate(velocities)]
        joined = [
            (sig, _make_order(sig, entry_price=100.0, exit_price=100.0 + sig.velocity * 5))
            for sig in signals
        ]
        results = calc.compute(joined, "kalshi_fed")
        agg = next(r for r in results if r.contract_category is None)
        assert agg.ic > 0

    def test_ic_negative_for_anticorrelated_data(self) -> None:
        calc = ICCalculator(equity_fetcher=_null_fetcher, min_observations=5)
        velocities = [0.1 * (i + 1) for i in range(15)]
        signals = [_make_signal(velocity=v, hours_ago=float(i)) for i, v in enumerate(velocities)]
        joined = [
            (sig, _make_order(sig, entry_price=100.0, exit_price=100.0 - sig.velocity * 5))
            for sig in signals
        ]
        results = calc.compute(joined, "kalshi_fed")
        agg = next(r for r in results if r.contract_category is None)
        assert agg.ic < 0

    def test_ic_not_significant_below_min_obs(self) -> None:
        calc = ICCalculator(equity_fetcher=_null_fetcher, min_observations=10)
        signals = [_make_signal(velocity=0.3, hours_ago=float(i)) for i in range(5)]
        joined = [(sig, _make_order(sig)) for sig in signals]
        results = calc.compute(joined, "kalshi_fed")
        agg = next(r for r in results if r.contract_category is None)
        assert agg.ic_significant is False

    def test_ic_not_significant_when_pvalue_high(self) -> None:
        random.seed(99)
        calc = ICCalculator(equity_fetcher=_null_fetcher, min_observations=5)
        signals = [_make_signal(velocity=random.uniform(0.1, 0.5), hours_ago=float(i)) for i in range(20)]
        joined = [
            (sig, _make_order(sig, exit_price=100.0 + random.uniform(-3, 3)))
            for sig in signals
        ]
        results = calc.compute(joined, "kalshi_fed")
        agg = next(r for r in results if r.contract_category is None)
        if agg.ic_pvalue >= 0.05:
            assert not agg.ic_significant

    def test_aggregate_and_per_category_results(self) -> None:
        calc = ICCalculator(equity_fetcher=_null_fetcher, min_observations=5)
        fed_sigs = [_make_signal(contract_slug="KXFED-APR", velocity=0.1 * (i + 1), hours_ago=float(i)) for i in range(10)]
        cpi_sigs = [_make_signal(contract_slug="KXCPI-MAR", velocity=0.1 * (i + 1), hours_ago=float(i + 20)) for i in range(10)]
        all_sigs = fed_sigs + cpi_sigs
        joined = [(sig, _make_order(sig, exit_price=100.0 + sig.velocity * 3)) for sig in all_sigs]
        results = calc.compute(joined, "kalshi_fed")
        categories = {r.contract_category for r in results}
        assert None in categories
        assert "KXFED" in categories or "KXCPI" in categories

    def test_all_orders_none_returns_zero_observations(self) -> None:
        calc = ICCalculator(equity_fetcher=_null_fetcher, min_observations=5)
        signals = [_make_signal() for _ in range(5)]
        joined = [(sig, None) for sig in signals]
        results = calc.compute(joined, "kalshi_fed")
        agg = next(r for r in results if r.contract_category is None)
        assert agg.n_observations == 0

    def test_equity_fetcher_none_skips_observation(self) -> None:
        calc = ICCalculator(equity_fetcher=_null_fetcher, min_observations=1)
        signals = [_make_signal() for _ in range(3)]
        orders = [_make_order(sig, entry_price=None, exit_price=None) for sig in signals]
        for o in orders:
            o.entry_price = None
            o.exit_price = None
        joined = list(zip(signals, orders))
        results = calc.compute(joined, "kalshi_fed")
        agg = next(r for r in results if r.contract_category is None)
        assert agg.n_observations == 0


class TestComputeRolling:
    def test_rolling_returns_correct_count(self) -> None:
        calc = ICCalculator(equity_fetcher=_null_fetcher, min_observations=5)
        n = 25
        signals = [_make_signal(velocity=0.1 * (i + 1), hours_ago=float(i)) for i in range(n)]
        joined = [(sig, _make_order(sig, exit_price=100.0 + sig.velocity * 2)) for sig in signals]
        rolling = calc.compute_rolling(joined, "kalshi_fed", window_size=10)
        assert len(rolling) == n - 10 + 1

    def test_rolling_returns_timestamps(self) -> None:
        calc = ICCalculator(equity_fetcher=_null_fetcher)
        signals = [_make_signal(hours_ago=float(i)) for i in range(25)]
        joined = [(sig, _make_order(sig)) for sig in signals]
        rolling = calc.compute_rolling(joined, "kalshi_fed", window_size=20)
        assert all(isinstance(ts, datetime) for ts, _ in rolling)


class TestICDecay:
    def test_ic_decay_returns_one_per_bucket(self) -> None:
        fetcher_called: list[tuple] = []

        def fetcher(ticker: str, start: datetime, end: datetime) -> float | None:
            fetcher_called.append((ticker, start))
            return 101.0

        calc = ICCalculator(equity_fetcher=fetcher, min_observations=1)
        signals = [_make_signal(velocity=0.3 * (i + 1), hours_ago=float(i * 5)) for i in range(5)]
        joined = [(sig, _make_order(sig)) for sig in signals]
        result = calc.ic_decay(joined, "kalshi_fed", max_hours=1.0, bucket_minutes=15)
        assert 15 in result
        assert 30 in result
        assert 45 in result
        assert 60 in result
