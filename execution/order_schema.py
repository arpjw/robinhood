from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

ORDER_LOG_PATH_DEFAULT = "logs/orders.jsonl"


@dataclass
class OrderRecord:
    id: str
    timestamp: str
    mode: Literal["mock", "live"]
    strategy_id: str
    ticker: str
    side: Literal["buy", "sell"]
    size_usd: float
    contract_slug: str
    velocity: float
    signal_timestamp: str
    size_shares: float | None = None
    entry_price: float | None = None
    exit_reason: str | None = None
    exit_timestamp: str | None = None
    exit_price: float | None = None
    pnl_usd: float | None = None

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_dict(cls, d: dict) -> "OrderRecord":
        return cls(
            id=d["id"],
            timestamp=d["timestamp"],
            mode=d["mode"],
            strategy_id=d["strategy_id"],
            ticker=d["ticker"],
            side=d["side"],
            size_usd=d["size_usd"],
            contract_slug=d["contract_slug"],
            velocity=d["velocity"],
            signal_timestamp=d["signal_timestamp"],
            size_shares=d.get("size_shares"),
            entry_price=d.get("entry_price"),
            exit_reason=d.get("exit_reason"),
            exit_timestamp=d.get("exit_timestamp"),
            exit_price=d.get("exit_price"),
            pnl_usd=d.get("pnl_usd"),
        )


def load_order(order_id: str, log_path: str = ORDER_LOG_PATH_DEFAULT) -> OrderRecord | None:
    p = Path(log_path)
    if not p.exists():
        return None
    for line in p.read_text().splitlines():
        if not line.strip():
            continue
        try:
            d = json.loads(line)
            if d.get("id") == order_id:
                return OrderRecord.from_dict(d)
        except (json.JSONDecodeError, KeyError):
            continue
    return None


def write_order(record: OrderRecord, log_path: str = ORDER_LOG_PATH_DEFAULT) -> None:
    p = Path(log_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        f.write(record.to_json() + "\n")


def update_order_exit(
    order_id: str,
    exit_reason: str,
    exit_timestamp: str,
    exit_price: float,
    pnl_usd: float,
    log_path: str = ORDER_LOG_PATH_DEFAULT,
) -> None:
    record = load_order(order_id, log_path)
    if record is None:
        return
    record.exit_reason = exit_reason
    record.exit_timestamp = exit_timestamp
    record.exit_price = exit_price
    record.pnl_usd = pnl_usd
    write_order(record, log_path)
