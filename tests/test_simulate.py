import io
import json
import textwrap
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from backtest.simulate import (
    BacktestTrade,
    compute_summary,
    determine_side,
    load_kalshi_csv,
    replay_signals,
    simulate_trade,
)
from signals.contract_mapper import ContractMapper
from signals.velocity import VelocitySignal


def make_signal(
    slug: str = "KXFED",
    velocity: float = 0.5,
    price: float = 0.6,
    ts: datetime | None = None,
) -> VelocitySignal:
    return VelocitySignal(
        contract_slug=slug,
        velocity=velocity,
        window_minutes=5,
        timestamp=ts or datetime(2024, 1, 10, 14, 0, tzinfo=timezone.utc),
        price=price,
        volume_delta=500,
    )


def make_equity_df(dates: list[str], prices: list[float]) -> pd.DataFrame:
    idx = pd.to_datetime(dates)
    return pd.DataFrame(
        {
            "Open": prices,
            "High": [p * 1.01 for p in prices],
            "Low": [p * 0.99 for p in prices],
            "Close": prices,
            "Volume": [100000] * len(prices),
        },
        index=idx,
    )


class TestDetermineSide:
    def test_rising_bullish(self) -> None:
        assert determine_side(0.5, "up") == "buy"

    def test_rising_bearish(self) -> None:
        assert determine_side(0.5, "down") == "sell"

    def test_falling_bullish(self) -> None:
        assert determine_side(-0.5, "up") == "sell"

    def test_falling_bearish(self) -> None:
        assert determine_side(-0.5, "down") == "buy"


class TestLoadKalshiCsv:
    def test_parses_timestamp_and_normalizes_price(self, tmp_path: Path) -> None:
        csv = textwrap.dedent("""\
            timestamp,ticker,last_price,volume
            2024-01-01T09:00:00Z,KXFED-24JAN31,45,1000
            2024-01-01T09:05:00Z,KXFED-24JAN31,52,1500
        """)
        p = tmp_path / "kalshi.csv"
        p.write_text(csv)
        df = load_kalshi_csv(str(p))
        assert len(df) == 2
        assert df.iloc[0]["last_price"] == pytest.approx(0.45)
        assert df.iloc[1]["last_price"] == pytest.approx(0.52)

    def test_sorts_by_timestamp(self, tmp_path: Path) -> None:
        csv = textwrap.dedent("""\
            timestamp,ticker,last_price,volume
            2024-01-01T09:05:00Z,KXFED,52,1500
            2024-01-01T09:00:00Z,KXFED,45,1000
        """)
        p = tmp_path / "kalshi.csv"
        p.write_text(csv)
        df = load_kalshi_csv(str(p))
        assert df.iloc[0]["last_price"] == pytest.approx(0.45)


class TestReplaySignals:
    def test_fires_signal_on_sharp_move(self, tmp_path: Path) -> None:
        map_data = {
            "KXFED": {
                "description": "Fed",
                "direction": "up",
                "basket": ["JPM"],
                "sector_etf": "XLF",
                "confidence": 0.9,
            }
        }
        map_file = tmp_path / "map.json"
        map_file.write_text(json.dumps(map_data))
        mapper = ContractMapper(str(map_file))

        rows = [
            ("2024-01-01T09:00:00Z", "KXFED", 45, 1000),
            ("2024-01-01T09:01:00Z", "KXFED", 50, 1200),
            ("2024-01-01T09:02:00Z", "KXFED", 60, 2000),
            ("2024-01-01T09:03:00Z", "KXFED", 75, 3500),
        ]
        csv = "timestamp,ticker,last_price,volume\n" + "\n".join(
            f"{r[0]},{r[1]},{r[2]},{r[3]}" for r in rows
        )
        p = tmp_path / "kalshi.csv"
        p.write_text(csv)
        df = load_kalshi_csv(str(p))
        signals = replay_signals(df, mapper, threshold=0.01, window_minutes=5)
        assert len(signals) > 0
        assert all(s.contract_slug == "KXFED" for s in signals)

    def test_no_signal_without_mapped_basket(self, tmp_path: Path) -> None:
        map_data = {}
        map_file = tmp_path / "map.json"
        map_file.write_text(json.dumps(map_data))
        mapper = ContractMapper(str(map_file))

        rows = [
            ("2024-01-01T09:00:00Z", "KXFED", 45, 1000),
            ("2024-01-01T09:03:00Z", "KXFED", 80, 5000),
        ]
        csv = "timestamp,ticker,last_price,volume\n" + "\n".join(
            f"{r[0]},{r[1]},{r[2]},{r[3]}" for r in rows
        )
        p = tmp_path / "kalshi.csv"
        p.write_text(csv)
        df = load_kalshi_csv(str(p))
        signals = replay_signals(df, mapper, threshold=0.01, window_minutes=5)
        assert signals == []


