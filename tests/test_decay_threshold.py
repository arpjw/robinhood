from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from oracle.decay_analyzer import DecayAnalyzer, DecayCurve
from oracle.models import OrderRecord, SignalRecord
from oracle.threshold_tuner import ThresholdTuner


def _utc(hours_ago: float = 0) -> datetime:
    return datetime.now(tz=timezone.utc) - timedelta(hours=hours_ago)


def _make_signal(
    velocity: float = 0.3,
    contract_slug: str = "KXFED-APR",
    hours_ago: float = 0,
    source: str = "kalshi_fed",
) -> SignalRecord:
    ts = _utc(hours_ago)
    return SignalRecord(
        signal_id=f"sig_{abs(hash(ts.isoformat() + str(velocity)))}",
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
    pnl_usd: float | None = 1.0,
) -> OrderRecord:
    return OrderRecord(
        order_id=f"ord_{abs(hash(signal.signal_id))}",
        signal_id=signal.signal_id,
        timestamp=signal.timestamp,
        mode="mock",
        ticker="JPM",
        side="buy",
        size_usd=100.0,
        entry_price=entry_price,
        exit_price=(entry_price * 1.01) if (pnl_usd or 0) > 0 else (entry_price * 0.99),
        exit_reason="time_decay",
        exit_timestamp=signal.timestamp + timedelta(hours=2),
        pnl_usd=pnl_usd,
        source=signal.source,
        contract_slug=signal.contract_slug,
        velocity=signal.velocity,
    )


