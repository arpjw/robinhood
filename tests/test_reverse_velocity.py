import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from execution.exit_manager import ExitManager, TrackedPosition
from signals.velocity import PricePoint, VelocityTracker


def make_tracker_with_velocity(slug: str, velocity: float) -> VelocityTracker:
    tracker = VelocityTracker(window_minutes=5, threshold=0.0, history_minutes=60)
    now = datetime.now(tz=timezone.utc)
    # Points 1 min apart — within the 5-min window; dp = velocity * 1 min
    tracker.update(slug, PricePoint(timestamp=now - timedelta(minutes=1), price=0.5, volume=100))
    tracker.update(slug, PricePoint(timestamp=now, price=0.5 + velocity, volume=200))
    return tracker


def make_pos(
    slug: str = "KXFED",
    entry_velocity: float = 0.25,
    side: str = "buy",
    entry_hours_ago: float = 0.5,
) -> TrackedPosition:
    return TrackedPosition(
        order_id="ord-1",
        ticker="JPM",
        side=side,
        size=100.0,
        entry_time=datetime.now(tz=timezone.utc) - timedelta(hours=entry_hours_ago),
        strategy_id="s1",
        direction="up",
        contract_slug=slug,
        entry_velocity=entry_velocity,
        exit_hours=2.0,
        exit_adverse_pct=0.03,
        entry_price=100.0,
    )


def make_manager(tracker=None, exposure_manager=None) -> tuple[ExitManager, MagicMock]:
    client = MagicMock()
    mgr = ExitManager(
        client=client,
        price_fetcher=lambda tickers: {t: 100.0 for t in tickers},
        check_interval_seconds=9999,
        velocity_tracker=tracker,
        exposure_manager=exposure_manager,
    )
    return mgr, client


class TestReverseVelocityDetection:
    @pytest.mark.asyncio
    async def test_reverse_velocity_triggers_exit(self, monkeypatch):
        monkeypatch.setenv("REVERSE_VELOCITY_THRESHOLD", "0.20")
        monkeypatch.setenv("REVERSE_VELOCITY_ENABLED", "true")
        tracker = make_tracker_with_velocity("KXFED", -0.25)
        mgr, client = make_manager(tracker=tracker)
        mgr.register(make_pos(entry_velocity=0.25))
        await mgr._check_exits()
        assert mgr.open_count() == 0
        client.submit_order.assert_called_once()

    @pytest.mark.asyncio
    async def test_below_threshold_no_exit(self, monkeypatch):
        monkeypatch.setenv("REVERSE_VELOCITY_THRESHOLD", "0.20")
        monkeypatch.setenv("REVERSE_VELOCITY_ENABLED", "true")
        tracker = make_tracker_with_velocity("KXFED", -0.10)
        mgr, client = make_manager(tracker=tracker)
        mgr.register(make_pos(entry_velocity=0.25))
        await mgr._check_exits()
        assert mgr.open_count() == 1
        client.submit_order.assert_not_called()

    @pytest.mark.asyncio
    async def test_same_direction_velocity_no_exit(self, monkeypatch):
        monkeypatch.setenv("REVERSE_VELOCITY_THRESHOLD", "0.20")
        monkeypatch.setenv("REVERSE_VELOCITY_ENABLED", "true")
        tracker = make_tracker_with_velocity("KXFED", 0.30)
        mgr, client = make_manager(tracker=tracker)
        mgr.register(make_pos(entry_velocity=0.25))
        await mgr._check_exits()
        assert mgr.open_count() == 1
        client.submit_order.assert_not_called()

    @pytest.mark.asyncio
    async def test_disabled_feature_passthrough(self, monkeypatch):
        monkeypatch.setenv("REVERSE_VELOCITY_THRESHOLD", "0.20")
        monkeypatch.setenv("REVERSE_VELOCITY_ENABLED", "false")
        tracker = make_tracker_with_velocity("KXFED", -0.50)
        mgr, client = make_manager(tracker=tracker)
        mgr.register(make_pos(entry_velocity=0.25))
        await mgr._check_exits()
        assert mgr.open_count() == 1

    @pytest.mark.asyncio
    async def test_no_tracker_no_reverse_exit(self, monkeypatch):
        monkeypatch.setenv("REVERSE_VELOCITY_ENABLED", "true")
        mgr, client = make_manager(tracker=None)
        mgr.register(make_pos(entry_velocity=0.25))
        await mgr._check_exits()
        assert mgr.open_count() == 1

    @pytest.mark.asyncio
    async def test_exit_reason_is_reverse_velocity(self, monkeypatch):
        monkeypatch.setenv("REVERSE_VELOCITY_THRESHOLD", "0.20")
        monkeypatch.setenv("REVERSE_VELOCITY_ENABLED", "true")
        tracker = make_tracker_with_velocity("KXFED", -0.30)
        mgr, client = make_manager(tracker=tracker)
        mgr.register(make_pos(entry_velocity=0.25))
        await mgr._check_exits()
        assert mgr.open_count() == 0

    @pytest.mark.asyncio
    async def test_reverse_velocity_calls_exposure_close(self, monkeypatch):
        monkeypatch.setenv("REVERSE_VELOCITY_THRESHOLD", "0.20")
        monkeypatch.setenv("REVERSE_VELOCITY_ENABLED", "true")
        tracker = make_tracker_with_velocity("KXFED", -0.30)
        exposure = MagicMock()
        mgr, client = make_manager(tracker=tracker, exposure_manager=exposure)
        mgr.register(make_pos(entry_velocity=0.25))
        await mgr._check_exits()
        exposure.register_close.assert_called_once_with("KXFED", "JPM")

    @pytest.mark.asyncio
    async def test_insufficient_history_no_exit(self, monkeypatch):
        monkeypatch.setenv("REVERSE_VELOCITY_THRESHOLD", "0.20")
        monkeypatch.setenv("REVERSE_VELOCITY_ENABLED", "true")
        tracker = VelocityTracker()
        mgr, client = make_manager(tracker=tracker)
        mgr.register(make_pos(entry_velocity=0.25))
        await mgr._check_exits()
        assert mgr.open_count() == 1
