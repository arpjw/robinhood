# Signal Quality Oracle — Build Plan

The Oracle is a continuous signal evaluation system that runs alongside the Robinhood Velocity Signal Engine. It consumes runtime logs, computes per-connector quality metrics, detects macro regimes, tunes thresholds, and publishes connector reputation scores back to the Prism registry. It runs as a separate process — never blocking the signal pipeline.

---

## Architecture Overview

```
logs/signals.jsonl ──┐
                     ├──► Oracle ──► oracle/output/scores.json ──► registry_publisher ──► prism/registry/registry.json
logs/orders.jsonl ───┘         │
                               ├──► oracle/output/ic_report.json
                               ├──► oracle/output/decay_curves.json
                               ├──► oracle/output/thresholds.json
                               └──► oracle/output/regime.json
```

The Oracle reads logs, writes structured JSON output to `oracle/output/`, and optionally publishes connector scores to the Prism registry via the GitHub API. All output files are human-readable and can be consumed by the dashboard.

---

## Prompt 1 — Core Oracle Infrastructure

```
Build the core Oracle infrastructure: log reader, data models, and the base computation pipeline.

---

PART A — Data Models (oracle/models.py)

SignalRecord dataclass:
  Parsed representation of a single line from logs/signals.jsonl.
  Fields:
    signal_id: str               # uuid
    timestamp: datetime          # UTC
    contract_slug: str           # e.g. KXFED-27APR-T4.25
    velocity: float              # Δp/Δt at signal time
    direction: Literal["up", "down"]
    source: str                  # connector slug e.g. "kalshi_fed"
    basket: list[str]            # equity tickers
    sector: str
    macro_factors: list[str]
    confidence: float            # from contract_equity_map.json
    fired: bool                  # True if signal passed dedup and exposure checks

OrderRecord dataclass:
  Parsed representation of a single line from logs/orders.jsonl.
  Fields (subset of execution/order_schema.py — replicate only what Oracle needs):
    order_id: str
    signal_id: str               # foreign key to SignalRecord
    timestamp: datetime
    mode: Literal["mock", "live"]
    ticker: str
    side: Literal["buy", "sell"]
    size_usd: float
    entry_price: float | None
    exit_price: float | None
    exit_reason: str | None      # "time_decay", "adverse_move", "reverse_velocity"
    exit_timestamp: datetime | None
    pnl_usd: float | None
    source: str                  # connector slug
    contract_slug: str
    velocity: float

OracleMetrics dataclass:
  Computed metrics for a single connector over a time window.
  Fields:
    connector_slug: str
    computed_at: datetime
    window_days: int
    signal_count: int
    fired_count: int             # signals that passed all filters
    trade_count: int             # fired signals that resulted in orders
    win_count: int
    win_rate: float              # win_count / trade_count, NaN if trade_count == 0
    total_pnl_usd: float
    avg_pnl_usd: float
    sharpe: float | None         # None if fewer than 10 trades
    ic: float | None             # information coefficient, None if insufficient data
    ic_pvalue: float | None      # p-value for IC, None if ic is None
    avg_hold_minutes: float
    best_trade_usd: float
    worst_trade_usd: float
    signal_decay_curve: dict[int, float]   # {minutes: avg_pnl} at 15m buckets up to 4h
    optimal_velocity_threshold: float | None
    suppression_rate: float      # (signal_count - fired_count) / signal_count
    reputation_score: float      # composite 0-100, see reputation_scorer.py

RegimeState dataclass:
  Current macro regime classification.
  Fields:
    detected_at: datetime
    regime: Literal["risk_on", "risk_off", "high_vol", "low_vol", "trending", "mean_reverting", "unknown"]
    confidence: float            # 0-1
    evidence: list[str]          # human-readable evidence strings e.g. "VIX proxy above 25"
    recommended_threshold_multiplier: float  # multiply base threshold by this in current regime
    recommended_position_multiplier: float   # multiply max_position_pct by this

---

PART B — Log Reader (oracle/log_reader.py)

LogReader class:
  Reads and parses logs/signals.jsonl and logs/orders.jsonl.
  Both files are append-only JSONL — each line is a JSON object.

  Methods:
    read_signals(
      since: datetime | None = None,
      until: datetime | None = None,
      connector_slug: str | None = None,
      contract_slug: str | None = None,
    ) -> list[SignalRecord]:
      Read all signals from logs/signals.jsonl matching the filters.
      Parse each line into SignalRecord. Skip malformed lines with a WARNING log.
      Return sorted by timestamp ascending.

    read_orders(
      since: datetime | None = None,
      until: datetime | None = None,
      connector_slug: str | None = None,
      mode: str | None = None,
    ) -> list[OrderRecord]:
      Read all orders from logs/orders.jsonl matching the filters.
      Parse each line into OrderRecord. Skip malformed lines with a WARNING log.
      Return sorted by timestamp ascending.

    join(signals: list[SignalRecord], orders: list[OrderRecord]) -> list[tuple[SignalRecord, OrderRecord | None]]:
      Join signals to their corresponding orders by signal_id (foreign key).
      Signals with no matching order get None as the order.
      Returns list of (signal, order_or_none) tuples sorted by signal timestamp.

    watch(callback: Callable[[str, dict], None], poll_interval: float = 5.0) -> None:
      Async method. Poll both log files every poll_interval seconds.
      On each poll, read only new lines since last read (track file position).
      Call callback("signal", parsed_dict) or callback("order", parsed_dict) for each new line.
      Used by the live oracle runner to process events as they arrive.

  Implementation notes:
  - Use file position tracking (store last byte offset per file) for efficient incremental reads.
  - Handle log rotation gracefully: if file size is smaller than last known position, reset to 0.
  - All timestamps parsed as UTC-aware datetime objects.

---

PART C — Oracle Runner (oracle/runner.py)

OracleRunner class:
  Orchestrates the full oracle computation pipeline.

  Constructor:
    log_reader: LogReader
    window_days: int = 30         # default evaluation window
    output_dir: Path = Path("oracle/output")
    publish: bool = False         # whether to push scores to Prism registry

  Methods:
    async def run_once(self) -> dict[str, OracleMetrics]:
      Run the full pipeline once and write all output files.
      Steps:
      1. Read signals and orders for the configured window.
      2. For each connector slug seen in signals, compute OracleMetrics.
      3. Detect current regime.
      4. Compute recommended thresholds.
      5. Write all output files to oracle/output/.
      6. If publish=True, call registry_publisher.publish_scores().
      Return dict mapping connector_slug -> OracleMetrics.

    async def run_continuous(self, interval_seconds: int = 300) -> None:
      Run run_once() every interval_seconds. Log timing.
      Never crash on a single run failure — catch exceptions, log ERROR, continue.

    def write_outputs(self, metrics: dict[str, OracleMetrics], regime: RegimeState) -> None:
      Write all output JSON files. Overwrite on each run.
      Files:
        oracle/output/scores.json       — reputation scores per connector
        oracle/output/ic_report.json    — full IC data per connector
        oracle/output/decay_curves.json — signal decay curves per connector
        oracle/output/thresholds.json   — recommended thresholds per contract category
        oracle/output/regime.json       — current regime state
        oracle/output/summary.json      — human-readable summary of last run

---

PART D — Entry Point (scripts/run_oracle.py)

CLI script using typer:

Commands:
  run
    Options:
      --window-days INT     Evaluation window (default 30)
      --interval INT        Seconds between runs in continuous mode (default 300)
      --once                Run once and exit (default: continuous)
      --publish             Push scores to Prism registry after each run
      --output-dir PATH     Where to write output JSON (default: oracle/output/)
    
    Behavior:
    - Load .env with dotenv
    - Create LogReader, OracleRunner
    - If --once: run_once(), print summary, exit
    - Else: run_continuous()
    - On SIGINT: print final summary and exit cleanly

  report
    Options:
      --connector TEXT      Show report for specific connector (default: all)
      --format TEXT         "table" (default) or "json"
    
    Reads oracle/output/scores.json and other output files.
    Prints a rich formatted report to terminal showing:
    - Current regime and recommended adjustments
    - Per-connector table: slug, signal_count, win_rate, IC, sharpe, reputation_score
    - Threshold recommendations per contract category
    - Last computed timestamp

---

PART E — Tests (tests/test_oracle_core.py)

At least 15 tests covering:
- LogReader.read_signals parses valid JSONL correctly
- LogReader.read_signals skips malformed lines without crashing
- LogReader.read_signals filters by connector_slug
- LogReader.read_signals filters by since/until datetime
- LogReader.read_orders parses all OrderRecord fields
- LogReader.join correctly links signals to orders by signal_id
- LogReader.join returns None for signals with no matching order
- LogReader incremental read tracks file position correctly
- OracleMetrics fields are computed correctly from known input
- OracleRunner.run_once writes all expected output files
- OracleRunner.run_continuous catches exceptions and continues
- Output JSON files are valid JSON
- report command prints without error when output files exist
- report command handles missing output files gracefully
- run --once exits after one run
```

