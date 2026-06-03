import asyncio
import os
from datetime import datetime, timezone
from typing import Callable

from connectors.base import PrismConnector, PrismMetadata
from signals.kalshi_poller import KalshiPoller
from signals.velocity import VelocitySignal, VelocityTracker
from signals.contract_mapper import ContractMapper


class KalshiFedConnector(PrismConnector):
    metadata = PrismMetadata(
        name="Kalshi Fed Markets",
        slug="kalshi_fed",
        version="1.0.0",
        author="arpjw",
        source_type="prediction_market",
        transport="websocket",
        description="Streams KXFED contract prices from Kalshi via WebSocket.",
        auth_required=True,
        auth_fields=["KALSHI_API_KEY", "KALSHI_PRIVATE_KEY_PATH"],
        contract_slugs=["KXFED"],
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
        self._message = "running"

        api_key = os.environ["KALSHI_API_KEY"]
        tickers_env = os.getenv("KALSHI_TICKERS", "")
        tracked = (
            [t.strip() for t in tickers_env.split(",") if t.strip()]
            or mapper.get_all_slugs()
        )
        interval = float(os.getenv("POLL_INTERVAL_SECONDS", "30"))

        poller = KalshiPoller(api_key=api_key, tracked_tickers=tracked, tracker=tracker)

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
