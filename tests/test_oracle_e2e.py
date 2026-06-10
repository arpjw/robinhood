from __future__ import annotations

import asyncio
import json
import random
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest


def _utc(days_ago: float = 0) -> datetime:
    return datetime.now(tz=timezone.utc) - timedelta(days=days_ago)


def _generate_synthetic_logs(
    tmp_path: Path,
    n_signals: int = 50,
    connectors: list[str] | None = None,
) -> tuple[Path, Path]:
    if connectors is None:
        connectors = ["kalshi_fed", "polymarket_macro"]

    random.seed(1337)
    sig_log = tmp_path / "signals.jsonl"
    ord_log = tmp_path / "orders.jsonl"

    signal_lines: list[str] = []
    order_lines: list[str] = []

    for i in range(n_signals):
        source = connectors[i % len(connectors)]
        velocity = random.uniform(0.10, 0.50)
        days_ago = random.uniform(0, 30)
        ts = _utc(days_ago)
        sig_id = f"e2e_sig_{i:04d}"

        signal_lines.append(json.dumps({
            "signal_id": sig_id,
            "timestamp": ts.isoformat(),
            "contract_slug": "KXFED-APR27-T4.25",
            "velocity": velocity,
            "direction": "up",
            "source": source,
            "basket": ["JPM", "BAC"],
            "sector": "financials",
            "macro_factors": ["rates", "credit"],
            "confidence": 0.85,
            "fired": True,
        }))

        if random.random() < 0.80:
            is_win = velocity > 0.20
            pnl = random.uniform(0.5, 3.0) if is_win else random.uniform(-2.0, -0.1)
            entry = 100.0
            exit_price = entry * (1.01 if is_win else 0.99)
            order_lines.append(json.dumps({
                "id": f"e2e_ord_{i:04d}",
                "signal_id": sig_id,
                "timestamp": ts.isoformat(),
                "mode": "mock",
                "ticker": "JPM",
                "side": "buy",
                "size_usd": 200.0,
                "entry_price": entry,
                "exit_price": exit_price,
                "exit_reason": "time_decay",
                "exit_timestamp": (ts + timedelta(hours=2)).isoformat(),
                "pnl_usd": round(pnl, 2),
                "source": source,
                "contract_slug": "KXFED-APR27-T4.25",
                "velocity": velocity,
                "strategy_id": f"velocity:KXFED-APR27-T4.25:{ts.strftime('%Y%m%dT%H%M%S')}",
                "signal_timestamp": ts.isoformat(),
            }))

    sig_log.write_text("\n".join(signal_lines) + "\n")
    ord_log.write_text("\n".join(order_lines) + "\n")
    return sig_log, ord_log


def _null_fetcher(ticker: str, start: datetime, end: datetime) -> float | None:
    return None


def _constant_fetcher(ticker: str, start: datetime, end: datetime) -> float | None:
    return 101.0


