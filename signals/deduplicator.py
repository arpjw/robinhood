import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from signals.velocity import VelocitySignal

DEDUP_WINDOW_MINUTES = int(os.getenv("DEDUP_WINDOW_MINUTES", "30"))

logger = logging.getLogger(__name__)


class SignalDeduplicator:
    def __init__(
        self,
        window_minutes: int = DEDUP_WINDOW_MINUTES,
        map_path: str = "data/contract_equity_map.json",
    ) -> None:
        self._window = timedelta(minutes=window_minutes)
        self._last_fired: dict[str, datetime] = {}
        try:
            self._map: dict = json.loads(Path(map_path).read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            self._map = {}

    def _sector_dedup_enabled(self) -> bool:
        return os.getenv("SECTOR_DEDUP_ENABLED", "true").lower() not in ("0", "false", "no")

    def _max_per_sector(self) -> int:
        return int(os.getenv("MAX_CONCURRENT_SIGNALS_PER_SECTOR", "2"))

    def _get_sector(self, contract_slug: str) -> str | None:
        return self._map.get(contract_slug, {}).get("sector")

    def _active_slugs_in_sector(self, sector: str, now: datetime) -> list[str]:
        return [
            slug
            for slug, last_ts in self._last_fired.items()
            if (now - last_ts) < self._window
            and self._map.get(slug, {}).get("sector") == sector
        ]

    def should_fire(self, signal: VelocitySignal) -> bool:
        now = datetime.now(tz=timezone.utc)

        last = self._last_fired.get(signal.contract_slug)
        if last is not None and (now - last) < self._window:
            return False

        if self._sector_dedup_enabled():
            sector = self._get_sector(signal.contract_slug)
            if sector is not None:
                active = self._active_slugs_in_sector(sector, now)
                if len(active) >= self._max_per_sector():
                    logger.warning(
                        "sector dedup: suppressing %s (sector=%s active=%d slugs=%s)",
                        signal.contract_slug,
                        sector,
                        len(active),
                        active,
                    )
                    return False

        self._last_fired[signal.contract_slug] = signal.timestamp
        return True
