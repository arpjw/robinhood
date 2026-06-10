import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import anthropic

from signals.velocity import VelocitySignal

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are a signal gatekeeper for a prediction market velocity trading engine.\n"
    "You receive a borderline signal (velocity between threshold and fast-path cutoff).\n"
    "Your job: decide if this signal is genuine or noise. Be skeptical of signals near threshold.\n"
    'Respond with JSON only: {"approved": bool, "confidence": float (0-1), "reason": str (one sentence)}.'
)


class SignalGatekeeper:
    def __init__(self) -> None:
        self._enabled = os.getenv("GATEKEEPER_ENABLED", "true").lower() not in ("0", "false", "no")
        self._threshold = float(os.getenv("VELOCITY_THRESHOLD", "0.15"))
        self._fast_path_multiplier = float(os.getenv("GATEKEEPER_FAST_PATH_MULTIPLIER", "2.0"))
        self._log_path = Path(os.getenv("GATEKEEPER_LOG_PATH", "logs/gatekeeper.jsonl"))
        self._client: anthropic.AsyncAnthropic | None = None

    def _get_client(self) -> anthropic.AsyncAnthropic:
        if self._client is None:
            self._client = anthropic.AsyncAnthropic()
        return self._client

    def _is_fast_path(self, velocity: float) -> bool:
        return abs(velocity) >= self._threshold * self._fast_path_multiplier

    def _build_user_message(
        self,
        signal: VelocitySignal,
        source: str,
        basket: dict | None,
        dedup_window_minutes: int,
    ) -> str:
        return json.dumps({
            "contract_id": signal.contract_slug,
            "source": source,
            "velocity": round(signal.velocity, 5),
            "threshold": self._threshold,
            "velocity_window_minutes": signal.window_minutes,
            "dedup_window_minutes": dedup_window_minutes,
            "equity_basket": basket.get("basket", []) if basket else [],
        })

    def _write_log(
        self,
        signal: VelocitySignal,
        source: str,
        approved: bool,
        confidence: float,
        reason: str,
        latency_ms: float,
        path: str,
    ) -> None:
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "contract_id": signal.contract_slug,
            "source": source,
            "velocity": signal.velocity,
            "approved": approved,
            "confidence": confidence,
            "reason": reason,
            "latency_ms": round(latency_ms, 1),
            "path": path,
        }
        with self._log_path.open("a") as f:
            f.write(json.dumps(record) + "\n")

    async def _call_llm(
        self,
        signal: VelocitySignal,
        source: str,
        basket: dict | None,
        dedup_window_minutes: int,
    ) -> tuple[bool, float, str]:
        try:
            response = await self._get_client().messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1024,
                thinking={"type": "adaptive"},
                system=_SYSTEM_PROMPT,
                messages=[{
                    "role": "user",
                    "content": self._build_user_message(signal, source, basket, dedup_window_minutes),
                }],
            )
            text = next(
                (b.text for b in response.content if b.type == "text"), ""
            ).strip()
            parsed = json.loads(text)
            return bool(parsed["approved"]), float(parsed["confidence"]), str(parsed["reason"])
        except Exception as exc:
            logger.warning(
                "gatekeeper LLM call failed for slug=%s: %s — defaulting to approved",
                signal.contract_slug,
                exc,
            )
            return True, 1.0, "LLM infrastructure error — defaulted to approved"

    async def evaluate(
        self,
        signal: VelocitySignal,
        source: str = "unknown",
        basket: dict | None = None,
        dedup_window_minutes: int = 30,
    ) -> VelocitySignal | None:
        if not self._enabled:
            return signal

        start = time.monotonic()

        if self._is_fast_path(signal.velocity):
            latency_ms = (time.monotonic() - start) * 1000
            self._write_log(signal, source, True, 1.0, "fast path — above threshold multiplier", latency_ms, "fast")
            return signal

        approved, confidence, reason = await self._call_llm(signal, source, basket, dedup_window_minutes)
        latency_ms = (time.monotonic() - start) * 1000
        self._write_log(signal, source, approved, confidence, reason, latency_ms, "gated")

        if not approved:
            logger.info(
                "gatekeeper suppressed slug=%s velocity=%.4f reason=%s",
                signal.contract_slug,
                signal.velocity,
                reason,
            )
            return None

        try:
            signal.gatekeeper_confidence = confidence  # type: ignore[attr-defined]
        except (AttributeError, TypeError):
            pass

        return signal
