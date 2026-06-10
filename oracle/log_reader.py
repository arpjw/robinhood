from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from oracle.models import OrderRecord, SignalRecord

logger = logging.getLogger(__name__)

SIGNAL_LOG_PATH = Path(os.getenv("SIGNAL_LOG_PATH", "logs/signals.jsonl"))
ORDER_LOG_PATH = Path(os.getenv("ORDER_LOG_PATH", "logs/orders.jsonl"))


def _parse_dt(s: str) -> datetime:
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _signal_id_from(timestamp: str, contract_slug: str) -> str:
    raw = f"{timestamp}:{contract_slug}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def _parse_signal(raw: dict) -> SignalRecord:
    ts = _parse_dt(raw["timestamp"])
    slug = raw["contract_slug"]
    return SignalRecord(
        signal_id=raw.get("signal_id") or _signal_id_from(raw["timestamp"], slug),
        timestamp=ts,
        contract_slug=slug,
        velocity=float(raw["velocity"]),
        direction=raw.get("direction", "up"),
        source=raw.get("source", "unknown"),
        basket=raw.get("basket", []),
        sector=raw.get("sector", "unknown"),
        macro_factors=raw.get("macro_factors", []),
        confidence=float(raw.get("confidence", 1.0)),
        fired=bool(raw.get("fired", True)),
    )


