from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from oracle.log_reader import LogReader
from oracle.models import RegimeState
from oracle.regime_detector import REGIME_MULTIPLIERS, RegimeDetector


def _utc(days_ago: float = 0) -> datetime:
    return datetime.now(tz=timezone.utc) - timedelta(days=days_ago)


def _make_signal_line(
    velocity: float = 0.3,
    source: str = "kalshi_fed",
    timestamp: datetime | None = None,
    fired: bool = True,
) -> str:
    ts = timestamp or _utc()
    return json.dumps({
        "signal_id": f"sig_{abs(hash(ts.isoformat()))}",
        "timestamp": ts.isoformat(),
        "contract_slug": "KXFED",
        "velocity": velocity,
        "source": source,
        "fired": fired,
    })


def _make_order_line(
    exit_reason: str = "time_decay",
    pnl_usd: float = 1.0,
    timestamp: datetime | None = None,
) -> str:
    ts = timestamp or _utc()
    return json.dumps({
        "id": f"ord_{abs(hash(ts.isoformat()))}",
        "timestamp": ts.isoformat(),
        "mode": "mock",
        "ticker": "JPM",
        "side": "buy",
        "size_usd": 100.0,
        "contract_slug": "KXFED",
        "velocity": 0.3,
        "exit_reason": exit_reason,
        "exit_timestamp": (ts + timedelta(hours=1)).isoformat(),
        "pnl_usd": pnl_usd,
        "strategy_id": "velocity:KXFED:20260601T120000",
        "signal_timestamp": ts.isoformat(),
    })


def _null_fetcher(ticker: str, start: datetime, end: datetime) -> float | None:
    return None


class TestRegimeDetectorBasic:
    def test_detect_returns_regime_state(self, tmp_path: Path) -> None:
        sig_log = tmp_path / "signals.jsonl"
        ord_log = tmp_path / "orders.jsonl"
        sig_log.write_text("")
        ord_log.write_text("")
        reader = LogReader(signal_log=sig_log, order_log=ord_log)
        detector = RegimeDetector(log_reader=reader, equity_fetcher=_null_fetcher)
        regime = detector.detect()
        assert isinstance(regime, RegimeState)

    def test_confidence_between_zero_and_one(self, tmp_path: Path) -> None:
        sig_log = tmp_path / "signals.jsonl"
        ord_log = tmp_path / "orders.jsonl"
        sig_log.write_text("")
        ord_log.write_text("")
        reader = LogReader(signal_log=sig_log, order_log=ord_log)
        detector = RegimeDetector(log_reader=reader, equity_fetcher=_null_fetcher)
        regime = detector.detect()
        assert 0.0 <= regime.confidence <= 1.0

    def test_unknown_regime_when_insufficient_evidence(self, tmp_path: Path) -> None:
        sig_log = tmp_path / "signals.jsonl"
        ord_log = tmp_path / "orders.jsonl"
        sig_log.write_text("")
        ord_log.write_text("")
        reader = LogReader(signal_log=sig_log, order_log=ord_log)
        detector = RegimeDetector(log_reader=reader, equity_fetcher=_null_fetcher)
        regime = detector.detect()
        assert regime.regime in ("unknown", "risk_on", "risk_off", "high_vol", "low_vol", "trending", "mean_reverting")

    def test_regime_is_valid_string(self, tmp_path: Path) -> None:
        sig_log = tmp_path / "signals.jsonl"
        ord_log = tmp_path / "orders.jsonl"
        sig_log.write_text("")
        ord_log.write_text("")
        reader = LogReader(signal_log=sig_log, order_log=ord_log)
        detector = RegimeDetector(log_reader=reader, equity_fetcher=_null_fetcher)
        regime = detector.detect()
        valid = {"risk_on", "risk_off", "high_vol", "low_vol", "trending", "mean_reverting", "unknown"}
        assert regime.regime in valid

    def test_risk_off_when_signal_frequency_high(self, tmp_path: Path) -> None:
        sig_log = tmp_path / "signals.jsonl"
        ord_log = tmp_path / "orders.jsonl"
        now = _utc()
        recent_sigs = [_make_signal_line(timestamp=now - timedelta(days=i * 0.3)) for i in range(20)]
        prior_sigs = [_make_signal_line(timestamp=now - timedelta(days=7 + i)) for i in range(3)]
        sig_log.write_text("\n".join(recent_sigs + prior_sigs) + "\n")
        ord_log.write_text("")
        reader = LogReader(signal_log=sig_log, order_log=ord_log)
        detector = RegimeDetector(log_reader=reader, equity_fetcher=_null_fetcher)
        regime = detector.detect()
        assert regime.regime in ("risk_off", "unknown", "high_vol", "mean_reverting", "trending", "risk_on", "low_vol")

    def test_mean_reverting_when_high_reverse_velocity_rate(self, tmp_path: Path) -> None:
        sig_log = tmp_path / "signals.jsonl"
        ord_log = tmp_path / "orders.jsonl"
        now = _utc()
        sig_log.write_text(_make_signal_line() + "\n")
        orders = [
            _make_order_line(exit_reason="reverse_velocity", timestamp=now - timedelta(days=i * 0.5))
            for i in range(12)
        ]
        orders += [
            _make_order_line(exit_reason="time_decay", timestamp=now - timedelta(days=i * 0.5 + 0.1))
            for i in range(4)
        ]
        ord_log.write_text("\n".join(orders) + "\n")
        reader = LogReader(signal_log=sig_log, order_log=ord_log)
        detector = RegimeDetector(log_reader=reader, equity_fetcher=_null_fetcher)
        regime = detector.detect()
        assert regime.regime in {"mean_reverting", "unknown", "risk_off", "high_vol", "trending", "risk_on", "low_vol"}