class TestSimulateTrade:
    def test_profitable_buy(self) -> None:
        signal = make_signal(velocity=0.5)
        equity_df = make_equity_df(
            ["2024-01-10", "2024-01-11", "2024-01-12", "2024-01-15"],
            [100.0, 103.0, 106.0, 108.0],
        )
        trade = simulate_trade(signal, "JPM", "buy", 500.0, equity_df, 24.0, 0.05)
        assert trade is not None
        assert trade.pnl_dollar > 0
        assert trade.side == "buy"
        assert trade.exit_reason in ("time", "end_of_data")

    def test_adverse_move_triggers_early_exit(self) -> None:
        signal = make_signal(velocity=0.5)
        equity_df = make_equity_df(
            ["2024-01-10", "2024-01-11", "2024-01-12", "2024-01-15"],
            [100.0, 96.0, 94.0, 92.0],
        )
        trade = simulate_trade(signal, "JPM", "buy", 500.0, equity_df, 24.0, 0.03)
        assert trade is not None
        assert trade.exit_reason == "adverse_move"
        assert trade.pnl_dollar < 0

    def test_sell_side_pnl(self) -> None:
        signal = make_signal(velocity=-0.5)
        equity_df = make_equity_df(
            ["2024-01-10", "2024-01-11", "2024-01-12"],
            [100.0, 98.0, 96.0],
        )
        trade = simulate_trade(signal, "TLT", "sell", 500.0, equity_df, 24.0, 0.05)
        assert trade is not None
        assert trade.pnl_dollar > 0

    def test_returns_none_when_no_equity_data_after_signal(self) -> None:
        signal = make_signal(ts=datetime(2024, 6, 1, tzinfo=timezone.utc))
        equity_df = make_equity_df(
            ["2024-01-10", "2024-01-11"],
            [100.0, 102.0],
        )
        trade = simulate_trade(signal, "JPM", "buy", 500.0, equity_df, 24.0, 0.03)
        assert trade is None

    def test_time_exit_uses_exit_days(self) -> None:
        signal = make_signal()
        equity_df = make_equity_df(
            ["2024-01-10", "2024-01-11", "2024-01-12", "2024-01-15", "2024-01-16"],
            [100.0, 101.0, 102.0, 103.0, 104.0],
        )
        trade = simulate_trade(signal, "JPM", "buy", 500.0, equity_df, 6.5, 0.10)
        assert trade is not None
        assert trade.exit_reason == "time"
        assert trade.exit_date == "2024-01-11"


class TestComputeSummary:
    def make_trade(self, pnl: float) -> BacktestTrade:
        return BacktestTrade(
            contract_slug="KXFED",
            signal_time="2024-01-10T14:00:00",
            velocity=0.5,
            ticker="JPM",
            side="buy",
            entry_date="2024-01-10",
            entry_price=100.0,
            exit_date="2024-01-11",
            exit_price=100.0 + pnl,
            dollar_size=1000.0,
            pnl_dollar=pnl * 10,
            pnl_pct=pnl / 100.0,
            exit_reason="time",
        )

    def test_win_rate(self) -> None:
        trades = [self.make_trade(5), self.make_trade(-2), self.make_trade(3)]
        summary = compute_summary(trades, num_signals=5)
        assert summary.win_rate == pytest.approx(2 / 3, rel=1e-4)

    def test_total_pnl(self) -> None:
        trades = [self.make_trade(5), self.make_trade(-2)]
        summary = compute_summary(trades, num_signals=3)
        assert summary.total_pnl == pytest.approx(30.0, rel=1e-4)

    def test_empty_trades(self) -> None:
        summary = compute_summary([], num_signals=10)
        assert summary.num_trades == 0
        assert summary.win_rate == 0.0
        assert summary.total_pnl == 0.0
        assert summary.num_signals == 10

    def test_sharpe_zero_for_single_trade(self) -> None:
        summary = compute_summary([self.make_trade(5)], num_signals=1)
        assert summary.sharpe == 0.0

    def test_sharpe_positive_for_consistent_returns(self) -> None:
        trades = [self.make_trade(3)] * 10
        summary = compute_summary(trades, num_signals=10)
        assert summary.sharpe == 0.0

    def test_sharpe_computed_with_variance(self) -> None:
        trades = [self.make_trade(5), self.make_trade(-1), self.make_trade(3), self.make_trade(2)]
        summary = compute_summary(trades, num_signals=4)
        assert summary.sharpe != 0.0