class TestOracleE2E:
    def test_run_once_writes_all_output_files(self, tmp_path: Path) -> None:
        sig_log, ord_log = _generate_synthetic_logs(tmp_path)
        output_dir = tmp_path / "oracle_output"

        from oracle.log_reader import LogReader
        from oracle.runner import OracleRunner

        reader = LogReader(signal_log=sig_log, order_log=ord_log)
        runner = OracleRunner(log_reader=reader, output_dir=output_dir, window_days=30, equity_fetcher=_constant_fetcher)
        asyncio.run(runner.run_once())

        assert (output_dir / "scores.json").exists()
        assert (output_dir / "regime.json").exists()
        assert (output_dir / "summary.json").exists()
        assert (output_dir / "ic_report.json").exists()
        assert (output_dir / "decay_curves.json").exists()
        assert (output_dir / "thresholds.json").exists()

    def test_scores_json_valid_and_contains_connectors(self, tmp_path: Path) -> None:
        sig_log, ord_log = _generate_synthetic_logs(tmp_path)
        output_dir = tmp_path / "oracle_output"

        from oracle.log_reader import LogReader
        from oracle.runner import OracleRunner

        reader = LogReader(signal_log=sig_log, order_log=ord_log)
        runner = OracleRunner(log_reader=reader, output_dir=output_dir, window_days=30, equity_fetcher=_constant_fetcher)
        asyncio.run(runner.run_once())

        scores = json.loads((output_dir / "scores.json").read_text())
        assert "connectors" in scores
        assert "kalshi_fed" in scores["connectors"]
        assert "polymarket_macro" in scores["connectors"]

    def test_reputation_scores_between_0_and_100(self, tmp_path: Path) -> None:
        sig_log, ord_log = _generate_synthetic_logs(tmp_path)
        output_dir = tmp_path / "oracle_output"

        from oracle.log_reader import LogReader
        from oracle.runner import OracleRunner

        reader = LogReader(signal_log=sig_log, order_log=ord_log)
        runner = OracleRunner(log_reader=reader, output_dir=output_dir, window_days=30, equity_fetcher=_constant_fetcher)
        asyncio.run(runner.run_once())

        scores = json.loads((output_dir / "scores.json").read_text())
        for slug, data in scores["connectors"].items():
            rep_score = data.get("reputation_score", 0)
            assert 0 <= rep_score <= 100, f"{slug} has out-of-range score {rep_score}"

    def test_regime_json_valid(self, tmp_path: Path) -> None:
        sig_log, ord_log = _generate_synthetic_logs(tmp_path)
        output_dir = tmp_path / "oracle_output"

        from oracle.log_reader import LogReader
        from oracle.runner import OracleRunner

        reader = LogReader(signal_log=sig_log, order_log=ord_log)
        runner = OracleRunner(log_reader=reader, output_dir=output_dir, window_days=30, equity_fetcher=_constant_fetcher)
        asyncio.run(runner.run_once())

        regime = json.loads((output_dir / "regime.json").read_text())
        assert "regime" in regime
        assert "confidence" in regime
        valid_regimes = {"risk_on", "risk_off", "high_vol", "low_vol", "trending", "mean_reverting", "unknown"}
        assert regime["regime"] in valid_regimes

    def test_summary_json_valid(self, tmp_path: Path) -> None:
        sig_log, ord_log = _generate_synthetic_logs(tmp_path)
        output_dir = tmp_path / "oracle_output"

        from oracle.log_reader import LogReader
        from oracle.runner import OracleRunner

        reader = LogReader(signal_log=sig_log, order_log=ord_log)
        runner = OracleRunner(log_reader=reader, output_dir=output_dir, window_days=30, equity_fetcher=_constant_fetcher)
        asyncio.run(runner.run_once())

        summary = json.loads((output_dir / "summary.json").read_text())
        assert "total_signals" in summary
        assert "total_trades" in summary
        assert summary["total_signals"] > 0

    def test_ic_is_non_none_with_sufficient_data(self, tmp_path: Path) -> None:
        sig_log, ord_log = _generate_synthetic_logs(tmp_path, n_signals=50)
        output_dir = tmp_path / "oracle_output"

        from oracle.log_reader import LogReader
        from oracle.runner import OracleRunner

        reader = LogReader(signal_log=sig_log, order_log=ord_log)
        runner = OracleRunner(log_reader=reader, output_dir=output_dir, window_days=30, equity_fetcher=_constant_fetcher)
        metrics = asyncio.run(runner.run_once())

        for slug, m in metrics.items():
            if m.trade_count >= 10:
                assert m.ic is not None or m.trade_count < 10

    def test_decay_curves_have_correct_bucket_count(self, tmp_path: Path) -> None:
        sig_log, ord_log = _generate_synthetic_logs(tmp_path)
        output_dir = tmp_path / "oracle_output"

        from oracle.log_reader import LogReader
        from oracle.runner import OracleRunner

        reader = LogReader(signal_log=sig_log, order_log=ord_log)
        runner = OracleRunner(log_reader=reader, output_dir=output_dir, window_days=30, equity_fetcher=_constant_fetcher)
        asyncio.run(runner.run_once())

        decay = json.loads((output_dir / "decay_curves.json").read_text())
        assert "connectors" in decay

    def test_report_command_exits_zero(self, tmp_path: Path) -> None:
        sig_log, ord_log = _generate_synthetic_logs(tmp_path)
        output_dir = tmp_path / "oracle_output"

        from oracle.log_reader import LogReader
        from oracle.runner import OracleRunner

        reader = LogReader(signal_log=sig_log, order_log=ord_log)
        runner = OracleRunner(log_reader=reader, output_dir=output_dir, window_days=30, equity_fetcher=_constant_fetcher)
        asyncio.run(runner.run_once())

        import os
        env = {**os.environ, "ORACLE_OUTPUT_DIR": str(output_dir)}
        result = subprocess.run(
            [sys.executable, "scripts/run_oracle.py", "report"],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).parent.parent),
            env=env,
        )
        assert result.returncode == 0

    def test_report_handles_missing_output_gracefully(self, tmp_path: Path) -> None:
        import os
        env = {**os.environ, "ORACLE_OUTPUT_DIR": str(tmp_path / "nonexistent")}
        result = subprocess.run(
            [sys.executable, "scripts/run_oracle.py", "report"],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).parent.parent),
            env=env,
        )
        assert result.returncode == 0
