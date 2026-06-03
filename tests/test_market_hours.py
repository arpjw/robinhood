from datetime import datetime, timedelta, timezone

import pytz
import pytest

from signals.market_hours import MarketHoursGuard

ET = pytz.timezone("America/New_York")


def et(year, month, day, hour, minute=0) -> datetime:
    return ET.localize(datetime(year, month, day, hour, minute))


def utc(year, month, day, hour, minute=0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


@pytest.fixture
def guard():
    return MarketHoursGuard()


class TestIsOpen:
    def test_open_during_market_hours(self, guard):
        tuesday_open = et(2025, 6, 3, 10, 0)
        assert guard.is_open(tuesday_open) is True

    def test_closed_before_open(self, guard):
        tuesday_early = et(2025, 6, 3, 9, 0)
        assert guard.is_open(tuesday_early) is False

    def test_closed_after_close(self, guard):
        tuesday_late = et(2025, 6, 3, 16, 30)
        assert guard.is_open(tuesday_late) is False

    def test_closed_on_saturday(self, guard):
        saturday = et(2025, 6, 7, 11, 0)
        assert guard.is_open(saturday) is False

    def test_closed_on_sunday(self, guard):
        sunday = et(2025, 6, 8, 11, 0)
        assert guard.is_open(sunday) is False

    def test_closed_on_holiday_july4(self, guard):
        july4_2025 = et(2025, 7, 4, 12, 0)
        assert guard.is_open(july4_2025) is False

    def test_open_at_exact_930(self, guard):
        tuesday_930 = et(2025, 6, 3, 9, 30)
        assert guard.is_open(tuesday_930) is True

    def test_closed_at_exact_1600(self, guard):
        tuesday_1600 = et(2025, 6, 3, 16, 0)
        assert guard.is_open(tuesday_1600) is False


class TestMinutesToOpen:
    def test_returns_none_when_open(self, guard):
        tuesday_open = et(2025, 6, 3, 10, 0)
        assert guard.minutes_to_open(tuesday_open) is None

    def test_returns_minutes_when_closed(self, guard):
        tuesday_morning = et(2025, 6, 3, 8, 0)
        mins = guard.minutes_to_open(tuesday_morning)
        assert mins is not None
        assert pytest.approx(mins, abs=1.0) == 90.0

    def test_overnight_gap_to_next_day(self, guard):
        monday_evening = et(2025, 6, 2, 20, 0)
        mins = guard.minutes_to_open(monday_evening)
        assert mins is not None
        assert mins > 0

    def test_weekend_skips_to_monday(self, guard):
        friday_evening = et(2025, 5, 30, 18, 0)
        mins = guard.minutes_to_open(friday_evening)
        assert mins is not None
        assert mins > 60 * 12


class TestEdgeDecayFactor:
    def test_no_decay_when_open(self, guard, monkeypatch):
        monkeypatch.setenv("EDGE_HALF_LIFE_HOURS", "1.0")
        tuesday_open = et(2025, 6, 3, 10, 0)
        assert guard.edge_decay_factor(tuesday_open) == pytest.approx(1.0)

    def test_half_decay_30min_before_open(self, guard, monkeypatch):
        monkeypatch.setenv("EDGE_HALF_LIFE_HOURS", "1.0")
        thirty_min_before = et(2025, 6, 3, 9, 0)
        factor = guard.edge_decay_factor(thirty_min_before)
        assert factor == pytest.approx(0.5, abs=0.01)

    def test_zero_decay_far_before_open(self, guard, monkeypatch):
        monkeypatch.setenv("EDGE_HALF_LIFE_HOURS", "1.0")
        six_hours_before = et(2025, 6, 3, 3, 30)
        factor = guard.edge_decay_factor(six_hours_before)
        assert factor == pytest.approx(0.0)

    def test_decay_clamped_to_zero(self, guard, monkeypatch):
        monkeypatch.setenv("EDGE_HALF_LIFE_HOURS", "1.0")
        previous_day = et(2025, 6, 2, 18, 0)
        factor = guard.edge_decay_factor(previous_day)
        assert factor == 0.0

    def test_configurable_half_life(self, guard, monkeypatch):
        monkeypatch.setenv("EDGE_HALF_LIFE_HOURS", "2.0")
        one_hour_before = et(2025, 6, 3, 8, 30)
        factor = guard.edge_decay_factor(one_hour_before)
        assert factor == pytest.approx(0.5, abs=0.01)
