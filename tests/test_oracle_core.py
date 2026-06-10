from __future__ import annotations

import asyncio
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from oracle.log_reader import LogReader
from oracle.models import OracleMetrics, OrderRecord, SignalRecord


def _utc(days_ago: int = 0, hours_ago: int = 0) -> datetime:
    return datetime.now(tz=timezone.utc) - timedelta(days=days_ago, hours=hours_ago)


def _make_signal_line(
    contract_slug: str = "KXFED-27APR-T4.25",
    velocity: float = 0.25,
    source: str = "kalshi_fed",
    timestamp: datetime | None = None,
    fired: bool = True,
) -> str:
    ts = timestamp or _utc()
    return json.dumps({
        "signal_id": f"sig_{hash(ts.isoformat())}",
        "timestamp": ts.isoformat(),
        "contract_slug": contract_slug,
        "velocity": velocity,
        "direction": "up",
        "source": source,
        "basket": ["JPM", "BAC"],
        "sector": "financials",
        "macro_factors": ["rates"],
        "confidence": 0.9,
        "fired": fired,
    })


def _make_order_line(
    signal_id: str = "test_sig_001",
    contract_slug: str = "KXFED-27APR-T4.25",
    source: str = "kalshi_fed",
    velocity: float = 0.25,
    pnl_usd: float | None = 1.5,
    timestamp: datetime | None = None,
) -> str:
    ts = timestamp or _utc()
    exit_ts = ts + timedelta(hours=1)
    return json.dumps({
        "id": f"ord_{hash(ts.isoformat())}",
        "signal_id": signal_id,
        "timestamp": ts.isoformat(),
        "mode": "mock",
        "ticker": "JPM",
        "side": "buy",
        "size_usd": 100.0,
        "entry_price": 150.0,
        "exit_price": 151.5 if pnl_usd and pnl_usd > 0 else 148.5,
        "exit_reason": "time_decay",
        "exit_timestamp": exit_ts.isoformat(),
        "pnl_usd": pnl_usd,
        "source": source,
        "contract_slug": contract_slug,
        "velocity": velocity,
        "strategy_id": f"velocity:{contract_slug}:{ts.strftime('%Y%m%dT%H%M%S')}",
        "signal_timestamp": ts.isoformat(),
    })


class TestLogReaderSignals:
    def test_parse_valid_jsonl(self, tmp_path: Path) -> None:
        log = tmp_path / "signals.jsonl"
        log.write_text(_make_signal_line() + "\n")
        reader = LogReader(signal_log=log)
        records = reader.read_signals()
        assert len(records) == 1
        assert records[0].contract_slug == "KXFED-27APR-T4.25"
        assert records[0].velocity == 0.25
        assert records[0].source == "kalshi_fed"

    def test_skips_malformed_lines(self, tmp_path: Path) -> None:
        log = tmp_path / "signals.jsonl"
        log.write_text("not json\n" + _make_signal_line() + "\n")
        reader = LogReader(signal_log=log)
        records = reader.read_signals()
        assert len(records) == 1

    def test_filter_by_connector_slug(self, tmp_path: Path) -> None:
        log = tmp_path / "signals.jsonl"
        log.write_text(
            _make_signal_line(source="kalshi_fed") + "\n"
            + _make_signal_line(source="polymarket_macro") + "\n"
        )
        reader = LogReader(signal_log=log)
        records = reader.read_signals(connector_slug="kalshi_fed")
        assert len(records) == 1
        assert records[0].source == "kalshi_fed"

    def test_filter_by_since(self, tmp_path: Path) -> None:
        log = tmp_path / "signals.jsonl"
        old = _utc(days_ago=10)
        recent = _utc(days_ago=1)
        log.write_text(
            _make_signal_line(timestamp=old) + "\n"
            + _make_signal_line(timestamp=recent) + "\n"
        )
        reader = LogReader(signal_log=log)
        cutoff = _utc(days_ago=5)
        records = reader.read_signals(since=cutoff)
        assert len(records) == 1

    def test_filter_by_until(self, tmp_path: Path) -> None:
        log = tmp_path / "signals.jsonl"
        old = _utc(days_ago=10)
        recent = _utc(days_ago=1)
        log.write_text(
            _make_signal_line(timestamp=old) + "\n"
            + _make_signal_line(timestamp=recent) + "\n"
        )
        reader = LogReader(signal_log=log)
        cutoff = _utc(days_ago=5)
        records = reader.read_signals(until=cutoff)
        assert len(records) == 1

    def test_returns_empty_when_file_missing(self, tmp_path: Path) -> None:
        reader = LogReader(signal_log=tmp_path / "missing.jsonl")
        assert reader.read_signals() == []

    def test_sorted_by_timestamp(self, tmp_path: Path) -> None:
        log = tmp_path / "signals.jsonl"
        t1 = _utc(hours_ago=2)
        t2 = _utc(hours_ago=1)
        log.write_text(
            _make_signal_line(timestamp=t2) + "\n"
            + _make_signal_line(timestamp=t1) + "\n"
        )
        reader = LogReader(signal_log=log)
        records = reader.read_signals()
        assert records[0].timestamp < records[1].timestamp


