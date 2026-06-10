import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from signals.parallel_poller import ParallelPoller
from signals.velocity import VelocitySignal


def make_signal(slug: str = "KXFED") -> VelocitySignal:
    return VelocitySignal(
        contract_slug=slug,
        velocity=0.25,
        window_minutes=5,
        timestamp=datetime.now(tz=timezone.utc),
        price=0.55,
        volume_delta=300,
    )


def make_poller(tmp_path: Path) -> tuple[ParallelPoller, MagicMock, MagicMock]:
    kalshi = MagicMock()
    polymarket = MagicMock()
    kalshi.poll_once = AsyncMock()
    polymarket.poll_once = AsyncMock()

    pp = ParallelPoller(kalshi=kalshi, polymarket=polymarket)
    pp._log_path = tmp_path / "signals.jsonl"

    import signals.parallel_poller as mod
    mod.SIGNAL_LOG_PATH = tmp_path / "signals.jsonl"

    return pp, kalshi, polymarket


class TestConcurrentPolling:
    async def test_both_pollers_called(self, tmp_path: Path) -> None:
        pp, kalshi, polymarket = make_poller(tmp_path)
        on_signal = AsyncMock()

        await pp.poll_once(on_signal)

        kalshi.poll_once.assert_awaited_once_with(on_signal)
        polymarket.poll_once.assert_awaited_once_with(on_signal)

    async def test_concurrent_execution(self, tmp_path: Path) -> None:
        kalshi = MagicMock()
        polymarket = MagicMock()
        order: list[str] = []

        async def slow_kalshi(on_signal):
            await asyncio.sleep(0.05)
            order.append("kalshi")

        async def slow_poly(on_signal):
            await asyncio.sleep(0.05)
            order.append("polymarket")

        kalshi.poll_once = slow_kalshi
        polymarket.poll_once = slow_poly

        import signals.parallel_poller as mod
        mod.SIGNAL_LOG_PATH = tmp_path / "signals.jsonl"

        pp = ParallelPoller(kalshi=kalshi, polymarket=polymarket)
        on_signal = AsyncMock()

        import time
        t0 = time.monotonic()
        await pp.poll_once(on_signal)
        elapsed = time.monotonic() - t0

        assert set(order) == {"kalshi", "polymarket"}
        assert elapsed < 0.09

    async def test_timing_logged(self, tmp_path: Path) -> None:
        import signals.parallel_poller as mod
        mod.SIGNAL_LOG_PATH = tmp_path / "signals.jsonl"

        kalshi = MagicMock()
        polymarket = MagicMock()
        kalshi.poll_once = AsyncMock()
        polymarket.poll_once = AsyncMock()

        pp = ParallelPoller(kalshi=kalshi, polymarket=polymarket)
        on_signal = AsyncMock()
        await pp.poll_once(on_signal)

        lines = (tmp_path / "signals.jsonl").read_text().splitlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["type"] == "poll_timing"
        assert "wall_clock_ms" in record
        assert "kalshi_ms" in record
        assert "polymarket_ms" in record
        assert record["kalshi_ok"] is True
        assert record["polymarket_ok"] is True

    async def test_kalshi_error_does_not_stop_polymarket(self, tmp_path: Path) -> None:
        import signals.parallel_poller as mod
        mod.SIGNAL_LOG_PATH = tmp_path / "signals.jsonl"

        signals_received: list[VelocitySignal] = []

        async def failing_kalshi(on_signal):
            raise RuntimeError("kalshi down")

        async def ok_poly(on_signal):
            await on_signal(make_signal("KXCPI"))

        kalshi = MagicMock()
        polymarket = MagicMock()
        kalshi.poll_once = failing_kalshi
        polymarket.poll_once = ok_poly

        pp = ParallelPoller(kalshi=kalshi, polymarket=polymarket)

        async def capture(s):
            signals_received.append(s)

        await pp.poll_once(capture)

        assert len(signals_received) == 1
        assert signals_received[0].contract_slug == "KXCPI"

        record = json.loads((tmp_path / "signals.jsonl").read_text().splitlines()[0])
        assert record["kalshi_ok"] is False
        assert record["polymarket_ok"] is True

    async def test_polymarket_error_does_not_stop_kalshi(self, tmp_path: Path) -> None:
        import signals.parallel_poller as mod
        mod.SIGNAL_LOG_PATH = tmp_path / "signals.jsonl"

        signals_received: list[VelocitySignal] = []

        async def ok_kalshi(on_signal):
            await on_signal(make_signal("KXFED"))

        async def failing_poly(on_signal):
            raise RuntimeError("polymarket down")

        kalshi = MagicMock()
        polymarket = MagicMock()
        kalshi.poll_once = ok_kalshi
        polymarket.poll_once = failing_poly

        pp = ParallelPoller(kalshi=kalshi, polymarket=polymarket)

        async def capture(s):
            signals_received.append(s)

        await pp.poll_once(capture)

        assert len(signals_received) == 1
        assert signals_received[0].contract_slug == "KXFED"

        record = json.loads((tmp_path / "signals.jsonl").read_text().splitlines()[0])
        assert record["kalshi_ok"] is True
        assert record["polymarket_ok"] is False

    async def test_signal_forwarding(self, tmp_path: Path) -> None:
        import signals.parallel_poller as mod
        mod.SIGNAL_LOG_PATH = tmp_path / "signals.jsonl"

        signals_received: list[VelocitySignal] = []
        sig_k = make_signal("KXFED")
        sig_p = make_signal("KXCPI")

        async def kalshi_fires(on_signal):
            await on_signal(sig_k)

        async def poly_fires(on_signal):
            await on_signal(sig_p)

        kalshi = MagicMock()
        polymarket = MagicMock()
        kalshi.poll_once = kalshi_fires
        polymarket.poll_once = poly_fires

        pp = ParallelPoller(kalshi=kalshi, polymarket=polymarket)

        async def capture(s):
            signals_received.append(s)

        await pp.poll_once(capture)

        slugs = {s.contract_slug for s in signals_received}
        assert slugs == {"KXFED", "KXCPI"}
