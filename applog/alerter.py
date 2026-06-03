import asyncio
import os
from datetime import datetime, timezone

import httpx

from execution.order_schema import OrderRecord
from signals.velocity import VelocitySignal

ALERT_WEBHOOK_URL = os.getenv("ALERT_WEBHOOK_URL", "")
ALERTS_ENABLED = os.getenv("ALERTS_ENABLED", "true").lower() not in ("0", "false", "no")


class Alerter:
    def __init__(
        self,
        webhook_url: str = ALERT_WEBHOOK_URL,
        enabled: bool = ALERTS_ENABLED,
    ) -> None:
        self._url = webhook_url
        self._enabled = enabled and bool(webhook_url)

    def _is_discord(self) -> bool:
        return "discord.com" in self._url

    def _build_signal_payload(
        self,
        signal: VelocitySignal,
        direction: str,
        basket: list[str],
    ) -> dict:
        if self._is_discord():
            color = 0x00FF00 if direction == "buy" else 0xFF0000
            return {
                "embeds": [{
                    "title": f"Signal: {signal.contract_slug}",
                    "color": color,
                    "fields": [
                        {"name": "Velocity", "value": f"{signal.velocity:.4f}", "inline": True},
                        {"name": "Direction", "value": direction, "inline": True},
                        {"name": "Basket", "value": ", ".join(basket), "inline": False},
                        {"name": "Timestamp", "value": signal.timestamp.isoformat(), "inline": False},
                    ],
                    "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                }]
            }
        return {
            "text": (
                f"*Signal*: {signal.contract_slug} | "
                f"velocity={signal.velocity:.4f} | direction={direction} | "
                f"basket={', '.join(basket)} | ts={signal.timestamp.isoformat()}"
            )
        }

    def _build_order_payload(self, order: OrderRecord) -> dict:
        if self._is_discord():
            return {
                "embeds": [{
                    "title": f"Order: {order.ticker} {order.side.upper()}",
                    "color": 0x0000FF,
                    "fields": [
                        {"name": "Ticker", "value": order.ticker, "inline": True},
                        {"name": "Side", "value": order.side, "inline": True},
                        {"name": "Size", "value": f"${order.size_usd:.2f}", "inline": True},
                        {"name": "Strategy", "value": order.strategy_id, "inline": True},
                        {"name": "Mode", "value": order.mode, "inline": True},
                    ],
                    "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                }]
            }
        return {
            "text": (
                f"*Order*: {order.ticker} {order.side} "
                f"${order.size_usd:.2f} | strategy={order.strategy_id} | mode={order.mode}"
            )
        }

    def _build_exit_payload(
        self,
        ticker: str,
        exit_reason: str,
        hold_minutes: float,
        pnl_usd: float,
    ) -> dict:
        if self._is_discord():
            color = 0x00FF00 if pnl_usd >= 0 else 0xFF0000
            prefix = "+" if pnl_usd >= 0 else ""
            return {
                "embeds": [{
                    "title": f"Exit: {ticker}",
                    "color": color,
                    "fields": [
                        {"name": "Ticker", "value": ticker, "inline": True},
                        {"name": "Reason", "value": exit_reason, "inline": True},
                        {"name": "Hold Time", "value": f"{hold_minutes:.1f}m", "inline": True},
                        {"name": "P&L", "value": f"{prefix}${pnl_usd:.2f}", "inline": True},
                    ],
                    "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                }]
            }
        prefix = "+" if pnl_usd >= 0 else ""
        return {
            "text": (
                f"*Exit*: {ticker} | "
                f"reason={exit_reason} | "
                f"hold={hold_minutes:.1f}m | "
                f"pnl={prefix}${pnl_usd:.2f}"
            )
        }

    async def _send(self, payload: dict) -> None:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                await client.post(self._url, json=payload)
        except Exception:
            pass

    def _fire(self, payload: dict) -> None:
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._send(payload))
        except RuntimeError:
            pass

    def alert_signal(
        self,
        signal: VelocitySignal,
        direction: str,
        basket: list[str],
    ) -> None:
        if not self._enabled:
            return
        self._fire(self._build_signal_payload(signal, direction, basket))

    def alert_order(self, order: OrderRecord) -> None:
        if not self._enabled:
            return
        self._fire(self._build_order_payload(order))

    def alert_exit(
        self,
        ticker: str,
        exit_reason: str,
        hold_minutes: float,
        pnl_usd: float,
    ) -> None:
        if not self._enabled:
            return
        self._fire(self._build_exit_payload(ticker, exit_reason, hold_minutes, pnl_usd))
