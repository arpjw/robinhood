from datetime import datetime, timedelta, timezone

import pytest

from signals.velocity import (
    PricePoint,
    VelocityTracker,
    compute_velocity,
    is_volume_spike,
)


def make_point(minutes_ago: float, price: float, volume: int) -> PricePoint:
    ts = datetime.now(tz=timezone.utc) - timedelta(minutes=minutes_ago)
    return PricePoint(timestamp=ts, price=price, volume=volume)


class TestComputeVelocity:
    def test_returns_zero_with_single_point(self) -> None:
        points = [make_point(0, 0.5, 100)]
        assert compute_velocity(points, 5) == 0.0

    def test_positive_velocity(self) -> None:
        points = [make_point(4, 0.5, 100), make_point(0, 0.7, 200)]
        assert compute_velocity(points, 5) > 0

    def test_negative_velocity(self) -> None:
        points = [make_point(4, 0.7, 100), make_point(0, 0.5, 200)]
        assert compute_velocity(points, 5) < 0

    def test_excludes_points_outside_window(self) -> None:
        points = [
            make_point(20, 0.2, 0),
            make_point(4, 0.5, 100),
            make_point(0, 0.6, 200),
        ]
        v = compute_velocity(points, 5)
        assert abs(v - (0.1 / 4.0)) < 1e-9

    def test_zero_dt_returns_zero(self) -> None:
        ts = datetime.now(tz=timezone.utc)
        points = [
            PricePoint(timestamp=ts, price=0.5, volume=100),
            PricePoint(timestamp=ts, price=0.6, volume=200),
        ]
        assert compute_velocity(points, 5) == 0.0

    def test_sub_30s_dt_returns_zero(self) -> None:
        ts = datetime.now(tz=timezone.utc)
        points = [
            PricePoint(timestamp=ts, price=0.1, volume=100),
            PricePoint(timestamp=ts + timedelta(seconds=10), price=0.9, volume=200),
        ]
        assert compute_velocity(points, 5) == 0.0

    def test_exactly_30s_dt_computes_velocity(self) -> None:
        ts = datetime.now(tz=timezone.utc)
        points = [
            PricePoint(timestamp=ts, price=0.5, volume=100),
            PricePoint(timestamp=ts + timedelta(seconds=30), price=0.7, volume=200),
        ]
        v = compute_velocity(points, 5)
        assert v == pytest.approx(0.2 / 0.5)

    def test_returns_zero_when_all_points_outside_window(self) -> None:
        points = [make_point(30, 0.5, 100), make_point(25, 0.7, 200)]
        assert compute_velocity(points, 5) == 0.0


class TestIsVolumeSpike:
    def test_false_with_single_point(self) -> None:
        assert is_volume_spike([make_point(0, 0.5, 100)], 5) is False

    def test_true_when_no_baseline(self) -> None:
        points = [make_point(4, 0.5, 100), make_point(0, 0.5, 200)]
        assert is_volume_spike(points, 5) is True

    def test_false_when_no_volume_change_and_no_baseline(self) -> None:
        points = [make_point(4, 0.5, 100), make_point(0, 0.5, 100)]
        assert is_volume_spike(points, 5) is False

    def test_true_when_recent_exceeds_baseline_multiplier(self) -> None:
        points = [
            make_point(9, 0.5, 0),
            make_point(6, 0.5, 50),
            make_point(4, 0.5, 50),
            make_point(0, 0.5, 250),
        ]
        assert is_volume_spike(points, 5, multiplier=2.0) is True

    def test_false_when_recent_below_baseline_multiplier(self) -> None:
        points = [
            make_point(9, 0.5, 0),
            make_point(6, 0.5, 200),
            make_point(4, 0.5, 200),
            make_point(0, 0.5, 250),
        ]
        assert is_volume_spike(points, 5, multiplier=2.0) is False


class TestVelocityTracker:
    def test_no_signal_below_threshold(self) -> None:
        tracker = VelocityTracker(window_minutes=5, threshold=0.15, volume_multiplier=1.0)
        tracker.update("X", make_point(4, 0.50, 0))
        signal = tracker.update("X", make_point(0, 0.51, 1000))
        assert signal is None

    def test_no_signal_at_exactly_threshold(self) -> None:
        tracker = VelocityTracker(window_minutes=4, threshold=0.025, volume_multiplier=0.0)
        tracker.update("X", make_point(4, 0.5, 0))
        signal = tracker.update("X", make_point(0, 0.6, 1000))
        assert signal is None

    def test_signal_fires_above_threshold(self) -> None:
        tracker = VelocityTracker(window_minutes=5, threshold=0.01, volume_multiplier=0.0)
        tracker.update("X", make_point(4, 0.5, 0))
        signal = tracker.update("X", make_point(0, 0.8, 1000))
        assert signal is not None
        assert signal.contract_slug == "X"
        assert signal.velocity > 0
        assert signal.price == pytest.approx(0.8)

    def test_signal_negative_velocity(self) -> None:
        tracker = VelocityTracker(window_minutes=5, threshold=0.01, volume_multiplier=0.0)
        tracker.update("X", make_point(4, 0.8, 0))
        signal = tracker.update("X", make_point(0, 0.5, 1000))
        assert signal is not None
        assert signal.velocity < 0

    def test_no_signal_without_volume_spike(self) -> None:
        tracker = VelocityTracker(window_minutes=5, threshold=0.01, volume_multiplier=2.0)
        tracker.update("X", make_point(9, 0.5, 0))
        tracker.update("X", make_point(6, 0.5, 200))
        tracker.update("X", make_point(4, 0.5, 200))
        signal = tracker.update("X", make_point(0, 0.9, 220))
        assert signal is None

    def test_signal_fires_with_volume_spike(self) -> None:
        tracker = VelocityTracker(window_minutes=5, threshold=0.01, volume_multiplier=2.0)
        tracker.update("X", make_point(9, 0.5, 0))
        tracker.update("X", make_point(6, 0.5, 50))
        tracker.update("X", make_point(4, 0.5, 50))
        signal = tracker.update("X", make_point(0, 0.9, 350))
        assert signal is not None

    def test_prunes_old_history(self) -> None:
        tracker = VelocityTracker(
            window_minutes=5, threshold=0.01, volume_multiplier=0.0, history_minutes=10
        )
        tracker.update("X", make_point(70, 0.5, 0))
        tracker.update("X", make_point(4, 0.5, 100))
        signal = tracker.update("X", make_point(0, 0.8, 1000))
        assert signal is not None

    def test_independent_slugs(self) -> None:
        tracker = VelocityTracker(window_minutes=5, threshold=0.01, volume_multiplier=0.0)
        tracker.update("A", make_point(4, 0.5, 0))
        tracker.update("B", make_point(4, 0.5, 0))
        sig_a = tracker.update("A", make_point(0, 0.9, 1000))
        sig_b = tracker.update("B", make_point(0, 0.5, 1000))
        assert sig_a is not None
        assert sig_b is None
