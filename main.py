import argparse
import asyncio
import json
import logging
import os
import signal
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from connectors.base import PrismRegistry
from execution.exit_manager import ExitManager, TrackedPosition, yfinance_price_fetcher
from execution.exposure_manager import ExposureManager
from execution.mcp_client import make_client
from execution.sizer import size_basket
from signals.contract_mapper import ContractMapper
from signals.deduplicator import SignalDeduplicator
from signals.market_hours import MarketHoursGuard
from signals.velocity import VelocitySignal, VelocityTracker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

_signal_count = 0
_order_count = 0
_tasks: list[asyncio.Task] = []
_off_hours_queue: list[VelocitySignal] = []


def determine_side(velocity: float, direction: str) -> str:
    return "buy" if (velocity > 0) == (direction == "up") else "sell"


async def _submit_signal(
    signal: VelocitySignal,
    mapper: ContractMapper,
    client,
    exit_manager: ExitManager,
    deduplicator: SignalDeduplicator,
    exposure_manager: ExposureManager,
    size_multiplier: float = 1.0,
) -> None:
    global _signal_count, _order_count

    if not deduplicator.should_fire(signal):
        logger.info("dedup: suppressing duplicate signal for %s", signal.contract_slug)
        return

    _signal_count += 1
    basket = mapper.get_basket(signal.contract_slug)
    if basket is None:
        logger.info("no basket mapped for %s", signal.contract_slug)
        return

    side = determine_side(signal.velocity, basket["direction"])
    sizes = size_basket(basket, velocity=signal.velocity)
    if size_multiplier != 1.0:
        sizes = {t: round(s * size_multiplier, 2) for t, s in sizes.items()}

    total_size = sum(sizes.values())
    can_open, reason = exposure_manager.can_open(signal.contract_slug, total_size)
    if not can_open:
        logger.warning(
            "EXPOSURE LIMIT slug=%s reason=%s", signal.contract_slug, reason
        )
        return

    strategy_id = f"velocity:{signal.contract_slug}:{signal.timestamp.strftime('%Y%m%dT%H%M%S')}"

    logger.info(
        "SIGNAL slug=%s velocity=%.4f price=%.3f side=%s strategy=%s",
        signal.contract_slug,
        signal.velocity,
        signal.price,
        side,
        strategy_id,
    )

    for ticker, dollar_size in sizes.items():
        order = client.submit_order(ticker, side, dollar_size, strategy_id)
        _order_count += 1
        exposure_manager.register_open(signal.contract_slug, ticker, dollar_size)
        exit_manager.register(
            TrackedPosition(
                order_id=order["id"],
                ticker=ticker,
                side=side,
                size=dollar_size,
                entry_time=signal.timestamp,
                strategy_id=strategy_id,
                direction=basket["direction"],
                contract_slug=signal.contract_slug,
                entry_velocity=signal.velocity,
                exit_hours=float(basket.get("exit_hours", 2.0)),
                exit_adverse_pct=float(basket.get("exit_adverse_pct", 0.03)),
                entry_price=None,
            )
        )


async def handle_signal(
    signal: VelocitySignal,
    mapper: ContractMapper,
    client,
    exit_manager: ExitManager,
    deduplicator: SignalDeduplicator,
    exposure_manager: ExposureManager,
    hours_guard: MarketHoursGuard,
) -> None:
    if not hours_guard.is_open():
        mode = os.getenv("OFF_HOURS_MODE", "suppress")
        mins = hours_guard.minutes_to_open()
        if mode == "queue":
            _off_hours_queue.append(signal)
            logger.info(
                "queued off-hours signal slug=%s velocity=%.4f mins_to_open=%s",
                signal.contract_slug,
                signal.velocity,
                f"{mins:.1f}" if mins is not None else "unknown",
            )
        else:
            logger.info(
                "suppressed off-hours signal slug=%s velocity=%.4f mins_to_open=%s",
                signal.contract_slug,
                signal.velocity,
                f"{mins:.1f}" if mins is not None else "unknown",
            )
        return

    await _submit_signal(signal, mapper, client, exit_manager, deduplicator, exposure_manager)


async def _queue_replay_worker(
    hours_guard: MarketHoursGuard,
    mapper: ContractMapper,
    client,
    exit_manager: ExitManager,
    deduplicator: SignalDeduplicator,
    exposure_manager: ExposureManager,
) -> None:
    was_open = hours_guard.is_open()
    while True:
        await asyncio.sleep(30)
        is_open = hours_guard.is_open()
        if is_open and not was_open and _off_hours_queue:
            queued = list(_off_hours_queue)
            _off_hours_queue.clear()
            logger.info("market opened — replaying %d queued signals", len(queued))
            for sig in queued:
                decay = hours_guard.edge_decay_factor(sig.timestamp)
                if decay == 0.0:
                    logger.warning(
                        "queue replay: dropped stale signal slug=%s (edge decay=0.0)",
                        sig.contract_slug,
                    )
                    continue
                await _submit_signal(
                    sig, mapper, client, exit_manager, deduplicator, exposure_manager,
                    size_multiplier=decay,
                )
        was_open = is_open


