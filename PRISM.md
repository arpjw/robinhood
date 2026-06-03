# Prism Connector Framework — Build Plan

One Claude Code session. Build the full `.prism` connector framework, migrate existing connectors to it, ship three built-in extra connectors, and update the landing page to showcase the ecosystem.

---

## What Prism Is

Prism is the connector format for the Robinhood Velocity Signal Engine. A `.prism` connector is a self-contained directory package that ingests data from any external source — prediction markets, alternative data, news feeds, custom signals — and emits `PricePoint` objects that the VelocityTracker can process. Any developer can build a `.prism` connector and drop it into the `connectors/` directory. The engine loads it automatically at startup.

The name: a prism refracts a single input into structured components. A `.prism` connector takes raw external data and refracts it into normalized velocity signals.

---

## Prompt 1 — Core Prism Framework

```
Build the core .prism connector framework. This is a foundational refactor — it adds a plugin architecture to the existing engine without breaking any existing functionality. All 149 tests must continue to pass after this prompt.

---

PART A — Base Interface

Create connectors/base.py with the following:

PrismMetadata dataclass:
  name: str                          # human-readable connector name
  slug: str                          # machine-readable identifier, snake_case, e.g. "kalshi_fed"
  version: str                       # semver, e.g. "1.0.0"
  author: str                        # GitHub username or full name
  source_type: Literal["prediction_market", "alternative_data", "news", "custom"]
  transport: Literal["websocket", "rest", "push"]
  description: str                   # one sentence
  auth_required: bool
  auth_fields: list[str]             # env var names required for auth, e.g. ["KALSHI_API_KEY", "KALSHI_PRIVATE_KEY_PATH"]
  contract_slugs: list[str]          # which slugs from contract_equity_map.json this connector can emit signals for
  poll_interval_seconds: float | None  # None for WebSocket/push connectors
  capabilities: list[str]           # e.g. ["velocity", "volume", "orderbook"]

PrismConnector abstract base class:
  Class variables:
    metadata: PrismMetadata          # must be defined on every subclass

  Abstract methods:
    async def start(self, tracker: VelocityTracker, mapper: ContractMapper, handle_signal: Callable) -> None
      # Start the connector. This method runs indefinitely (event loop). It is responsible for
      # fetching/streaming data, constructing PricePoint objects, feeding them to tracker,
      # and calling handle_signal when tracker fires a VelocitySignal.
      # Must handle its own reconnection and error recovery internally.

    async def stop(self) -> None
      # Graceful shutdown. Cancel any running tasks, close connections.

    def health_check(self) -> dict
      # Return a dict with at minimum: {"status": "ok"|"degraded"|"error", "message": str, "last_update": ISO timestamp | None}

  Concrete methods (provided in base, not overridable):
    def validate_auth(self) -> None
      # Reads all auth_fields from environment. Raises RuntimeError with a clear message if any are missing.
      # Called automatically before start().

    @classmethod
    def from_prism_package(cls, package_path: Path) -> "PrismConnector"
      # Factory method. Given a path to a .prism directory package, load connector.prism manifest,
      # import __init__.py, find the PrismConnector subclass, validate metadata matches manifest, return instance.

PrismRegistry class:
  Manages all loaded connectors for a session.

  Methods:
    def register(self, connector: PrismConnector) -> None
    def load_directory(self, path: Path) -> int
      # Scan a directory for .prism packages. Load each one via PrismConnector.from_prism_package().
      # Return the number of connectors successfully loaded. Log a WARNING for any that fail to load
      # (bad manifest, missing class, auth missing) and continue — never crash on a bad connector.
    def get_all(self) -> list[PrismConnector]
    def get_by_slug(self, slug: str) -> PrismConnector | None
    def get_health_report(self) -> dict[str, dict]
      # Returns {slug: health_check()} for all registered connectors.

---

PART B — Manifest Format

The connector.prism manifest is a YAML file at the root of every .prism directory package. Schema:

```yaml
prism: "1.0"                          # manifest format version, always "1.0" for now
name: "Kalshi Fed Rate Markets"
slug: "kalshi_fed"
version: "1.0.0"
author: "arpjw"
source_type: "prediction_market"
transport: "websocket"
description: "Streams KXFED contract prices from Kalshi via WebSocket."
auth_required: true
auth_fields:
  - KALSHI_API_KEY
  - KALSHI_PRIVATE_KEY_PATH
