import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from applog.logger import Logger
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


def make_order() -> OrderRecord:
    return OrderRecord(
        id="test-order-1",
        timestamp="2026-01-01T00:00:00+00:00",
        mode="mock",
        strategy_id="s1",
        ticker="AAPL",
        side="buy",
        size_usd=100.0,
        contract_slug="KXFED",
        velocity=0.25,
        signal_timestamp="2026-01-01T00:00:00+00:00",
    )


def test_log_signal_writes_jsonl(tmp_path: Path, capsys) -> None:
    log = Logger(signal_log=tmp_path / "signals.jsonl", order_log=tmp_path / "orders.jsonl")
    sig = make_signal()
    log.log_signal(sig, source="kalshi")
    lines = (tmp_path / "signals.jsonl").read_text().strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["contract_slug"] == "KXFED"
    assert record["source"] == "kalshi"


def test_log_signal_prints_summary(tmp_path: Path, capsys) -> None:
    log = Logger(signal_log=tmp_path / "signals.jsonl", order_log=tmp_path / "orders.jsonl")
    log.log_signal(make_signal(), source="polymarket")
    out = capsys.readouterr().out
    assert "[SIGNAL]" in out
    assert "KXFED" in out
    assert "source=polymarket" in out


def test_log_order_writes_jsonl(tmp_path: Path) -> None:
    log = Logger(signal_log=tmp_path / "signals.jsonl", order_log=tmp_path / "orders.jsonl")
    log.log_order(make_order())
    lines = (tmp_path / "orders.jsonl").read_text().strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["ticker"] == "AAPL"


def test_log_order_prints_summary(tmp_path: Path, capsys) -> None:
    log = Logger(signal_log=tmp_path / "signals.jsonl", order_log=tmp_path / "orders.jsonl")
    log.log_order(make_order())
    out = capsys.readouterr().out
    assert "[ORDER]" in out
    assert "AAPL" in out


def test_log_exit_appends_updated_record(tmp_path: Path) -> None:
    log = Logger(signal_log=tmp_path / "signals.jsonl", order_log=tmp_path / "orders.jsonl")
    log.log_order(make_order())
    log.log_exit("test-order-1", exit_reason="time", exit_price=155.0, pnl_usd=5.0)
    lines = (tmp_path / "orders.jsonl").read_text().strip().splitlines()
    last = json.loads(lines[-1])
    assert last["exit_reason"] == "time"
    assert last["exit_price"] == 155.0
    assert last["pnl_usd"] == 5.0
