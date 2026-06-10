from __future__ import annotations

import asyncio
import json
import logging
import math
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

import yfinance as yf

from oracle.decay_analyzer import DecayAnalyzer
from oracle.ic_calculator import ICCalculator, ICResult
from oracle.log_reader import LogReader
from oracle.models import OracleMetrics, RegimeState
from oracle.regime_detector import RegimeDetector
from oracle.reputation_scorer import ReputationScorer
from oracle.threshold_tuner import ThresholdTuner

logger = logging.getLogger(__name__)


def _yfinance_fetcher(ticker: str, start: datetime, end: datetime) -> float | None:
    try:
        df = yf.download(
            ticker,
            start=start.strftime("%Y-%m-%d"),
            end=(end + timedelta(days=1)).strftime("%Y-%m-%d"),
            progress=False,
            auto_adjust=True,
        )
        if df is None or df.empty:
            return None
        closes = df["Close"].dropna()
        if closes.empty:
            return None
        return float(closes.iloc[0])
    except Exception:
        return None


def _stdev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return math.sqrt(sum((v - mean) ** 2 for v in values) / (len(values) - 1))


def _compute_metrics(
    connector_slug: str,
    joined: list,
    window_days: int,
    ic_result: ICResult | None,
) -> OracleMetrics:
    now = datetime.now(tz=timezone.utc)
    signals = [s for s, _ in joined]
    orders = [o for _, o in joined if o is not None]
    closed = [o for o in orders if o.pnl_usd is not None]

    fired = sum(1 for s in signals if s.fired)
    wins = sum(1 for o in closed if (o.pnl_usd or 0) > 0)
    total_pnl = sum(o.pnl_usd or 0 for o in closed)
    avg_pnl = total_pnl / len(closed) if closed else 0.0
    win_rate = wins / len(closed) if closed else float("nan")

    hold_minutes: list[float] = []
    for o in closed:
        if o.exit_timestamp and o.timestamp:
            hold_m = (o.exit_timestamp - o.timestamp).total_seconds() / 60
            hold_minutes.append(hold_m)
    avg_hold = sum(hold_minutes) / len(hold_minutes) if hold_minutes else 0.0

    pnls = [o.pnl_usd or 0 for o in closed]
    best = max(pnls) if pnls else 0.0
    worst = min(pnls) if pnls else 0.0

    sharpe: float | None = None
    if len(pnls) >= 10:
        std = _stdev(pnls)
        if std > 0:
            sharpe = (sum(pnls) / len(pnls)) / std * math.sqrt(252)

    signal_count = len(signals)
    suppression_rate = (signal_count - fired) / signal_count if signal_count > 0 else 0.0

    return OracleMetrics(
        connector_slug=connector_slug,
        computed_at=now,
        window_days=window_days,
        signal_count=signal_count,
        fired_count=fired,
        trade_count=len(orders),
        win_count=wins,
        win_rate=win_rate if not math.isnan(win_rate) else 0.0,
        total_pnl_usd=total_pnl,
        avg_pnl_usd=avg_pnl,
        sharpe=sharpe,
        ic=ic_result.ic if ic_result and ic_result.n_observations >= 10 else None,
        ic_pvalue=ic_result.ic_pvalue if ic_result and ic_result.n_observations >= 10 else None,
        avg_hold_minutes=avg_hold,
        best_trade_usd=best,
        worst_trade_usd=worst,
        signal_decay_curve={},
        optimal_velocity_threshold=None,
        suppression_rate=suppression_rate,
    )