contract_slugs:
  - KXFED
poll_interval_seconds: null           # null for WebSocket connectors
capabilities:
  - velocity
  - volume
```

Write a validate_manifest(path: Path) -> dict function in connectors/base.py that reads a connector.prism file, validates all required fields are present and correctly typed, and returns the parsed dict. Raise a descriptive ValueError if any field is invalid.

---

PART C — Migration of Existing Connectors

Migrate both existing connectors to the .prism format. Do not delete the original files — instead, create .prism packages that wrap them.

Create connectors/kalshi_fed.prism/:
  connector.prism    # manifest as above
  __init__.py        # KalshiFedConnector(PrismConnector) — thin wrapper around existing KalshiPoller
  README.md          # one paragraph describing what it tracks and what equities it maps to

Create connectors/polymarket_macro.prism/:
  connector.prism    # manifest for Polymarket
  __init__.py        # PolymarketMacroConnector(PrismConnector) — thin wrapper around existing PolymarketPoller
  README.md

The wrapper pattern: the __init__.py should instantiate the existing poller class and delegate start()/stop()/health_check() to it. Do not duplicate logic.

---

PART D — Registry Integration

Update main.py:
- On startup, instantiate a PrismRegistry.
- Call registry.load_directory(Path("connectors/")) to load all .prism packages.
- Also load from connectors/custom/ if the directory exists (user-dropped connectors).
- Replace the direct KalshiPoller and PolymarketPoller instantiation in main.py with registry.get_all() — iterate over all registered connectors and start them as concurrent asyncio tasks.
- On the --dry-run startup banner, add a "prism connectors loaded: N" line listing each connector's name and slug.
- On graceful shutdown, call stop() on all registered connectors.

Update scripts/healthcheck.py:
- Add a new check: "Prism connectors" — loads the registry, validates all connector manifests in connectors/, checks that auth fields for each are present in the environment. Reports pass/fail per connector. A connector failing auth does not fail the overall healthcheck — it reports WARN and the connector is skipped at runtime.

---

PART E — Tests

Add tests/test_prism_framework.py with at least 15 tests covering:
- PrismMetadata field validation
- validate_manifest with a valid manifest
- validate_manifest with missing required fields (should raise ValueError)
- validate_manifest with wrong type on a field
- PrismRegistry.load_directory with a valid .prism package
- PrismRegistry.load_directory with a malformed package (should warn and skip, not crash)
- PrismRegistry.load_directory with missing auth fields (should warn and skip)
- PrismRegistry.get_by_slug
- PrismRegistry.get_health_report
- PrismConnector.validate_auth passes when env vars are set
- PrismConnector.validate_auth raises when env vars are missing
- KalshiFedConnector metadata matches its connector.prism manifest
- PolymarketMacroConnector metadata matches its connector.prism manifest
- from_prism_package loads a connector correctly
- Full registry startup in main.py does not break when custom/ directory is absent
```

---

## Prompt 2 — Built-in Extra Connectors

