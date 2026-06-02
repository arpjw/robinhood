import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable

import httpx

from signals.contract_mapper import ContractMapper
from signals.velocity import PricePoint, VelocitySignal, VelocityTracker

POLYMARKET_CLOB_URL = "https://clob.polymarket.com"
SIGNAL_LOG_PATH = Path(os.getenv("SIGNAL_LOG_PATH", "logs/signals.jsonl"))

logger = logging.getLogger(__name__)


def _log_signal(signal: VelocitySignal) -> None:
    SIGNAL_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": signal.timestamp.isoformat(),
        "contract_slug": signal.contract_slug,
        "velocity": signal.velocity,
        "window_minutes": signal.window_minutes,
        "price": signal.price,
        "volume_delta": signal.volume_delta,
        "source": "polymarket",
    }
    with SIGNAL_LOG_PATH.open("a") as f:
        f.write(json.dumps(record) + "\n")


class PolymarketPoller:
    def __init__(
        self,
        condition_ids: list[str],
        tracker: VelocityTracker,
        mapper: ContractMapper,
    ) -> None:
        self._condition_ids = condition_ids
        self._tracker = tracker
        self._mapper = mapper
        self._api_key = os.getenv("POLYMARKET_API_KEY", "")

    async def _fetch_market(
        self, client: httpx.AsyncClient, condition_id: str
    ) -> dict | None:
        url = f"{POLYMARKET_CLOB_URL}/markets/{condition_id}"
        headers = {}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        try:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "polymarket fetch failed for %s: %s — %s",
                condition_id,
                exc,
                exc.response.text[:200],
            )
            return None
        except httpx.HTTPError as exc:
            logger.warning("polymarket fetch failed for %s: %s", condition_id, exc)
            return None

    def _extract_price_volume(self, market: dict) -> tuple[float, int] | None:
        tokens = market.get("tokens") or []
        if not tokens:
            return None
        token = tokens[0]
        price = token.get("price")
        if price is None:
            return None
        volume = int(float(market.get("volume", 0) or 0))
        return float(price), volume

    async def poll_once(
        self,
        on_signal: Callable[[VelocitySignal], Awaitable[None]],
    ) -> None:
        now = datetime.now(tz=timezone.utc)
        async with httpx.AsyncClient(timeout=10.0) as client:
            results = await asyncio.gather(
                *[self._fetch_market(client, cid) for cid in self._condition_ids]
            )

        for condition_id, market in zip(self._condition_ids, results):
            if market is None:
                continue
            extracted = self._extract_price_volume(market)
            if extracted is None:
                continue
            price, volume = extracted
            point = PricePoint(timestamp=now, price=price, volume=volume)
            signal = self._tracker.update(condition_id, point)
            if signal is not None:
                _log_signal(signal)
                await on_signal(signal)

    async def run(
        self,
        interval_seconds: float,
        on_signal: Callable[[VelocitySignal], Awaitable[None]],
    ) -> None:
        while True:
            await self.poll_once(on_signal)
            await asyncio.sleep(interval_seconds)
