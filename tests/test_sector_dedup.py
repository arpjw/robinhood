import json
import tempfile
from datetime import datetime, timedelta, timezone

import pytest

from signals.deduplicator import SignalDeduplicator
from signals.velocity import VelocitySignal


_MAP = {
    "KXFED": {"sector": "financials", "macro_factors": ["rates", "credit"]},
    "KXJOBS": {"sector": "financials", "macro_factors": ["credit"]},
    "KXCPI": {"sector": "commodities", "macro_factors": ["inflation"]},
    "KXPCE": {"sector": "commodities", "macro_factors": ["inflation"]},
    "KXGLD": {"sector": "commodities", "macro_factors": ["inflation"]},
    "KXSPY": {"sector": "broad_market", "macro_factors": ["risk_off"]},
    "KXOIL": {"sector": "energy", "macro_factors": ["energy"]},
}


def _map_path() -> str:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(_MAP, f)
        return f.name


def make_signal(slug: str, ts: datetime | None = None) -> VelocitySignal:
    return VelocitySignal(
        contract_slug=slug,
        velocity=0.25,
        window_minutes=5,
        timestamp=ts or datetime.now(tz=timezone.utc),
        price=0.6,
        volume_delta=100,
    )


@pytest.fixture
def dedup():
    return SignalDeduplicator(window_minutes=30, map_path=_map_path())


class TestSlugDedup:
    def test_first_signal_fires(self, dedup):
        assert dedup.should_fire(make_signal("KXFED")) is True

    def test_duplicate_within_window_suppressed(self, dedup):
        dedup.should_fire(make_signal("KXFED"))
        assert dedup.should_fire(make_signal("KXFED")) is False

    def test_different_slug_not_suppressed(self, dedup):
        dedup.should_fire(make_signal("KXFED"))
        assert dedup.should_fire(make_signal("KXSPY")) is True

    def test_signal_after_window_fires_again(self, dedup):
        old_ts = datetime.now(tz=timezone.utc) - timedelta(minutes=31)
        dedup._last_fired["KXFED"] = old_ts
        assert dedup.should_fire(make_signal("KXFED")) is True


class TestSectorDedup:
    def test_sector_cap_enforced(self, dedup, monkeypatch):
        monkeypatch.setenv("MAX_CONCURRENT_SIGNALS_PER_SECTOR", "2")
        monkeypatch.setenv("SECTOR_DEDUP_ENABLED", "true")
        assert dedup.should_fire(make_signal("KXCPI")) is True
        assert dedup.should_fire(make_signal("KXPCE")) is True
        assert dedup.should_fire(make_signal("KXGLD")) is False

    def test_different_sectors_not_suppressed(self, dedup, monkeypatch):
        monkeypatch.setenv("MAX_CONCURRENT_SIGNALS_PER_SECTOR", "1")
        monkeypatch.setenv("SECTOR_DEDUP_ENABLED", "true")
        assert dedup.should_fire(make_signal("KXFED")) is True
        assert dedup.should_fire(make_signal("KXCPI")) is True
        assert dedup.should_fire(make_signal("KXOIL")) is True

    def test_sector_dedup_disabled_passthrough(self, dedup, monkeypatch):
        monkeypatch.setenv("MAX_CONCURRENT_SIGNALS_PER_SECTOR", "1")
        monkeypatch.setenv("SECTOR_DEDUP_ENABLED", "false")
        dedup.should_fire(make_signal("KXCPI"))
        assert dedup.should_fire(make_signal("KXPCE")) is True

    def test_slug_dedup_runs_independently_of_sector(self, dedup, monkeypatch):
        monkeypatch.setenv("SECTOR_DEDUP_ENABLED", "true")
        dedup.should_fire(make_signal("KXFED"))
        assert dedup.should_fire(make_signal("KXFED")) is False

    def test_expired_sector_slots_open_up(self, dedup, monkeypatch):
        monkeypatch.setenv("MAX_CONCURRENT_SIGNALS_PER_SECTOR", "1")
        monkeypatch.setenv("SECTOR_DEDUP_ENABLED", "true")
        old_ts = datetime.now(tz=timezone.utc) - timedelta(minutes=31)
        dedup._last_fired["KXCPI"] = old_ts
        assert dedup.should_fire(make_signal("KXPCE")) is True

    def test_unknown_sector_slug_not_suppressed(self, dedup, monkeypatch):
        monkeypatch.setenv("MAX_CONCURRENT_SIGNALS_PER_SECTOR", "1")
        monkeypatch.setenv("SECTOR_DEDUP_ENABLED", "true")
        sig = make_signal("UNKNOWN_SLUG")
        assert dedup.should_fire(sig) is True

    def test_configurable_max_per_sector(self, dedup, monkeypatch):
        monkeypatch.setenv("MAX_CONCURRENT_SIGNALS_PER_SECTOR", "3")
        monkeypatch.setenv("SECTOR_DEDUP_ENABLED", "true")
        assert dedup.should_fire(make_signal("KXCPI")) is True
        assert dedup.should_fire(make_signal("KXPCE")) is True
        assert dedup.should_fire(make_signal("KXGLD")) is True

    def test_sector_dedup_logs_suppressed_slug(self, dedup, monkeypatch, caplog):
        monkeypatch.setenv("MAX_CONCURRENT_SIGNALS_PER_SECTOR", "1")
        monkeypatch.setenv("SECTOR_DEDUP_ENABLED", "true")
        dedup.should_fire(make_signal("KXCPI"))
        import logging
        with caplog.at_level(logging.WARNING, logger="signals.deduplicator"):
            dedup.should_fire(make_signal("KXPCE"))
        assert "KXPCE" in caplog.text

    def test_financials_sector_cap(self, dedup, monkeypatch):
        monkeypatch.setenv("MAX_CONCURRENT_SIGNALS_PER_SECTOR", "1")
        monkeypatch.setenv("SECTOR_DEDUP_ENABLED", "true")
        assert dedup.should_fire(make_signal("KXFED")) is True
        assert dedup.should_fire(make_signal("KXJOBS")) is False

    def test_slug_dedup_checked_before_sector_dedup(self, dedup, monkeypatch):
        monkeypatch.setenv("MAX_CONCURRENT_SIGNALS_PER_SECTOR", "5")
        monkeypatch.setenv("SECTOR_DEDUP_ENABLED", "true")
        dedup.should_fire(make_signal("KXFED"))
        assert dedup.should_fire(make_signal("KXFED")) is False