```
Build three additional built-in .prism connectors. Each must be a complete .prism package with manifest, connector class, and README. All must implement the full PrismConnector interface.

---

CONNECTOR 1: Metaculus

Package: connectors/metaculus_macro.prism/

What it does: Polls Metaculus for resolution probability on macro-relevant questions. Metaculus has public API endpoints that return question data including community probability. Target questions: US recession probability, Fed pivot questions, inflation questions.

API: GET https://www.metaculus.com/api2/questions/?search={query}&status=open — no auth required for public questions.

Manifest fields:
  name: "Metaculus Macro Questions"
  slug: "metaculus_macro"
  source_type: "prediction_market"
  transport: "rest"
  auth_required: false
  contract_slugs: ["KXFED", "KXCPI", "KXJOBS"]   # approximate mappings
  poll_interval_seconds: 300   # 5 minutes — Metaculus doesn't update that frequently
  capabilities: ["velocity"]

Configuration env vars (not auth, just config):
  METACULUS_QUESTION_IDS: comma-separated list of Metaculus question IDs to track. Default: empty (connector logs a WARNING and no-ops if not set).

Implementation:
- GET /api2/questions/{id}/ for each question ID.
- Extract community_prediction.full.q2 (the median community probability, 0-1).
- Map each question ID to a contract_slug via a METACULUS_SLUG_MAP env var in format "12345:KXFED,67890:KXCPI". If a question has no mapping, skip it.
- Construct PricePoint(timestamp=now, price=community_prediction, volume=num_predictions) and feed to VelocityTracker.
- Poll every METACULUS_POLL_INTERVAL_SECONDS (default 300).
- health_check returns last successful fetch timestamp and number of questions tracked.

README: explain that Metaculus questions update slowly but represent aggregated expert forecasts, making velocity spikes rare but high-conviction.

---

CONNECTOR 2: Manifold Markets

Package: connectors/manifold_macro.prism/

What it does: Polls Manifold Markets for binary market probabilities on macro questions. Manifold is faster-moving than Metaculus and has active trading on US economic questions.

API: GET https://api.manifold.markets/v0/markets?term={query}&limit=20 — no auth required for reads.

Manifest fields:
  name: "Manifold Markets Macro"
  slug: "manifold_macro"
  source_type: "prediction_market"
  transport: "rest"
  auth_required: false
  contract_slugs: ["KXFED", "KXCPI", "KXJOBS", "KXBTC"]
  poll_interval_seconds: 120
  capabilities: ["velocity", "volume"]

Configuration env vars:
  MANIFOLD_MARKET_IDS: comma-separated Manifold market slugs to track (e.g. "will-the-fed-cut-rates-in-2026").
  MANIFOLD_SLUG_MAP: mapping from Manifold market slug to contract_slug, same format as Metaculus.

Implementation:
- GET /v0/market/{marketSlug} for each configured market.
- Extract probability field (0-1) and volume field.
- Construct PricePoint and feed to VelocityTracker.
- Poll every MANIFOLD_POLL_INTERVAL_SECONDS (default 120).

README: explain that Manifold uses play money but has surprisingly accurate calibration on macro questions, and velocity spikes here often precede Kalshi moves.

---

CONNECTOR 3: FRED Alternative Data

Package: connectors/fred_macro.prism/

What it does: Polls the St. Louis Fed FRED API for macro economic series that are leading indicators for the events tracked by Kalshi/Polymarket contracts. This is not a prediction market — it is an alternative data connector that feeds economic data into the velocity framework as if it were a probability series.

API: GET https://api.stlouisfed.org/fred/series/observations?series_id={id}&api_key={key}&file_type=json&limit=10&sort_order=desc

Auth: FRED_API_KEY (free, register at fred.stlouisfed.org/docs/api/api_key.html)

Manifest fields:
  name: "FRED Macro Indicators"
  slug: "fred_macro"
  source_type: "alternative_data"
  transport: "rest"
  auth_required: true
  auth_fields: ["FRED_API_KEY"]
  contract_slugs: ["KXFED", "KXCPI", "KXJOBS"]
  poll_interval_seconds: 3600   # FRED updates at most daily, polling hourly is sufficient
  capabilities: ["velocity"]

Configuration env vars:
  FRED_SERIES: comma-separated FRED series IDs to track, e.g. "FEDFUNDS,CPIAUCSL,UNRATE"
  FRED_SERIES_SLUG_MAP: mapping from FRED series ID to contract_slug, e.g. "FEDFUNDS:KXFED,CPIAUCSL:KXCPI"

Implementation note — normalization:
FRED series are not probabilities (0-1). They are raw economic values. Normalize each series to 0-1 using a rolling 52-week min-max normalization: price_normalized = (value - rolling_min) / (rolling_max - rolling_min). Store the rolling window in memory (deque of last 52 weekly observations). This transforms the economic series into a pseudo-probability that the velocity framework can process.

This means a FRED velocity spike represents an unusually rapid move in the economic indicator relative to its recent history — exactly the kind of information that prediction markets will reprice on.

health_check: return last fetch timestamp, number of series tracked, and current normalized values.

README: explain the normalization approach, what each default series means, and that FRED data is a leading indicator for prediction market moves rather than a concurrent signal.

---

TESTS

Add tests/test_builtin_connectors.py with at least 12 tests covering:
- MetaculusConnector metadata is valid
- MetaculusConnector skips gracefully when METACULUS_QUESTION_IDS is not set
- MetaculusConnector parses API response correctly (mock the HTTP call)
- ManifoldConnector metadata is valid
- ManifoldConnector parses probability correctly
- FREDConnector metadata is valid
- FREDConnector rolling min-max normalization at edge cases (all same value, first observation, 52+ observations)
- FREDConnector raises on missing FRED_API_KEY
- All three connectors load correctly via PrismRegistry.load_directory
- All three connector.prism manifests pass validate_manifest
```

