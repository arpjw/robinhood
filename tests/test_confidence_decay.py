import pytest

from signals.confidence_decay import ConfidenceDecay


class TestCentrality:
    def test_at_maximum_extreme(self) -> None:
        decay = ConfidenceDecay(enabled=True)
        prices = [0.3, 0.4, 0.5, 0.6, 0.7]
        centrality = decay._centrality(prices)
        assert centrality == pytest.approx(0.0, abs=1e-9)

    def test_at_minimum_extreme(self) -> None:
        decay = ConfidenceDecay(enabled=True)
        prices = [0.7, 0.6, 0.5, 0.4, 0.3]
        centrality = decay._centrality(prices)
        assert centrality == pytest.approx(0.0, abs=1e-9)

    def test_at_midpoint(self) -> None:
        decay = ConfidenceDecay(enabled=True)
        prices = [0.3, 0.7, 0.5]
        centrality = decay._centrality(prices)
        assert centrality == pytest.approx(1.0, abs=1e-6)

    def test_single_price_returns_full_confidence(self) -> None:
        decay = ConfidenceDecay(enabled=True)
        centrality = decay._centrality([0.5])
        assert centrality == pytest.approx(1.0)

    def test_flat_prices_returns_full_confidence(self) -> None:
        decay = ConfidenceDecay(enabled=True)
        centrality = decay._centrality([0.5, 0.5, 0.5])
        assert centrality == pytest.approx(1.0)


class TestAdjust:
    def test_midpoint_gives_full_base_confidence(self) -> None:
        decay = ConfidenceDecay(enabled=True)
        for p in [0.0, 1.0]:
            decay._history["KXFED"].append(p)
        result = decay.adjust("KXFED", 0.8, 0.5)
        assert result == pytest.approx(0.8, rel=1e-4)

    def test_extreme_gives_half_base_confidence(self) -> None:
        decay = ConfidenceDecay(enabled=True)
        for p in [0.0, 0.5]:
            decay._history["KXFED"].append(p)
        result = decay.adjust("KXFED", 0.8, 1.0)
        assert result == pytest.approx(0.4, rel=1e-4)

    def test_adjust_updates_history(self) -> None:
        decay = ConfidenceDecay(enabled=True)
        decay.adjust("KXFED", 0.8, 0.5)
        assert len(decay._history["KXFED"]) == 1

    def test_adjustment_formula_bounds(self) -> None:
        decay = ConfidenceDecay(enabled=True)
        for p in [0.0, 1.0]:
            decay._history["KXFED"].append(p)
        result_mid = decay.adjust("KXFED", 1.0, 0.5)
        assert result_mid == pytest.approx(1.0, rel=1e-4)

        decay2 = ConfidenceDecay(enabled=True)
        for p in [0.0, 0.5]:
            decay2._history["KXFED"].append(p)
        result_ext = decay2.adjust("KXFED", 1.0, 1.0)
        assert result_ext == pytest.approx(0.5, rel=1e-4)


class TestDisabledDecay:
    def test_passthrough_returns_base_confidence(self) -> None:
        decay = ConfidenceDecay(enabled=False)
        result = decay.adjust("KXFED", 0.8, 0.95)
        assert result == pytest.approx(0.8)

    def test_disabled_still_updates_history(self) -> None:
        decay = ConfidenceDecay(enabled=False)
        decay.adjust("KXFED", 0.8, 0.5)
        assert len(decay._history["KXFED"]) == 1

    def test_disabled_different_slugs(self) -> None:
        decay = ConfidenceDecay(enabled=False)
        assert decay.adjust("A", 0.9, 0.5) == pytest.approx(0.9)
        assert decay.adjust("B", 0.3, 0.7) == pytest.approx(0.3)
