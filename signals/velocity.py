from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime
import os

VELOCITY_THRESHOLD = float(os.getenv("VELOCITY_THRESHOLD", "0.15"))
VELOCITY_WINDOW_MINUTES = int(os.getenv("VELOCITY_WINDOW_MINUTES", "5"))


@dataclass
class PricePoint:
    timestamp: datetime
    price: float  # normalized 0.0–1.0
    volume: int


@dataclass
class VelocitySignal:
    contract_slug: str
    velocity: float  # Δp/Δt, decimal probability per minute
    window_minutes: int
    timestamp: datetime
    price: float
    volume_delta: int


def compute_velocity(points: list[PricePoint], window_minutes: int) -> float:
    if len(points) < 2:
        return 0.0
    cutoff_ts = points[-1].timestamp.timestamp() - window_minutes * 60
    window = [p for p in points if p.timestamp.timestamp() >= cutoff_ts]
    if len(window) < 2:
        return 0.0
    dp = window[-1].price - window[0].price
    dt = (window[-1].timestamp - window[0].timestamp).total_seconds() / 60.0
    if dt == 0.0:
        return 0.0
    return dp / dt


def is_volume_spike(
    points: list[PricePoint],
    window_minutes: int,
    multiplier: float = 2.0,
) -> bool:
    if len(points) < 2:
        return False
    latest_ts = points[-1].timestamp.timestamp()
    cutoff_ts = latest_ts - window_minutes * 60
    window = [p for p in points if p.timestamp.timestamp() >= cutoff_ts]
    if len(window) < 2:
        return False

    recent_volume = window[-1].volume - window[0].volume

    baseline_start_ts = cutoff_ts - window_minutes * 60
    baseline = [
        p for p in points
        if baseline_start_ts <= p.timestamp.timestamp() < cutoff_ts
    ]
    if len(baseline) < 2:
        return recent_volume > 0

    baseline_volume = baseline[-1].volume - baseline[0].volume
    if baseline_volume <= 0:
        return recent_volume > 0

    return recent_volume >= multiplier * baseline_volume


class VelocityTracker:
    def __init__(
        self,
        window_minutes: int = VELOCITY_WINDOW_MINUTES,
        threshold: float = VELOCITY_THRESHOLD,
        volume_multiplier: float = 2.0,
        history_minutes: int = 60,
    ) -> None:
        self.window_minutes = window_minutes
        self.threshold = threshold
        self.volume_multiplier = volume_multiplier
        self.history_minutes = history_minutes
        self._history: dict[str, deque[PricePoint]] = defaultdict(deque)

    def get_current_velocity(self, slug: str) -> float | None:
        history = self._history.get(slug)
        if not history or len(history) < 2:
            return None
        return compute_velocity(list(history), self.window_minutes)

    def update(self, slug: str, point: PricePoint) -> VelocitySignal | None:
        history = self._history[slug]
        history.append(point)
        cutoff = point.timestamp.timestamp() - self.history_minutes * 60
        while history and history[0].timestamp.timestamp() < cutoff:
            history.popleft()

        points = list(history)
        velocity = compute_velocity(points, self.window_minutes)

        if abs(velocity) <= self.threshold:
            return None
        if not is_volume_spike(points, self.window_minutes, self.volume_multiplier):
            return None

        volume_delta = points[-1].volume - points[0].volume if len(points) >= 2 else 0
        return VelocitySignal(
            contract_slug=slug,
            velocity=velocity,
            window_minutes=self.window_minutes,
            timestamp=point.timestamp,
            price=point.price,
            volume_delta=volume_delta,
        )
