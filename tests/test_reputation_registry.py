from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from oracle.ic_calculator import ICResult
from oracle.models import OracleMetrics
from oracle.reputation_scorer import ReputationScorer


def _utc() -> datetime:
    return datetime.now(tz=timezone.utc)


def _make_metrics(
    trade_count: int = 20,
    win_rate: float = 0.55,
    sharpe: float | None = 1.2,
    ic: float | None = 0.12,
    ic_pvalue: float | None = 0.03,
    signal_count: int = 30,
) -> OracleMetrics:
    return OracleMetrics(
        connector_slug="kalshi_fed",
        computed_at=_utc(),
        window_days=30,
        signal_count=signal_count,
        fired_count=signal_count,
        trade_count=trade_count,
        win_count=int(trade_count * win_rate),
        win_rate=win_rate,
        total_pnl_usd=float(trade_count) * 0.5,
        avg_pnl_usd=0.5,
        sharpe=sharpe,
        ic=ic,
        ic_pvalue=ic_pvalue,
        avg_hold_minutes=90.0,
        best_trade_usd=5.0,
        worst_trade_usd=-2.0,
        signal_decay_curve={},
        optimal_velocity_threshold=0.20,
        suppression_rate=0.1,
    )


def _make_ic_result(
    ic: float = 0.12,
    pvalue: float = 0.03,
    n: int = 20,
    significant: bool = True,
) -> ICResult:
    return ICResult(
        connector_slug="kalshi_fed",
        contract_category=None,
        n_observations=n,
        ic=ic,
        ic_pvalue=pvalue,
        ic_significant=significant,
        lookback_hours=2.0,
        computed_at=_utc(),
    )


class TestReputationScorer:
    def test_score_between_zero_and_hundred(self) -> None:
        scorer = ReputationScorer()
        metrics = _make_metrics()
        ic = _make_ic_result()
        score = scorer.score(metrics, ic)
        assert 0 <= score <= 100

    def test_score_sets_metrics_reputation_score(self) -> None:
        scorer = ReputationScorer()
        metrics = _make_metrics()
        ic = _make_ic_result()
        score = scorer.score(metrics, ic)
        assert metrics.reputation_score == score

    def test_ic_band_excellent(self) -> None:
        scorer = ReputationScorer()
        metrics = _make_metrics(ic=0.21)
        ic = _make_ic_result(ic=0.21, n=15, significant=True)
        assert scorer._ic_points(metrics, ic) == 100.0

    def test_ic_band_meaningful(self) -> None:
        scorer = ReputationScorer()
        metrics = _make_metrics(ic=0.12)
        ic = _make_ic_result(ic=0.12, n=15, significant=True)
        assert scorer._ic_points(metrics, ic) == 70.0

    def test_ic_band_weak(self) -> None:
        scorer = ReputationScorer()
        metrics = _make_metrics(ic=0.07)
        ic = _make_ic_result(ic=0.07, n=15, significant=True)
        assert scorer._ic_points(metrics, ic) == 40.0

    def test_ic_band_negative(self) -> None:
        scorer = ReputationScorer()
        metrics = _make_metrics(ic=-0.05)
        ic = _make_ic_result(ic=-0.05, n=15, significant=True)
        assert scorer._ic_points(metrics, ic) == 0.0

    def test_ic_insufficient_data_neutral(self) -> None:
        scorer = ReputationScorer()
        metrics = _make_metrics(ic=None)
        ic = _make_ic_result(ic=0.15, n=5, significant=False)
        assert scorer._ic_points(metrics, ic) == 30.0

    def test_win_rate_band_60_plus(self) -> None:
        scorer = ReputationScorer()
        metrics = _make_metrics(win_rate=0.62, trade_count=20)
        assert scorer._win_rate_points(metrics) == 100.0

    def test_win_rate_band_below_45(self) -> None:
        scorer = ReputationScorer()
        metrics = _make_metrics(win_rate=0.40, trade_count=20)
        assert scorer._win_rate_points(metrics) == 0.0

    def test_win_rate_insufficient_data(self) -> None:
        scorer = ReputationScorer()
        metrics = _make_metrics(win_rate=0.70, trade_count=3)
        assert scorer._win_rate_points(metrics) == 30.0

    def test_sharpe_band_2_plus(self) -> None:
        scorer = ReputationScorer()
        metrics = _make_metrics(sharpe=2.5)
        assert scorer._sharpe_points(metrics) == 100.0

    def test_sharpe_band_negative(self) -> None:
        scorer = ReputationScorer()
        metrics = _make_metrics(sharpe=-0.5)
        assert scorer._sharpe_points(metrics) == 0.0

    def test_sharpe_none(self) -> None:
        scorer = ReputationScorer()
        metrics = _make_metrics(sharpe=None)
        assert scorer._sharpe_points(metrics) == 30.0

    def test_data_quality_50_trades(self) -> None:
        scorer = ReputationScorer()
        metrics = _make_metrics(trade_count=55)
        assert scorer._data_quality_points(metrics) == 100.0

    def test_data_quality_2_trades(self) -> None:
        scorer = ReputationScorer()
        metrics = _make_metrics(trade_count=2)
        assert scorer._data_quality_points(metrics) == 20.0

    def test_weighted_sum_correct(self) -> None:
        scorer = ReputationScorer()
        metrics = _make_metrics(trade_count=25, win_rate=0.60, sharpe=1.5, ic=0.22)
        ic = _make_ic_result(ic=0.22, n=25, significant=True)
        score = scorer.score(metrics, ic)
        expected = 100 * 0.35 + 100 * 0.25 + 80 * 0.25 + 80 * 0.15
        assert abs(score - expected) < 1.0

    def test_label_returns_correct_band(self) -> None:
        scorer = ReputationScorer()
        assert scorer.label(90) == "EXCELLENT"
        assert scorer.label(75) == "GOOD"
        assert scorer.label(60) == "MODERATE"
        assert scorer.label(40) == "WEAK"
        assert scorer.label(20) == "POOR"

    def test_format_scorecard_contains_components(self) -> None:
        scorer = ReputationScorer()
        metrics = _make_metrics()
        ic = _make_ic_result()
        scorecard = scorer.format_scorecard(metrics, ic)
        assert "Reputation" in scorecard
        assert "IC" in scorecard
        assert "Win rate" in scorecard
        assert "Sharpe" in scorecard
        assert "Data quality" in scorecard