class OracleRunner:
    def __init__(
        self,
        log_reader: LogReader,
        window_days: int = 30,
        output_dir: Path = Path("oracle/output"),
        publish: bool = False,
        equity_fetcher: "Callable | None" = None,
    ) -> None:
        self._log_reader = log_reader
        self._window_days = window_days
        self._output_dir = output_dir
        self._publish = publish
        fetcher = equity_fetcher or _yfinance_fetcher
        self._ic_calc = ICCalculator(equity_fetcher=fetcher)
        self._decay_analyzer = DecayAnalyzer(equity_fetcher=fetcher)
        self._threshold_tuner = ThresholdTuner()
        self._regime_detector = RegimeDetector(
            log_reader=log_reader,
            equity_fetcher=fetcher,
        )
        self._scorer = ReputationScorer()

    async def run_once(self) -> dict[str, OracleMetrics]:
        now = datetime.now(tz=timezone.utc)
        since = now - timedelta(days=self._window_days)

        signals = self._log_reader.read_signals(since=since)
        orders = self._log_reader.read_orders(since=since)
        joined = self._log_reader.join(signals, orders)

        connectors = list({s.source for s, _ in joined if s.source != "unknown"})
        if not connectors:
            connectors = list({s.source for s, _ in joined})

        metrics_map: dict[str, OracleMetrics] = {}
        all_ic_results: dict[str, ICResult | None] = {}

        for slug in connectors:
            slug_joined = [(s, o) for s, o in joined if s.source == slug]
            ic_results = self._ic_calc.compute(slug_joined, slug)
            ic_agg = next((r for r in ic_results if r.contract_category is None), None)
            all_ic_results[slug] = ic_agg

            metrics = _compute_metrics(slug, slug_joined, self._window_days, ic_agg)

            threshold_results = self._threshold_tuner.tune(slug_joined, slug)
            if threshold_results:
                agg = next((r for r in threshold_results if r.contract_category is None), None)
                if agg:
                    metrics.optimal_velocity_threshold = agg.optimal_threshold

            decay_curves = self._decay_analyzer.analyze(slug_joined, slug)
            if decay_curves:
                agg_curve = next((c for c in decay_curves if c.contract_category is None), None)
                if agg_curve:
                    metrics.signal_decay_curve = {
                        p.minutes: p.avg_pnl_usd for p in agg_curve.points
                    }

            self._scorer.score(metrics, ic_agg)
            metrics_map[slug] = metrics

        regime = self._regime_detector.detect()

        recommendations = self._collect_recommendations(metrics_map, joined)

        self.write_outputs(metrics_map, regime, recommendations, all_ic_results)

        if self._publish:
            from oracle.registry_publisher import RegistryPublisher
            publisher = RegistryPublisher()
            scores = {slug: m.reputation_score for slug, m in metrics_map.items()}
            labels = {slug: self._scorer.label(m.reputation_score) for slug, m in metrics_map.items()}
            await publisher.publish_scores(scores, labels)

        return metrics_map

    def _collect_recommendations(
        self,
        metrics_map: dict[str, OracleMetrics],
        joined: list,
    ) -> list[str]:
        recs: list[str] = []
        for slug, metrics in metrics_map.items():
            slug_joined = [(s, o) for s, o in joined if s.source == slug]
            threshold_results = self._threshold_tuner.tune(slug_joined, slug)
            for tr in threshold_results:
                if tr.contract_category is None and tr.optimal_threshold != tr.current_threshold:
                    recs.append(f"{tr.recommendation} ({slug})")
            decay_curves = self._decay_analyzer.analyze(slug_joined, slug)
            for curve in decay_curves:
                if curve.recommendation and "optimal" not in (curve.recommendation or ""):
                    recs.append(
                        f"{self._decay_analyzer.format_recommendation(curve)} ({slug})"
                    )
        return recs[:10]

    async def run_continuous(self, interval_seconds: int = 300) -> None:
        while True:
            start = datetime.now(tz=timezone.utc)
            try:
                metrics = await self.run_once()
                elapsed = (datetime.now(tz=timezone.utc) - start).total_seconds()
                logger.info(
                    "oracle run complete in %.1fs — %d connectors evaluated",
                    elapsed,
                    len(metrics),
                )
            except Exception as exc:
                logger.error("oracle run failed: %s", exc, exc_info=True)
            await asyncio.sleep(interval_seconds)

    def write_outputs(
        self,
        metrics: dict[str, OracleMetrics],
        regime: RegimeState,
        recommendations: list[str] | None = None,
        ic_results: dict[str, ICResult | None] | None = None,
    ) -> None:
        self._output_dir.mkdir(parents=True, exist_ok=True)
        now_iso = datetime.now(tz=timezone.utc).isoformat()

        scores_data: dict = {
            "computed_at": now_iso,
            "window_days": self._window_days,
            "connectors": {},
        }
        for slug, m in metrics.items():
            ic = ic_results.get(slug) if ic_results else None
            scores_data["connectors"][slug] = {
                "reputation_score": m.reputation_score,
                "reputation_label": self._scorer.label(m.reputation_score),
                "signal_count": m.signal_count,
                "trade_count": m.trade_count,
                "win_rate": round(m.win_rate, 4) if not math.isnan(m.win_rate) else None,
                "ic": round(ic.ic, 4) if ic and ic.n_observations >= 10 else None,
                "ic_significant": ic.ic_significant if ic else None,
                "sharpe": round(m.sharpe, 4) if m.sharpe is not None else None,
                "avg_pnl_usd": round(m.avg_pnl_usd, 4),
                "total_pnl_usd": round(m.total_pnl_usd, 4),
            }
        (self._output_dir / "scores.json").write_text(json.dumps(scores_data, indent=2))

        ic_report: dict = {"computed_at": now_iso, "connectors": {}}
        for slug, m in metrics.items():
            ic = ic_results.get(slug) if ic_results else None
            ic_report["connectors"][slug] = {
                "ic": ic.ic if ic else None,
                "ic_pvalue": ic.ic_pvalue if ic else None,
                "ic_significant": ic.ic_significant if ic else None,
                "n_observations": ic.n_observations if ic else 0,
            }
        (self._output_dir / "ic_report.json").write_text(json.dumps(ic_report, indent=2))

        decay_data: dict = {"computed_at": now_iso, "connectors": {}}
        for slug, m in metrics.items():
            decay_data["connectors"][slug] = {
                str(k): v for k, v in m.signal_decay_curve.items()
            }
        (self._output_dir / "decay_curves.json").write_text(json.dumps(decay_data, indent=2))

        thresholds_data: dict = {"computed_at": now_iso, "connectors": {}}
        for slug, m in metrics.items():
            thresholds_data["connectors"][slug] = {
                "optimal_velocity_threshold": m.optimal_velocity_threshold,
                "current_threshold": float(os.getenv("VELOCITY_THRESHOLD", "0.15")),
            }
        (self._output_dir / "thresholds.json").write_text(json.dumps(thresholds_data, indent=2))

        base_threshold = float(os.getenv("VELOCITY_THRESHOLD", "0.15"))
        base_position = float(os.getenv("MAX_POSITION_PCT", "0.05"))
        eff_threshold = base_threshold * regime.recommended_threshold_multiplier
        eff_position = min(base_position * regime.recommended_position_multiplier, 0.10)
        regime_data = {
            "detected_at": regime.detected_at.isoformat(),
            "regime": regime.regime,
            "confidence": regime.confidence,
            "evidence": regime.evidence,
            "recommended_threshold_multiplier": regime.recommended_threshold_multiplier,
            "recommended_position_multiplier": regime.recommended_position_multiplier,
            "effective_threshold": round(eff_threshold, 4),
            "effective_position_pct": round(eff_position, 4),
        }
        (self._output_dir / "regime.json").write_text(json.dumps(regime_data, indent=2))

        total_signals = sum(m.signal_count for m in metrics.values())
        total_trades = sum(m.trade_count for m in metrics.values())
        closed_trades = [(m.win_count, m.trade_count) for m in metrics.values()]
        total_closed = sum(t for _, t in closed_trades)
        total_wins = sum(w for w, _ in closed_trades)
        overall_win_rate = total_wins / total_closed if total_closed > 0 else 0.0
        top_slug = max(metrics, key=lambda s: metrics[s].reputation_score) if metrics else ""

        summary = {
            "computed_at": now_iso,
            "window_days": self._window_days,
            "total_signals": total_signals,
            "total_trades": total_trades,
            "overall_win_rate": round(overall_win_rate, 4),
            "regime": regime.regime,
            "connectors_evaluated": len(metrics),
            "top_connector": top_slug,
            "top_score": metrics[top_slug].reputation_score if top_slug else 0.0,
            "publishing_enabled": self._publish,
            "recommendations": recommendations or [],
        }
        (self._output_dir / "summary.json").write_text(json.dumps(summary, indent=2))