---

## Prompt 3 — Developer SDK and Documentation

```
Build the developer-facing SDK and documentation that allows external developers to build their own .prism connectors.

---

PART A — SDK Module

Create prism_sdk/ as a standalone importable package at the root of the repo (not inside connectors/). This is what an external developer would import to build a connector.

prism_sdk/__init__.py — re-exports:
  PrismConnector, PrismMetadata, PrismRegistry (from connectors/base.py)
  PricePoint, VelocitySignal (from signals/velocity.py)

prism_sdk/scaffold.py — CLI scaffolding tool:
  Command: python -m prism_sdk.scaffold --name "My Connector" --slug my_connector --type prediction_market --transport rest
  
  Creates a new .prism package directory at connectors/{slug}.prism/ with:
  - connector.prism manifest pre-filled with provided values and placeholder fields
  - __init__.py with a skeleton PrismConnector subclass, all abstract methods stubbed with NotImplementedError and docstrings explaining what each should do
  - schema.json with the PricePoint schema documented
  - README.md template with sections: Overview, Data Source, Authentication, Configuration, Emitted Signals, Contract Mappings

  Prints a success message with next steps:
  1. Fill in connector.prism manifest
  2. Implement start(), stop(), health_check() in __init__.py
  3. Add connector slug to data/contract_equity_map.json if needed
  4. Run python scripts/healthcheck.py to validate
  5. Drop into connectors/ and restart the engine

prism_sdk/validator.py:
  Command: python -m prism_sdk.validator --path connectors/my_connector.prism
  
  Validates a .prism package without running it:
  - Parses and validates connector.prism manifest
  - Imports __init__.py and checks for PrismConnector subclass
  - Verifies metadata on class matches manifest
  - Checks all auth_fields are described in README.md
  - Checks contract_slugs exist in data/contract_equity_map.json
  - Prints a pass/fail report for each check with actionable error messages
  - Exits 0 if all pass, 1 if any fail

---

PART B — CONTRIBUTING_CONNECTORS.md

Write a comprehensive guide for external developers at CONTRIBUTING_CONNECTORS.md in the repo root. Sections:

1. What is a .prism connector?
   - Explain the concept, the PrismConnector interface, what PricePoint is and why normalization to 0-1 is required
   - Explain that any data source can be a connector — prediction markets, news sentiment, order flow, satellite data, anything that produces a time series

2. Quickstart (5 minutes to first connector)
   - pip install requirements
   - python -m prism_sdk.scaffold --name "My Source" --slug my_source --type custom --transport rest
   - Walk through filling in each file
   - python -m prism_sdk.validator --path connectors/my_source.prism
   - Drop into connectors/ and run python main.py --dry-run

3. PrismConnector interface reference
   - Document every method: signature, parameters, return type, expected behavior, error handling contract
   - Include a fully worked minimal example (a connector that generates random walk price data for testing)

4. The PricePoint contract
   - Fields: timestamp (datetime, UTC), price (float, must be 0.0-1.0), volume (int, optional), slug (str, must match a key in contract_equity_map.json)
   - Why 0-1 normalization: the velocity framework assumes prices are probabilities. Explain the FRED normalization approach as a template for non-probability data sources.

5. Manifest reference
   - Every field documented with type, required/optional, valid values, and example

6. Authentication pattern
   - Env var convention: PREFIX_FIELD_NAME (e.g. MYCONNECTOR_API_KEY)
   - How validate_auth() works and when it is called
   - How to document auth requirements in README.md

7. Transport patterns
   - REST polling: show the pattern used in MetaculusConnector, explain the poll loop
   - WebSocket: show the pattern used in KalshiFedConnector, explain reconnection and backoff
   - Push: explain that push connectors call handle_signal directly without going through VelocityTracker (for pre-computed signals)

8. Contract mapping
   - How contract_equity_map.json works
   - When to add new entries vs reuse existing slugs
   - The macro_factors and sector fields added in v3

9. Submitting a connector
   - Fork the repo
   - Build and validate with prism_sdk.validator
   - Open a PR with the .prism package and a brief description of the data source
   - What the review process checks: manifest completeness, normalization correctness, error handling, test coverage

10. Built-in connector examples
    - Link to each of the four built-in connectors as reference implementations

---

PART C — Tests

Add tests/test_prism_sdk.py with at least 10 tests covering:
- scaffold creates correct directory structure
- scaffold pre-fills manifest with provided values
- validator passes on a valid .prism package
- validator fails with clear message on missing manifest
- validator fails with clear message on missing PrismConnector subclass
- validator fails when contract_slug not in contract_equity_map.json
- validator exit code 0 on pass, 1 on fail
- SDK re-exports are all importable from prism_sdk
- Minimal connector example in CONTRIBUTING_CONNECTORS.md is valid (parse and check)
```

