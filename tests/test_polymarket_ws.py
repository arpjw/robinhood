import asyncio
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from signals.polymarket_poller import PolymarketPoller
from signals.velocity import PricePoint, VelocitySignal, VelocityTracker


def make_poller(use_websocket=True) -> PolymarketPoller:
    tracker = VelocityTracker(window_minutes=5, threshold=0.0, history_minutes=60)
    mapper = MagicMock()
    return PolymarketPoller(
        condition_ids=["cond-1", "cond-2"],
        tracker=tracker,
        mapper=mapper,
        use_websocket=use_websocket,
    )


def price_change_msg(market: str, price: float) -> str:
    return json.dumps({"event_type": "price_change", "market": market, "price": price})


def price_change_list(market: str, price: float) -> str:
    return json.dumps([{"event_type": "price_change", "market": market, "price": price}])


def make_dummy_signal(slug: str = "cond-1") -> VelocitySignal:
    return VelocitySignal(
        contract_slug=slug,
        velocity=0.25,
        window_minutes=5,
        timestamp=datetime.now(tz=timezone.utc),
        price=0.6,
        volume_delta=10,
    )


class TestWsMessageParsing:
    @pytest.mark.asyncio
    async def test_price_change_dict_fires_signal(self):
        poller = make_poller()
        dummy = make_dummy_signal("cond-1")
        poller._tracker.update = MagicMock(return_value=dummy)
        signals = []

        async def on_signal(sig):
            signals.append(sig)

        raw = price_change_msg("cond-1", 0.6)
        await poller._handle_ws_message(raw, on_signal)

        assert len(signals) == 1
        assert signals[0].contract_slug == "cond-1"

    @pytest.mark.asyncio
    async def test_price_change_list_fires_signal(self):
        poller = make_poller()
        dummy = make_dummy_signal("cond-1")
        poller._tracker.update = MagicMock(return_value=dummy)
        signals = []

        async def on_signal(sig):
            signals.append(sig)

        raw = price_change_list("cond-1", 0.6)
        await poller._handle_ws_message(raw, on_signal)

        assert len(signals) == 1

    @pytest.mark.asyncio
    async def test_unknown_event_type_ignored(self):
        poller = make_poller()
        fired = []

        async def on_signal(sig):
            fired.append(sig)

        raw = json.dumps({"event_type": "book", "market": "cond-1", "price": 0.6})
        await poller._handle_ws_message(raw, on_signal)
        assert fired == []

    @pytest.mark.asyncio
    async def test_unknown_market_ignored(self):
        poller = make_poller()
        fired = []

        async def on_signal(sig):
            fired.append(sig)

        raw = price_change_msg("unknown-market", 0.6)
        await poller._handle_ws_message(raw, on_signal)
        assert fired == []

    @pytest.mark.asyncio
    async def test_invalid_json_ignored(self):
        poller = make_poller()
        fired = []

        async def on_signal(sig):
            fired.append(sig)

        await poller._handle_ws_message("not json {{{{", on_signal)
        assert fired == []

    @pytest.mark.asyncio
    async def test_missing_price_ignored(self):
        poller = make_poller()
        fired = []

        async def on_signal(sig):
            fired.append(sig)

        raw = json.dumps({"event_type": "price_change", "market": "cond-1"})
        await poller._handle_ws_message(raw, on_signal)
        assert fired == []


class TestWsFallback:
    @pytest.mark.asyncio
    async def test_rest_fallback_on_connection_failure(self):
        poller = make_poller(use_websocket=True)
        rest_called = []

        async def fake_run_rest(interval_seconds, on_signal):
            rest_called.append(True)

        async def fake_run_ws(on_signal):
            return False

        poller._run_rest = fake_run_rest
        poller._run_websocket = fake_run_ws

        await poller.run(30, AsyncMock())
        assert rest_called

    @pytest.mark.asyncio
    async def test_disabled_websocket_goes_directly_to_rest(self):
        poller = make_poller(use_websocket=False)
        rest_called = []

        async def fake_run_rest(interval_seconds, on_signal):
            rest_called.append(True)

        poller._run_rest = fake_run_rest

        await poller.run(30, AsyncMock())
        assert rest_called

    @pytest.mark.asyncio
    async def test_backoff_increments_on_failure(self):
        import websockets.exceptions

        poller = make_poller()
        sleep_calls = []

        original_sleep = asyncio.sleep

        async def fake_sleep(seconds):
            sleep_calls.append(seconds)

        with patch("signals.polymarket_poller.ws_connect") as mock_connect, \
             patch("asyncio.sleep", fake_sleep):
            mock_connect.side_effect = OSError("connection refused")
            result = await poller._run_websocket(AsyncMock())

        assert result is False
        if sleep_calls:
            assert sleep_calls[0] <= sleep_calls[-1]
