from __future__ import annotations

from oracle.ic_calculator import ICResult
from oracle.models import OracleMetrics


class ReputationScorer:
    def _ic_points(self, metrics: OracleMetrics, ic_result: ICResult | None) -> float:
        if ic_result is None or ic_result.n_observations < 10:
            return 30.0
        if not ic_result.ic_significant:
            return 20.0 if ic_result.ic >= 0 else 0.0
        if ic_result.ic >= 0.20:
            return 100.0
        if ic_result.ic >= 0.10:
            return 70.0
        if ic_result.ic >= 0.05:
            return 40.0
        if ic_result.ic >= 0:
            return 20.0
        return 0.0

    def _win_rate_points(self, metrics: OracleMetrics) -> float:
        if metrics.trade_count < 5:
            return 30.0
        wr = metrics.win_rate
        if wr >= 0.60:
            return 100.0
        if wr >= 0.55:
            return 80.0
        if wr >= 0.50:
            return 60.0
        if wr >= 0.45:
            return 30.0
        return 0.0

    def _sharpe_points(self, metrics: OracleMetrics) -> float:
        if metrics.sharpe is None:
            return 30.0
        s = metrics.sharpe
        if s >= 2.0:
            return 100.0
        if s >= 1.0:
            return 80.0
        if s >= 0.5:
            return 60.0
        if s >= 0:
            return 30.0
        return 0.0

    def _data_quality_points(self, metrics: OracleMetrics) -> float:
        tc = metrics.trade_count
        if tc >= 50:
            return 100.0
        if tc >= 20:
            return 80.0
        if tc >= 10:
            return 60.0
        if tc >= 5:
            return 40.0
        return 20.0

    def score(self, metrics: OracleMetrics, ic_result: ICResult | None) -> float:
        ic_pts = self._ic_points(metrics, ic_result)
        wr_pts = self._win_rate_points(metrics)
        sharpe_pts = self._sharpe_points(metrics)
        dq_pts = self._data_quality_points(metrics)

        total = (
            ic_pts * 0.35
            + wr_pts * 0.25
            + sharpe_pts * 0.25
            + dq_pts * 0.15
        )
        result = round(total, 1)
        metrics.reputation_score = result
        return result

    def label(self, score: float) -> str:
        if score >= 85:
            return "EXCELLENT"
        if score >= 70:
            return "GOOD"
        if score >= 50:
            return "MODERATE"
        if score >= 30:
            return "WEAK"
        return "POOR"

    def format_scorecard(self, metrics: OracleMetrics, ic_result: ICResult | None) -> str:
        ic_pts = self._ic_points(metrics, ic_result)
        wr_pts = self._win_rate_points(metrics)
        sharpe_pts = self._sharpe_points(metrics)
        dq_pts = self._data_quality_points(metrics)

        total = round(ic_pts * 0.35 + wr_pts * 0.25 + sharpe_pts * 0.25 + dq_pts * 0.15, 1)
        lbl = self.label(total)

        ic_line = "n/a (insufficient data)"
        if ic_result and ic_result.n_observations >= 10:
            sig_str = f"significant, p={ic_result.ic_pvalue:.2f}" if ic_result.ic_significant else f"not significant, p={ic_result.ic_pvalue:.2f}"
            ic_line = f"{ic_result.ic:.2f} ({sig_str})"

        sharpe_str = f"{metrics.sharpe:.2f}" if metrics.sharpe is not None else "n/a"

        lines = [
            f"Reputation: {total} ({lbl})",
            f"IC: {ic_line} → {ic_pts:.0f}pts × 35% = {ic_pts * 0.35:.1f}",
            f"Win rate: {metrics.win_rate:.2f} → {wr_pts:.0f}pts × 25% = {wr_pts * 0.25:.1f}",
            f"Sharpe: {sharpe_str} → {sharpe_pts:.0f}pts × 25% = {sharpe_pts * 0.25:.1f}",
            f"Data quality: {metrics.trade_count} trades → {dq_pts:.0f}pts × 15% = {dq_pts * 0.15:.1f}",
        ]
        return "\n".join(lines)
