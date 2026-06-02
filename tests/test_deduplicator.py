from datetime import datetime, timedelta, timezone

import pytest

from signals.deduplicator import SignalDeduplicator
from signals.velocity import VelocitySignal


def make_signal(slug: str = "KXFED", ts: datetime | None = None) -> VelocitySignal:
    return VelocitySignal(
        contract_slug=slug,
        velocity=0.25,
        window_minutes=5,
        timestamp=ts or datetime.now(tz=timezone.utc),
        price=0.6,
        volume_delta=100,
    )


def test_first_signal_fires() -> None:
    dedup = SignalDeduplicator(window_minutes=30)
    assert dedup.should_fire(make_signal("KXFED")) is True


def test_duplicate_within_window_suppressed() -> None:
    dedup = SignalDeduplicator(window_minutes=30)
    dedup.should_fire(make_signal("KXFED"))
    assert dedup.should_fire(make_signal("KXFED")) is False


def test_different_slug_not_suppressed() -> None:
    dedup = SignalDeduplicator(window_minutes=30)
    dedup.should_fire(make_signal("KXFED"))
    assert dedup.should_fire(make_signal("KXCPI")) is True


def test_signal_after_window_fires_again() -> None:
    dedup = SignalDeduplicator(window_minutes=30)
    old_ts = datetime.now(tz=timezone.utc) - timedelta(minutes=31)
    dedup._last_fired["KXFED"] = old_ts
    assert dedup.should_fire(make_signal("KXFED")) is True


def test_records_timestamp_on_fire() -> None:
    dedup = SignalDeduplicator(window_minutes=30)
    sig = make_signal("KXFED")
    dedup.should_fire(sig)
    assert "KXFED" in dedup._last_fired
    assert dedup._last_fired["KXFED"] == sig.timestamp
