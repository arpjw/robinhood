import asyncio
import json
import pytest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from signals.kalshi_poller import KalshiPoller
from signals.velocity import VelocityTracker


def make_rsa_key(tmp_path: Path) -> str:
    key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend(),
    )
    key_path = tmp_path / "key.pem"
    key_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    return str(key_path)


@pytest.fixture
def poller(tmp_path: Path) -> KalshiPoller:
    tracker = VelocityTracker(threshold=0.01)
    return KalshiPoller(
        api_key="test-key",
        tracked_tickers=["KXFED", "KXCPI"],
        tracker=tracker,
        private_key_path=make_rsa_key(tmp_path),
        use_websocket=True,
    )


class TestWsMessageParsing:
    @pytest.mark.asyncio
    async def test_ticker_message_updates_tracker(self, poller: KalshiPoller) -> None:
        raw = json.dumps({
            "type": "ticker",
            "msg": {
                "market_ticker": "KXFED",
                "yes_price": 55,
                "volume": 1000,
            },
        })
        await poller._handle_ws_message(raw, AsyncMock())
        history = list(poller._tracker._history.get("KXFED", []))
        assert len(history) == 1
        assert history[0].price == pytest.approx(0.55)

    @pytest.mark.asyncio
    async def test_yes_price_normalized_to_0_1(self, poller: KalshiPoller) -> None:
        for cents in [0, 25, 50, 75, 100]:
            raw = json.dumps({
                "type": "ticker",
                "msg": {"market_ticker": "KXFED", "yes_price": cents, "volume": 0},
            })
            await poller._handle_ws_message(raw, AsyncMock())
        history = list(poller._tracker._history["KXFED"])
        prices = [p.price for p in history]
        assert prices[0] == pytest.approx(0.0)
        assert prices[2] == pytest.approx(0.5)
        assert prices[4] == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_non_ticker_message_ignored(self, poller: KalshiPoller) -> None:
        raw = json.dumps({"type": "orderbook_delta", "msg": {"market_ticker": "KXFED"}})
        await poller._handle_ws_message(raw, AsyncMock())
        assert "KXFED" not in poller._tracker._history

    @pytest.mark.asyncio
    async def test_untracked_ticker_ignored(self, poller: KalshiPoller) -> None:
        raw = json.dumps({
            "type": "ticker",
            "msg": {"market_ticker": "UNKNOWN", "yes_price": 50, "volume": 100},
        })
        await poller._handle_ws_message(raw, AsyncMock())
        assert "UNKNOWN" not in poller._tracker._history

    @pytest.mark.asyncio
    async def test_malformed_json_ignored(self, poller: KalshiPoller) -> None:
        await poller._handle_ws_message("not valid json {{{", AsyncMock())

    @pytest.mark.asyncio
    async def test_signal_callback_fires_on_velocity(self, poller: KalshiPoller) -> None:
        signals = []
        async def capture(s):
            signals.append(s)

        for i in range(5):
            raw = json.dumps({
                "type": "ticker",
                "msg": {
                    "market_ticker": "KXFED",
                    "yes_price": 10 + i * 15,
                    "volume": 1000 + i * 500,
                },
            })
            await poller._handle_ws_message(raw, capture)

        assert len(signals) > 0


class TestWsFallbackToRest:
    @pytest.mark.asyncio
    async def test_falls_back_to_rest_on_connection_failure(self, poller: KalshiPoller) -> None:
        rest_called = asyncio.Event()

        async def mock_rest(interval, on_signal):
            rest_called.set()

        poller._run_rest = mock_rest

        with patch("signals.kalshi_poller.ws_connect", side_effect=OSError("Connection refused")):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                await poller.run(30.0, AsyncMock())

        assert rest_called.is_set()

    @pytest.mark.asyncio
    async def test_rest_mode_skips_websocket(self, tmp_path: Path) -> None:
        tracker = VelocityTracker()
        p = KalshiPoller(
            api_key="k",
            tracked_tickers=["KXFED"],
            tracker=tracker,
            private_key_path=make_rsa_key(tmp_path),
            use_websocket=False,
        )

        rest_called = asyncio.Event()

        async def mock_rest(interval, on_signal):
            rest_called.set()

        p._run_rest = mock_rest

        ws_called = False

        async def mock_ws(on_signal):
            nonlocal ws_called
            ws_called = True
            return False

        p._run_websocket = mock_ws

        await p.run(30.0, AsyncMock())

        assert rest_called.is_set()
        assert not ws_called


class TestWsExponentialBackoff:
    @pytest.mark.asyncio
    async def test_backoff_delays_double(self, poller: KalshiPoller) -> None:
        sleep_delays: list[float] = []

        async def capture_sleep(delay: float) -> None:
            sleep_delays.append(delay)

        with patch("websockets.connect", side_effect=OSError("refused")):
            with patch("asyncio.sleep", side_effect=capture_sleep):
                await poller._run_websocket(AsyncMock())

        assert len(sleep_delays) == 4
        assert sleep_delays[0] == pytest.approx(1.0)
        assert sleep_delays[1] == pytest.approx(2.0)
        assert sleep_delays[2] == pytest.approx(4.0)
        assert sleep_delays[3] == pytest.approx(8.0)

    @pytest.mark.asyncio
    async def test_backoff_capped_at_60s(self, poller: KalshiPoller) -> None:
        from signals.kalshi_poller import _WS_MAX_ATTEMPTS, _WS_BACKOFF_MAX

        poller_big = KalshiPoller(
            api_key="k",
            tracked_tickers=["KXFED"],
            tracker=VelocityTracker(),
            private_key_path=poller._private_key.__class__.__name__,
            use_websocket=True,
        ) if False else poller

        sleep_delays: list[float] = []

        async def capture_sleep(delay: float) -> None:
            sleep_delays.append(delay)

        with patch("websockets.connect", side_effect=OSError("refused")):
            with patch("asyncio.sleep", side_effect=capture_sleep):
                await poller._run_websocket(AsyncMock())

        for delay in sleep_delays:
            assert delay <= _WS_BACKOFF_MAX

    @pytest.mark.asyncio
    async def test_returns_false_after_max_attempts(self, poller: KalshiPoller) -> None:
        with patch("websockets.connect", side_effect=OSError("refused")):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                result = await poller._run_websocket(AsyncMock())
        assert result is False
