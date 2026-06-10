import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from signals.gatekeeper import SignalGatekeeper
from signals.velocity import VelocitySignal


def make_signal(velocity: float = 0.20) -> VelocitySignal:
    return VelocitySignal(
        contract_slug="KXFED",
        velocity=velocity,
        window_minutes=5,
        timestamp=datetime.now(tz=timezone.utc),
        price=0.55,
        volume_delta=500,
    )


def make_gatekeeper(tmp_path: Path, enabled: bool = True, threshold: float = 0.15, multiplier: float = 2.0) -> SignalGatekeeper:
    gk = SignalGatekeeper()
    gk._enabled = enabled
    gk._threshold = threshold
    gk._fast_path_multiplier = multiplier
    gk._log_path = tmp_path / "gatekeeper.jsonl"
    return gk


class TestFastPath:
    async def test_fast_path_bypasses_llm(self, tmp_path: Path) -> None:
        gk = make_gatekeeper(tmp_path)
        signal = make_signal(velocity=0.35)  # 0.35 >= 0.15 * 2.0 = 0.30

        llm_called = False

        async def fake_call_llm(*args, **kwargs):
            nonlocal llm_called
            llm_called = True
            return True, 1.0, "should not be called"

        gk._call_llm = fake_call_llm
        result = await gk.evaluate(signal, source="kalshi")

        assert result is signal
        assert not llm_called

    async def test_fast_path_logs_path_fast(self, tmp_path: Path) -> None:
        gk = make_gatekeeper(tmp_path)
        signal = make_signal(velocity=0.35)
        await gk.evaluate(signal, source="kalshi")

        log_lines = gk._log_path.read_text().splitlines()
        assert len(log_lines) == 1
        record = json.loads(log_lines[0])
        assert record["path"] == "fast"
        assert record["approved"] is True
        assert record["confidence"] == 1.0

    async def test_negative_fast_path_bypasses_llm(self, tmp_path: Path) -> None:
        gk = make_gatekeeper(tmp_path)
        signal = make_signal(velocity=-0.35)

        llm_called = False

        async def fake_call_llm(*args, **kwargs):
            nonlocal llm_called
            llm_called = True
            return True, 1.0, "should not be called"

        gk._call_llm = fake_call_llm
        result = await gk.evaluate(signal)

        assert result is signal
        assert not llm_called


class TestGatedPath:
    async def test_gated_approval_returns_signal(self, tmp_path: Path) -> None:
        gk = make_gatekeeper(tmp_path)
        signal = make_signal(velocity=0.20)  # 0.20 < 0.30 fast-path cutoff

        mock_client = AsyncMock()
        mock_response = MagicMock()
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = json.dumps({"approved": True, "confidence": 0.85, "reason": "strong signal"})
        mock_response.content = [text_block]
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        gk._client = mock_client

        result = await gk.evaluate(signal, source="kalshi")

        assert result is signal
        assert getattr(result, "gatekeeper_confidence", None) == pytest.approx(0.85)

    async def test_gated_suppression_returns_none(self, tmp_path: Path) -> None:
        gk = make_gatekeeper(tmp_path)
        signal = make_signal(velocity=0.20)

        mock_client = AsyncMock()
        mock_response = MagicMock()
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = json.dumps({"approved": False, "confidence": 0.30, "reason": "near-threshold noise"})
        mock_response.content = [text_block]
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        gk._client = mock_client

        result = await gk.evaluate(signal)

        assert result is None

    async def test_gated_path_logs_path_gated(self, tmp_path: Path) -> None:
        gk = make_gatekeeper(tmp_path)
        signal = make_signal(velocity=0.20)

        mock_client = AsyncMock()
        mock_response = MagicMock()
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = json.dumps({"approved": True, "confidence": 0.75, "reason": "ok"})
        mock_response.content = [text_block]
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        gk._client = mock_client

        await gk.evaluate(signal, source="polymarket")

        record = json.loads(gk._log_path.read_text().splitlines()[0])
        assert record["path"] == "gated"
        assert record["source"] == "polymarket"
        assert record["approved"] is True


class TestLLMFailureFallback:
    async def test_llm_exception_defaults_to_approved(self, tmp_path: Path) -> None:
        gk = make_gatekeeper(tmp_path)
        signal = make_signal(velocity=0.20)

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(side_effect=RuntimeError("connection timeout"))
        gk._client = mock_client

        result = await gk.evaluate(signal)

        assert result is signal

    async def test_llm_bad_json_defaults_to_approved(self, tmp_path: Path) -> None:
        gk = make_gatekeeper(tmp_path)
        signal = make_signal(velocity=0.20)

        mock_client = AsyncMock()
        mock_response = MagicMock()
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "not valid json"
        mock_response.content = [text_block]
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        gk._client = mock_client

        result = await gk.evaluate(signal)

        assert result is signal

    async def test_llm_failure_logs_reason(self, tmp_path: Path) -> None:
        gk = make_gatekeeper(tmp_path)
        signal = make_signal(velocity=0.20)

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(side_effect=RuntimeError("timeout"))
        gk._client = mock_client

        await gk.evaluate(signal)

        record = json.loads(gk._log_path.read_text().splitlines()[0])
        assert "LLM infrastructure error" in record["reason"]
        assert record["approved"] is True


class TestDisabledGatekeeper:
    async def test_disabled_always_passes(self, tmp_path: Path) -> None:
        gk = make_gatekeeper(tmp_path, enabled=False)
        signal = make_signal(velocity=0.16)  # borderline

        llm_called = False

        async def fake_call_llm(*args, **kwargs):
            nonlocal llm_called
            llm_called = True
            return False, 0.0, "never called"

        gk._call_llm = fake_call_llm
        result = await gk.evaluate(signal)

        assert result is signal
        assert not llm_called
        assert not gk._log_path.exists()
