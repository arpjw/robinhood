"""
Backtest signal engine against historical Kalshi + equity data.

Kalshi CSV format (required columns):
    timestamp   ISO-8601 datetime string (UTC)
    ticker      Kalshi market ticker string
    last_price  integer 0-100 (cents)
    volume      cumulative volume integer

Usage:
    python -m backtest.simulate --kalshi-csv data/kalshi_history.csv
    python -m backtest.simulate --kalshi-csv data/kalshi_history.csv --output results/backtest.json
    python -m backtest.simulate --kalshi-csv data/kalshi_history.csv --plot
    python -m backtest.simulate --kalshi-csv data/kalshi_history.csv --realistic
    python -m backtest.simulate --kalshi-csv data/kalshi_history.csv --optimistic
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf

from execution.sizer import size_basket
from signals.contract_mapper import ContractMapper
from signals.velocity import PricePoint, VelocitySignal, VelocityTracker

VELOCITY_THRESHOLD = float(os.getenv("VELOCITY_THRESHOLD", "0.15"))
VELOCITY_WINDOW_MINUTES = int(os.getenv("VELOCITY_WINDOW_MINUTES", "5"))
PORTFOLIO_VALUE = float(os.getenv("PORTFOLIO_VALUE", "10000"))
MAX_POSITION_PCT = float(os.getenv("MAX_POSITION_PCT", "0.05"))
BACKTEST_SLIPPAGE_BPS = float(os.getenv("BACKTEST_SLIPPAGE_BPS", "10"))
BACKTEST_LATENCY_SECONDS = float(os.getenv("BACKTEST_LATENCY_SECONDS", "5"))
BACKTEST_SPREAD_BPS = float(os.getenv("BACKTEST_SPREAD_BPS", "5"))


@dataclass
class BacktestTrade:
    contract_slug: str
    signal_time: str
    velocity: float
    ticker: str
    side: str
    entry_date: str
    entry_price: float
    exit_date: str
    exit_price: float
    dollar_size: float
    pnl_dollar: float
    pnl_pct: float
    exit_reason: str
    hold_minutes: float = 0.0


@dataclass
class SlugBreakdown:
    contract_slug: str
    trade_count: int
    win_rate: float
    avg_pnl: float
    avg_hold_minutes: float


@dataclass
class BacktestSummary:
    num_signals: int
    num_trades: int
    winning_trades: int
    win_rate: float
    total_pnl: float
    avg_pnl_pct: float
    sharpe: float
    trades: list[BacktestTrade]
    per_slug: list[SlugBreakdown] | None = None
    signal_decay_curve: list[dict] | None = None
    execution_assumptions: dict | None = None


def apply_entry_price(
    price: float,
    side: str,
    slippage_bps: float,
    spread_bps: float,
) -> float:
    cost = (slippage_bps + spread_bps) / 10000.0
    return price * (1.0 + cost) if side == "buy" else price * (1.0 - cost)


def apply_exit_price(
    price: float,
    side: str,
    slippage_bps: float,
    spread_bps: float,
) -> float:
    cost = (slippage_bps + spread_bps) / 10000.0
    return price * (1.0 - cost) if side == "buy" else price * (1.0 + cost)


def get_fill_date(signal_ts: datetime, latency_seconds: float) -> datetime.date:
    return (signal_ts + timedelta(seconds=latency_seconds)).date()


def load_kalshi_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df["last_price"] = df["last_price"].astype(float) / 100.0
    df["volume"] = df["volume"].astype(int)
    return df.sort_values("timestamp").reset_index(drop=True)


def replay_signals(
    kalshi_df: pd.DataFrame,
    mapper: ContractMapper,
    threshold: float = VELOCITY_THRESHOLD,
    window_minutes: int = VELOCITY_WINDOW_MINUTES,
) -> list[VelocitySignal]:
    tracker = VelocityTracker(
        window_minutes=window_minutes,
        threshold=threshold,
        volume_multiplier=2.0,
    )
    signals: list[VelocitySignal] = []
    for _, row in kalshi_df.iterrows():
        ts = row["timestamp"]
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        point = PricePoint(
            timestamp=ts.to_pydatetime(),
            price=float(row["last_price"]),
            volume=int(row["volume"]),
        )
        signal = tracker.update(str(row["ticker"]), point)
        if signal is not None and mapper.get_basket(signal.contract_slug) is not None:
            signals.append(signal)
    return signals


def fetch_equity_ohlcv(
    tickers: list[str],
    start: str,
    end: str,
) -> dict[str, pd.DataFrame]:
    data: dict[str, pd.DataFrame] = {}
    for ticker in tickers:
        try:
            hist = yf.Ticker(ticker).history(start=start, end=end, interval="1d")
            if hist.empty:
                continue
            hist.index = pd.to_datetime(hist.index.date)
            data[ticker] = hist[["Open", "High", "Low", "Close", "Volume"]]
        except Exception:
            pass
    return data


def determine_side(velocity: float, direction: str) -> str:
    rising = velocity > 0
    bullish = direction == "up"
    return "buy" if rising == bullish else "sell"


def simulate_trade(
    signal: VelocitySignal,
    ticker: str,
    side: str,
    dollar_size: float,
    equity_df: pd.DataFrame,
    exit_hours: float,
    exit_adverse_pct: float,
    slippage_bps: float = 0.0,
    latency_seconds: float = 0.0,
    spread_bps: float = 0.0,
) -> BacktestTrade | None:
    fill_date = pd.Timestamp(get_fill_date(signal.timestamp, latency_seconds))
    future = equity_df[equity_df.index >= fill_date]
    if future.empty:
        return None

    entry_row = future.iloc[0]
    raw_entry = float(entry_row["Open"])
    if raw_entry <= 0:
        return None
    entry_price = apply_entry_price(raw_entry, side, slippage_bps, spread_bps)
    entry_date = future.index[0].date().isoformat()
    exit_trading_days = max(1, math.ceil(exit_hours / 6.5))

    bars_after = future.iloc[1:]
    exit_idx: int | None = None
    exit_reason = "end_of_data"

    for i, (_, bar) in enumerate(bars_after.iterrows()):
        close = float(bar["Close"])
        if side == "buy":
            move = (close - raw_entry) / raw_entry
        else:
            move = (raw_entry - close) / raw_entry

        if move <= -exit_adverse_pct:
            exit_idx = i
            exit_reason = "adverse_move"
            break

        if i + 1 >= exit_trading_days:
            exit_idx = i
            exit_reason = "time"
            break

    if exit_idx is not None:
        exit_row = bars_after.iloc[exit_idx]
        exit_date = bars_after.index[exit_idx].date().isoformat()
    elif not bars_after.empty:
        exit_row = bars_after.iloc[-1]
        exit_date = bars_after.index[-1].date().isoformat()
    else:
        exit_row = entry_row
        exit_date = entry_date

    raw_exit = float(exit_row["Close"])
    exit_price = apply_exit_price(raw_exit, side, slippage_bps, spread_bps)

    if side == "buy":
        pnl_pct = (exit_price - entry_price) / entry_price
    else:
        pnl_pct = (entry_price - exit_price) / entry_price
    pnl_dollar = dollar_size * pnl_pct

    hold_minutes = exit_hours * 60 if exit_idx is not None else 0.0

    return BacktestTrade(
        contract_slug=signal.contract_slug,
        signal_time=signal.timestamp.isoformat(),
        velocity=round(signal.velocity, 6),
        ticker=ticker,
        side=side,
        entry_date=entry_date,
        entry_price=round(entry_price, 4),
        exit_date=exit_date,
        exit_price=round(exit_price, 4),
        dollar_size=round(dollar_size, 2),
        pnl_dollar=round(pnl_dollar, 2),
        pnl_pct=round(pnl_pct, 6),
        exit_reason=exit_reason,
        hold_minutes=round(hold_minutes, 1),
    )


def compute_per_slug(trades: list[BacktestTrade], min_trades: int = 0) -> list[SlugBreakdown]:
    by_slug: dict[str, list[BacktestTrade]] = defaultdict(list)
    for t in trades:
        by_slug[t.contract_slug].append(t)
    result: list[SlugBreakdown] = []
    for slug, slug_trades in by_slug.items():
        if len(slug_trades) < min_trades:
            continue
        winning = sum(1 for t in slug_trades if t.pnl_dollar > 0)
        result.append(
            SlugBreakdown(
                contract_slug=slug,
                trade_count=len(slug_trades),
                win_rate=round(winning / len(slug_trades), 4),
                avg_pnl=round(sum(t.pnl_dollar for t in slug_trades) / len(slug_trades), 2),
                avg_hold_minutes=round(
                    sum(t.hold_minutes for t in slug_trades) / len(slug_trades), 1
                ),
            )
        )
    return sorted(result, key=lambda s: s.trade_count, reverse=True)


def compute_signal_decay_curve(trades: list[BacktestTrade]) -> list[dict]:
    bucket_size = 15
    max_minutes = 240
    buckets: dict[int, list[float]] = defaultdict(list)
    for t in trades:
        bucket = int(t.hold_minutes // bucket_size) * bucket_size
        bucket = min(bucket, max_minutes)
        buckets[bucket].append(t.pnl_dollar)
    result = []
    for b in range(0, max_minutes + 1, bucket_size):
        pnls = buckets.get(b, [])
        result.append(
            {
                "hold_minutes_bucket": b,
                "trade_count": len(pnls),
                "avg_pnl": round(sum(pnls) / len(pnls), 2) if pnls else 0.0,
            }
        )
    return result


def compute_summary(
    trades: list[BacktestTrade],
    num_signals: int,
    min_trades: int = 0,
    execution_assumptions: dict | None = None,
) -> BacktestSummary:
    if not trades:
        return BacktestSummary(
            num_signals=num_signals,
            num_trades=0,
            winning_trades=0,
            win_rate=0.0,
            total_pnl=0.0,
            avg_pnl_pct=0.0,
            sharpe=0.0,
            trades=[],
            per_slug=[],
            signal_decay_curve=[],
            execution_assumptions=execution_assumptions,
        )
    winning = sum(1 for t in trades if t.pnl_dollar > 0)
    total_pnl = sum(t.pnl_dollar for t in trades)
    returns = [t.pnl_pct for t in trades]
    avg_return = sum(returns) / len(returns)
    sharpe = _sharpe(returns)
    return BacktestSummary(
        num_signals=num_signals,
        num_trades=len(trades),
        winning_trades=winning,
        win_rate=round(winning / len(trades), 4),
        total_pnl=round(total_pnl, 2),
        avg_pnl_pct=round(avg_return, 6),
        sharpe=round(sharpe, 4),
        trades=trades,
        per_slug=compute_per_slug(trades, min_trades),
        signal_decay_curve=compute_signal_decay_curve(trades),
        execution_assumptions=execution_assumptions,
    )


def _sharpe(returns: list[float]) -> float:
    if len(returns) < 2:
        return 0.0
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    std = variance ** 0.5
    if std == 0.0:
        return 0.0
    return (mean / std) * (252 ** 0.5)


def _plot_results(trades: list[BacktestTrade], signals: list[VelocitySignal], output_path: str) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    if not trades:
        return

    trades_sorted = sorted(trades, key=lambda t: t.entry_date)
    dates = [t.entry_date for t in trades_sorted]
    cumulative_pnl = []
    running = 0.0
    for t in trades_sorted:
        running += t.pnl_dollar
        cumulative_pnl.append(running)

    signal_dates = [s.timestamp.date().isoformat() for s in signals]

    fig, ax = plt.subplots(figsize=(12, 6))
    ax.plot(range(len(cumulative_pnl)), cumulative_pnl, linewidth=2, label="Cumulative P&L")

    for sig_date in signal_dates:
        idxs = [i for i, d in enumerate(dates) if d == sig_date]
        for idx in idxs:
            ax.axvline(x=idx, color="orange", alpha=0.3, linewidth=0.8)

    ax.set_title("Backtest — Cumulative P&L with Signal Events")
    ax.set_xlabel("Trade #")
    ax.set_ylabel("P&L (USD)")
    ax.legend()
    ax.grid(True, alpha=0.3)

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"chart saved to {out}", file=sys.stderr)


def run_backtest(
    kalshi_csv: str,
    contract_map_path: str = "data/contract_equity_map.json",
    threshold: float = VELOCITY_THRESHOLD,
    window_minutes: int = VELOCITY_WINDOW_MINUTES,
    portfolio_value: float = PORTFOLIO_VALUE,
    max_position_pct: float = MAX_POSITION_PCT,
    min_trades: int = 0,
    slippage_bps: float = BACKTEST_SLIPPAGE_BPS,
    latency_seconds: float = BACKTEST_LATENCY_SECONDS,
    spread_bps: float = BACKTEST_SPREAD_BPS,
) -> tuple[BacktestSummary, list[VelocitySignal]]:
    kalshi_df = load_kalshi_csv(kalshi_csv)
    mapper = ContractMapper(contract_map_path)
    signals = replay_signals(kalshi_df, mapper, threshold, window_minutes)

    execution_assumptions = {
        "slippage_bps": slippage_bps,
        "latency_seconds": latency_seconds,
        "spread_bps": spread_bps,
        "total_cost_bps": (2 * spread_bps) + (2 * slippage_bps),
    }

    if not signals:
        return compute_summary([], 0, min_trades, execution_assumptions), []

    all_baskets = [mapper.get_basket(s.contract_slug) for s in signals]
    all_tickers: list[str] = []
    for b in all_baskets:
        if b:
            all_tickers.extend(b.get("basket", []))
    equity_tickers = list(dict.fromkeys(all_tickers))

    ts_min = kalshi_df["timestamp"].min()
    ts_max = kalshi_df["timestamp"].max()
    start = (ts_min - timedelta(days=1)).strftime("%Y-%m-%d")
    end = (ts_max + timedelta(days=10)).strftime("%Y-%m-%d")
    equity_data = fetch_equity_ohlcv(equity_tickers, start, end)

    trades: list[BacktestTrade] = []
    for signal, basket in zip(signals, all_baskets):
        if basket is None:
            continue
        side = determine_side(signal.velocity, basket["direction"])
        sizes = size_basket(basket, portfolio_value, max_position_pct)
        for ticker, dollar_size in sizes.items():
            eq_df = equity_data.get(ticker)
            if eq_df is None:
                continue
            trade = simulate_trade(
                signal=signal,
                ticker=ticker,
                side=side,
                dollar_size=dollar_size,
                equity_df=eq_df,
                exit_hours=float(basket.get("exit_hours", 2.0)),
                exit_adverse_pct=float(basket.get("exit_adverse_pct", 0.03)),
                slippage_bps=slippage_bps,
                latency_seconds=latency_seconds,
                spread_bps=spread_bps,
            )
            if trade is not None:
                trades.append(trade)

    return compute_summary(trades, len(signals), min_trades, execution_assumptions), signals


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay velocity signals against historical data.")
    parser.add_argument("--kalshi-csv", required=True, help="Path to Kalshi price history CSV")
    parser.add_argument("--contract-map", default="data/contract_equity_map.json")
    parser.add_argument("--threshold", type=float, default=VELOCITY_THRESHOLD)
    parser.add_argument("--window-minutes", type=int, default=VELOCITY_WINDOW_MINUTES)
    parser.add_argument("--portfolio-value", type=float, default=PORTFOLIO_VALUE)
    parser.add_argument("--max-position-pct", type=float, default=MAX_POSITION_PCT)
    parser.add_argument("--output", default=None, help="Write JSON results to this path")
    parser.add_argument("--plot", action="store_true", help="Generate cumulative P&L chart")
    parser.add_argument(
        "--min-trades", type=int, default=5,
        help="Exclude slugs with fewer than N trades from per-slug summary (default: 5)"
    )
    parser.add_argument(
        "--slippage-bps", type=float, default=None,
        help="Entry/exit slippage in basis points (default from env)"
    )
    parser.add_argument(
        "--latency-seconds", type=float, default=None,
        help="Execution latency in seconds (default from env)"
    )
    parser.add_argument(
        "--spread-bps", type=float, default=None,
        help="One-way spread cost in basis points (default from env)"
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--realistic",
        action="store_true",
        help="Use realistic execution: slippage=10bps, latency=5s, spread=5bps",
    )
    mode.add_argument(
        "--optimistic",
        action="store_true",
        help="Use optimistic execution: all costs set to 0 for comparison",
    )
    args = parser.parse_args()

    if args.realistic:
        slippage_bps = 10.0
        latency_seconds = 5.0
        spread_bps = 5.0
    elif args.optimistic:
        slippage_bps = 0.0
        latency_seconds = 0.0
        spread_bps = 0.0
    else:
        slippage_bps = args.slippage_bps if args.slippage_bps is not None else BACKTEST_SLIPPAGE_BPS
        latency_seconds = args.latency_seconds if args.latency_seconds is not None else BACKTEST_LATENCY_SECONDS
        spread_bps = args.spread_bps if args.spread_bps is not None else BACKTEST_SPREAD_BPS

    summary, signals = run_backtest(
        kalshi_csv=args.kalshi_csv,
        contract_map_path=args.contract_map,
        threshold=args.threshold,
        window_minutes=args.window_minutes,
        portfolio_value=args.portfolio_value,
        max_position_pct=args.max_position_pct,
        min_trades=args.min_trades,
        slippage_bps=slippage_bps,
        latency_seconds=latency_seconds,
        spread_bps=spread_bps,
    )

    if args.plot:
        _plot_results(summary.trades, signals, "results/backtest_chart.png")

    result = {
        "summary": {
            "num_signals": summary.num_signals,
            "num_trades": summary.num_trades,
            "winning_trades": summary.winning_trades,
            "win_rate": summary.win_rate,
            "total_pnl": summary.total_pnl,
            "avg_pnl_pct": summary.avg_pnl_pct,
            "sharpe": summary.sharpe,
        },
        "execution_assumptions": summary.execution_assumptions or {},
        "per_slug": [asdict(s) for s in (summary.per_slug or [])],
        "signal_decay_curve": summary.signal_decay_curve or [],
        "trades": [asdict(t) for t in summary.trades],
    }

    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps(result, indent=2))
        print(f"results written to {args.output}", file=sys.stderr)
    else:
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
