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

from execution.exit_manager import ExitManager, TrackedPosition, yfinance_price_fetcher
from execution.mcp_client import make_client
from execution.sizer import size_basket
from signals.contract_mapper import ContractMapper
from signals.deduplicator import SignalDeduplicator
from signals.kalshi_poller import KalshiPoller
from signals.polymarket_poller import PolymarketPoller
from signals.velocity import VelocitySignal, VelocityTracker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

_signal_count = 0
_order_count = 0
_tasks: list[asyncio.Task] = []


def determine_side(velocity: float, direction: str) -> str:
    return "buy" if (velocity > 0) == (direction == "up") else "sell"


async def handle_signal(
    signal: VelocitySignal,
    mapper: ContractMapper,
    client,
    exit_manager: ExitManager,
    deduplicator: SignalDeduplicator,
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
        exit_manager.register(
            TrackedPosition(
                order_id=order["id"],
                ticker=ticker,
                side=side,
                size=dollar_size,
                entry_time=signal.timestamp,
                strategy_id=strategy_id,
                direction=basket["direction"],
                exit_hours=float(basket.get("exit_hours", 2.0)),
                exit_adverse_pct=float(basket.get("exit_adverse_pct", 0.03)),
                entry_price=None,
            )
        )


def _print_startup_banner(dry_run: bool, mode: str, tracked: list[str]) -> None:
    mapper_path = "data/contract_equity_map.json"
    try:
        contract_count = len(json.loads(Path(mapper_path).read_text()))
    except Exception:
        contract_count = len(tracked)

    polymarket_ids = os.getenv("POLYMARKET_CONDITION_IDS", "")
    poly_count = len([x for x in polymarket_ids.split(",") if x.strip()]) if polymarket_ids else 0

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
    print(f"  kalshi tickers      : {len(tracked)}")
    print(f"  polymarket ids      : {poly_count}")
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

    api_key = os.environ.get("KALSHI_API_KEY")
    if not api_key:
        logger.error("KALSHI_API_KEY not set")
        sys.exit(1)

    mapper = ContractMapper()
    client = make_client()
    deduplicator = SignalDeduplicator()
    exit_check_interval = float(os.getenv("EXIT_CHECK_INTERVAL_SECONDS", "60"))
    exit_manager = ExitManager(
        client=client,
        price_fetcher=yfinance_price_fetcher,
        check_interval_seconds=exit_check_interval,
    )

    tickers_env = os.getenv("KALSHI_TICKERS", "")
    if tickers_env:
        tracked = [t.strip() for t in tickers_env.split(",") if t.strip()]
    else:
        tracked = mapper.get_all_slugs()
        logger.warning(
            "KALSHI_TICKERS not set — using series keys as tickers. "
            "Set to specific market tickers for production."
        )

    _print_startup_banner(args.dry_run, mode, tracked)

    polymarket_env = os.getenv("POLYMARKET_CONDITION_IDS", "")
    condition_ids = [x.strip() for x in polymarket_env.split(",") if x.strip()]

    tracker = VelocityTracker()
    interval = float(os.getenv("POLL_INTERVAL_SECONDS", "30"))

    poller = KalshiPoller(api_key=api_key, tracked_tickers=tracked, tracker=tracker)

    async def _on_signal(sig: VelocitySignal) -> None:
        await handle_signal(sig, mapper, client, exit_manager, deduplicator)

    coroutines = [
        poller.run(interval_seconds=interval, on_signal=_on_signal),
        exit_manager.run(),
    ]

    if condition_ids:
        poly_tracker = VelocityTracker()
        poly_poller = PolymarketPoller(
            condition_ids=condition_ids,
            tracker=poly_tracker,
            mapper=mapper,
        )
        coroutines.append(
            poly_poller.run(interval_seconds=interval, on_signal=_on_signal)
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
        if mode == "live":
            try:
                client.cancel_all("*")
            except Exception as exc:
                logger.warning("cancel_all on shutdown failed: %s", exc)

        positions = client.get_positions()
        print("\n=== Shutdown Summary ===")
        print(f"  signals fired  : {_signal_count}")
        print(f"  orders placed  : {_order_count}")
        print(f"  open positions : {len(positions)}")
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