---

## Prompt 2 — Information Coefficient Calculator

```
Build the Information Coefficient (IC) calculator. IC measures how well signal velocity predicts subsequent equity returns — it is the primary measure of signal quality in quantitative research.

---

WHAT IC IS

The Information Coefficient is the Spearman rank correlation between:
- X: the velocity magnitude at signal fire time (a prediction of subsequent return magnitude)
- Y: the actual equity return in the N hours following signal entry

IC ranges from -1 to +1.
- IC > 0.05 is considered weak positive predictive power
- IC > 0.10 is meaningful
- IC > 0.20 is strong
- IC < 0 means the signal is anti-predictive (velocity up → equity down on average)

IC p-value: the two-tailed p-value for the Spearman correlation. IC is only reliable when p < 0.05.

We compute IC separately for each connector and each contract category (Fed, CPI, jobs, etc.) because predictive power may vary significantly across event types.

---

PART A — IC Calculator (oracle/ic_calculator.py)

ICResult dataclass:
  connector_slug: str
  contract_category: str | None   # e.g. "KXFED", None for aggregate across all categories
  n_observations: int
  ic: float
  ic_pvalue: float
  ic_significant: bool            # True if pvalue < 0.05 and n_observations >= 10
  lookback_hours: float           # what return window was used
  computed_at: datetime
  velocity_series: list[float]    # velocities at signal time (for debugging)
  return_series: list[float]      # realized returns over lookback window

ICCalculator class:

  Constructor:
    equity_fetcher: Callable[[str, datetime, datetime], float | None]
      # Function that fetches equity close price for ticker at a given datetime.
      # Use yfinance: yf.download(ticker, start=dt, end=dt+timedelta(hours=1))["Close"].iloc[0]
      # Returns None if data unavailable.
    lookback_hours: float = 2.0   # match default exit window
    min_observations: int = 10    # minimum trades needed to compute IC

  Methods:
    def compute(
      self,
      joined: list[tuple[SignalRecord, OrderRecord | None]],
      connector_slug: str,
    ) -> list[ICResult]:
      Compute IC for the given connector across all contract categories and in aggregate.
      
      Steps:
      1. Filter joined pairs to those with: order is not None, entry_price is not None, exit_price is not None.
      2. For each pair, compute realized_return = (exit_price - entry_price) / entry_price * direction_sign.
         direction_sign: +1 if side == "buy", -1 if side == "sell".
      3. Compute Spearman rank correlation between velocity (X) and realized_return (Y).
         Use scipy.stats.spearmanr.
      4. Compute p-value from spearmanr result.
      5. Build ICResult for aggregate (contract_category=None).
      6. Repeat steps 2-5 grouping by contract category (first two chars of contract_slug: "KXFED", "KXCPI", etc.).
         Only compute per-category IC if n >= min_observations.
      7. Return list of ICResult objects (aggregate first, then per-category).

    def compute_rolling(
      self,
      joined: list[tuple[SignalRecord, OrderRecord | None]],
      connector_slug: str,
      window_size: int = 20,
    ) -> list[tuple[datetime, float]]:
      Compute rolling IC over the last window_size trades.
      Returns list of (timestamp, ic) pairs — one per trade after the first window_size.
      Used for the rolling IC chart in the dashboard.

    def ic_decay(
      self,
      joined: list[tuple[SignalRecord, OrderRecord | None]],
      connector_slug: str,
      max_hours: float = 4.0,
      bucket_minutes: int = 15,
    ) -> dict[int, ICResult]:
      Compute IC at multiple exit windows (15m, 30m, 45m, ... up to max_hours).
      For each window, fetch the equity price at entry_time + window and compute IC.
      Returns dict mapping minutes -> ICResult.
      This shows whether the signal has more predictive power at shorter or longer horizons.

  Dependencies: scipy, yfinance. Add to requirements.txt.

---

PART B — Tests (tests/test_ic_calculator.py)

At least 12 tests covering:
- ICResult dataclass fields and defaults
- compute returns ICResult with correct n_observations
- compute returns IC = 0 when velocity and return are uncorrelated (random data)
- compute returns IC > 0 when velocity positively correlates with return (synthetic data)
- compute returns IC < 0 when velocity negatively correlates (synthetic data)
- ic_significant is False when n < min_observations
- ic_significant is False when pvalue >= 0.05
- compute returns aggregate result and per-category results
- compute_rolling returns correct number of (timestamp, ic) pairs
- ic_decay returns one ICResult per bucket up to max_hours
- compute handles joined list where all orders are None (returns ICResult with n=0)
- equity_fetcher returning None is handled gracefully (skip that observation)
```

