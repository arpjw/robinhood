#!/usr/bin/env python3
"""
Live performance dashboard. Reads logs/orders.jsonl and displays metrics.

Usage:
    python scripts/dashboard.py
    python scripts/dashboard.py --since 2026-01-01
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from rich.columns import Columns
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

load_dotenv()

ORDER_LOG_PATH = Path(os.getenv("ORDER_LOG_PATH", "logs/orders.jsonl"))
SIGNAL_LOG_PATH = Path(os.getenv("SIGNAL_LOG_PATH", "logs/signals.jsonl"))
ORACLE_OUTPUT_DIR = Path(os.getenv("ORACLE_OUTPUT_DIR", "oracle/output"))
REFRESH_SECONDS = 5
ORACLE_STALE_MINUTES = 10


def _parse_iso(s: str) -> datetime:
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return datetime.now(tz=timezone.utc)


def load_orders(log_path: Path, since: datetime | None = None) -> list[dict]:
    if not log_path.exists():
        return []
    records: dict[str, dict] = {}
    for line in log_path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
            records[rec["id"]] = rec
        except (json.JSONDecodeError, KeyError):
            continue
    orders = list(records.values())
    if since:
        orders = [o for o in orders if _parse_iso(o.get("timestamp", "")).replace(tzinfo=timezone.utc if _parse_iso(o.get("timestamp", "")).tzinfo is None else None) >= since]
    return orders


def load_recent_activity(order_log: Path, signal_log: Path, n: int = 10) -> list[dict]:
    entries: list[dict] = []
    for path, kind in [(signal_log, "signal"), (order_log, "order")]:
        if not path.exists():
            continue
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                rec["_kind"] = kind
                entries.append(rec)
            except json.JSONDecodeError:
                continue
    entries.sort(key=lambda e: e.get("timestamp", ""), reverse=True)
    return entries[:n]


def get_current_prices(tickers: list[str]) -> dict[str, float]:
    if not tickers:
        return {}
    try:
        import yfinance as yf
    except ImportError:
        return {}
    prices: dict[str, float] = {}
    for ticker in tickers:
        try:
            info = yf.Ticker(ticker).fast_info
            price = getattr(info, "last_price", None)
            if price is not None:
                prices[ticker] = float(price)
        except Exception:
            pass
    return prices


def build_summary_panel(orders: list[dict]) -> Panel:
    closed = [o for o in orders if o.get("pnl_usd") is not None]
    open_orders = [o for o in orders if o.get("pnl_usd") is None and o.get("exit_reason") is None]
    wins = [o for o in closed if (o.get("pnl_usd") or 0) > 0]
    total_pnl = sum(o.get("pnl_usd") or 0 for o in closed)
    win_rate = len(wins) / len(closed) if closed else 0.0
    hold_times = [
        (
            _parse_iso(o.get("exit_timestamp", "")) - _parse_iso(o.get("timestamp", ""))
        ).total_seconds() / 60.0
        for o in closed
        if o.get("exit_timestamp") and o.get("timestamp")
    ]
    avg_hold = sum(hold_times) / len(hold_times) if hold_times else 0.0

    t = Table.grid(padding=(0, 2))
    t.add_column(style="bold cyan")
    t.add_column()
    t.add_row("Total orders placed:", str(len(orders)))
    t.add_row("Open positions:", str(len(open_orders)))
    t.add_row("Closed positions:", str(len(closed)))
    t.add_row("Total realized P&L:", f"[{'green' if total_pnl >= 0 else 'red'}]${total_pnl:.2f}[/]")
    t.add_row("Win rate:", f"{win_rate:.1%}")
    t.add_row("Avg hold time:", f"{avg_hold:.1f}m")

    return Panel(t, title="[bold]Summary[/bold]", border_style="blue")


def build_per_contract_table(orders: list[dict]) -> Panel:
    closed = [o for o in orders if o.get("pnl_usd") is not None]
    by_slug: dict[str, list[dict]] = defaultdict(list)
    for o in closed:
        by_slug[o.get("contract_slug", "unknown")].append(o)

    table = Table(show_header=True, header_style="bold magenta", expand=True)
    table.add_column("Contract")
    table.add_column("Trades", justify="right")
    table.add_column("Wins", justify="right")
    table.add_column("Win%", justify="right")
    table.add_column("Avg P&L", justify="right")
    table.add_column("Avg Hold", justify="right")
    table.add_column("Best", justify="right")
    table.add_column("Worst", justify="right")

    sorted_slugs = sorted(by_slug.items(), key=lambda x: len(x[1]), reverse=True)
    for slug, trades in sorted_slugs:
        pnls = [o.get("pnl_usd") or 0 for o in trades]
        wins = sum(1 for p in pnls if p > 0)
        win_rate = wins / len(trades) if trades else 0.0
        avg_pnl = sum(pnls) / len(pnls) if pnls else 0.0
        best = max(pnls) if pnls else 0.0
        worst = min(pnls) if pnls else 0.0

        hold_times = [
            (_parse_iso(o.get("exit_timestamp", "")) - _parse_iso(o.get("timestamp", ""))).total_seconds() / 60.0
            for o in trades
            if o.get("exit_timestamp") and o.get("timestamp")
        ]
        avg_hold = sum(hold_times) / len(hold_times) if hold_times else 0.0

        avg_style = "green" if avg_pnl >= 0 else "red"
        table.add_row(
            slug,
            str(len(trades)),
            str(wins),
            f"{win_rate:.1%}",
            f"[{avg_style}]${avg_pnl:.2f}[/]",
            f"{avg_hold:.1f}m",
            f"[green]${best:.2f}[/]",
            f"[red]${worst:.2f}[/]",
        )

    return Panel(table, title="[bold]Per-Contract Breakdown[/bold]", border_style="magenta")


def build_threshold_panel(orders: list[dict]) -> Panel:
    closed = [o for o in orders if o.get("pnl_usd") is not None]
    buckets = [
        ("0.15-0.20", 0.15, 0.20),
        ("0.20-0.30", 0.20, 0.30),
        ("0.30-0.50", 0.30, 0.50),
        ("0.50+", 0.50, float("inf")),
    ]

    table = Table(show_header=True, header_style="bold yellow", expand=True)
    table.add_column("Velocity Bucket")
    table.add_column("Trades", justify="right")
    table.add_column("Win%", justify="right")
    table.add_column("Avg P&L", justify="right")

    for label, lo, hi in buckets:
        bucket_trades = [
            o for o in closed
            if lo <= abs(o.get("velocity") or 0) < hi
        ]
        if not bucket_trades:
            table.add_row(label, "0", "—", "—")
            continue
        pnls = [o.get("pnl_usd") or 0 for o in bucket_trades]
        wins = sum(1 for p in pnls if p > 0)
        win_rate = wins / len(bucket_trades)
        avg_pnl = sum(pnls) / len(pnls)
        style = "green" if avg_pnl >= 0 else "red"
        table.add_row(
            label,
            str(len(bucket_trades)),
            f"{win_rate:.1%}",
            f"[{style}]${avg_pnl:.2f}[/]",
        )

    return Panel(table, title="[bold]Velocity Threshold Analysis[/bold]", border_style="yellow")


def build_open_positions_panel(orders: list[dict]) -> Panel:
    open_orders = [o for o in orders if o.get("pnl_usd") is None and o.get("exit_reason") is None]
    tickers = list({o.get("ticker") for o in open_orders if o.get("ticker")})
    current_prices = get_current_prices(tickers)
    now = datetime.now(tz=timezone.utc)

    table = Table(show_header=True, header_style="bold cyan", expand=True)
    table.add_column("Ticker")
    table.add_column("Side")
    table.add_column("Entry Time")
    table.add_column("Hold", justify="right")
    table.add_column("Entry Price", justify="right")
    table.add_column("Current", justify="right")
    table.add_column("Unreal. P&L", justify="right")

    for o in open_orders:
        ticker = o.get("ticker", "?")
        side = o.get("side", "?")
        entry_time = o.get("timestamp", "")
        entry_dt = _parse_iso(entry_time)
        hold_min = (now - entry_dt.replace(tzinfo=timezone.utc if entry_dt.tzinfo is None else None)).total_seconds() / 60.0
        entry_price = o.get("entry_price")
        current = current_prices.get(ticker)
        size_usd = o.get("size_usd") or 0
        upnl: float | None = None
        if entry_price and current:
            shares = o.get("size_shares") or (size_usd / entry_price if entry_price > 0 else 0)
            if side == "buy":
                upnl = (current - entry_price) * shares
            else:
                upnl = (entry_price - current) * shares
        upnl_str = f"[{'green' if (upnl or 0) >= 0 else 'red'}]${upnl:.2f}[/]" if upnl is not None else "—"
        table.add_row(
            ticker,
            side,
            entry_time[:16],
            f"{hold_min:.0f}m",
            f"${entry_price:.4f}" if entry_price else "—",
            f"${current:.4f}" if current else "—",
            upnl_str,
        )

    return Panel(table, title="[bold]Open Positions[/bold]", border_style="cyan")


def build_activity_panel(order_log: Path, signal_log: Path) -> Panel:
    entries = load_recent_activity(order_log, signal_log)
    table = Table(show_header=True, header_style="bold white", expand=True)
    table.add_column("Time")
    table.add_column("Type")
    table.add_column("Details")

    for e in entries:
        ts = e.get("timestamp", "")[:16]
        kind = e.get("_kind", "?")
        if kind == "signal":
            details = (
                f"{e.get('contract_slug', '?')} "
                f"vel={e.get('velocity', 0):.3f}"
            )
            style = "yellow"
        else:
            details = (
                f"{e.get('ticker', '?')} {e.get('side', '?')} "
                f"${e.get('size_usd', 0):.2f}"
            )
            style = "white"
        table.add_row(ts, f"[{style}]{kind}[/]", details)

    return Panel(table, title="[bold]Recent Activity[/bold]", border_style="white")


def _load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _is_stale(computed_at: str | None) -> bool:
    if not computed_at:
        return True
    try:
        ts = datetime.fromisoformat(computed_at)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age_minutes = (datetime.now(tz=timezone.utc) - ts).total_seconds() / 60
        return age_minutes > ORACLE_STALE_MINUTES
    except Exception:
        return True


def build_oracle_scores_panel(oracle_dir: Path) -> Panel:
    scores_path = oracle_dir / "scores.json"
    if not scores_path.exists():
        return Panel(
            "[dim]Oracle not running. Start with:\n  python scripts/run_oracle.py[/dim]",
            title="[bold]ORACLE: CONNECTOR SCORES[/bold]",
            border_style="dim",
        )

    scores = _load_json(scores_path)
    if scores is None:
        return Panel("[red]Failed to read scores.json[/red]", title="[bold]ORACLE: CONNECTOR SCORES[/bold]")

    stale = _is_stale(scores.get("computed_at"))
    title = "[bold]ORACLE: CONNECTOR SCORES[/bold]"
    if stale:
        title += " [yellow][STALE][/yellow]"

    label_colors = {
        "EXCELLENT": "bright_green",
        "GOOD": "green",
        "MODERATE": "yellow",
        "WEAK": "orange1",
        "POOR": "red",
    }

    table = Table(show_header=True, header_style="bold magenta", expand=True)
    table.add_column("Connector")
    table.add_column("Score", justify="right")
    table.add_column("Label")
    table.add_column("Trades", justify="right")
    table.add_column("Win%", justify="right")
    table.add_column("IC", justify="right")
    table.add_column("Sharpe", justify="right")
    table.add_column("Updated")

    connectors = scores.get("connectors", {})
    sorted_connectors = sorted(
        connectors.items(),
        key=lambda x: x[1].get("reputation_score", 0),
        reverse=True,
    )
    computed_at = scores.get("computed_at", "—")[:16]
    for slug, data in sorted_connectors:
        lbl = data.get("reputation_label", "—")
        color = label_colors.get(lbl, "white")
        ic_val = data.get("ic")
        sharpe_val = data.get("sharpe")
        win_rate = data.get("win_rate")
        table.add_row(
            slug,
            str(data.get("reputation_score", 0)),
            f"[{color}]{lbl}[/]",
            str(data.get("trade_count", 0)),
            f"{win_rate:.1%}" if win_rate is not None else "—",
            f"{ic_val:.3f}" if ic_val is not None else "—",
            f"{sharpe_val:.2f}" if sharpe_val is not None else "—",
            computed_at,
        )

    return Panel(table, title=title, border_style="magenta")


def build_oracle_regime_panel(oracle_dir: Path) -> Panel:
    regime_path = oracle_dir / "regime.json"
    summary_path = oracle_dir / "summary.json"

    regime = _load_json(regime_path)
    summary = _load_json(summary_path)

    if regime is None and summary is None:
        return Panel(
            "[dim]No regime data.[/dim]",
            title="[bold]ORACLE: REGIME + RECOMMENDATIONS[/bold]",
            border_style="dim",
        )

    stale = _is_stale((regime or {}).get("detected_at"))
    title = "[bold]ORACLE: REGIME + RECOMMENDATIONS[/bold]"
    if stale:
        title += " [yellow][STALE][/yellow]"

    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="bold cyan")
    grid.add_column()

    if regime:
        regime_name = (regime.get("regime") or "unknown").upper()
        conf = regime.get("confidence", 0)
        grid.add_row("Regime:", f"[bold]{regime_name}[/bold] ({conf:.1%} confidence)")

        eff_thresh = regime.get("effective_threshold")
        eff_pos = regime.get("effective_position_pct")
        base_thresh = float(os.getenv("VELOCITY_THRESHOLD", "0.15"))
        base_pos = float(os.getenv("MAX_POSITION_PCT", "0.05"))

        thresh_str = f"{eff_thresh}"
        if eff_thresh is not None and abs(eff_thresh - base_thresh) > 0.001:
            thresh_str = f"[yellow]{eff_thresh}[/yellow]"

        pos_str = f"{eff_pos:.1%}" if eff_pos is not None else "—"
        if eff_pos is not None and abs(eff_pos - base_pos) > 0.001:
            pos_str = f"[yellow]{pos_str}[/yellow]"

        grid.add_row("Eff. Threshold:", thresh_str)
        grid.add_row("Eff. Position:", pos_str)
        detected = (regime.get("detected_at") or "")[:16]
        grid.add_row("Last computed:", detected)

    if summary:
        recs = summary.get("recommendations", [])[:5]
        if recs:
            grid.add_row("", "")
            grid.add_row("[bold]Recommendations:[/bold]", "")
            for rec in recs:
                grid.add_row("  •", rec[:80])

    return Panel(grid, title=title, border_style="cyan")


def render(since: datetime | None = None) -> Layout:
    orders = load_orders(ORDER_LOG_PATH, since)

    layout = Layout()
    layout.split_column(
        Layout(name="top", size=10),
        Layout(name="mid", size=14),
        Layout(name="bottom"),
        Layout(name="oracle_row", size=12),
    )
    layout["top"].update(build_summary_panel(orders))
    layout["mid"].split_row(
        Layout(build_per_contract_table(orders), name="per_contract"),
        Layout(build_threshold_panel(orders), name="threshold"),
    )
    layout["bottom"].split_column(
        Layout(build_open_positions_panel(orders), name="open", size=12),
        Layout(build_activity_panel(ORDER_LOG_PATH, SIGNAL_LOG_PATH), name="activity"),
    )
    layout["oracle_row"].split_row(
        Layout(build_oracle_scores_panel(ORACLE_OUTPUT_DIR), name="oracle_scores"),
        Layout(build_oracle_regime_panel(ORACLE_OUTPUT_DIR), name="oracle_regime"),
    )
    return layout


def main() -> None:
    parser = argparse.ArgumentParser(description="Live P&L dashboard")
    parser.add_argument(
        "--since",
        default=None,
        help="Filter to entries since this ISO date (e.g. 2026-01-01)",
    )
    args = parser.parse_args()

    since: datetime | None = None
    if args.since:
        try:
            since = datetime.fromisoformat(args.since).replace(tzinfo=timezone.utc)
        except ValueError:
            print(f"Invalid date: {args.since}", file=sys.stderr)
            sys.exit(1)

    console = Console()
    with Live(render(since), console=console, refresh_per_second=0.2) as live:
        while True:
            time.sleep(REFRESH_SECONDS)
            live.update(render(since))


if __name__ == "__main__":
    main()
