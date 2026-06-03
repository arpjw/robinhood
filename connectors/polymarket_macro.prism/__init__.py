import asyncio
import os
from datetime import datetime, timezone
from typing import Callable

from connectors.base import PrismConnector, PrismMetadata
from signals.polymarket_poller import PolymarketPoller
from signals.velocity import VelocitySignal, VelocityTracker
from signals.contract_mapper import ContractMapper


class PolymarketMacroConnector(PrismConnector):
    metadata = PrismMetadata(
        name="Polymarket Macro",
        slug="polymarket_macro",
        version="1.0.0",
        author="arpjw",
        source_type="prediction_market",
        transport="websocket",
        description="Streams macro prediction market prices from Polymarket's CLOB via WebSocket.",
        auth_required=False,
        auth_fields=[],
        contract_slugs=["KXFED", "KXCPI", "KXJOBS"],
        poll_interval_seconds=None,
        capabilities=["velocity", "volume"],
    )

    def __init__(self) -> None:
        self._running_task: asyncio.Task | None = None
        self._last_update: datetime | None = None
        self._status = "ok"
        self._message = "not started"

    async def start(
        self,
        tracker: VelocityTracker,
        mapper: ContractMapper,
        handle_signal: Callable,
    ) -> None:
        self._running_task = asyncio.current_task()

        polymarket_env = os.getenv("POLYMARKET_CONDITION_IDS", "")
        condition_ids = [x.strip() for x in polymarket_env.split(",") if x.strip()]

        if not condition_ids:
            self._message = "idle — POLYMARKET_CONDITION_IDS not set"
            return

        self._message = "running"
        interval = float(os.getenv("POLL_INTERVAL_SECONDS", "30"))
        poller = PolymarketPoller(
            condition_ids=condition_ids, tracker=tracker, mapper=mapper
        )

        async def _on_signal(sig: VelocitySignal) -> None:
            self._last_update = datetime.now(tz=timezone.utc)
            await handle_signal(sig)

        try:
            await poller.run(interval_seconds=interval, on_signal=_on_signal)
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