---

## Prompt 3 — Signal Decay Analyzer and Threshold Tuner

```
Build the signal decay analyzer (optimal exit window) and threshold tuner (optimal velocity threshold per contract category).

---

PART A — Decay Analyzer (oracle/decay_analyzer.py)

The decay analyzer answers: "For each contract category, at what hold time does the signal edge disappear?"

DecayPoint dataclass:
  minutes: int
  avg_pnl_usd: float
  avg_return_pct: float
  n_observations: int
  std_pnl_usd: float
  sharpe_at_exit: float | None   # annualized Sharpe if we exited at this exact minute

DecayCurve dataclass:
  connector_slug: str
  contract_category: str | None
  computed_at: datetime
  points: list[DecayPoint]       # one per 15-minute bucket, 0-240 minutes
  optimal_exit_minutes: int      # bucket with highest sharpe_at_exit
  current_exit_minutes: int      # from EXIT_HOURS env var * 60
  recommendation: str | None     # "reduce to Xm" or "extend to Xm" or "current is optimal"

DecayAnalyzer class:

  Constructor:
    equity_fetcher: Callable[[str, datetime, datetime], float | None]
    bucket_minutes: int = 15
    max_minutes: int = 240       # 4 hours

  Methods:
    def analyze(
      self,
      joined: list[tuple[SignalRecord, OrderRecord | None]],
      connector_slug: str,
    ) -> list[DecayCurve]:
      For each contract category (and aggregate), compute a DecayCurve.
      
      Steps:
      1. Filter to trades with entry_price and entry_timestamp.
      2. For each bucket (15, 30, 45, ... 240 minutes):
         a. For each trade, fetch equity price at entry_time + bucket_minutes.
         b. Compute hypothetical P&L if we had exited at exactly that bucket.
         c. Aggregate: avg_pnl_usd, avg_return_pct, std_pnl_usd across all trades.
         d. Compute Sharpe: (avg_return_pct / std_return_pct) * sqrt(252 * 6.5 * 60 / bucket_minutes)
            (annualized assuming 6.5 trading hours per day)
      3. Find optimal_exit_minutes = bucket with highest Sharpe.
      4. Compare to current EXIT_HOURS * 60. Generate recommendation string.
      5. Return one DecayCurve per category + one aggregate.

    def format_recommendation(self, curve: DecayCurve) -> str:
      Returns a human-readable recommendation string.
      Examples:
        "Optimal exit for KXFED signals is 45m (current: 120m). Sharpe at 45m: 1.82 vs 0.91 at 120m."
        "Current 120m exit is near-optimal for KXCPI signals (optimal: 105m, Sharpe difference: 0.03)."

---

PART B — Threshold Tuner (oracle/threshold_tuner.py)

The threshold tuner answers: "For each contract category, what velocity threshold maximizes risk-adjusted returns?"

ThresholdResult dataclass:
  connector_slug: str
  contract_category: str | None
  tested_thresholds: list[float]          # e.g. [0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50]
  win_rates: list[float]                  # parallel to tested_thresholds
  avg_pnls: list[float]                   # parallel
  sharpes: list[float | None]             # parallel
  trade_counts: list[int]                 # parallel — how many trades qualify at each threshold
  current_threshold: float                # from VELOCITY_THRESHOLD env var
  optimal_threshold: float                # threshold with best Sharpe (min 5 trades)
  optimal_sharpe: float | None
  current_sharpe: float | None
  recommendation: str
  computed_at: datetime

ThresholdTuner class:

  Constructor:
    tested_thresholds: list[float] = [0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50]
    min_trades_for_threshold: int = 5     # minimum trades at a threshold to consider it

  Methods:
    def tune(
      self,
      joined: list[tuple[SignalRecord, OrderRecord | None]],
      connector_slug: str,
    ) -> list[ThresholdResult]:
      For each contract category (and aggregate):
      1. For each tested threshold T:
         a. Filter signals to those with velocity >= T.
         b. Find corresponding orders.
         c. Compute win_rate, avg_pnl_usd, Sharpe from realized P&L.
         d. If fewer than min_trades_for_threshold, Sharpe = None.
      2. Find optimal_threshold = threshold with highest non-None Sharpe.
      3. Record current_threshold from VELOCITY_THRESHOLD env var.
      4. Generate recommendation string.
      Return list of ThresholdResult (aggregate + per-category).

    def format_recommendation(self, result: ThresholdResult) -> str:
      Examples:
        "Raise threshold for KXFED from 0.15 to 0.25 — Sharpe improves from 0.82 to 1.41 (12 trades)."
        "Current threshold 0.15 is optimal for KXCPI — no improvement found across tested range."
        "Insufficient data for KXJOBS (3 trades). Need at least 5 trades per threshold."

---

PART C — Tests (tests/test_decay_threshold.py)

At least 14 tests covering:
- DecayAnalyzer.analyze returns one DecayCurve per category plus aggregate
- DecayCurve.points has correct number of buckets (max_minutes / bucket_minutes)
- optimal_exit_minutes is within the tested range
- recommendation string is non-empty
- format_recommendation returns correct string for below/above/optimal cases
- ThresholdTuner.tune returns ThresholdResult for each category
- ThresholdResult.tested_thresholds matches constructor input
- optimal_threshold is in tested_thresholds list
- ThresholdResult when all thresholds have fewer than min_trades: optimal_threshold = current, recommendation notes insufficient data
- Trade counts decrease monotonically as threshold increases
- Sharpe is None when trade_count < min_trades_for_threshold
- current_threshold reads from VELOCITY_THRESHOLD env var
- format_recommendation for raise case contains "Raise" and both threshold values
- format_recommendation for insufficient data case mentions trade count
```

