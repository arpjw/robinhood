#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncio
import json
import logging
import os
import signal

from dotenv import load_dotenv

load_dotenv()

import typer
from rich.console import Console
from rich.table import Table
from rich.text import Text

app = typer.Typer(add_completion=False)
console = Console()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)


def _make_runner(
    window_days: int,
    output_dir: Path,
    publish: bool,
) -> "OracleRunner":
    from oracle.log_reader import LogReader
    from oracle.runner import OracleRunner

    reader = LogReader()
    return OracleRunner(
        log_reader=reader,
        window_days=window_days,
        output_dir=output_dir,
        publish=publish,
    )


@app.command()
def run(
    window_days: int = typer.Option(30, "--window-days", help="Evaluation window in days"),
    interval: int = typer.Option(300, "--interval", help="Seconds between runs (continuous mode)"),
    once: bool = typer.Option(False, "--once", help="Run once and exit"),
    publish: bool = typer.Option(False, "--publish", help="Push scores to Prism registry"),
    output_dir: Path = typer.Option(Path("oracle/output"), "--output-dir", help="Output directory"),
) -> None:
    runner = _make_runner(window_days, output_dir, publish)

    def _handle_sigint(sig: int, frame: object) -> None:
        summary_path = output_dir / "summary.json"
        if summary_path.exists():
            try:
                summary = json.loads(summary_path.read_text())
                console.print("\n[bold]Final Summary[/bold]")
                console.print(f"Signals: {summary.get('total_signals', 0)}")
                console.print(f"Trades: {summary.get('total_trades', 0)}")
                console.print(f"Win rate: {summary.get('overall_win_rate', 0):.1%}")
                console.print(f"Regime: {summary.get('regime', 'unknown')}")
            except Exception:
                pass
        sys.exit(0)

    signal.signal(signal.SIGINT, _handle_sigint)

    if once:
        metrics = asyncio.run(runner.run_once())
        _print_summary(output_dir)
        sys.exit(0)
    else:
        asyncio.run(runner.run_continuous(interval_seconds=interval))


@app.command()
def report(
    connector: str = typer.Option("", "--connector", help="Specific connector slug (default: all)"),
    format: str = typer.Option("table", "--format", help="Output format: table or json"),
) -> None:
    output_dir = Path(os.getenv("ORACLE_OUTPUT_DIR", "oracle/output"))

    scores_path = output_dir / "scores.json"
    regime_path = output_dir / "regime.json"
    summary_path = output_dir / "summary.json"

    if not scores_path.exists():
        console.print("[yellow]Oracle output not found. Run first with:[/yellow]")
        console.print("  python scripts/run_oracle.py run --once")
        raise typer.Exit(0)

    try:
        scores = json.loads(scores_path.read_text())
    except Exception as exc:
        console.print(f"[red]Failed to read scores.json: {exc}[/red]")
        raise typer.Exit(1)

    if format == "json":
        console.print_json(scores_path.read_text())
        return

    regime_data: dict = {}
    if regime_path.exists():
        try:
            regime_data = json.loads(regime_path.read_text())
        except Exception:
            pass

    summary_data: dict = {}
    if summary_path.exists():
        try:
            summary_data = json.loads(summary_path.read_text())
        except Exception:
            pass

    if regime_data:
        regime_name = regime_data.get("regime", "unknown").upper()
        conf = regime_data.get("confidence", 0)
        console.print(f"\n[bold]Regime:[/bold] {regime_name} (confidence: {conf:.1%})")
        eff_thresh = regime_data.get("effective_threshold")
        eff_pos = regime_data.get("effective_position_pct")
        if eff_thresh is not None:
            console.print(f"  Effective threshold: {eff_thresh}  |  Effective position: {eff_pos:.1%}" if eff_pos else f"  Effective threshold: {eff_thresh}")

    console.print(f"\n[bold]Computed at:[/bold] {scores.get('computed_at', 'unknown')}")
    console.print(f"[bold]Window:[/bold] {scores.get('window_days', 30)} days\n")

    connectors_data = scores.get("connectors", {})
    if connector:
        if connector not in connectors_data:
            console.print(f"[red]Connector '{connector}' not found in report.[/red]")
            raise typer.Exit(1)
        connectors_data = {connector: connectors_data[connector]}

    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Connector")
    table.add_column("Score", justify="right")
    table.add_column("Label")
    table.add_column("Signals", justify="right")
    table.add_column("Trades", justify="right")
    table.add_column("Win%", justify="right")
    table.add_column("IC", justify="right")
    table.add_column("Sharpe", justify="right")

    label_colors = {
        "EXCELLENT": "bright_green",
        "GOOD": "green",
        "MODERATE": "yellow",
        "WEAK": "orange1",
        "POOR": "red",
    }

    sorted_connectors = sorted(
        connectors_data.items(),
        key=lambda x: x[1].get("reputation_score", 0),
        reverse=True,
    )
    for slug, data in sorted_connectors:
        lbl = data.get("reputation_label", "UNKNOWN")
        color = label_colors.get(lbl, "white")
        ic_val = data.get("ic")
        ic_str = f"{ic_val:.3f}" if ic_val is not None else "—"
        sharpe_val = data.get("sharpe")
        sharpe_str = f"{sharpe_val:.2f}" if sharpe_val is not None else "—"
        win_rate = data.get("win_rate")
        win_str = f"{win_rate:.1%}" if win_rate is not None else "—"
        table.add_row(
            slug,
            str(data.get("reputation_score", 0)),
            f"[{color}]{lbl}[/]",
            str(data.get("signal_count", 0)),
            str(data.get("trade_count", 0)),
            win_str,
            ic_str,
            sharpe_str,
        )

    console.print(table)

    if summary_data.get("recommendations"):
        console.print("\n[bold]Recommendations:[/bold]")
        for rec in summary_data["recommendations"][:5]:
            console.print(f"  • {rec}")


def _print_summary(output_dir: Path) -> None:
    summary_path = output_dir / "summary.json"
    if not summary_path.exists():
        return
    try:
        summary = json.loads(summary_path.read_text())
        console.print(f"\n[bold]Oracle run complete[/bold]")
        console.print(f"  Connectors: {summary.get('connectors_evaluated', 0)}")
        console.print(f"  Signals: {summary.get('total_signals', 0)}")
        console.print(f"  Trades: {summary.get('total_trades', 0)}")
        console.print(f"  Regime: {summary.get('regime', 'unknown')}")
        if summary.get("top_connector"):
            console.print(f"  Top connector: {summary['top_connector']} (score: {summary.get('top_score', 0)})")
    except Exception:
        pass


if __name__ == "__main__":
    app()
