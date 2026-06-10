import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable

from signals.kalshi_poller import KalshiPoller
from signals.polymarket_poller import PolymarketPoller
from signals.velocity import VelocitySignal

logger = logging.getLogger(__name__)

SIGNAL_LOG_PATH = Path(os.getenv("SIGNAL_LOG_PATH", "logs/signals.jsonl"))


class ParallelPoller:
    def __init__(self, kalshi: KalshiPoller, polymarket: PolymarketPoller) -> None:
        self._kalshi = kalshi
        self._polymarket = polymarket

    def _log_poll_timing(
        self,
        kalshi_ms: float | None,
        polymarket_ms: float | None,
        wall_clock_ms: float,
        kalshi_ok: bool,
        polymarket_ok: bool,
    ) -> None:
        SIGNAL_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "type": "poll_timing",
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "kalshi_ms": round(kalshi_ms, 1) if kalshi_ms is not None else None,
            "polymarket_ms": round(polymarket_ms, 1) if polymarket_ms is not None else None,
            "wall_clock_ms": round(wall_clock_ms, 1),
            "concurrent": kalshi_ok and polymarket_ok,
            "kalshi_ok": kalshi_ok,
            "polymarket_ok": polymarket_ok,
        }
        with SIGNAL_LOG_PATH.open("a") as f:
            f.write(json.dumps(record) + "\n")

    async def poll_once(self, on_signal: Callable[[VelocitySignal], Awaitable[None]]) -> None:
        wall_start = time.monotonic()
        kalshi_ms: float | None = None
        polymarket_ms: float | None = None
        kalshi_ok = True
        polymarket_ok = True

        async def _poll_kalshi() -> None:
            nonlocal kalshi_ms, kalshi_ok
            t0 = time.monotonic()
            try:
                await self._kalshi.poll_once(on_signal)
                kalshi_ms = (time.monotonic() - t0) * 1000
            except Exception as exc:
                kalshi_ok = False
                logger.warning("parallel poll kalshi error: %s", exc)

        async def _poll_poly() -> None:
            nonlocal polymarket_ms, polymarket_ok
            t0 = time.monotonic()
            try:
                await self._polymarket.poll_once(on_signal)
                polymarket_ms = (time.monotonic() - t0) * 1000
            except Exception as exc:
                polymarket_ok = False
                logger.warning("parallel poll polymarket error: %s", exc)

        await asyncio.gather(_poll_kalshi(), _poll_poly())
        wall_clock_ms = (time.monotonic() - wall_start) * 1000
        self._log_poll_timing(kalshi_ms, polymarket_ms, wall_clock_ms, kalshi_ok, polymarket_ok)

    async def run(
        self,
        interval_seconds: float,
        on_signal: Callable[[VelocitySignal], Awaitable[None]],
    ) -> None:
        while True:
            await self.poll_once(on_signal)
            await asyncio.sleep(interval_seconds)
