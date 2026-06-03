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

_METACULUS_API = "https://www.metaculus.com/api2/questions"
_DEFAULT_POLL_INTERVAL = 300.0


class MetaculusConnector(PrismConnector):
    metadata = PrismMetadata(
        name="Metaculus Macro Questions",
        slug="metaculus_macro",
        version="1.0.0",
        author="arpjw",
        source_type="prediction_market",
        transport="rest",
        description="Polls Metaculus for expert-aggregated probability on macro questions.",
        auth_required=False,
        auth_fields=[],
        contract_slugs=["KXFED", "KXCPI", "KXJOBS"],
        poll_interval_seconds=300.0,
        capabilities=["velocity"],
    )

    def __init__(self) -> None:
        self._running_task: asyncio.Task | None = None
        self._last_update: datetime | None = None
        self._status = "ok"
        self._message = "not started"
        self._questions_tracked: int = 0

    def _parse_question_ids(self) -> list[str]:
        raw = os.getenv("METACULUS_QUESTION_IDS", "")
        return [q.strip() for q in raw.split(",") if q.strip()]

    def _parse_slug_map(self) -> dict[str, str]:
        raw = os.getenv("METACULUS_SLUG_MAP", "")
        result: dict[str, str] = {}
        for pair in raw.split(","):
            pair = pair.strip()
            if ":" in pair:
                qid, slug = pair.split(":", 1)
                result[qid.strip()] = slug.strip()
        return result

    async def _fetch_question(
        self, client: httpx.AsyncClient, question_id: str
    ) -> dict | None:
        url = f"{_METACULUS_API}/{question_id}/"
        try:
            resp = await client.get(url, timeout=10.0)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            logger.warning("metaculus fetch failed for %s: %s", question_id, exc)
            return None

    def _extract_probability(self, data: dict) -> float | None:
        cp = data.get("community_prediction") or {}
        full = cp.get("full") or {}
        q2 = full.get("q2")
        if q2 is not None:
            return float(q2)
        return None

    async def _poll_once(
        self,
        question_ids: list[str],
        slug_map: dict[str, str],
        tracker: VelocityTracker,
        handle_signal: Callable,
    ) -> None:
        async with httpx.AsyncClient() as client:
            for qid in question_ids:
                data = await self._fetch_question(client, qid)
                if data is None:
                    continue
                prob = self._extract_probability(data)
                if prob is None:
                    continue
                slug = slug_map.get(qid)
                if slug is None:
                    continue
                num_predictions = data.get("nr_forecasters", 1)
                point = PricePoint(
                    timestamp=datetime.now(tz=timezone.utc),
                    price=prob,
                    volume=int(num_predictions),
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

        question_ids = self._parse_question_ids()
        if not question_ids:
            logger.warning(
                "metaculus_macro: METACULUS_QUESTION_IDS not set — connector no-op"
            )
            self._message = "idle — METACULUS_QUESTION_IDS not set"
            return

        slug_map = self._parse_slug_map()
        self._questions_tracked = len(question_ids)
        self._message = f"polling {self._questions_tracked} question(s)"
        interval = float(
            os.getenv("METACULUS_POLL_INTERVAL_SECONDS", str(_DEFAULT_POLL_INTERVAL))
        )

        try:
            while True:
                await self._poll_once(question_ids, slug_map, tracker, handle_signal)
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
            "questions_tracked": self._questions_tracked,
        }