---

## Prompt 4 — Regime Detector

```
Build the macro regime detector. The regime detector classifies the current market environment using signals available within the engine — no external data feeds required beyond what's already being consumed.

---

WHAT REGIMES MEAN FOR THE SIGNAL

The velocity signal behaves differently across regimes:
- risk_off: prediction markets and equities both move faster. Signal fires more often but equity moves are larger. Raise velocity threshold to avoid noise; reduce position size.
- risk_on: markets are complacent. Velocity spikes are rarer but more reliable. Can lower threshold slightly; increase position size.
- high_vol: large price swings in both directions. 3% adverse stop fires more often. Widen the stop or reduce size.
- low_vol: compressed ranges. Signal edge is smaller. Be conservative.
- trending: equity prices have persistent directional drift. Signal direction aligned with trend is higher conviction.
- mean_reverting: equity prices oscillate around a level. Velocity signals should be faded more quickly (shorter exit window).

---

PART A — Regime Detector (oracle/regime_detector.py)

RegimeEvidence dataclass:
  indicator: str          # e.g. "kalshi_velocity_frequency"
  value: float
  threshold: float
  direction: str          # "above" or "below"
  interpretation: str     # e.g. "high signal frequency suggests elevated uncertainty"

RegimeDetector class:

  Constructor:
    log_reader: LogReader
    equity_fetcher: Callable[[str, datetime, datetime], float | None]
    lookback_days: int = 14

  Methods:
    def detect(self) -> RegimeState:
      Detect the current regime using the following indicators derived from internal data.
      Do not call external APIs beyond yfinance (which is already a dependency).

      Internal indicators (from log data):
      1. signal_frequency: number of signals fired in the last 7 days vs prior 7 days.
         High and rising → elevated uncertainty → risk_off evidence.
      2. suppression_rate_trend: if ExposureManager is suppressing more signals lately,
         macro factor correlations are clustering → risk_off evidence.
      3. win_rate_trend: rolling 10-trade win rate vs prior 10. Falling → regime shift.
      4. avg_hold_time_trend: if positions are being stopped out faster (adverse move exits increasing),
         volatility is rising → high_vol evidence.
      5. reverse_velocity_exit_rate: if reverse_velocity exits are increasing,
         signals are less persistent → mean_reverting evidence.

      External indicators (yfinance, minimal):
      6. SPY 14-day realized volatility (annualized): above 20% → high_vol, below 12% → low_vol.
         Fetch SPY daily closes for last 14 days.
      7. SPY 14-day trend: linear regression slope. Positive and significant → trending up.
         Negative and significant → trending down.
      8. VIX proxy: compute from SPY option-implied moves if available, else use SPY realized vol as proxy.

      Regime classification logic (majority vote across evidence):
      - Count evidence items for each regime.
      - Regime with most supporting evidence wins.
      - confidence = winning_count / total_evidence_count.
      - If confidence < 0.4: regime = "unknown".

      Regime multipliers (applied to base threshold and position size):
      - risk_off:       threshold_mult=1.3, position_mult=0.7
      - risk_on:        threshold_mult=0.9, position_mult=1.1
      - high_vol:       threshold_mult=1.2, position_mult=0.6
      - low_vol:        threshold_mult=1.0, position_mult=1.0
      - trending:       threshold_mult=0.95, position_mult=1.05
      - mean_reverting: threshold_mult=1.1, position_mult=0.85
      - unknown:        threshold_mult=1.0, position_mult=1.0

    def effective_threshold(self, base_threshold: float, regime: RegimeState) -> float:
      return base_threshold * regime.recommended_threshold_multiplier

    def effective_position_pct(self, base_pct: float, regime: RegimeState) -> float:
      return min(base_pct * regime.recommended_position_multiplier, 0.10)
      # cap at 10% regardless of regime

    def format_summary(self, regime: RegimeState) -> str:
      Human-readable summary. Example:
      "Current regime: RISK_OFF (confidence: 0.71)
       Evidence: high signal frequency (+34% vs prior week), rising suppression rate, 3 reverse-velocity exits in 7 days.
       Recommended adjustments: raise threshold from 0.15 → 0.20, reduce max position from 5% → 3.5%."

---

PART B — Regime Integration with Main Pipeline (optional, controlled by env var)

Add REGIME_AWARE=true env var (default false). When true:
- OracleRunner detects regime after each run_once().
- Write regime.json to oracle/output/.
- Main pipeline reads oracle/output/regime.json at startup and on each signal fire.
- Apply effective_threshold() and effective_position_pct() instead of raw env vars.
- Log the regime and multipliers in the startup banner.

This is opt-in because it adds complexity and requires the oracle to be running alongside the engine. When REGIME_AWARE=false (default), the engine uses raw VELOCITY_THRESHOLD and MAX_POSITION_PCT regardless of oracle state.

---

PART C — Tests (tests/test_regime_detector.py)

At least 10 tests covering:
- RegimeDetector.detect returns RegimeState with valid regime string
- confidence is between 0 and 1
- unknown regime when fewer than 3 evidence items
- risk_off detected when signal_frequency is high and win_rate is falling (mock log data)
- high_vol detected when avg hold time shows rising adverse exits (mock log data)
- effective_threshold applies correct multiplier per regime
- effective_position_pct caps at 0.10 regardless of multiplier
- format_summary contains regime name and confidence
- RegimeState.evidence list is non-empty for non-unknown regimes
- All 7 regime types produce valid multipliers
```