class TestDecayAnalyzer:
    def _null_fetcher(self, ticker: str, start: datetime, end: datetime) -> float | None:
        return None

    def _constant_fetcher(self, ticker: str, start: datetime, end: datetime) -> float | None:
        return 101.0

    def test_returns_curves_for_each_category(self) -> None:
        analyzer = DecayAnalyzer(equity_fetcher=self._constant_fetcher, bucket_minutes=15, max_minutes=60)
        fed_sigs = [_make_signal(contract_slug="KXFED-APR", hours_ago=float(i)) for i in range(5)]
        cpi_sigs = [_make_signal(contract_slug="KXCPI-MAR", hours_ago=float(i + 10)) for i in range(5)]
        all_sigs = fed_sigs + cpi_sigs
        joined = [(sig, _make_order(sig)) for sig in all_sigs]
        curves = analyzer.analyze(joined, "kalshi_fed")
        categories = {c.contract_category for c in curves}
        assert None in categories

    def test_curve_has_correct_bucket_count(self) -> None:
        analyzer = DecayAnalyzer(equity_fetcher=self._constant_fetcher, bucket_minutes=15, max_minutes=60)
        signals = [_make_signal(hours_ago=float(i)) for i in range(5)]
        joined = [(sig, _make_order(sig)) for sig in signals]
        curves = analyzer.analyze(joined, "kalshi_fed")
        agg = next(c for c in curves if c.contract_category is None)
        assert len(agg.points) == 60 // 15

    def test_optimal_exit_within_range(self) -> None:
        analyzer = DecayAnalyzer(equity_fetcher=self._constant_fetcher, bucket_minutes=15, max_minutes=120)
        signals = [_make_signal(hours_ago=float(i)) for i in range(8)]
        joined = [(sig, _make_order(sig)) for sig in signals]
        curves = analyzer.analyze(joined, "kalshi_fed")
        agg = next(c for c in curves if c.contract_category is None)
        assert 15 <= agg.optimal_exit_minutes <= 120

    def test_recommendation_is_non_empty(self) -> None:
        analyzer = DecayAnalyzer(equity_fetcher=self._constant_fetcher, bucket_minutes=15, max_minutes=60)
        signals = [_make_signal(hours_ago=float(i)) for i in range(5)]
        joined = [(sig, _make_order(sig)) for sig in signals]
        curves = analyzer.analyze(joined, "kalshi_fed")
        agg = next(c for c in curves if c.contract_category is None)
        assert agg.recommendation is not None and len(agg.recommendation) > 0

    def test_format_recommendation_reduce(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EXIT_HOURS", "4.0")
        analyzer = DecayAnalyzer(equity_fetcher=self._constant_fetcher, bucket_minutes=15, max_minutes=240)
        signals = [_make_signal(hours_ago=float(i)) for i in range(10)]
        joined = [(sig, _make_order(sig)) for sig in signals]
        curves = analyzer.analyze(joined, "kalshi_fed")
        agg = next(c for c in curves if c.contract_category is None)
        agg.optimal_exit_minutes = 30
        agg.current_exit_minutes = 240
        rec = analyzer.format_recommendation(agg)
        assert "30m" in rec

    def test_format_recommendation_extend(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EXIT_HOURS", "0.5")
        analyzer = DecayAnalyzer(equity_fetcher=self._constant_fetcher, bucket_minutes=15, max_minutes=240)
        signals = [_make_signal(hours_ago=float(i)) for i in range(5)]
        joined = [(sig, _make_order(sig)) for sig in signals]
        curves = analyzer.analyze(joined, "kalshi_fed")
        agg = next(c for c in curves if c.contract_category is None)
        agg.optimal_exit_minutes = 120
        agg.current_exit_minutes = 30
        rec = analyzer.format_recommendation(agg)
        assert "120m" in rec

    def test_empty_joined_returns_no_curves(self) -> None:
        analyzer = DecayAnalyzer(equity_fetcher=self._null_fetcher)
        curves = analyzer.analyze([], "kalshi_fed")
        assert curves == []


class TestThresholdTuner:
    def test_returns_result_for_aggregate(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VELOCITY_THRESHOLD", "0.15")
        tuner = ThresholdTuner(min_trades_for_threshold=2)
        signals = [_make_signal(velocity=0.1 * (i + 1), hours_ago=float(i)) for i in range(10)]
        joined = [(sig, _make_order(sig)) for sig in signals]
        results = tuner.tune(joined, "kalshi_fed")
        assert any(r.contract_category is None for r in results)

    def test_tested_thresholds_matches_constructor(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VELOCITY_THRESHOLD", "0.15")
        custom = [0.10, 0.20, 0.30]
        tuner = ThresholdTuner(tested_thresholds=custom, min_trades_for_threshold=1)
        signals = [_make_signal(velocity=0.25, hours_ago=float(i)) for i in range(5)]
        joined = [(sig, _make_order(sig)) for sig in signals]
        results = tuner.tune(joined, "kalshi_fed")
        agg = next(r for r in results if r.contract_category is None)
        assert agg.tested_thresholds == custom

    def test_optimal_threshold_in_tested_list(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VELOCITY_THRESHOLD", "0.15")
        tuner = ThresholdTuner(min_trades_for_threshold=2)
        signals = [_make_signal(velocity=0.3 * (i + 1) / 10, hours_ago=float(i)) for i in range(15)]
        joined = [(sig, _make_order(sig, pnl_usd=1.0 if sig.velocity > 0.2 else -0.5)) for sig in signals]
        results = tuner.tune(joined, "kalshi_fed")
        agg = next(r for r in results if r.contract_category is None)
        assert agg.optimal_threshold in tuner._thresholds

    def test_insufficient_data_recommendation(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VELOCITY_THRESHOLD", "0.15")
        tuner = ThresholdTuner(min_trades_for_threshold=10)
        signals = [_make_signal(velocity=0.2) for _ in range(3)]
        joined = [(sig, _make_order(sig)) for sig in signals]
        results = tuner.tune(joined, "kalshi_fed")
        agg = next(r for r in results if r.contract_category is None)
        assert agg.optimal_threshold == agg.current_threshold

    def test_trade_counts_decrease_monotonically(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VELOCITY_THRESHOLD", "0.10")
        tuner = ThresholdTuner(min_trades_for_threshold=1)
        velocities = [0.05, 0.12, 0.18, 0.22, 0.32, 0.45, 0.55]
        signals = [_make_signal(velocity=v, hours_ago=float(i)) for i, v in enumerate(velocities)]
        joined = [(sig, _make_order(sig)) for sig in signals]
        results = tuner.tune(joined, "kalshi_fed")
        agg = next(r for r in results if r.contract_category is None)
        counts = agg.trade_counts
        for i in range(1, len(counts)):
            assert counts[i] <= counts[i - 1]

    def test_sharpe_none_when_below_min_trades(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VELOCITY_THRESHOLD", "0.15")
        tuner = ThresholdTuner(min_trades_for_threshold=10)
        signals = [_make_signal(velocity=0.3) for _ in range(3)]
        joined = [(sig, _make_order(sig)) for sig in signals]
        results = tuner.tune(joined, "kalshi_fed")
        agg = next(r for r in results if r.contract_category is None)
        assert all(s is None for s in agg.sharpes)

    def test_current_threshold_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VELOCITY_THRESHOLD", "0.25")
        tuner = ThresholdTuner(min_trades_for_threshold=1)
        signals = [_make_signal(velocity=0.3, hours_ago=float(i)) for i in range(5)]
        joined = [(sig, _make_order(sig)) for sig in signals]
        results = tuner.tune(joined, "kalshi_fed")
        agg = next(r for r in results if r.contract_category is None)
        assert agg.current_threshold == 0.25

    def test_raise_recommendation_contains_both_thresholds(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VELOCITY_THRESHOLD", "0.10")
        tuner = ThresholdTuner(tested_thresholds=[0.10, 0.25, 0.40], min_trades_for_threshold=1)
        pnls = {0.10: -1.0, 0.25: 2.0, 0.40: 3.0}
        signals = [
            _make_signal(velocity=v, hours_ago=float(i))
            for i, v in enumerate([0.10, 0.10, 0.26, 0.26, 0.41, 0.41, 0.41])
        ]
        joined = [(sig, _make_order(sig, pnl_usd=2.0 if sig.velocity > 0.20 else -1.0)) for sig in signals]
        results = tuner.tune(joined, "kalshi_fed")
        agg = next(r for r in results if r.contract_category is None)
        if "Raise" in agg.recommendation:
            assert "0.10" in agg.recommendation

    def test_insufficient_data_mentions_trade_count(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VELOCITY_THRESHOLD", "0.15")
        tuner = ThresholdTuner(min_trades_for_threshold=20)
        signals = [_make_signal(velocity=0.2) for _ in range(2)]
        joined = [(sig, _make_order(sig)) for sig in signals]
        results = tuner.tune(joined, "kalshi_fed")
        agg = next(r for r in results if r.contract_category is None)
        assert "trades" in agg.recommendation.lower() or "Insufficient" in agg.recommendation