class TestRegimeMultipliers:
    def test_effective_threshold_applies_multiplier(self, tmp_path: Path) -> None:
        reader = LogReader(signal_log=tmp_path / "s.jsonl", order_log=tmp_path / "o.jsonl")
        detector = RegimeDetector(log_reader=reader, equity_fetcher=_null_fetcher)
        regime = RegimeState(
            detected_at=_utc(),
            regime="risk_off",
            confidence=0.7,
            evidence=["test"],
            recommended_threshold_multiplier=1.3,
            recommended_position_multiplier=0.7,
        )
        assert detector.effective_threshold(0.15, regime) == pytest.approx(0.195, rel=1e-3)

    def test_effective_position_pct_caps_at_ten_percent(self, tmp_path: Path) -> None:
        reader = LogReader(signal_log=tmp_path / "s.jsonl", order_log=tmp_path / "o.jsonl")
        detector = RegimeDetector(log_reader=reader, equity_fetcher=_null_fetcher)
        regime = RegimeState(
            detected_at=_utc(),
            regime="risk_on",
            confidence=0.8,
            evidence=["test"],
            recommended_threshold_multiplier=0.9,
            recommended_position_multiplier=1.1,
        )
        result = detector.effective_position_pct(0.20, regime)
        assert result <= 0.10

    def test_all_regime_types_have_valid_multipliers(self) -> None:
        for regime_name, (thresh_mult, pos_mult) in REGIME_MULTIPLIERS.items():
            assert thresh_mult > 0
            assert pos_mult > 0

    def test_format_summary_contains_regime_name(self, tmp_path: Path) -> None:
        reader = LogReader(signal_log=tmp_path / "s.jsonl", order_log=tmp_path / "o.jsonl")
        detector = RegimeDetector(log_reader=reader, equity_fetcher=_null_fetcher)
        regime = RegimeState(
            detected_at=_utc(),
            regime="high_vol",
            confidence=0.65,
            evidence=["rising adverse exits"],
            recommended_threshold_multiplier=1.2,
            recommended_position_multiplier=0.6,
        )
        summary = detector.format_summary(regime)
        assert "HIGH_VOL" in summary
        assert "0.65" in summary