---

## Prompt 4 — Landing Page Prism Section

```
Add a Prism connector ecosystem section to the landing page in ui/. This section should appear between the Architecture section and the Stack section. It showcases the .prism format and the built-in connectors, inviting developers to build their own.

---

SECTION: PRISM CONNECTORS

Section label: "05 // PRISM"

Headline: "Bring your own signal." in DM Serif Display 48px.

Sub-headline below: "Any data source. One interface." DM Sans 20px text-secondary.

Body paragraph (DM Sans 16px text-secondary, max-width 600px, margin-top 16px):
".prism is the connector format for the Velocity Signal Engine. Drop a .prism package into the connectors/ directory and the engine loads it automatically. Prediction markets, alternative data, news sentiment, order flow — if it produces a time series, it can drive a signal."

---

Connector cards grid (2x2 on desktop, 1-col on mobile, gap 16px, margin-top 64px):

Each card: background #111111, border 1px solid #222222, border-radius 8px, padding 28px 32px.
On hover: border-color Robin Neon, transition 200ms.

Card 1 — Kalshi (BUILT-IN):
- Top row: slug "kalshi_fed" in DM Mono 11px text-tertiary, badge "BUILT-IN" in DM Mono 10px — background #1a2e1a, color #86efac, border-radius 2px, padding 2px 6px
- Name: "Kalshi Fed Markets" DM Serif Display 20px
- Transport badge: "WS" (WebSocket) — Robin Neon background, #000 text, DM Mono 10px, padding 2px 6px, border-radius 2px
- Description: DM Sans 14px text-secondary "Streams KXFED contract prices via WebSocket. Five contracts tracking Fed funds rate targets through April 2027."
- Bottom: "5 contracts  ·  Auth required  ·  v1.0.0" DM Mono 11px text-tertiary

Card 2 — Polymarket (BUILT-IN):
- Same structure, slug "polymarket_macro", transport "WS"
- Name: "Polymarket Macro"
- Description: "Streams macro prediction market prices from Polymarket's CLOB via WebSocket. Covers Fed, inflation, and economic event contracts."

Card 3 — Metaculus (BUILT-IN):
- Slug "metaculus_macro", transport "REST", badge "BUILT-IN"
- Name: "Metaculus Macro Questions"
- Description: "Polls Metaculus for expert-aggregated probability on macro questions. Low frequency, high conviction — velocity spikes here are rare but informative."

Card 4 — Build Your Own:
- No slug, no version
- Border: 1px dashed #333333 (dashed, not solid)
- Top row: ".prism" in DM Mono 11px Robin Neon
- Name: "Your Connector" DM Serif Display 20px text-secondary
- Body: "Any data source. One interface. Drop a .prism package into connectors/ and the engine loads it automatically." DM Sans 14px text-tertiary
- Bottom: a button "Read the spec →" — same style as secondary CTA in hero, links to GitHub CONTRIBUTING_CONNECTORS.md

---

Below the cards, a code snippet showing the minimal connector interface. Use a styled pre/code block:
- Background #0d0d0d, border 1px solid #222222, border-radius 8px, padding 24px 28px
- DM Mono 13px, line-height 1.7
- Syntax highlighting: comments in #555555, keywords (class, def, async, return) in Robin Neon, strings in #888888, everything else text-primary
- No external syntax highlighting library — implement with simple span wrapping

Code to display:
```python
class MyConnector(PrismConnector):
    metadata = PrismMetadata(
        name="My Data Source",
        slug="my_source",
        source_type="prediction_market",
        transport="rest",
        auth_fields=["MY_API_KEY"],
        contract_slugs=["KXFED"],
    )

    async def start(self, tracker, mapper, handle_signal):
        while True:
            price = await self.fetch_latest_price()
            tracker.update(self.metadata.slug, PricePoint(
                timestamp=datetime.now(UTC),
                price=price,   # must be 0.0 – 1.0
                volume=1,
            ))
            await asyncio.sleep(self.metadata.poll_interval_seconds)
