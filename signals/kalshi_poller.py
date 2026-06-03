import asyncio
import base64
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable
from urllib.parse import urlparse

import httpx
from websockets.asyncio.client import connect as ws_connect, ClientConnection
import websockets.exceptions
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey

from signals.velocity import PricePoint, VelocitySignal, VelocityTracker

KALSHI_BASE_URL = os.getenv(
    "KALSHI_BASE_URL", "https://api.elections.kalshi.com/trade-api/v2"
)
KALSHI_WS_URL = os.getenv(
    "KALSHI_WS_URL", "wss://api.elections.kalshi.com/trade-api/v2/ws/v2"
)
SIGNAL_LOG_PATH = Path(os.getenv("SIGNAL_LOG_PATH", "logs/signals.jsonl"))
DEBUG_AUTH = os.getenv("KALSHI_DEBUG_AUTH", "").lower() in ("1", "true", "yes")
_USE_WEBSOCKET = os.getenv("KALSHI_USE_WEBSOCKET", "true").lower() not in ("0", "false", "no")

_WS_MAX_ATTEMPTS = 5
_WS_BACKOFF_INITIAL = 1.0
_WS_BACKOFF_MAX = 60.0

logger = logging.getLogger(__name__)


def _load_private_key(path: str) -> RSAPrivateKey:
    pem = Path(path).read_bytes()
    key = serialization.load_pem_private_key(pem, password=None)
    if not isinstance(key, RSAPrivateKey):
        raise ValueError(f"key at {path!r} is not an RSA private key")
    return key


def _sign_request(
    key_id: str,
    private_key: RSAPrivateKey,
    method: str,
    url: str,
) -> dict[str, str]:
    parsed = urlparse(url)
    path = parsed.path
    if parsed.query:
        path = f"{path}?{parsed.query}"

    timestamp_s = str(int(time.time()))
    msg_string = timestamp_s + method.upper() + path

    if DEBUG_AUTH:
        logger.debug("KALSHI_AUTH_DEBUG timestamp_s=%s", timestamp_s)
        logger.debug("KALSHI_AUTH_DEBUG msg_string=%r", msg_string)

    signature_bytes = private_key.sign(
        msg_string.encode("utf-8"),
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.DIGEST_LENGTH,
        ),
        hashes.SHA256(),
    )
    sig_b64 = base64.b64encode(signature_bytes).decode("utf-8")

    headers = {
        "KALSHI-ACCESS-KEY": key_id,
        "KALSHI-ACCESS-SIGNATURE": sig_b64,
        "KALSHI-ACCESS-TIMESTAMP": timestamp_s,
        "Content-Type": "application/json",
    }

    if DEBUG_AUTH:
        printable = {k: v if k != "KALSHI-ACCESS-SIGNATURE" else v[:16] + "…" for k, v in headers.items()}
        logger.debug("KALSHI_AUTH_DEBUG headers=%s", printable)
        print(f"[KALSHI AUTH DEBUG]\n  timestamp_s  : {timestamp_s}\n  msg_string   : {msg_string!r}\n  headers      : {dict(headers)}", flush=True)

    return headers


def _normalize_price(cents: int) -> float:
    return cents / 100.0


def _log_signal(signal: VelocitySignal) -> None:
    SIGNAL_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": signal.timestamp.isoformat(),
        "contract_slug": signal.contract_slug,
        "velocity": signal.velocity,
        "window_minutes": signal.window_minutes,
        "price": signal.price,
        "volume_delta": signal.volume_delta,
    }
    with SIGNAL_LOG_PATH.open("a") as f:
        f.write(json.dumps(record) + "\n")


class KalshiPoller:
    def __init__(
        self,
        api_key: str,
        tracked_tickers: list[str],
        tracker: VelocityTracker,
        private_key_path: str | None = None,
        use_websocket: bool = _USE_WEBSOCKET,
    ) -> None:
        self._key_id = api_key
        self._tracked = tracked_tickers
        self._tracker = tracker
        self._use_websocket = use_websocket
        private_key_path = private_key_path or os.getenv("KALSHI_PRIVATE_KEY_PATH")
        if not private_key_path:
            raise ValueError(
                "KALSHI_PRIVATE_KEY_PATH must be set — Kalshi v2 requires RSA-PSS signing"
            )
        self._private_key = _load_private_key(private_key_path)

    def _ws_auth_headers(self) -> dict[str, str]:
        auth_url = KALSHI_WS_URL.replace("wss://", "https://")
        return _sign_request(self._key_id, self._private_key, "GET", auth_url)

    async def _send_subscribe(self, ws: ClientConnection) -> None:
        msg = {
            "id": 1,
            "cmd": "subscribe",
            "params": {
                "channels": ["ticker", "orderbook_delta"],
                "market_tickers": self._tracked,
            },
        }
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

        if data.get("type") != "ticker":
            return

        msg = data.get("msg", {})
        market_ticker = msg.get("market_ticker")
        yes_price = msg.get("yes_price")
        volume = msg.get("volume", 0)

        if market_ticker not in self._tracked or yes_price is None:
            return

        now = datetime.now(tz=timezone.utc)
        point = PricePoint(
            timestamp=now,
            price=_normalize_price(int(yes_price)),
            volume=int(volume),
        )
        signal = self._tracker.update(market_ticker, point)
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
                headers = self._ws_auth_headers()
                async with ws_connect(
                    KALSHI_WS_URL,
                    additional_headers=headers,
                ) as ws:
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
                    "WebSocket error (attempt %d/%d): %s",
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

    async def _fetch_market(
        self, client: httpx.AsyncClient, ticker: str
    ) -> dict | None:
        url = f"{KALSHI_BASE_URL}/markets/{ticker}"
        headers = _sign_request(self._key_id, self._private_key, "GET", url)
        try:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            return resp.json().get("market")
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "fetch failed for %s: %s — response: %s",
                ticker,
                exc,
                exc.response.text[:400],
            )
            return None
        except httpx.HTTPError as exc:
            logger.warning("fetch failed for %s: %s", ticker, exc)
            return None

    async def poll_once(
        self,
        on_signal: Callable[[VelocitySignal], Awaitable[None]],
    ) -> None:
        now = datetime.now(tz=timezone.utc)
        async with httpx.AsyncClient(timeout=10.0) as client:
            results = await asyncio.gather(
                *[self._fetch_market(client, t) for t in self._tracked]
            )

        for ticker, market in zip(self._tracked, results):
            if market is None:
                continue
            price_cents = market.get("last_price")
            volume = market.get("volume", 0)
            if price_cents is None:
                continue
            point = PricePoint(
                timestamp=now,
                price=_normalize_price(int(price_cents)),
                volume=int(volume),
            )
            signal = self._tracker.update(ticker, point)
            if signal is not None:
                _log_signal(signal)
                await on_signal(signal)

    async def run(
        self,
        interval_seconds: float,
        on_signal: Callable[[VelocitySignal], Awaitable[None]],
    ) -> None:
        if self._use_websocket:
            ws_ok = await self._run_websocket(on_signal)
            if not ws_ok:
                logger.warning(
                    "WebSocket unavailable after %d attempts; falling back to REST polling",
                    _WS_MAX_ATTEMPTS,
                )
                await self._run_rest(interval_seconds, on_signal)
        else:
            await self._run_rest(interval_seconds, on_signal)
