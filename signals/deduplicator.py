import os
from datetime import datetime, timedelta, timezone

from signals.velocity import VelocitySignal

DEDUP_WINDOW_MINUTES = int(os.getenv("DEDUP_WINDOW_MINUTES", "30"))


class SignalDeduplicator:
    def __init__(self, window_minutes: int = DEDUP_WINDOW_MINUTES) -> None:
        self._window = timedelta(minutes=window_minutes)
        self._last_fired: dict[str, datetime] = {}

    def should_fire(self, signal: VelocitySignal) -> bool:
        last = self._last_fired.get(signal.contract_slug)
        now = datetime.now(tz=timezone.utc)
        if last is not None and (now - last) < self._window:
            return False
        self._last_fired[signal.contract_slug] = signal.timestamp
        return True
