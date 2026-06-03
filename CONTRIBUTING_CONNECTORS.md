# Contributing Connectors

This guide explains how to build a `.prism` connector for the Robinhood Velocity Signal Engine and submit it to the project.

---

## 1. What is a .prism connector?

A `.prism` connector is a self-contained directory package that ingests data from any external source and emits `PricePoint` objects that the `VelocityTracker` can process. Each connector implements the `PrismConnector` interface — three methods: `start()`, `stop()`, and `health_check()`.

The `PrismConnector` interface:

```python
class PrismConnector(ABC):
    metadata: PrismMetadata  # must be defined on every subclass

    async def start(self, tracker: VelocityTracker, mapper: ContractMapper, handle_signal: Callable) -> None:
        # Start the connector. Runs indefinitely. Feed PricePoint objects to tracker.
        ...

    async def stop(self) -> None:
        # Graceful shutdown. Cancel any running tasks.
        ...

    def health_check(self) -> dict:
        # Return {"status": "ok"|"degraded"|"error", "message": str, "last_update": ISO | None}
        ...
```

The key invariant: **every `PricePoint` price must be in [0.0, 1.0]**. The velocity framework treats prices as probabilities. If your data source emits raw values (like FRED economic series), you must normalize them before feeding to the tracker.

Any data source can be a connector — prediction markets, news sentiment scores, order flow imbalance, satellite data, IoT sensors, anything that produces a time series.

---

## 2. Quickstart (5 minutes to first connector)

**Install dependencies:**
```bash
pip install -r requirements.txt
```

**Scaffold a new connector:**
```bash
python -m prism_sdk.scaffold --name "My Source" --slug my_source --type custom --transport rest
```

This creates `connectors/my_source.prism/` with:
- `connector.prism` — manifest with placeholder fields
- `__init__.py` — skeleton class with all abstract methods stubbed
- `schema.json` — PricePoint schema reference
- `README.md` — documentation template

**Fill in the manifest** (`connectors/my_source.prism/connector.prism`):
```yaml
prism: "1.0"
name: "My Source"
slug: "my_source"
version: "1.0.0"
author: "your-github-username"
source_type: "custom"
transport: "rest"
description: "Fetches probability from my-api.com."
auth_required: true
auth_fields:
  - MY_API_KEY
contract_slugs:
  - KXFED
poll_interval_seconds: 60
capabilities:
  - velocity
```

**Implement the connector** (`connectors/my_source.prism/__init__.py`):
```python
async def fetch_latest_price(self) -> float:
    async with httpx.AsyncClient() as client:
        resp = await client.get("https://my-api.com/probability", headers={"Authorization": os.environ["MY_API_KEY"]})
        return resp.json()["probability"]  # must be 0.0–1.0
```

**Validate:**
```bash
python -m prism_sdk.validator --path connectors/my_source.prism
```

**Run the engine:**
```bash
python main.py --dry-run
```

---

## 3. PrismConnector interface reference

### `start(tracker, mapper, handle_signal)`

**Signature:** `async def start(self, tracker: VelocityTracker, mapper: ContractMapper, handle_signal: Callable) -> None`

Runs indefinitely. The engine calls this once at startup and keeps it running as an asyncio task. It is the connector's responsibility to:
1. Fetch or stream data from the external source
2. Construct `PricePoint(timestamp=..., price=..., volume=...)` objects
3. Feed them to `tracker.update(slug, point)`
4. If `tracker.update()` returns a `VelocitySignal`, call `await handle_signal(signal)`
5. Handle its own reconnection and error recovery internally

Must handle `asyncio.CancelledError` — catch it, set `self._message = "stopped"`, then re-raise.

**Parameters:**
- `tracker: VelocityTracker` — shared tracker instance (same instance used by all connectors and the exit manager)
- `mapper: ContractMapper` — provides `get_basket(slug)` and `get_all_slugs()`
- `handle_signal: Callable[[VelocitySignal], Awaitable[None]]` — fire-and-forget coroutine, called when tracker fires a signal

### `stop()`

**Signature:** `async def stop(self) -> None`

Called on graceful shutdown. Typical implementation:
```python
async def stop(self) -> None:
    if self._running_task is not None:
        self._running_task.cancel()
```

Store `asyncio.current_task()` in `self._running_task` at the start of `start()`.

### `health_check()`

**Signature:** `def health_check(self) -> dict`

Returns a dict with at minimum:
- `"status"`: `"ok"` | `"degraded"` | `"error"`
- `"message"`: human-readable status string
- `"last_update"`: ISO 8601 timestamp of the last successful data update, or `None`

### Minimal working example (random walk for testing)