```

---

Update the section numbering in the existing sections:
- Stack section label changes from "03 // STACK" to "04 // STACK"  
- Status section label changes from "04 // STATUS" to "06 // STATUS"
- Footer stat box updates: add "4 prism connectors" to the footer right column stat line

Update the Architecture diagram in ArchitectureSection to add a [Prism Registry] node between the pollers and VelocityTracker:

[Kalshi .prism] ──►
[Polymarket .prism] ──► [Prism Registry] ──► [VelocityTracker] ──► ...
[Custom .prism] ──►

The Prism Registry node should be highlighted in Robin Neon by default (not just on hover) — it is the new central piece of the architecture.
```

---

## Prompt 5 — README and Documentation Final Update

```
Update README.md, CLAUDE.md, and .env.example to fully reflect the Prism framework.

README.md additions:
- Add a "Prism Connector Framework" section after the V3 Improvements section. Include: what .prism is and why it exists, the directory structure of a .prism package with all four files described, how to use the scaffold tool, how to validate a connector, how to drop it into the engine. Link to CONTRIBUTING_CONNECTORS.md for the full developer guide.
- Update the Architecture diagram to show the Prism Registry layer.
- Add all four built-in connectors to a "Built-in Connectors" table with columns: name, slug, source, transport, auth required, contract slugs.
- Add new env vars to the table: METACULUS_QUESTION_IDS, METACULUS_SLUG_MAP, MANIFOLD_MARKET_IDS, MANIFOLD_SLUG_MAP, FRED_API_KEY, FRED_SERIES, FRED_SERIES_SLUG_MAP.

CLAUDE.md additions:
- Add a "Prism Framework" section documenting: the PrismConnector interface contract, the manifest schema, how PrismRegistry.load_directory works, the connector loading order (built-in first, then custom/), what happens when a connector fails to load (warn and skip), the SDK scaffold and validator commands, and the normalization requirement (all prices must be 0.0-1.0).
- Update the Stack section to include prism_sdk as a first-party package.

.env.example additions:
- Add commented-out sections for each new connector with all their env vars and brief descriptions of what each does.
- Add a section header comment "# PRISM CONNECTORS" before the connector-specific vars.
- Add FRED_API_KEY with a comment: "# Free API key from https://fred.stlouisfed.org/docs/api/api_key.html"
```

---

## Notes

- Run `pytest tests/ -q` after every prompt. Target: 149 + 15 + 12 + 10 = 196+ tests passing after all four feature prompts.
- After Prompt 1, manually test the registry by running `python main.py --dry-run` and verifying the startup banner shows "prism connectors loaded: 2" for Kalshi and Polymarket.
- After Prompt 2, register for a FRED API key (free, instant) and add to .env so the FRED connector can be tested end-to-end.
- After Prompt 3, run `python -m prism_sdk.scaffold --name "Test" --slug test --type custom --transport rest` and verify the scaffolded package passes `python -m prism_sdk.validator`.
- The prism_sdk package should eventually be publishable to PyPI as a standalone package so developers can pip install it without cloning the full repo. Do not implement PyPI publishing now, but structure the package so it could be extracted cleanly.
- The .prism format version is "1.0" — bake this in everywhere. When breaking changes are needed in the future, version 2.0 connectors will be handled differently.
