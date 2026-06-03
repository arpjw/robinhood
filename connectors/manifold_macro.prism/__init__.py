import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Callable

import httpx

from connectors.base import PrismConnector, PrismMetadata
from signals.velocity import PricePoint, VelocityTracker
from signals.contract_mapper import ContractMapper

logger = logging.getLogger(__name__)

_MANIFOLD_API = "https://api.manifold.markets/v0"
_DEFAULT_POLL_INTERVAL = 120.0


class ManifoldConnector(PrismConnector):
    metadata = PrismMetadata(
        name="Manifold Markets Macro",
        slug="manifold_macro",
        version="1.0.0",
        author="arpjw",
        source_type="prediction_market",
        transport="rest",
        description="Polls Manifold Markets for binary market probabilities on macro questions.",
        auth_required=False,
        auth_fields=[],
        contract_slugs=["KXFED", "KXCPI", "KXJOBS", "KXBTC"],
        poll_interval_seconds=120.0,
        capabilities=["velocity", "volume"],
    )

    def __init__(self) -> None:
        self._running_task: asyncio.Task | None = None
        self._last_update: datetime | None = None
        self._status = "ok"
        self._message = "not started"

    def _parse_market_ids(self) -> list[str]:
        raw = os.getenv("MANIFOLD_MARKET_IDS", "")
        return [m.strip() for m in raw.split(",") if m.strip()]

    def _parse_slug_map(self) -> dict[str, str]:
        raw = os.getenv("MANIFOLD_SLUG_MAP", "")
        result: dict[str, str] = {}
        for pair in raw.split(","):
            pair = pair.strip()
            if ":" in pair:
                market_slug, contract_slug = pair.split(":", 1)
                result[market_slug.strip()] = contract_slug.strip()
        return result

    async def _fetch_market(
        self, client: httpx.AsyncClient, market_slug: str
    ) -> dict | None:
        url = f"{_MANIFOLD_API}/market/{market_slug}"
        try:
            resp = await client.get(url, timeout=10.0)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            logger.warning("manifold fetch failed for %s: %s", market_slug, exc)
            return None

    async def _poll_once(
        self,
        market_ids: list[str],
        slug_map: dict[str, str],
        tracker: VelocityTracker,
        handle_signal: Callable,
    ) -> None:
        async with httpx.AsyncClient() as client:
            for market_slug in market_ids:
                data = await self._fetch_market(client, market_slug)
                if data is None:
                    continue
                prob = data.get("probability")
                if prob is None:
                    continue
                contract_slug = slug_map.get(market_slug)
                if contract_slug is None:
                    continue
                volume = int(float(data.get("volume", 0) or 0))
                point = PricePoint(
                    timestamp=datetime.now(tz=timezone.utc),
                    price=float(prob),
                    volume=volume,
                )
                signal = tracker.update(contract_slug, point)
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

        market_ids = self._parse_market_ids()
        if not market_ids:
            logger.warning(
                "manifold_macro: MANIFOLD_MARKET_IDS not set — connector no-op"
            )
            self._message = "idle — MANIFOLD_MARKET_IDS not set"
            return

        slug_map = self._parse_slug_map()
        self._message = f"polling {len(market_ids)} market(s)"
        interval = float(
            os.getenv("MANIFOLD_POLL_INTERVAL_SECONDS", str(_DEFAULT_POLL_INTERVAL))
        )

        try:
            while True:
                await self._poll_once(market_ids, slug_map, tracker, handle_signal)
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
        }