```python
import asyncio
import random
from datetime import datetime, timezone
from typing import Callable

from connectors.base import PrismConnector, PrismMetadata
from signals.velocity import PricePoint, VelocityTracker
from signals.contract_mapper import ContractMapper


class RandomWalkConnector(PrismConnector):
    metadata = PrismMetadata(
        name="Random Walk",
        slug="random_walk",
        version="1.0.0",
        author="example",
        source_type="custom",
        transport="push",
        description="Generates random walk price data for testing.",
        auth_required=False,
        auth_fields=[],
        contract_slugs=["KXFED"],
        poll_interval_seconds=1.0,
        capabilities=["velocity"],
    )

    def __init__(self) -> None:
        self._running_task = None
        self._price = 0.5
        self._last_update = None
        self._message = "not started"

    async def start(self, tracker: VelocityTracker, mapper: ContractMapper, handle_signal: Callable) -> None:
        self._running_task = asyncio.current_task()
        self._message = "running"
        try:
            while True:
                self._price = max(0.01, min(0.99, self._price + random.uniform(-0.02, 0.02)))
                point = PricePoint(
                    timestamp=datetime.now(tz=timezone.utc),
                    price=self._price,
                    volume=random.randint(10, 100),
                )
                signal = tracker.update("KXFED", point)
                if signal is not None:
                    self._last_update = datetime.now(tz=timezone.utc)
                    await handle_signal(signal)
                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            self._message = "stopped"
            raise

    async def stop(self) -> None:
        if self._running_task is not None:
            self._running_task.cancel()

    def health_check(self) -> dict:
        return {
            "status": "ok",
            "message": self._message,
            "last_update": self._last_update.isoformat() if self._last_update else None,
        }
```

---

## 4. The PricePoint contract

```python
@dataclass
class PricePoint:
    timestamp: datetime  # UTC, use datetime.now(tz=timezone.utc)
    price: float         # MUST be in [0.0, 1.0]
    volume: int          # cumulative or incremental — use 0 or 1 if unavailable
```

**Fields:**
- `timestamp` — UTC datetime. Always use `datetime.now(tz=timezone.utc)` or parse the API timestamp with timezone info.
- `price` — normalized to [0.0, 1.0]. This is the key invariant. The velocity framework computes Δp/Δt assuming prices are probabilities. Values outside this range will produce misleading velocity signals.
- `volume` — used by the volume spike filter. If your data source has no volume, pass `volume=1` and the spike filter will fall back to a simple positivity check.

**Why 0–1 normalization:**

The velocity threshold (default 0.15) means "15 percentage points per minute." This only makes sense if prices are in [0, 1]. For non-probability data sources, use rolling min-max normalization as used in the FRED connector:

```python
def normalize(self, series_id: str, value: float) -> float:
    window = self._rolling.setdefault(series_id, deque(maxlen=52))
    window.append(value)
    if len(window) < 2:
        return 1.0
    min_val, max_val = min(window), max(window)
    if max_val == min_val:
        return 1.0
    return (value - min_val) / (max_val - min_val)
```

---

## 5. Manifest reference

All fields in `connector.prism`:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `prism` | string | yes | Format version — always `"1.0"` |
| `name` | string | yes | Human-readable connector name |
| `slug` | string | yes | Machine-readable identifier, snake_case |
| `version` | string | yes | SemVer, e.g. `"1.0.0"` |
| `author` | string | yes | GitHub username or full name |
| `source_type` | string | yes | One of: `prediction_market`, `alternative_data`, `news`, `custom` |
| `transport` | string | yes | One of: `websocket`, `rest`, `push` |
| `description` | string | yes | One sentence |
| `auth_required` | bool | yes | `true` if env vars are needed for auth |
| `auth_fields` | list[str] | yes | Env var names required for auth |
| `contract_slugs` | list[str] | yes | Slugs from `contract_equity_map.json` this connector can emit |
| `poll_interval_seconds` | float or null | no | `null` for WebSocket/push connectors |
| `capabilities` | list[str] | yes | e.g. `["velocity", "volume", "orderbook"]` |

---

## 6. Authentication pattern

**Convention:** use the `PREFIX_FIELD_NAME` naming pattern, e.g. `MYCONNECTOR_API_KEY`, `MYCONNECTOR_SECRET`.

```yaml
auth_required: true
auth_fields:
  - MYCONNECTOR_API_KEY
```

`validate_auth()` is called automatically by `PrismRegistry.load_directory()` before registering your connector. If any auth field is missing from the environment, the connector logs a WARNING and is skipped at runtime — the engine continues with the remaining connectors.

In `start()`, read auth env vars directly:
```python
api_key = os.environ["MYCONNECTOR_API_KEY"]  # KeyError is fine here — validate_auth already checked
```