class TestLogReaderOrders:
    def test_parse_order_fields(self, tmp_path: Path) -> None:
        log = tmp_path / "orders.jsonl"
        log.write_text(_make_order_line() + "\n")
        reader = LogReader(order_log=log)
        orders = reader.read_orders()
        assert len(orders) == 1
        o = orders[0]
        assert o.ticker == "JPM"
        assert o.side == "buy"
        assert o.size_usd == 100.0
        assert o.entry_price == 150.0
        assert o.pnl_usd is not None

    def test_deduplicate_by_order_id(self, tmp_path: Path) -> None:
        log = tmp_path / "orders.jsonl"
        ts = _utc()
        line = _make_order_line(timestamp=ts)
        log.write_text(line + "\n" + line + "\n")
        reader = LogReader(order_log=log)
        orders = reader.read_orders()
        assert len(orders) == 1

    def test_skips_malformed_order_lines(self, tmp_path: Path) -> None:
        log = tmp_path / "orders.jsonl"
        log.write_text("{invalid}\n" + _make_order_line() + "\n")
        reader = LogReader(order_log=log)
        orders = reader.read_orders()
        assert len(orders) == 1


class TestLogReaderJoin:
    def test_join_links_signal_to_order(self, tmp_path: Path) -> None:
        sig_log = tmp_path / "signals.jsonl"
        ord_log = tmp_path / "orders.jsonl"
        ts = _utc()
        sig_id = f"sig_{abs(hash(ts.isoformat()))}"
        sig_log.write_text(json.dumps({
            "signal_id": sig_id,
            "timestamp": ts.isoformat(),
            "contract_slug": "KXFED",
            "velocity": 0.3,
            "source": "kalshi_fed",
            "fired": True,
        }) + "\n")
        ord_log.write_text(json.dumps({
            "id": "ord_001",
            "signal_id": sig_id,
            "timestamp": ts.isoformat(),
            "mode": "mock",
            "ticker": "JPM",
            "side": "buy",
            "size_usd": 100.0,
            "contract_slug": "KXFED",
            "velocity": 0.3,
            "strategy_id": "velocity:KXFED:20260601T120000",
            "signal_timestamp": ts.isoformat(),
        }) + "\n")
        reader = LogReader(signal_log=sig_log, order_log=ord_log)
        signals = reader.read_signals()
        orders = reader.read_orders()
        joined = reader.join(signals, orders)
        assert len(joined) == 1
        sig, ord_ = joined[0]
        assert ord_ is not None
        assert ord_.ticker == "JPM"

    def test_join_returns_none_for_unmatched_signal(self, tmp_path: Path) -> None:
        sig_log = tmp_path / "signals.jsonl"
        ord_log = tmp_path / "orders.jsonl"
        sig_log.write_text(_make_signal_line() + "\n")
        ord_log.write_text("")
        reader = LogReader(signal_log=sig_log, order_log=ord_log)
        signals = reader.read_signals()
        orders = reader.read_orders()
        joined = reader.join(signals, orders)
        assert len(joined) == 1
        _, ord_ = joined[0]
        assert ord_ is None

    def test_join_sorted_by_signal_timestamp(self, tmp_path: Path) -> None:
        sig_log = tmp_path / "signals.jsonl"
        ord_log = tmp_path / "orders.jsonl"
        t1, t2 = _utc(hours_ago=2), _utc(hours_ago=1)
        sig_log.write_text(
            _make_signal_line(timestamp=t2) + "\n"
            + _make_signal_line(timestamp=t1) + "\n"
        )
        ord_log.write_text("")
        reader = LogReader(signal_log=sig_log, order_log=ord_log)
        signals = reader.read_signals()
        joined = reader.join(signals, [])
        assert joined[0][0].timestamp < joined[1][0].timestamp


