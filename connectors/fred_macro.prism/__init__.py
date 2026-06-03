import asyncio
import logging
import os
from collections import deque
from datetime import datetime, timezone
from typing import Callable

import httpx

from connectors.base import PrismConnector, PrismMetadata
from signals.velocity import PricePoint, VelocityTracker
from signals.contract_mapper import ContractMapper

logger = logging.getLogger(__name__)

_FRED_API = "https://api.stlouisfed.org/fred/series/observations"
_DEFAULT_POLL_INTERVAL = 3600.0
_ROLLING_WINDOW = 52


class FREDConnector(PrismConnector):
    metadata = PrismMetadata(
        name="FRED Macro Indicators",
        slug="fred_macro",
        version="1.0.0",
        author="arpjw",
        source_type="alternative_data",
        transport="rest",
        description="Polls FRED for macro economic series normalized as pseudo-probability signals.",
        auth_required=True,
        auth_fields=["FRED_API_KEY"],
        contract_slugs=["KXFED", "KXCPI", "KXJOBS"],
        poll_interval_seconds=3600.0,
        capabilities=["velocity"],
    )

    def __init__(self) -> None:
        self._running_task: asyncio.Task | None = None
        self._last_update: datetime | None = None
        self._status = "ok"
        self._message = "not started"
        self._rolling: dict[str, deque[float]] = {}
        self._current_normalized: dict[str, float] = {}

    def _parse_series(self) -> list[str]:
        raw = os.getenv("FRED_SERIES", "")
        return [s.strip() for s in raw.split(",") if s.strip()]

    def _parse_slug_map(self) -> dict[str, str]:
        raw = os.getenv("FRED_SERIES_SLUG_MAP", "")
        result: dict[str, str] = {}
        for pair in raw.split(","):
            pair = pair.strip()
            if ":" in pair:
                series_id, slug = pair.split(":", 1)
                result[series_id.strip()] = slug.strip()
        return result

    def normalize(self, series_id: str, value: float) -> float:
        window = self._rolling.setdefault(series_id, deque(maxlen=_ROLLING_WINDOW))
        window.append(value)
        if len(window) < 2:
            return 1.0
        min_val = min(window)
        max_val = max(window)
        if max_val == min_val:
            return 1.0
        return (value - min_val) / (max_val - min_val)

    async def _fetch_series(
        self, client: httpx.AsyncClient, series_id: str, api_key: str
    ) -> float | None:
        params = {
            "series_id": series_id,
            "api_key": api_key,
            "file_type": "json",
            "limit": "10",
            "sort_order": "desc",
        }
        try:
            resp = await client.get(_FRED_API, params=params, timeout=15.0)
            resp.raise_for_status()
            observations = resp.json().get("observations", [])
            for obs in observations:
                val = obs.get("value", ".")
                if val != ".":
                    return float(val)
            return None
        except Exception as exc:
            logger.warning("FRED fetch failed for %s: %s", series_id, exc)
            return None

    async def _poll_once(
        self,
        series_ids: list[str],
        slug_map: dict[str, str],
        api_key: str,
        tracker: VelocityTracker,
        handle_signal: Callable,
    ) -> None:
        async with httpx.AsyncClient() as client:
            for series_id in series_ids:
                raw_value = await self._fetch_series(client, series_id, api_key)
                if raw_value is None:
                    continue
                normalized = self.normalize(series_id, raw_value)
                self._current_normalized[series_id] = normalized
                slug = slug_map.get(series_id)
                if slug is None:
                    continue
                point = PricePoint(
                    timestamp=datetime.now(tz=timezone.utc),
                    price=normalized,
                    volume=1,
                )
                signal = tracker.update(slug, point)
                if signal is not None:
                    self._last_update = datetime.now(tz=timezone.utc)
                    await handle_signal(signal)

        self._last_update = datetime.now(tz=timezone.utc)

    async def start(
        self,
        tracker: VelocityTracker,
        mapper: ContractMapper,
        handle_signal: Callable,
    ) -> None:
        self._running_task = asyncio.current_task()

        api_key = os.environ["FRED_API_KEY"]
        series_ids = self._parse_series()
        if not series_ids:
            logger.warning("fred_macro: FRED_SERIES not set — connector no-op")
            self._message = "idle — FRED_SERIES not set"
            return

        slug_map = self._parse_slug_map()
        self._message = f"polling {len(series_ids)} series"
        interval = float(
            os.getenv("FRED_POLL_INTERVAL_SECONDS", str(_DEFAULT_POLL_INTERVAL))
        )

        try:
            while True:
                await self._poll_once(series_ids, slug_map, api_key, tracker, handle_signal)
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            self._message = "stopped"
            raise

    async def stop(self) -> None:
        if self._running_task is not None:
            self._running_task.cancel()

    def health_check(self) -> dict:
        return {
            "status": self._status,
            "message": self._message,
            "last_update": self._last_update.isoformat() if self._last_update else None,
            "series_tracked": len(self._rolling),
            "normalized_values": dict(self._current_normalized),
        }