def _extract_signal_id_from_strategy(strategy_id: str, timestamp_str: str, contract_slug: str) -> str:
    parts = strategy_id.split(":")
    if len(parts) >= 3 and parts[0] == "velocity":
        slug = parts[1]
        ts_part = parts[2]
        try:
            ts = datetime.strptime(ts_part, "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
            return _signal_id_from(ts.isoformat(), slug)
        except ValueError:
            pass
    return _signal_id_from(timestamp_str, contract_slug)


def _parse_order(raw: dict) -> OrderRecord:
    ts = _parse_dt(raw["timestamp"])
    contract_slug = raw.get("contract_slug", "unknown")
    strategy_id = raw.get("strategy_id", "")
    signal_id = raw.get("signal_id") or _extract_signal_id_from_strategy(
        strategy_id, raw["timestamp"], contract_slug
    )

    exit_ts: datetime | None = None
    if raw.get("exit_timestamp"):
        exit_ts = _parse_dt(raw["exit_timestamp"])

    source = raw.get("source", "unknown")
    if source == "unknown" and strategy_id.startswith("velocity:"):
        parts = strategy_id.split(":")
        if len(parts) >= 2:
            slug_parts = parts[1].split("-")
            if slug_parts:
                source = slug_parts[0].lower()

    return OrderRecord(
        order_id=raw.get("id") or raw.get("order_id", ""),
        signal_id=signal_id,
        timestamp=ts,
        mode=raw.get("mode", "mock"),
        ticker=raw.get("ticker", ""),
        side=raw.get("side", "buy"),
        size_usd=float(raw.get("size_usd", 0)),
        entry_price=float(raw["entry_price"]) if raw.get("entry_price") is not None else None,
        exit_price=float(raw["exit_price"]) if raw.get("exit_price") is not None else None,
        exit_reason=raw.get("exit_reason"),
        exit_timestamp=exit_ts,
        pnl_usd=float(raw["pnl_usd"]) if raw.get("pnl_usd") is not None else None,
        source=source,
        contract_slug=contract_slug,
        velocity=float(raw.get("velocity", 0.0)),
    )


class LogReader:
    def __init__(
        self,
        signal_log: Path = SIGNAL_LOG_PATH,
        order_log: Path = ORDER_LOG_PATH,
    ) -> None:
        self._signal_log = signal_log
        self._order_log = order_log
        self._signal_offset: int = 0
        self._order_offset: int = 0

    def read_signals(
        self,
        since: datetime | None = None,
        until: datetime | None = None,
        connector_slug: str | None = None,
        contract_slug: str | None = None,
    ) -> list[SignalRecord]:
        results: list[SignalRecord] = []
        if not self._signal_log.exists():
            return results
        for line in self._signal_log.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
                record = _parse_signal(raw)
            except Exception as exc:
                logger.warning("malformed signal line: %s — %s", line[:80], exc)
                continue
            if since and record.timestamp < since:
                continue
            if until and record.timestamp > until:
                continue
            if connector_slug and record.source != connector_slug:
                continue
            if contract_slug and record.contract_slug != contract_slug:
                continue
            results.append(record)
        results.sort(key=lambda r: r.timestamp)
        return results

    def read_orders(
        self,
        since: datetime | None = None,
        until: datetime | None = None,
        connector_slug: str | None = None,
        mode: str | None = None,
    ) -> list[OrderRecord]:
        results: list[OrderRecord] = []
        if not self._order_log.exists():
            return results

        seen_ids: dict[str, OrderRecord] = {}
        for line in self._order_log.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
                record = _parse_order(raw)
            except Exception as exc:
                logger.warning("malformed order line: %s — %s", line[:80], exc)
                continue
            if since and record.timestamp < since:
                continue
            if until and record.timestamp > until:
                continue
            if connector_slug and record.source != connector_slug:
                continue
            if mode and record.mode != mode:
                continue
            seen_ids[record.order_id] = record

        results = sorted(seen_ids.values(), key=lambda r: r.timestamp)
        return results

    def join(
        self,
        signals: list[SignalRecord],
        orders: list[OrderRecord],
    ) -> list[tuple[SignalRecord, OrderRecord | None]]:
        order_by_signal: dict[str, list[OrderRecord]] = {}
        for order in orders:
            order_by_signal.setdefault(order.signal_id, []).append(order)

        result: list[tuple[SignalRecord, OrderRecord | None]] = []
        for signal in signals:
            matching = order_by_signal.get(signal.signal_id, [])
            if matching:
                for order in matching:
                    result.append((signal, order))
            else:
                result.append((signal, None))

        result.sort(key=lambda pair: pair[0].timestamp)
        return result

    async def watch(
        self,
        callback: Callable[[str, dict], None],
        poll_interval: float = 5.0,
    ) -> None:
        signal_pos = 0
        order_pos = 0

        while True:
            for path, kind, pos_attr in [
                (self._signal_log, "signal", "signal_pos"),
                (self._order_log, "order", "order_pos"),
            ]:
                if not path.exists():
                    continue
                file_size = path.stat().st_size
                current_pos = signal_pos if kind == "signal" else order_pos
                if file_size < current_pos:
                    current_pos = 0

                with path.open("r", encoding="utf-8") as f:
                    f.seek(current_pos)
                    new_lines = f.readlines()
                    new_pos = f.tell()

                for line in new_lines:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        parsed = json.loads(line)
                        callback(kind, parsed)
                    except json.JSONDecodeError:
                        pass

                if kind == "signal":
                    signal_pos = new_pos
                else:
                    order_pos = new_pos

            await asyncio.sleep(poll_interval)

    def read_signals_incremental(self) -> list[SignalRecord]:
        results: list[SignalRecord] = []
        if not self._signal_log.exists():
            return results

        file_size = self._signal_log.stat().st_size
        if file_size < self._signal_offset:
            self._signal_offset = 0

        with self._signal_log.open("r", encoding="utf-8") as f:
            f.seek(self._signal_offset)
            new_lines = f.readlines()
            self._signal_offset = f.tell()

        for line in new_lines:
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
                results.append(_parse_signal(raw))
            except Exception as exc:
                logger.warning("malformed signal line: %s — %s", line[:80], exc)

        return results

    def read_orders_incremental(self) -> list[OrderRecord]:
        results: list[OrderRecord] = []
        if not self._order_log.exists():
            return results

        file_size = self._order_log.stat().st_size
        if file_size < self._order_offset:
            self._order_offset = 0

        with self._order_log.open("r", encoding="utf-8") as f:
            f.seek(self._order_offset)
            new_lines = f.readlines()
            self._order_offset = f.tell()

        for line in new_lines:
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
                results.append(_parse_order(raw))
            except Exception as exc:
                logger.warning("malformed order line: %s — %s", line[:80], exc)

        return results