---

## Prompt 5 — Reputation Scorer and Registry Publisher

```
Build the reputation scorer (composite 0-100 score per connector) and the registry publisher (pushes scores back to the Prism registry.json on GitHub).

---

PART A — Reputation Scorer (oracle/reputation_scorer.py)

The reputation score is a single number summarizing connector signal quality. It is published to the Prism registry so users can evaluate connectors before installing them.

Score components and weights:
  IC score (35%):
    - IC >= 0.20 and significant: 100 points
    - IC >= 0.10 and significant: 70 points
    - IC >= 0.05 and significant: 40 points
    - IC >= 0 but not significant: 20 points
    - IC < 0: 0 points
    - Insufficient data (n < 10): 30 points (neutral — not penalized for low volume)

  Win rate score (25%):
    - win_rate >= 0.60: 100 points
    - win_rate >= 0.55: 80 points
    - win_rate >= 0.50: 60 points
    - win_rate >= 0.45: 30 points
    - win_rate < 0.45: 0 points
    - Insufficient data (trade_count < 5): 30 points

  Sharpe score (25%):
    - sharpe >= 2.0: 100 points
    - sharpe >= 1.0: 80 points
    - sharpe >= 0.5: 60 points
    - sharpe >= 0: 30 points
    - sharpe < 0: 0 points
    - None (insufficient data): 30 points

  Data quality score (15%):
    - trade_count >= 50: 100 points
    - trade_count >= 20: 80 points
    - trade_count >= 10: 60 points
    - trade_count >= 5: 40 points
    - trade_count < 5: 20 points

  Final score = weighted sum, rounded to one decimal.
  Score bands: 0-30 (poor), 30-50 (weak), 50-70 (moderate), 70-85 (good), 85-100 (excellent).

ReputationScorer class:
  Methods:
    def score(self, metrics: OracleMetrics, ic_result: ICResult | None) -> float:
      Compute and return the reputation score.
      Also sets metrics.reputation_score in-place.

    def label(self, score: float) -> str:
      Returns "POOR" | "WEAK" | "MODERATE" | "GOOD" | "EXCELLENT"

    def format_scorecard(self, metrics: OracleMetrics, ic_result: ICResult | None) -> str:
      Returns a formatted string showing score breakdown:
      "Reputation: 74.2 (GOOD)
       IC: 0.14 (significant, p=0.03) → 70pts × 35% = 24.5
       Win rate: 0.58 → 80pts × 25% = 20.0
       Sharpe: 1.24 → 80pts × 25% = 20.0
       Data quality: 23 trades → 80pts × 15% = 12.0"

---

PART B — Registry Publisher (oracle/registry_publisher.py)

Pushes connector reputation scores back to the Prism registry.json on GitHub via the GitHub API.
This requires a GitHub personal access token with contents:write permission on the arpjw/prism repo.

Configuration env vars:
  PRISM_GITHUB_TOKEN: GitHub PAT with contents:write on arpjw/prism (required for publishing)
  PRISM_REGISTRY_REPO: default "arpjw/prism"
  PRISM_REGISTRY_BRANCH: default "main"
  PRISM_REGISTRY_PATH: default "registry/registry.json"

RegistryPublisher class:

  Methods:
    async def fetch_registry(self) -> dict:
      GET https://api.github.com/repos/{repo}/contents/{path}?ref={branch}
      Decode base64 content. Return parsed JSON dict.
      Also return SHA (needed for update).

    async def publish_scores(self, scores: dict[str, float], labels: dict[str, str]) -> bool:
      Fetch current registry.json.
      For each connector in registry.json:
        If connector slug is in scores dict:
          Set connector["reputation_score"] = scores[slug]
          Set connector["reputation_label"] = labels[slug]
          Set connector["scores_updated_at"] = ISO timestamp
      PUT updated registry.json back via GitHub API (requires SHA from fetch).
      Return True on success, False on failure.
      On failure: log ERROR with response body, do not raise.

    async def check_auth(self) -> bool:
      Verify PRISM_GITHUB_TOKEN has write access to the registry repo.
      GET /repos/{repo} and check permissions.push. Return True/False.

  Important: publishing is best-effort. If GitHub API fails for any reason,
  log the error and continue — never crash the oracle because publishing failed.

---

PART C — oracle/output/ Schema

Define the schema for all output files written by OracleRunner:

oracle/output/scores.json:
{
  "computed_at": "<ISO>",
  "window_days": 30,
  "connectors": {
    "kalshi_fed": {
      "reputation_score": 74.2,
      "reputation_label": "GOOD",
      "signal_count": 45,
      "trade_count": 23,
      "win_rate": 0.58,
      "ic": 0.14,
      "ic_significant": true,
      "sharpe": 1.24,
      "avg_pnl_usd": 0.87,
      "total_pnl_usd": 20.01
    }
  }
}

oracle/output/regime.json:
{
  "detected_at": "<ISO>",
  "regime": "risk_off",
  "confidence": 0.71,
  "evidence": ["...", "..."],
  "recommended_threshold_multiplier": 1.3,
  "recommended_position_multiplier": 0.7,
  "effective_threshold": 0.195,
  "effective_position_pct": 0.035
}

oracle/output/summary.json:
{
  "computed_at": "<ISO>",
  "window_days": 30,
  "total_signals": 156,
  "total_trades": 67,
  "overall_win_rate": 0.55,
  "regime": "risk_off",
  "connectors_evaluated": 2,
  "top_connector": "kalshi_fed",
  "top_score": 74.2,
  "publishing_enabled": false,
  "recommendations": [
    "Raise threshold from 0.15 to 0.25 for KXFED signals (kalshi_fed)",
    "Reduce exit window from 120m to 45m for KXCPI signals (kalshi_fed)"
  ]
}

---

PART D — Tests (tests/test_reputation_registry.py)

At least 12 tests covering:
- ReputationScorer.score returns value between 0 and 100
- IC component scores for each band (>= 0.20, >= 0.10, >= 0.05, < 0, insufficient)
- Win rate component scores for each band
- Sharpe component scores for each band
- Data quality component for each trade count band
- Weighted sum is correct for a known input
- label returns correct string for each score band
- format_scorecard contains score and all four components
- RegistryPublisher.fetch_registry parses response correctly (mock HTTP)
- RegistryPublisher.publish_scores updates correct fields and calls GitHub API (mock)
- RegistryPublisher returns False and logs ERROR on API failure (mock 403 response)
- check_auth returns False when token is missing
```

