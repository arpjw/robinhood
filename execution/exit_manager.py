import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable

from execution.mcp_client import MCPClient

logger = logging.getLogger(__name__)

_REVERSE_VELOCITY_THRESHOLD = float(os.getenv("REVERSE_VELOCITY_THRESHOLD", "0.20"))
_REVERSE_VELOCITY_ENABLED = os.getenv("REVERSE_VELOCITY_ENABLED", "true").lower() not in (
    "0", "false", "no"
)


@dataclass
class TrackedPosition:
    order_id: str
    ticker: str
    side: str
    size: float
    entry_time: datetime
    strategy_id: str
    direction: str
    contract_slug: str = ""
    entry_velocity: float = 0.0
    exit_hours: float = 2.0
    exit_adverse_pct: float = 0.03
    entry_price: float | None = None


def _exit_reason(
    pos: TrackedPosition,
    current_price: float | None,
    now: datetime,
) -> str | None:
    if now - pos.entry_time >= timedelta(hours=pos.exit_hours):
        return "time"
    if current_price is not None and pos.entry_price is not None:
        if pos.side == "buy":
            move = (current_price - pos.entry_price) / pos.entry_price
        else:
            move = (pos.entry_price - current_price) / pos.entry_price
        if move <= -pos.exit_adverse_pct:
            return "adverse_move"
    return None


class ExitManager:
    def __init__(
        self,
        client: MCPClient,
        price_fetcher: Callable[[list[str]], dict[str, float]],
        check_interval_seconds: float = 60.0,
        velocity_tracker=None,
        exposure_manager=None,
    ) -> None:
        self._client = client
        self._price_fetcher = price_fetcher
        self._interval = check_interval_seconds
        self._positions: list[TrackedPosition] = []
        self._velocity_tracker = velocity_tracker
        self._exposure_manager = exposure_manager

    def register(self, position: TrackedPosition) -> None:
        self._positions.append(position)
        logger.info(
            "tracking ticker=%s side=%s size=%.2f entry_price=%s strategy=%s",
            position.ticker,
            position.side,
            position.size,
            position.entry_price,
            position.strategy_id,
        )

    async def run(self) -> None:
        while True:
            await asyncio.sleep(self._interval)
            await self._check_exits()

    def _check_reverse_velocity(self, pos: TrackedPosition) -> bool:
        reverse_enabled = os.getenv("REVERSE_VELOCITY_ENABLED", "true").lower() not in (
            "0", "false", "no"
        )
        if not reverse_enabled or self._velocity_tracker is None or not pos.contract_slug:
            return False

        current_vel = self._velocity_tracker.get_current_velocity(pos.contract_slug)
        if current_vel is None or pos.entry_velocity == 0.0:
            return False

        threshold = float(os.getenv("REVERSE_VELOCITY_THRESHOLD", "0.20"))
        opposite_sign = current_vel * pos.entry_velocity < 0
        above_threshold = abs(current_vel) >= threshold
        return opposite_sign and above_threshold

    async def _check_exits(self) -> None:
        if not self._positions:
            return
        tickers = list({p.ticker for p in self._positions})
        current_prices = await asyncio.to_thread(self._price_fetcher, tickers)
        now = datetime.now(tz=timezone.utc)
        to_keep: list[TrackedPosition] = []
        for pos in self._positions:
            reason: str | None = None

            if self._check_reverse_velocity(pos):
                reason = "reverse_velocity"
                current_vel = self._velocity_tracker.get_current_velocity(pos.contract_slug)
                hold_hours = (now - pos.entry_time).total_seconds() / 3600.0
                logger.warning(
                    "REVERSE_VELOCITY EXIT ticker=%s entry_velocity=%.4f current_velocity=%.4f "
                    "hold_hours=%.2f strategy=%s",
                    pos.ticker,
                    pos.entry_velocity,
                    current_vel,
                    hold_hours,
                    pos.strategy_id,
                )

            if reason is None:
                reason = _exit_reason(pos, current_prices.get(pos.ticker), now)

            if reason:
                exit_side = "sell" if pos.side == "buy" else "buy"
                self._client.submit_order(pos.ticker, exit_side, pos.size, pos.strategy_id)
                if self._exposure_manager is not None and pos.contract_slug:
                    self._exposure_manager.register_close(pos.contract_slug, pos.ticker)
                logger.info(
                    "EXIT ticker=%s side=%s reason=%s strategy=%s",
                    pos.ticker,
                    exit_side,
                    reason,
                    pos.strategy_id,
                )
            else:
                to_keep.append(pos)
        self._positions = to_keep

    def open_count(self) -> int:
        return len(self._positions)


def yfinance_price_fetcher(tickers: list[str]) -> dict[str, float]:
    import yfinance as yf

    prices: dict[str, float] = {}
    for ticker in tickers:
        try:
            hist = yf.Ticker(ticker).history(period="1d", interval="1m")
            if not hist.empty:
                prices[ticker] = float(hist["Close"].iloc[-1])
        except Exception as exc:
            logger.warning("price fetch failed for %s: %s", ticker, exc)
    return prices