class TestRegistryPublisher:
    def test_fetch_registry_parses_response(self) -> None:
        import base64
        from oracle.registry_publisher import RegistryPublisher

        publisher = RegistryPublisher()
        fake_registry = {"connectors": [{"slug": "kalshi_fed"}]}
        encoded = base64.b64encode(json.dumps(fake_registry).encode()).decode()
        fake_response = {"content": encoded + "\n", "sha": "abc123"}

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_response = MagicMock()
            mock_response.json.return_value = fake_response
            mock_response.raise_for_status = MagicMock()
            mock_client.get = AsyncMock(return_value=mock_response)

            import asyncio
            registry, sha = asyncio.run(publisher.fetch_registry())
            assert sha == "abc123"
            assert "connectors" in registry

    def test_publish_scores_updates_fields(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import base64
        import asyncio
        from oracle.registry_publisher import RegistryPublisher

        monkeypatch.setenv("PRISM_GITHUB_TOKEN", "fake_token")
        publisher = RegistryPublisher()

        fake_registry = {"connectors": [{"slug": "kalshi_fed"}]}
        encoded = base64.b64encode(json.dumps(fake_registry).encode()).decode()

        put_payloads: list[dict] = []

        async def fake_get(url: str, **kwargs: object) -> MagicMock:
            resp = MagicMock()
            resp.json.return_value = {"content": encoded + "\n", "sha": "sha123"}
            resp.raise_for_status = MagicMock()
            return resp

        async def fake_put(url: str, **kwargs: object) -> MagicMock:
            put_payloads.append(kwargs.get("json", {}))
            resp = MagicMock()
            resp.status_code = 200
            return resp

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value.__aenter__.return_value = mock_client
            mock_client.get = fake_get
            mock_client.put = fake_put

            result = asyncio.run(
                publisher.publish_scores({"kalshi_fed": 74.2}, {"kalshi_fed": "GOOD"})
            )
            assert result is True

    def test_publish_returns_false_on_api_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import base64
        import asyncio
        from oracle.registry_publisher import RegistryPublisher

        monkeypatch.setenv("PRISM_GITHUB_TOKEN", "fake_token")
        publisher = RegistryPublisher()

        fake_registry = {"connectors": [{"slug": "kalshi_fed"}]}
        encoded = base64.b64encode(json.dumps(fake_registry).encode()).decode()

        async def fake_get(url: str, **kwargs: object) -> MagicMock:
            resp = MagicMock()
            resp.json.return_value = {"content": encoded + "\n", "sha": "sha123"}
            resp.raise_for_status = MagicMock()
            return resp

        async def fake_put(url: str, **kwargs: object) -> MagicMock:
            resp = MagicMock()
            resp.status_code = 403
            resp.text = "Forbidden"
            return resp

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value.__aenter__.return_value = mock_client
            mock_client.get = fake_get
            mock_client.put = fake_put

            result = asyncio.run(
                publisher.publish_scores({"kalshi_fed": 74.2}, {"kalshi_fed": "GOOD"})
            )
            assert result is False

    def test_check_auth_returns_false_when_token_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import asyncio
        from oracle.registry_publisher import RegistryPublisher

        monkeypatch.delenv("PRISM_GITHUB_TOKEN", raising=False)
        publisher = RegistryPublisher()
        result = asyncio.run(publisher.check_auth())
        assert result is False
