import asyncio
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from applog.alerter import Alerter
from execution.order_schema import OrderRecord
from signals.velocity import VelocitySignal


def make_signal() -> VelocitySignal:
    return VelocitySignal(
        contract_slug="KXFED",
        velocity=0.25,
        window_minutes=5,
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        price=0.6,
        volume_delta=100,
    )


def make_order(mode: str = "mock") -> OrderRecord:
    return OrderRecord(
        id="ord-1",
        timestamp="2026-01-01T00:00:00+00:00",
        mode=mode,
        strategy_id="s1",
        ticker="JPM",
        side="buy",
        size_usd=500.0,
        contract_slug="KXFED",
        velocity=0.25,
        signal_timestamp="2026-01-01T00:00:00+00:00",
    )


class TestDiscordPayload:
    def test_signal_payload_has_embeds(self) -> None:
        alerter = Alerter(webhook_url="https://discord.com/api/webhooks/123/abc", enabled=True)
        payload = alerter._build_signal_payload(make_signal(), "buy", ["JPM", "BAC"])
        assert "embeds" in payload
        assert len(payload["embeds"]) == 1

    def test_signal_payload_embed_title(self) -> None:
        alerter = Alerter(webhook_url="https://discord.com/api/webhooks/123/abc", enabled=True)
        payload = alerter._build_signal_payload(make_signal(), "sell", ["TLT"])
        embed = payload["embeds"][0]
        assert "KXFED" in embed["title"]

    def test_signal_payload_fields(self) -> None:
        alerter = Alerter(webhook_url="https://discord.com/api/webhooks/123/abc", enabled=True)
        payload = alerter._build_signal_payload(make_signal(), "buy", ["JPM"])
        fields = {f["name"]: f["value"] for f in payload["embeds"][0]["fields"]}
        assert fields["Direction"] == "buy"
        assert "JPM" in fields["Basket"]
        assert "0.25" in fields["Velocity"]

    def test_order_payload_has_embeds(self) -> None:
        alerter = Alerter(webhook_url="https://discord.com/api/webhooks/123/abc", enabled=True)
        payload = alerter._build_order_payload(make_order())
        assert "embeds" in payload
        assert "JPM" in payload["embeds"][0]["title"]

    def test_exit_payload_has_embeds(self) -> None:
        alerter = Alerter(webhook_url="https://discord.com/api/webhooks/123/abc", enabled=True)
        payload = alerter._build_exit_payload("JPM", "time", 45.0, 12.50)
        assert "embeds" in payload
        assert "JPM" in payload["embeds"][0]["title"]


class TestSlackPayload:
    def test_signal_payload_has_text_not_embeds(self) -> None:
        alerter = Alerter(webhook_url="https://hooks.slack.com/services/123", enabled=True)
        payload = alerter._build_signal_payload(make_signal(), "buy", ["JPM"])
        assert "text" in payload
        assert "embeds" not in payload

    def test_signal_payload_contains_slug(self) -> None:
        alerter = Alerter(webhook_url="https://hooks.slack.com/services/123", enabled=True)
        payload = alerter._build_signal_payload(make_signal(), "sell", ["TLT"])
        assert "KXFED" in payload["text"]
        assert "TLT" in payload["text"]

    def test_order_payload_has_text(self) -> None:
        alerter = Alerter(webhook_url="https://hooks.slack.com/services/123", enabled=True)
        payload = alerter._build_order_payload(make_order())
        assert "text" in payload
        assert "JPM" in payload["text"]
        assert "mock" in payload["text"]

    def test_exit_payload_contains_pnl(self) -> None:
        alerter = Alerter(webhook_url="https://hooks.slack.com/services/123", enabled=True)
        payload = alerter._build_exit_payload("TLT", "adverse_move", 30.0, -5.25)
        assert "text" in payload
        assert "TLT" in payload["text"]
        assert "adverse_move" in payload["text"]


class TestTimeoutHandling:
    @pytest.mark.asyncio
    async def test_timeout_does_not_raise(self) -> None:
        alerter = Alerter(webhook_url="https://hooks.slack.com/services/123", enabled=True)
        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(side_effect=asyncio.TimeoutError())
            mock_cls.return_value = mock_client
            await alerter._send({"text": "test"})

    @pytest.mark.asyncio
    async def test_connection_error_does_not_raise(self) -> None:
        alerter = Alerter(webhook_url="https://hooks.slack.com/services/123", enabled=True)
        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(side_effect=OSError("connection refused"))
            mock_cls.return_value = mock_client
            await alerter._send({"text": "test"})


class TestDisabledAlerts:
    def test_alert_signal_does_not_fire_when_disabled(self) -> None:
        alerter = Alerter(webhook_url="https://hooks.slack.com/services/123", enabled=False)
        fired = []
        alerter._fire = lambda p: fired.append(p)
        alerter.alert_signal(make_signal(), "buy", ["JPM"])
        assert fired == []

    def test_alert_order_does_not_fire_when_disabled(self) -> None:
        alerter = Alerter(webhook_url="https://hooks.slack.com/services/123", enabled=False)
        fired = []
        alerter._fire = lambda p: fired.append(p)
        alerter.alert_order(make_order())
        assert fired == []

    def test_alert_exit_does_not_fire_when_disabled(self) -> None:
        alerter = Alerter(webhook_url="https://hooks.slack.com/services/123", enabled=False)
        fired = []
        alerter._fire = lambda p: fired.append(p)
        alerter.alert_exit("JPM", "time", 30.0, 5.0)
        assert fired == []

    def test_no_url_disables_alerter(self) -> None:
        alerter = Alerter(webhook_url="", enabled=True)
        assert not alerter._enabled
