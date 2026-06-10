from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal


@dataclass
class SignalRecord:
    signal_id: str
    timestamp: datetime
    contract_slug: str
    velocity: float
    direction: Literal["up", "down"]
    source: str
    basket: list[str]
    sector: str
    macro_factors: list[str]
    confidence: float
    fired: bool


@dataclass
class OrderRecord:
    order_id: str
    signal_id: str
    timestamp: datetime
    mode: Literal["mock", "live"]
    ticker: str
    side: Literal["buy", "sell"]
    size_usd: float
    entry_price: float | None
    exit_price: float | None
    exit_reason: str | None
    exit_timestamp: datetime | None
    pnl_usd: float | None
    source: str
    contract_slug: str
    velocity: float


@dataclass
class OracleMetrics:
    connector_slug: str
    computed_at: datetime
    window_days: int
    signal_count: int
    fired_count: int
    trade_count: int
    win_count: int
    win_rate: float
    total_pnl_usd: float
    avg_pnl_usd: float
    sharpe: float | None
    ic: float | None
    ic_pvalue: float | None
    avg_hold_minutes: float
    best_trade_usd: float
    worst_trade_usd: float
    signal_decay_curve: dict[int, float]
    optimal_velocity_threshold: float | None
    suppression_rate: float
    reputation_score: float = 0.0


@dataclass
class RegimeState:
    detected_at: datetime
    regime: Literal["risk_on", "risk_off", "high_vol", "low_vol", "trending", "mean_reverting", "unknown"]
    confidence: float
    evidence: list[str]
    recommended_threshold_multiplier: float
    recommended_position_multiplier: float
