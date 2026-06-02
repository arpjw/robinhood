import json
from pathlib import Path

import pytest

from execution.order_schema import OrderRecord, load_order, update_order_exit, write_order


def make_record(**kwargs) -> OrderRecord:
    defaults = dict(
        id="test-id-1",
        timestamp="2026-01-01T00:00:00+00:00",
        mode="mock",
        strategy_id="s1",
        ticker="AAPL",
        side="buy",
        size_usd=100.0,
        contract_slug="KXFED-25JAN29",
        velocity=0.25,
        signal_timestamp="2026-01-01T00:00:00+00:00",
    )
    defaults.update(kwargs)
    return OrderRecord(**defaults)


def test_to_json_round_trips(tmp_path: Path) -> None:
    rec = make_record()
    d = json.loads(rec.to_json())
    assert d["id"] == "test-id-1"
    assert d["mode"] == "mock"
    assert d["ticker"] == "AAPL"


def test_from_dict_round_trips() -> None:
    rec = make_record(entry_price=150.0)
    d = json.loads(rec.to_json())
    rec2 = OrderRecord.from_dict(d)
    assert rec2.entry_price == 150.0
    assert rec2.id == rec.id


def test_write_and_load_order(tmp_path: Path) -> None:
    log = str(tmp_path / "orders.jsonl")
    rec = make_record()
    write_order(rec, log)
    loaded = load_order("test-id-1", log)
    assert loaded is not None
    assert loaded.ticker == "AAPL"


def test_load_order_returns_none_for_missing(tmp_path: Path) -> None:
    log = str(tmp_path / "orders.jsonl")
    assert load_order("nonexistent", log) is None


def test_update_order_exit_appends_exit_fields(tmp_path: Path) -> None:
    log = str(tmp_path / "orders.jsonl")
    rec = make_record()
    write_order(rec, log)
    update_order_exit(
        order_id="test-id-1",
        exit_reason="time",
        exit_timestamp="2026-01-01T02:00:00+00:00",
        exit_price=155.0,
        pnl_usd=5.0,
        log_path=log,
    )
    lines = Path(log).read_text().strip().splitlines()
    last = json.loads(lines[-1])
    assert last["exit_reason"] == "time"
    assert last["exit_price"] == 155.0
    assert last["pnl_usd"] == 5.0


def test_optional_fields_default_to_none() -> None:
    rec = make_record()
    assert rec.size_shares is None
    assert rec.entry_price is None
    assert rec.exit_reason is None
    assert rec.pnl_usd is None
