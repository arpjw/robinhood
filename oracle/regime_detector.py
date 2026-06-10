from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Literal

from oracle.log_reader import LogReader
from oracle.models import RegimeState

logger = logging.getLogger(__name__)

REGIME_MULTIPLIERS: dict[str, tuple[float, float]] = {
    "risk_off":       (1.3, 0.7),
    "risk_on":        (0.9, 1.1),
    "high_vol":       (1.2, 0.6),
    "low_vol":        (1.0, 1.0),
    "trending":       (0.95, 1.05),
    "mean_reverting": (1.1, 0.85),
    "unknown":        (1.0, 1.0),
}


@dataclass
class RegimeEvidence:
    indicator: str
    value: float
    threshold: float
    direction: str
    interpretation: str


def _linear_slope(ys: list[float]) -> float:
    n = len(ys)
    if n < 2:
        return 0.0
    xs = list(range(n))
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    den = sum((x - mean_x) ** 2 for x in xs)
    return num / den if den != 0 else 0.0


def _stdev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return math.sqrt(sum((v - mean) ** 2 for v in values) / (len(values) - 1))


class RegimeDetector:
    def __init__(
        self,
        log_reader: LogReader,
        equity_fetcher: Callable[[str, datetime, datetime], float | None],
        lookback_days: int = 14,
    ) -> None:
        self._log_reader = log_reader
        self._equity_fetcher = equity_fetcher
        self._lookback_days = lookback_days

    def detect(self) -> RegimeState:
        now = datetime.now(tz=timezone.utc)
        evidence_items: list[RegimeEvidence] = []
        regime_votes: dict[str, int] = {r: 0 for r in REGIME_MULTIPLIERS}

        self._check_signal_frequency(now, regime_votes, evidence_items)
        self._check_suppression_trend(now, regime_votes, evidence_items)
        self._check_win_rate_trend(now, regime_votes, evidence_items)
        self._check_hold_time_trend(now, regime_votes, evidence_items)
        self._check_reverse_velocity_rate(now, regime_votes, evidence_items)
        self._check_spy_volatility(now, regime_votes, evidence_items)
        self._check_spy_trend(now, regime_votes, evidence_items)

        total = len(evidence_items)
        if total < 3:
            regime = "unknown"
            confidence = 0.0
        else:
            best_regime = max(regime_votes, key=lambda r: regime_votes[r])
            best_count = regime_votes[best_regime]
            confidence = best_count / total if total > 0 else 0.0
            regime = best_regime if confidence >= 0.4 else "unknown"

        threshold_mult, position_mult = REGIME_MULTIPLIERS[regime]

        return RegimeState(
            detected_at=now,
            regime=regime,  # type: ignore[arg-type]
            confidence=round(confidence, 3),
            evidence=[e.interpretation for e in evidence_items],
            recommended_threshold_multiplier=threshold_mult,
            recommended_position_multiplier=position_mult,
        )

    def _check_signal_frequency(
        self,
        now: datetime,
        votes: dict[str, int],
        evidence: list[RegimeEvidence],
    ) -> None:
        week_ago = now - timedelta(days=7)
        two_weeks_ago = now - timedelta(days=14)

        recent = self._log_reader.read_signals(since=week_ago, until=now)
        prior = self._log_reader.read_signals(since=two_weeks_ago, until=week_ago)

        if not prior:
            return

        recent_count = len(recent)
        prior_count = len(prior)
        ratio = recent_count / prior_count if prior_count > 0 else 1.0
        pct_change = (ratio - 1.0) * 100

        if ratio > 1.25:
            votes["risk_off"] += 1
            evidence.append(RegimeEvidence(
                indicator="signal_frequency",
                value=ratio,
                threshold=1.25,
                direction="above",
                interpretation=f"high signal frequency (+{pct_change:.0f}% vs prior week) suggests elevated uncertainty",
            ))
        elif ratio < 0.75:
            votes["risk_on"] += 1
            evidence.append(RegimeEvidence(
                indicator="signal_frequency",
                value=ratio,
                threshold=0.75,
                direction="below",
                interpretation=f"low signal frequency ({pct_change:.0f}% vs prior week) suggests market complacency",
            ))

    def _check_suppression_trend(
        self,
        now: datetime,
        votes: dict[str, int],
        evidence: list[RegimeEvidence],
    ) -> None:
        week_ago = now - timedelta(days=7)
        two_weeks_ago = now - timedelta(days=14)

        recent = self._log_reader.read_signals(since=week_ago, until=now)
        prior = self._log_reader.read_signals(since=two_weeks_ago, until=week_ago)

        def suppression_rate(signals: list) -> float:
            if not signals:
                return 0.0
            suppressed = sum(1 for s in signals if not s.fired)
            return suppressed / len(signals)

        recent_rate = suppression_rate(recent)
        prior_rate = suppression_rate(prior)

        if recent_rate > prior_rate + 0.1 and recent_rate > 0.3:
            votes["risk_off"] += 1
            evidence.append(RegimeEvidence(
                indicator="suppression_rate_trend",
                value=recent_rate,
                threshold=0.3,
                direction="above",
                interpretation=f"rising suppression rate ({prior_rate:.1%} → {recent_rate:.1%}) suggests macro factor clustering",
            ))

    def _check_win_rate_trend(
        self,
        now: datetime,
        votes: dict[str, int],
        evidence: list[RegimeEvidence],
    ) -> None:
        two_weeks_ago = now - timedelta(days=14)
        orders = self._log_reader.read_orders(since=two_weeks_ago, until=now)
        closed = [o for o in orders if o.pnl_usd is not None]

        if len(closed) < 20:
            return

        first_half = closed[:len(closed) // 2]
        second_half = closed[len(closed) // 2:]

        def win_rate(trades: list) -> float:
            if not trades:
                return 0.5
            wins = sum(1 for t in trades if (t.pnl_usd or 0) > 0)
            return wins / len(trades)

        prior_wr = win_rate(first_half)
        recent_wr = win_rate(second_half)

        if recent_wr < prior_wr - 0.10:
            votes["risk_off"] += 1
            evidence.append(RegimeEvidence(
                indicator="win_rate_trend",
                value=recent_wr,
                threshold=prior_wr - 0.10,
                direction="below",
                interpretation=f"falling win rate ({prior_wr:.1%} → {recent_wr:.1%}) indicates regime shift",
            ))

    def _check_hold_time_trend(
        self,
        now: datetime,
        votes: dict[str, int],
        evidence: list[RegimeEvidence],
    ) -> None:
        two_weeks_ago = now - timedelta(days=14)
        orders = self._log_reader.read_orders(since=two_weeks_ago, until=now)
        adverse = [o for o in orders if o.exit_reason == "adverse_move" and o.exit_timestamp]

        week_ago = now - timedelta(days=7)
        recent_adverse = [o for o in adverse if o.timestamp >= week_ago]
        prior_adverse = [o for o in adverse if o.timestamp < week_ago]

        if len(prior_adverse) == 0:
            return

        recent_rate = len(recent_adverse) / 7
        prior_rate = len(prior_adverse) / 7

        if recent_rate > prior_rate * 1.5 and recent_rate > 0.5:
            votes["high_vol"] += 1
            evidence.append(RegimeEvidence(
                indicator="adverse_exit_rate",
                value=recent_rate,
                threshold=prior_rate * 1.5,
                direction="above",
                interpretation=f"rising adverse-move exits ({prior_rate:.1f}/day → {recent_rate:.1f}/day) indicates higher volatility",
            ))

    def _check_reverse_velocity_rate(
        self,
        now: datetime,
        votes: dict[str, int],
        evidence: list[RegimeEvidence],
    ) -> None:
        week_ago = now - timedelta(days=7)
        orders = self._log_reader.read_orders(since=week_ago, until=now)
        closed = [o for o in orders if o.exit_reason is not None]

        if not closed:
            return

        rev_vel = sum(1 for o in closed if o.exit_reason == "reverse_velocity")
        rate = rev_vel / len(closed)

        if rate > 0.30:
            votes["mean_reverting"] += 1
            evidence.append(RegimeEvidence(
                indicator="reverse_velocity_exit_rate",
                value=rate,
                threshold=0.30,
                direction="above",
                interpretation=f"{rev_vel} reverse-velocity exits in 7 days ({rate:.1%} of closed) suggests mean-reverting regime",
            ))

    def _check_spy_volatility(
        self,
        now: datetime,
        votes: dict[str, int],
        evidence: list[RegimeEvidence],
    ) -> None:
        try:
            import yfinance as yf
            start = now - timedelta(days=self._lookback_days + 2)
            df = yf.download("SPY", start=start.strftime("%Y-%m-%d"), end=now.strftime("%Y-%m-%d"), progress=False)
            if df is None or len(df) < 5:
                return
            closes = df["Close"].dropna().tolist()
            if len(closes) < 2:
                return
            if hasattr(closes[0], '__len__'):
                closes = [float(c[0]) if hasattr(c, '__len__') else float(c) for c in closes]
            else:
                closes = [float(c) for c in closes]
            returns = [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes))]
            daily_std = _stdev(returns)
            ann_vol = daily_std * math.sqrt(252) * 100

            if ann_vol > 20:
                votes["high_vol"] += 1
                evidence.append(RegimeEvidence(
                    indicator="spy_realized_vol",
                    value=ann_vol,
                    threshold=20.0,
                    direction="above",
                    interpretation=f"SPY 14-day realized vol {ann_vol:.1f}% (above 20%) — high volatility regime",
                ))
            elif ann_vol < 12:
                votes["low_vol"] += 1
                evidence.append(RegimeEvidence(
                    indicator="spy_realized_vol",
                    value=ann_vol,
                    threshold=12.0,
                    direction="below",
                    interpretation=f"SPY 14-day realized vol {ann_vol:.1f}% (below 12%) — low volatility regime",
                ))
        except Exception as exc:
            logger.debug("SPY vol check failed: %s", exc)

    def _check_spy_trend(
        self,
        now: datetime,
        votes: dict[str, int],
        evidence: list[RegimeEvidence],
    ) -> None:
        try:
            import yfinance as yf
            start = now - timedelta(days=self._lookback_days + 2)
            df = yf.download("SPY", start=start.strftime("%Y-%m-%d"), end=now.strftime("%Y-%m-%d"), progress=False)
            if df is None or len(df) < 5:
                return
            closes = df["Close"].dropna().tolist()
            if len(closes) < 5:
                return
            if hasattr(closes[0], '__len__'):
                closes = [float(c[0]) if hasattr(c, '__len__') else float(c) for c in closes]
            else:
                closes = [float(c) for c in closes]
            slope = _linear_slope(closes)
            mean_price = sum(closes) / len(closes)
            normalized_slope = slope / mean_price if mean_price != 0 else 0

            if normalized_slope > 0.003:
                votes["trending"] += 1
                evidence.append(RegimeEvidence(
                    indicator="spy_trend",
                    value=normalized_slope,
                    threshold=0.003,
                    direction="above",
                    interpretation=f"SPY 14-day trend positive (slope: {normalized_slope:.4f}/day) — trending up",
                ))
            elif normalized_slope < -0.003:
                votes["trending"] += 1
                evidence.append(RegimeEvidence(
                    indicator="spy_trend",
                    value=normalized_slope,
                    threshold=-0.003,
                    direction="below",
                    interpretation=f"SPY 14-day trend negative (slope: {normalized_slope:.4f}/day) — trending down",
                ))
        except Exception as exc:
            logger.debug("SPY trend check failed: %s", exc)

    def effective_threshold(self, base_threshold: float, regime: RegimeState) -> float:
        return base_threshold * regime.recommended_threshold_multiplier

    def effective_position_pct(self, base_pct: float, regime: RegimeState) -> float:
        return min(base_pct * regime.recommended_position_multiplier, 0.10)

    def format_summary(self, regime: RegimeState) -> str:
        base_threshold = float(os.getenv("VELOCITY_THRESHOLD", "0.15"))
        base_position = float(os.getenv("MAX_POSITION_PCT", "0.05"))
        eff_threshold = self.effective_threshold(base_threshold, regime)
        eff_position = self.effective_position_pct(base_position, regime)

        evidence_str = ", ".join(regime.evidence[:3]) if regime.evidence else "none"
        lines = [
            f"Current regime: {regime.regime.upper()} (confidence: {regime.confidence:.2f})",
            f"Evidence: {evidence_str}.",
            f"Recommended adjustments: raise threshold from {base_threshold:.2f} → {eff_threshold:.2f}, "
            f"reduce max position from {base_position:.1%} → {eff_position:.1%}.",
        ]
        return "\n".join(lines)