def _print_startup_banner(
    dry_run: bool,
    mode: str,
    hours_guard: MarketHoursGuard,
    exposure_manager: ExposureManager,
    registry: PrismRegistry,
) -> None:
    mapper_path = "data/contract_equity_map.json"
    try:
        contract_count = len(json.loads(Path(mapper_path).read_text()))
    except Exception:
        contract_count = 0

    is_open = hours_guard.is_open()
    market_status = "OPEN" if is_open else "CLOSED"
    if not is_open:
        mins = hours_guard.minutes_to_open()
        if mins is not None:
            market_status += f" (opens in {mins:.0f}m)"

    connectors = registry.get_all()

    banner = "DRY RUN MODE — forced mock execution" if dry_run else ""
    print("=" * 60)
    if banner:
        print(f"  *** {banner} ***")
    print(f"  execution mode      : {mode}")
    print(f"  portfolio value     : ${os.getenv('PORTFOLIO_VALUE', '10000')}")
    print(f"  max position pct    : {os.getenv('MAX_POSITION_PCT', '0.05')}")
    print(f"  velocity threshold  : {os.getenv('VELOCITY_THRESHOLD', '0.15')}")
    print(f"  velocity window     : {os.getenv('VELOCITY_WINDOW_MINUTES', '5')}m")
    print(f"  contracts tracked   : {contract_count}")
    print(f"  market hours status : {market_status}")
    print(f"  off hours mode      : {os.getenv('OFF_HOURS_MODE', 'suppress')}")
    print(f"  max factor exposure : {os.getenv('MAX_FACTOR_EXPOSURE_PCT', '0.15')}")
    print(f"  max total exposure  : {os.getenv('MAX_TOTAL_EXPOSURE_PCT', '0.40')}")
    print(f"  prism connectors    : {len(connectors)}")
    for c in connectors:
        print(f"    - {c.metadata.name} ({c.metadata.slug})")
    print("=" * 60)


async def main() -> None:
    global _tasks

    parser = argparse.ArgumentParser(description="Robinhood velocity signal engine")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run full pipeline in mock mode regardless of EXECUTION_MODE",
    )
    args = parser.parse_args()

    if args.dry_run:
        os.environ["EXECUTION_MODE"] = "mock"

    mode = os.getenv("EXECUTION_MODE", "mock")

    mapper = ContractMapper()
    client = make_client()
    deduplicator = SignalDeduplicator()
    exposure_manager = ExposureManager()
    hours_guard = MarketHoursGuard()
    exit_check_interval = float(os.getenv("EXIT_CHECK_INTERVAL_SECONDS", "60"))

    tracker = VelocityTracker()
    exit_manager = ExitManager(
        client=client,
        price_fetcher=yfinance_price_fetcher,
        check_interval_seconds=exit_check_interval,
        velocity_tracker=tracker,
        exposure_manager=exposure_manager,
    )

    registry = PrismRegistry()
    n = registry.load_directory(Path("connectors"))
    custom_path = Path("connectors/custom")
    if custom_path.exists():
        n += registry.load_directory(custom_path)
    if n == 0:
        logger.warning(
            "no prism connectors loaded — check auth env vars and connectors/ directory"
        )

    _print_startup_banner(args.dry_run, mode, hours_guard, exposure_manager, registry)

    async def _on_signal(sig: VelocitySignal) -> None:
        await handle_signal(
            sig, mapper, client, exit_manager, deduplicator, exposure_manager, hours_guard
        )

    coroutines: list = [exit_manager.run()]

    for connector in registry.get_all():
        coroutines.append(connector.start(tracker, mapper, _on_signal))

    if os.getenv("OFF_HOURS_MODE", "suppress") == "queue":
        coroutines.append(
            _queue_replay_worker(
                hours_guard, mapper, client, exit_manager, deduplicator, exposure_manager
            )
        )

    loop = asyncio.get_running_loop()

    def _shutdown(signum, frame):
        logger.info("shutdown signal received (%s)", signum)
        for task in _tasks:
            task.cancel()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda s=sig: _shutdown(s, None))

    _tasks = [asyncio.create_task(c) for c in coroutines]
    try:
        await asyncio.gather(*_tasks)
    except asyncio.CancelledError:
        pass
    finally:
        for connector in registry.get_all():
            await connector.stop()

        if mode == "live":
            try:
                client.cancel_all("*")
            except Exception as exc:
                logger.warning("cancel_all on shutdown failed: %s", exc)

        positions = client.get_positions()
        factor_exposure = exposure_manager.get_factor_exposure()
        print("\n=== Shutdown Summary ===")
        print(f"  signals fired  : {_signal_count}")
        print(f"  orders placed  : {_order_count}")
        print(f"  open positions : {len(positions)}")
        if factor_exposure:
            print("  factor exposure:")
            for factor, pct in sorted(factor_exposure.items()):
                print(f"    {factor}: {pct*100:.1f}%")
        print("========================")


def _log_error(exc: BaseException) -> None:
    error_log = Path("logs/errors.jsonl")
    error_log.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "error": str(exc),
        "traceback": traceback.format_exc(),
    }
    with error_log.open("a") as f:
        f.write(json.dumps(record) + "\n")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        _log_error(exc)
        logger.error("unexpected error: %s", exc, exc_info=True)
        sys.exit(1)
