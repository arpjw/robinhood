import json
import os
from datetime import datetime, timezone
from pathlib import Path

from execution.order_schema import OrderRecord, update_order_exit
from signals.velocity import VelocitySignal

SIGNAL_LOG_PATH = Path(os.getenv("SIGNAL_LOG_PATH", "logs/signals.jsonl"))
ORDER_LOG_PATH = Path(os.getenv("ORDER_LOG_PATH", "logs/orders.jsonl"))


class Logger:
    def __init__(
        self,
        signal_log: Path = SIGNAL_LOG_PATH,
        order_log: Path = ORDER_LOG_PATH,
    ) -> None:
        self._signal_log = signal_log
        self._order_log = order_log

    def log_signal(self, signal: VelocitySignal, source: str) -> None:
        self._signal_log.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "timestamp": signal.timestamp.isoformat(),
            "contract_slug": signal.contract_slug,
            "velocity": signal.velocity,
            "window_minutes": signal.window_minutes,
            "price": signal.price,
            "volume_delta": signal.volume_delta,
            "source": source,
        }
        with self._signal_log.open("a") as f:
            f.write(json.dumps(record) + "\n")
        print(
            f"[SIGNAL] {signal.timestamp.isoformat()} {signal.contract_slug} "
            f"velocity={signal.velocity:.3f} source={source}"
        )

    def log_order(self, order: OrderRecord) -> None:
        self._order_log.parent.mkdir(parents=True, exist_ok=True)
        with self._order_log.open("a") as f:
            f.write(order.to_json() + "\n")
        print(
            f"[ORDER] {order.timestamp} {order.ticker} {order.side} "
            f"${order.size_usd:.2f} strategy={order.strategy_id}"
        )

    def log_exit(
        self,
        order_id: str,
        exit_reason: str,
        exit_price: float,
        pnl_usd: float,
    ) -> None:
        update_order_exit(
            order_id=order_id,
            exit_reason=exit_reason,
            exit_timestamp=datetime.now(tz=timezone.utc).isoformat(),
            exit_price=exit_price,
            pnl_usd=pnl_usd,
            log_path=str(self._order_log),
        )
        print(
            f"[EXIT] order={order_id} reason={exit_reason} "
            f"exit_price={exit_price:.4f} pnl=${pnl_usd:.2f}"
        )
