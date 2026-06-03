import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable

import httpx
import websockets.exceptions
from websockets.asyncio.client import connect as ws_connect

from signals.contract_mapper import ContractMapper
from signals.velocity import PricePoint, VelocitySignal, VelocityTracker

POLYMARKET_CLOB_URL = "https://clob.polymarket.com"
POLYMARKET_WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
SIGNAL_LOG_PATH = Path(os.getenv("SIGNAL_LOG_PATH", "logs/signals.jsonl"))

_USE_WEBSOCKET = os.getenv("POLYMARKET_USE_WEBSOCKET", "true").lower() not in ("0", "false", "no")
_WS_MAX_ATTEMPTS = 5
_WS_BACKOFF_INITIAL = 1.0
_WS_BACKOFF_MAX = 16.0

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
        use_websocket: bool = _USE_WEBSOCKET,
    ) -> None:
        self._condition_ids = condition_ids
        self._tracker = tracker
        self._mapper = mapper
        self._api_key = os.getenv("POLYMARKET_API_KEY", "")
        self._use_websocket = use_websocket

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

    async def _send_subscribe(self, ws) -> None:
        msg = {"type": "subscribe", "markets": self._condition_ids}
        await ws.send(json.dumps(msg))

    async def _handle_ws_message(
        self,
        raw: str,
        on_signal: Callable[[VelocitySignal], Awaitable[None]],
    ) -> None:
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return

        items = data if isinstance(data, list) else [data]
        for item in items:
            if not isinstance(item, dict):
                continue
            if item.get("event_type") != "price_change":
                continue
            market = item.get("market")
            price = item.get("price")
            if market is None or price is None:
                continue
            if market not in self._condition_ids:
                continue
            now = datetime.now(tz=timezone.utc)
            point = PricePoint(timestamp=now, price=float(price), volume=0)
            signal = self._tracker.update(market, point)
            if signal is not None:
                _log_signal(signal)
                await on_signal(signal)

    async def _run_websocket(
        self,
        on_signal: Callable[[VelocitySignal], Awaitable[None]],
    ) -> bool:
        attempts = 0
        backoff = _WS_BACKOFF_INITIAL

        while attempts < _WS_MAX_ATTEMPTS:
            try:
                async with ws_connect(POLYMARKET_WS_URL) as ws:
                    await self._send_subscribe(ws)
                    attempts = 0
                    backoff = _WS_BACKOFF_INITIAL
                    async for raw in ws:
                        await self._handle_ws_message(raw, on_signal)
            except (
                websockets.exceptions.WebSocketException,
                websockets.exceptions.ConnectionClosed,
                OSError,
            ) as exc:
                attempts += 1
                logger.warning(
                    "Polymarket WebSocket error (attempt %d/%d): %s",
                    attempts,
                    _WS_MAX_ATTEMPTS,
                    exc,
                )
                if attempts >= _WS_MAX_ATTEMPTS:
                    break
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, _WS_BACKOFF_MAX)

        return False

    async def _run_rest(
        self,
        interval_seconds: float,
        on_signal: Callable[[VelocitySignal], Awaitable[None]],
    ) -> None:
        while True:
            await self.poll_once(on_signal)
            await asyncio.sleep(interval_seconds)

    async def run(
        self,
        interval_seconds: float,
        on_signal: Callable[[VelocitySignal], Awaitable[None]],
    ) -> None:
        if self._use_websocket:
            ws_ok = await self._run_websocket(on_signal)
            if not ws_ok:
                logger.warning(
                    "Polymarket WebSocket unavailable after %d attempts; falling back to REST polling",
                    _WS_MAX_ATTEMPTS,
                )
                await self._run_rest(interval_seconds, on_signal)
        else:
            await self._run_rest(interval_seconds, on_signal)
