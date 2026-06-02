import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from execution.exit_manager import ExitManager, TrackedPosition, _exit_reason


def make_pos(
    ticker: str = "AAPL",
    side: str = "buy",
    entry_hours_ago: float = 1.0,
    entry_price: float | None = 100.0,
    exit_hours: float = 2.0,
    exit_adverse_pct: float = 0.03,
    direction: str = "up",
) -> TrackedPosition:
    return TrackedPosition(
        order_id="ord-1",
        ticker=ticker,
        side=side,
        size=100.0,
        entry_time=datetime.now(tz=timezone.utc) - timedelta(hours=entry_hours_ago),
        strategy_id="s1",
        direction=direction,
        exit_hours=exit_hours,
        exit_adverse_pct=exit_adverse_pct,
        entry_price=entry_price,
    )


class TestExitReason:
    def test_no_exit_within_window(self) -> None:
        pos = make_pos(entry_hours_ago=1.0, exit_hours=2.0)
        assert _exit_reason(pos, 102.0, datetime.now(tz=timezone.utc)) is None

    def test_time_exit_when_window_elapsed(self) -> None:
        pos = make_pos(entry_hours_ago=3.0, exit_hours=2.0)
        assert _exit_reason(pos, 102.0, datetime.now(tz=timezone.utc)) == "time"

    def test_time_exit_at_exact_boundary(self) -> None:
        pos = make_pos(entry_hours_ago=2.0, exit_hours=2.0)
        assert _exit_reason(pos, 100.0, datetime.now(tz=timezone.utc)) == "time"

    def test_adverse_move_buy_side(self) -> None:
        pos = make_pos(side="buy", entry_price=100.0, exit_adverse_pct=0.03)
        assert _exit_reason(pos, 96.0, datetime.now(tz=timezone.utc)) == "adverse_move"

    def test_no_adverse_move_buy_side_within_tolerance(self) -> None:
        pos = make_pos(side="buy", entry_price=100.0, exit_adverse_pct=0.03)
        assert _exit_reason(pos, 98.0, datetime.now(tz=timezone.utc)) is None

    def test_adverse_move_sell_side(self) -> None:
        pos = make_pos(side="sell", entry_price=100.0, exit_adverse_pct=0.03)
        assert _exit_reason(pos, 104.0, datetime.now(tz=timezone.utc)) == "adverse_move"

    def test_no_adverse_move_without_entry_price(self) -> None:
        pos = make_pos(entry_price=None)
        assert _exit_reason(pos, 90.0, datetime.now(tz=timezone.utc)) is None

    def test_time_exit_takes_priority_over_adverse(self) -> None:
        pos = make_pos(entry_hours_ago=5.0, exit_hours=2.0, entry_price=100.0)
        assert _exit_reason(pos, 80.0, datetime.now(tz=timezone.utc)) == "time"


class TestExitManager:
    def make_manager(self) -> tuple[ExitManager, MagicMock]:
        client = MagicMock()
        manager = ExitManager(
            client=client,
            price_fetcher=lambda tickers: {t: 100.0 for t in tickers},
            check_interval_seconds=0.01,
        )
        return manager, client

    def test_register_adds_position(self) -> None:
        manager, _ = self.make_manager()
        manager.register(make_pos())
        assert manager.open_count() == 1

    def test_multiple_registrations(self) -> None:
        manager, _ = self.make_manager()
        manager.register(make_pos("AAPL"))
        manager.register(make_pos("GOOG"))
        assert manager.open_count() == 2

    @pytest.mark.asyncio
    async def test_check_exits_removes_expired_positions(self) -> None:
        client = MagicMock()
        manager = ExitManager(
            client=client,
            price_fetcher=lambda tickers: {t: 100.0 for t in tickers},
            check_interval_seconds=9999,
        )
        manager.register(make_pos(entry_hours_ago=3.0, exit_hours=2.0))
        await manager._check_exits()
        assert manager.open_count() == 0
        client.submit_order.assert_called_once()

    @pytest.mark.asyncio
    async def test_check_exits_keeps_valid_positions(self) -> None:
        client = MagicMock()
        manager = ExitManager(
            client=client,
            price_fetcher=lambda tickers: {t: 100.0 for t in tickers},
            check_interval_seconds=9999,
        )
        manager.register(make_pos(entry_hours_ago=0.5, exit_hours=2.0))
        await manager._check_exits()
        assert manager.open_count() == 1
        client.submit_order.assert_not_called()

    @pytest.mark.asyncio
    async def test_exit_submits_opposite_side_for_buy(self) -> None:
        client = MagicMock()
        manager = ExitManager(
            client=client,
            price_fetcher=lambda tickers: {t: 100.0 for t in tickers},
            check_interval_seconds=9999,
        )
        manager.register(make_pos(side="buy", entry_hours_ago=3.0, exit_hours=2.0))
        await manager._check_exits()
        _, kwargs = client.submit_order.call_args
        assert client.submit_order.call_args[0][1] == "sell"

    @pytest.mark.asyncio
    async def test_exit_submits_opposite_side_for_sell(self) -> None:
        client = MagicMock()
        manager = ExitManager(
            client=client,
            price_fetcher=lambda tickers: {t: 100.0 for t in tickers},
            check_interval_seconds=9999,
        )
        manager.register(make_pos(side="sell", entry_hours_ago=3.0, exit_hours=2.0))
        await manager._check_exits()
        assert client.submit_order.call_args[0][1] == "buy"

    @pytest.mark.asyncio
    async def test_adverse_move_triggers_exit(self) -> None:
        client = MagicMock()
        manager = ExitManager(
            client=client,
            price_fetcher=lambda tickers: {t: 90.0 for t in tickers},
            check_interval_seconds=9999,
        )
        manager.register(
            make_pos(side="buy", entry_price=100.0, exit_adverse_pct=0.03, entry_hours_ago=0.1)
        )
        await manager._check_exits()
        assert manager.open_count() == 0
        client.submit_order.assert_called_once()