---

## Prompt 6 — Dashboard Integration and Final Wiring

```
Integrate the Oracle into the existing dashboard (scripts/dashboard.py) and wire all components together for end-to-end operation.

---

PART A — Dashboard Oracle Panel

Update scripts/dashboard.py to add an Oracle panel when oracle/output/ exists and contains output files. If oracle/output/scores.json does not exist, show a placeholder: "Oracle not running. Start with: python scripts/run_oracle.py".

Add two new panels to the existing rich dashboard layout:

Panel 1 — ORACLE: CONNECTOR SCORES
  Shows the content of oracle/output/scores.json as a rich table.
  Columns: connector, score, label, trades, win_rate, IC, sharpe, last_updated
  Sort by reputation_score descending.
  Color the label column: EXCELLENT→bright_green, GOOD→green, MODERATE→yellow, WEAK→orange1, POOR→red.

Panel 2 — ORACLE: REGIME + RECOMMENDATIONS
  Shows oracle/output/regime.json and oracle/output/summary.json.
  Top row: current regime in large text, confidence as percentage.
  Below: effective threshold and effective position pct (if different from env vars, highlight in yellow).
  Recommendations list: bullet points from summary.json["recommendations"], max 5 shown.
  Last computed timestamp.

Both panels refresh on the same 5-second cycle as the rest of the dashboard.
If oracle/output/ files are stale (last computed > 10 minutes ago), show a WARN badge on the panel header.

---

PART B — Healthcheck Update

Update scripts/healthcheck.py to add a new optional check:
  "Oracle output" — checks if oracle/output/scores.json exists and was updated in the last hour.
  If missing: INFO (not an error — oracle is optional).
  If stale (> 1 hour): WARN.
  If fresh: PASS with last computed timestamp.

---

PART C — README Update

Add an "Oracle" section to README.md between the Architecture section and the Built on Prism section.

Content:
  Brief description (2 sentences): what the oracle does and why it matters.
  
  How to run (3 commands):
    python scripts/run_oracle.py run --once     # single evaluation pass
    python scripts/run_oracle.py run            # continuous (every 5 minutes)
    python scripts/run_oracle.py report         # print current scores to terminal
  
  Output files table: filename, description, updated_by.
  
  Publishing scores to Prism registry: one paragraph explaining PRISM_GITHUB_TOKEN and what gets published.
  
  New env vars: REGIME_AWARE, PRISM_GITHUB_TOKEN, PRISM_REGISTRY_REPO, PRISM_REGISTRY_BRANCH, PRISM_REGISTRY_PATH. Add to .env.example with comments.

---

PART D — End-to-End Smoke Test

Add tests/test_oracle_e2e.py with a full end-to-end test using synthetic log data:

1. Generate synthetic logs/signals.jsonl with 50 signals across 2 connectors (kalshi_fed, polymarket_macro) over 30 days. Velocity values uniformly distributed 0.10-0.50.

2. Generate corresponding logs/orders.jsonl: 80% of signals become orders. P&L values: positive when velocity > 0.20 (simulating that higher velocity is more predictive), negative otherwise. This gives a known IC structure.

3. Run OracleRunner.run_once() against these synthetic logs.

4. Assert:
   - oracle/output/scores.json is written and valid JSON.
   - oracle/output/regime.json is written.
   - oracle/output/summary.json is written.
   - kalshi_fed and polymarket_macro both appear in scores.json.
   - Reputation scores are between 0 and 100.
   - IC for both connectors is non-None (sufficient synthetic data).
   - IC is positive (we engineered the synthetic data to be predictive).
   - Threshold tuner recommends a threshold above 0.20 (consistent with synthetic data).
   - Decay analyzer returns decay curves with correct number of buckets.

5. Run scripts/run_oracle.py report and assert exit code 0.

---

PART E — Final Test Count Target

After all 6 prompts, run pytest tests/ -q.
Target: 253 existing + 15 + 12 + 14 + 10 + 12 + (dashboard/e2e tests) = 320+ tests passing, 0 regressions.

Verify the full oracle workflow end-to-end:
  python scripts/run_oracle.py run --once
  python scripts/run_oracle.py report
  python scripts/dashboard.py    # verify Oracle panels appear
```

---

## Notes

- The Oracle never writes to logs/ — it only reads from them. All Oracle output goes to oracle/output/.
- oracle/output/ should be gitignored — it is runtime state, not source code. Add to .gitignore.
- The Oracle is always optional. If oracle/output/ doesn't exist, the engine and dashboard run normally without it. Never make the engine depend on the oracle.
- scipy is the only new heavyweight dependency. All other new imports (yfinance, httpx) are already in requirements.txt.
- IC computation requires realized P&L data — this means the oracle becomes more useful over time as more trades complete. With fewer than 10 completed trades, IC is reported as None and the reputation score uses the neutral 30-point placeholder.
- The regime detector uses only internal log data and SPY daily closes (5 API calls per run via yfinance). It does not require any new API keys.
- Publishing to the Prism registry requires PRISM_GITHUB_TOKEN — this is optional. If the token is not set, the oracle runs normally but skips publishing with an INFO log.
- Run Prompt 1 first and verify the full pipeline runs against your existing logs before building the individual calculators in Prompts 2-5. If logs/ is empty (no signals have fired yet in mock mode), the oracle will produce empty output — this is correct behavior, not a bug.
