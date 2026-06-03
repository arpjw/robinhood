import json
import os
from datetime import datetime, timezone
from pathlib import Path

from applog.alerter import Alerter
from execution.order_schema import OrderRecord, update_order_exit
from signals.velocity import VelocitySignal

SIGNAL_LOG_PATH = Path(os.getenv("SIGNAL_LOG_PATH", "logs/signals.jsonl"))
ORDER_LOG_PATH = Path(os.getenv("ORDER_LOG_PATH", "logs/orders.jsonl"))


class Logger:
    def __init__(
        self,
        signal_log: Path = SIGNAL_LOG_PATH,
        order_log: Path = ORDER_LOG_PATH,
        alerter: Alerter | None = None,
    ) -> None:
        self._signal_log = signal_log
        self._order_log = order_log
        self._alerter = alerter if alerter is not None else Alerter()

    def log_signal(
        self,
        signal: VelocitySignal,
        source: str,
        direction: str | None = None,
        basket: list[str] | None = None,
    ) -> None:
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
        if direction and basket:
            self._alerter.alert_signal(signal, direction, basket)

    def log_order(self, order: OrderRecord) -> None:
        self._order_log.parent.mkdir(parents=True, exist_ok=True)
        with self._order_log.open("a") as f:
            f.write(order.to_json() + "\n")
        print(
            f"[ORDER] {order.timestamp} {order.ticker} {order.side} "
            f"${order.size_usd:.2f} strategy={order.strategy_id}"
        )
        self._alerter.alert_order(order)

    def log_exit(
        self,
        order_id: str,
        exit_reason: str,
        exit_price: float,
        pnl_usd: float,
        ticker: str | None = None,
        hold_minutes: float | None = None,
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
        if ticker and hold_minutes is not None:
            self._alerter.alert_exit(ticker, exit_reason, hold_minutes, pnl_usd)