class TestIncrementalRead:
    def test_incremental_tracks_position(self, tmp_path: Path) -> None:
        sig_log = tmp_path / "signals.jsonl"
        sig_log.write_text(_make_signal_line() + "\n")
        reader = LogReader(signal_log=sig_log)
        first = reader.read_signals_incremental()
        assert len(first) == 1
        with sig_log.open("a") as f:
            f.write(_make_signal_line(velocity=0.5) + "\n")
        second = reader.read_signals_incremental()
        assert len(second) == 1
        assert second[0].velocity == 0.5

    def test_incremental_handles_rotation(self, tmp_path: Path) -> None:
        sig_log = tmp_path / "signals.jsonl"
        sig_log.write_text(_make_signal_line() + "\n")
        reader = LogReader(signal_log=sig_log)
        reader._signal_offset = 9999
        sig_log.write_text(_make_signal_line(velocity=0.9) + "\n")
        records = reader.read_signals_incremental()
        assert len(records) == 1


class TestOracleRunnerOutputs:
    def test_run_once_writes_output_files(self, tmp_path: Path) -> None:
        sig_log = tmp_path / "signals.jsonl"
        ord_log = tmp_path / "orders.jsonl"
        output_dir = tmp_path / "output"
        ts = _utc()
        sig_id = "sig_abc123"
        sig_log.write_text("\n".join([
            json.dumps({
                "signal_id": sig_id,
                "timestamp": (ts - timedelta(hours=i)).isoformat(),
                "contract_slug": "KXFED",
                "velocity": 0.3,
                "source": "kalshi_fed",
                "fired": True,
            })
            for i in range(5)
        ]) + "\n")
        ord_log.write_text("\n".join([
            json.dumps({
                "id": f"ord_{i}",
                "signal_id": sig_id,
                "timestamp": (ts - timedelta(hours=i)).isoformat(),
                "mode": "mock",
                "ticker": "JPM",
                "side": "buy",
                "size_usd": 100.0,
                "contract_slug": "KXFED",
                "velocity": 0.3,
                "pnl_usd": 1.0 if i % 2 == 0 else -0.5,
                "strategy_id": f"velocity:KXFED:20260601T12{i:02d}00",
                "signal_timestamp": (ts - timedelta(hours=i)).isoformat(),
            })
            for i in range(5)
        ]) + "\n")

        from oracle.log_reader import LogReader
        from oracle.runner import OracleRunner

        reader = LogReader(signal_log=sig_log, order_log=ord_log)
        runner = OracleRunner(log_reader=reader, output_dir=output_dir, window_days=30)
        asyncio.run(runner.run_once())

        assert (output_dir / "scores.json").exists()
        assert (output_dir / "ic_report.json").exists()
        assert (output_dir / "decay_curves.json").exists()
        assert (output_dir / "thresholds.json").exists()
        assert (output_dir / "regime.json").exists()
        assert (output_dir / "summary.json").exists()

    def test_output_files_are_valid_json(self, tmp_path: Path) -> None:
        sig_log = tmp_path / "signals.jsonl"
        ord_log = tmp_path / "orders.jsonl"
        output_dir = tmp_path / "output"
        sig_log.write_text(_make_signal_line() + "\n")
        ord_log.write_text("")

        from oracle.log_reader import LogReader
        from oracle.runner import OracleRunner

        reader = LogReader(signal_log=sig_log, order_log=ord_log)
        runner = OracleRunner(log_reader=reader, output_dir=output_dir)
        asyncio.run(runner.run_once())

        for fname in ["scores.json", "regime.json", "summary.json"]:
            content = (output_dir / fname).read_text()
            json.loads(content)

    def test_run_continuous_catches_exception(self, tmp_path: Path) -> None:
        from oracle.log_reader import LogReader
        from oracle.runner import OracleRunner

        reader = LogReader(
            signal_log=tmp_path / "missing_signals.jsonl",
            order_log=tmp_path / "missing_orders.jsonl",
        )
        runner = OracleRunner(log_reader=reader, output_dir=tmp_path / "output")

        async def _run_briefly() -> None:
            task = asyncio.create_task(runner.run_continuous(interval_seconds=1))
            await asyncio.sleep(0.1)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        asyncio.run(_run_briefly())
