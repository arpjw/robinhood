"""
python -m prism_sdk.scaffold --name "My Connector" --slug my_connector --type prediction_market --transport rest
"""
import argparse
import json
import sys
import textwrap
from pathlib import Path

_MANIFEST_TEMPLATE = """\
prism: "1.0"
name: "{name}"
slug: "{slug}"
version: "1.0.0"
author: "your-github-username"
source_type: "{source_type}"
transport: "{transport}"
description: "One sentence describing what this connector does."
auth_required: false
auth_fields: []
contract_slugs:
  - KXFED
poll_interval_seconds: 60
capabilities:
  - velocity
"""

_INIT_TEMPLATE = '''\
import asyncio
import os
from datetime import datetime, timezone
from typing import Callable

from connectors.base import PrismConnector, PrismMetadata
from signals.velocity import PricePoint, VelocityTracker
from signals.contract_mapper import ContractMapper


class {class_name}(PrismConnector):
    metadata = PrismMetadata(
        name="{name}",
        slug="{slug}",
        version="1.0.0",
        author="your-github-username",
        source_type="{source_type}",
        transport="{transport}",
        description="One sentence describing what this connector does.",
        auth_required=False,
        auth_fields=[],
        contract_slugs=["KXFED"],
        poll_interval_seconds=60.0,
        capabilities=["velocity"],
    )

    def __init__(self) -> None:
        self._running_task: asyncio.Task | None = None
        self._last_update: datetime | None = None
        self._status = "ok"
        self._message = "not started"

    async def fetch_latest_price(self) -> float:
        # TODO: implement — must return a float in 0.0–1.0
        raise NotImplementedError("implement fetch_latest_price()")

    async def start(
        self,
        tracker: VelocityTracker,
        mapper: ContractMapper,
        handle_signal: Callable,
    ) -> None:
        # Called once at engine startup. Runs indefinitely.
        # Feed PricePoint objects to tracker; call handle_signal when tracker fires.
        self._running_task = asyncio.current_task()
        self._message = "running"
        try:
            while True:
                price = await self.fetch_latest_price()
                signal = tracker.update(self.metadata.slug, PricePoint(
                    timestamp=datetime.now(tz=timezone.utc),
                    price=price,   # must be 0.0 – 1.0
                    volume=1,
                ))
                if signal is not None:
                    self._last_update = datetime.now(tz=timezone.utc)
                    await handle_signal(signal)
                await asyncio.sleep(self.metadata.poll_interval_seconds or 60.0)
        except asyncio.CancelledError:
            self._message = "stopped"
            raise

    async def stop(self) -> None:
        # Called on graceful shutdown — cancel the running task.
        if self._running_task is not None:
            self._running_task.cancel()

    def health_check(self) -> dict:
        # Return current connector health. Always include status, message, last_update.
        return {{
            "status": self._status,
            "message": self._message,
            "last_update": self._last_update.isoformat() if self._last_update else None,
        }}
'''

_SCHEMA_TEMPLATE = """\
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "PricePoint",
  "description": "A single price observation emitted by a .prism connector into the VelocityTracker.",
  "type": "object",
  "required": ["timestamp", "price", "volume"],
  "properties": {
    "timestamp": {
      "type": "string",
      "format": "date-time",
      "description": "UTC timestamp of the observation."
    },
    "price": {
      "type": "number",
      "minimum": 0.0,
      "maximum": 1.0,
      "description": "Normalized price in [0.0, 1.0]. Must represent a probability or be normalized to this range."
    },
    "volume": {
      "type": "integer",
      "minimum": 0,
      "description": "Cumulative or incremental volume. Use 0 or 1 if volume is not available."
    }
  }
}
"""

_README_TEMPLATE = """\
# {slug} — {name}

## Overview

Describe what this connector does and what data source it ingests.

## Data Source

Explain the external data source: API endpoints used, update frequency, and data quality notes.

## Authentication

List all required environment variables:

| Variable | Description |
|----------|-------------|
| `MY_API_KEY` | API key from example.com/settings |

## Configuration

List all optional configuration environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `MY_POLL_INTERVAL_SECONDS` | 60 | How often to poll the API |

## Emitted Signals

Describe what velocity signals this connector emits and under what conditions.

## Contract Mappings

Explain which contract slugs this connector maps to and why.
"""


def _slug_to_class_name(slug: str) -> str:
    return "".join(word.capitalize() for word in slug.split("_")) + "Connector"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scaffold a new .prism connector package."
    )
    parser.add_argument("--name", required=True, help='Human-readable name, e.g. "My Source"')
    parser.add_argument("--slug", required=True, help="Machine-readable slug, e.g. my_source")
    parser.add_argument(
        "--type",
        dest="source_type",
        default="custom",
        choices=["prediction_market", "alternative_data", "news", "custom"],
        help="Source type (default: custom)",
    )
    parser.add_argument(
        "--transport",
        default="rest",
        choices=["websocket", "rest", "push"],
        help="Transport type (default: rest)",
    )
    parser.add_argument(
        "--output-dir",
        default="connectors",
        help="Parent directory for the new package (default: connectors/)",
    )
    args = parser.parse_args()

    pkg_name = f"{args.slug}.prism"
    output_dir = Path(args.output_dir)
    pkg_path = output_dir / pkg_name

    if pkg_path.exists():
        print(f"Error: {pkg_path} already exists.", file=sys.stderr)
        sys.exit(1)

    pkg_path.mkdir(parents=True)

    (pkg_path / "connector.prism").write_text(
        _MANIFEST_TEMPLATE.format(
            name=args.name,
            slug=args.slug,
            source_type=args.source_type,
            transport=args.transport,
        )
    )

    class_name = _slug_to_class_name(args.slug)
    (pkg_path / "__init__.py").write_text(
        _INIT_TEMPLATE.format(
            name=args.name,
            slug=args.slug,
            source_type=args.source_type,
            transport=args.transport,
            class_name=class_name,
        )
    )

    (pkg_path / "schema.json").write_text(_SCHEMA_TEMPLATE)
    (pkg_path / "README.md").write_text(
        _README_TEMPLATE.format(slug=args.slug, name=args.name)
    )

    print(f"Created {pkg_path}/")
    print(f"  connector.prism  — manifest (fill in description, auth_fields, contract_slugs)")
    print(f"  __init__.py      — {class_name} skeleton (implement fetch_latest_price)")
    print(f"  schema.json      — PricePoint schema reference")
    print(f"  README.md        — documentation template")
    print()
    print("Next steps:")
    print(f"  1. Fill in {pkg_path}/connector.prism")
    print(f"  2. Implement start(), stop(), health_check() in {pkg_path}/__init__.py")
    print(f"  3. Add contract slugs to data/contract_equity_map.json if needed")
    print(f"  4. Run: python scripts/healthcheck.py")
    print(f"  5. Run: python main.py --dry-run")


if __name__ == "__main__":
    main()