**Document auth requirements in README.md** — the validator checks that every `auth_fields` entry appears in the README. Use a table:

```markdown
| Variable | Description |
|----------|-------------|
| `MYCONNECTOR_API_KEY` | API key from example.com/settings |
```

---

## 7. Transport patterns

### REST polling

The standard REST polling pattern:

```python
async def start(self, tracker, mapper, handle_signal):
    self._running_task = asyncio.current_task()
    interval = float(os.getenv("MY_POLL_INTERVAL_SECONDS", "60"))
    try:
        while True:
            await self._poll_once(tracker, handle_signal)
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        self._message = "stopped"
        raise
```

Always use `asyncio.sleep()` between polls — never `time.sleep()`. Use `httpx.AsyncClient` for HTTP calls.

### WebSocket

For WebSocket connectors, implement exponential backoff on reconnection. See `KalshiFedConnector` for the full pattern:

```python
_MAX_ATTEMPTS = 5
_BACKOFF_INITIAL = 1.0

async def start(self, tracker, mapper, handle_signal):
    self._running_task = asyncio.current_task()
    attempts = 0
    backoff = _BACKOFF_INITIAL
    while attempts < _MAX_ATTEMPTS:
        try:
            async with ws_connect(WS_URL) as ws:
                attempts = 0
                backoff = _BACKOFF_INITIAL
                async for message in ws:
                    await self._handle_message(message, tracker, handle_signal)
        except (WebSocketException, OSError) as exc:
            attempts += 1
            logger.warning("WS error (attempt %d/%d): %s", attempts, _MAX_ATTEMPTS, exc)
            if attempts >= _MAX_ATTEMPTS:
                break
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60.0)
```

### Push

Push connectors call `handle_signal` directly with pre-computed `VelocitySignal` objects, bypassing the `VelocityTracker`. Use this for data sources that already compute velocity or confidence scores:

```python
async def start(self, tracker, mapper, handle_signal):
    self._running_task = asyncio.current_task()
    async for event in self._listen_for_events():
        signal = VelocitySignal(
            contract_slug=event["slug"],
            velocity=event["confidence"],
            ...
        )
        await handle_signal(signal)
```

---

## 8. Contract mapping

`data/contract_equity_map.json` maps contract slugs to equity baskets. Your connector's `contract_slugs` must reference slugs that exist in this file.

**When to reuse existing slugs vs. add new ones:**
- Reuse `KXFED`, `KXCPI`, `KXJOBS` etc. if your data source tracks the same underlying events (Fed rate, CPI, jobs). The engine deduplicates signals by slug with a time window.
- Add a new slug only if your data source tracks a genuinely distinct event with its own equity basket. Add the new entry to `data/contract_equity_map.json` along with the connector.

**Required fields in `contract_equity_map.json`:**
```json
{
  "MY_SLUG": {
    "description": "human readable",
    "direction": "up",
    "basket": ["TICKER"],
    "sector_etf": "SPY",
    "sector": "broad_market",
    "confidence": 0.8,
    "macro_factors": ["rates"]
  }
}
```

`sector` valid values: `financials`, `utilities`, `energy`, `consumer_staples`, `technology`, `commodities`, `broad_market`.
`macro_factors` valid values: `rates`, `inflation`, `energy`, `credit`, `risk_off`.

---

## 9. Submitting a connector

1. **Fork the repo** and create a branch.
2. **Build and validate:**
   ```bash
   python -m prism_sdk.scaffold --name "My Source" --slug my_source --type custom --transport rest
   # implement the connector
   python -m prism_sdk.validator --path connectors/my_source.prism
   python -m pytest tests/ -q
   ```
3. **Open a pull request** with the `.prism` package. Include in the PR description:
   - What data source this tracks and its URL
   - How you verified normalization (prices are in [0.0, 1.0])
   - Sample output / signals fired in a test run
4. **Review checklist:**
   - Manifest complete and valid
   - Prices normalized to [0.0, 1.0]
   - Error handling: HTTP timeouts caught, WebSocket reconnects with backoff
   - No blocking calls (no `time.sleep`, no synchronous HTTP)
   - `health_check()` returns current state
   - README documents all env vars

---

## 10. Built-in connector examples

Four reference implementations are included in `connectors/`:

| Package | Transport | Auth | Notes |
|---------|-----------|------|-------|
| `kalshi_fed.prism` | WebSocket + REST fallback | Required | RSA-PSS signing |
| `polymarket_macro.prism` | WebSocket + REST fallback | Optional | No key needed |
| `metaculus_macro.prism` | REST polling | None | Public API |
| `manifold_macro.prism` | REST polling | None | Public API |
| `fred_macro.prism` | REST polling | Required | Normalization example |
