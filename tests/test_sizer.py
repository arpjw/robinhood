import pytest

from execution.sizer import size_basket


def make_basket(tickers: list[str], confidence: float = 0.9) -> dict:
    return {"basket": tickers, "confidence": confidence}


def test_total_dollar_allocation() -> None:
    basket = make_basket(["AAPL", "GOOG"], confidence=1.0)
    sizes = size_basket(basket, portfolio_value=10000, max_position_pct=0.10)
    total = sum(sizes.values())
    assert total == pytest.approx(1000.0, rel=1e-6)


def test_splits_equally_across_tickers() -> None:
    basket = make_basket(["A", "B", "C"], confidence=1.0)
    sizes = size_basket(basket, portfolio_value=10000, max_position_pct=0.10)
    values = list(sizes.values())
    assert values[0] == pytest.approx(values[1], rel=1e-6)
    assert values[1] == pytest.approx(values[2], rel=1e-6)


def test_confidence_scales_allocation() -> None:
    basket_full = make_basket(["AAPL"], confidence=1.0)
    basket_half = make_basket(["AAPL"], confidence=0.5)
    full_size = size_basket(basket_full, portfolio_value=10000, max_position_pct=0.10)
    half_size = size_basket(basket_half, portfolio_value=10000, max_position_pct=0.10)
    assert full_size["AAPL"] == pytest.approx(2 * half_size["AAPL"], rel=1e-6)


def test_empty_basket_returns_empty_dict() -> None:
    basket = {"basket": [], "confidence": 0.9}
    assert size_basket(basket) == {}


def test_returns_correct_tickers() -> None:
    basket = make_basket(["JPM", "BAC", "WFC"])
    sizes = size_basket(basket)
    assert set(sizes.keys()) == {"JPM", "BAC", "WFC"}


def test_default_params_produce_nonzero_sizes() -> None:
    basket = make_basket(["AAPL"])
    sizes = size_basket(basket)
    assert sizes["AAPL"] > 0


def test_portfolio_value_scales_proportionally() -> None:
    basket = make_basket(["AAPL"], confidence=1.0)
    s1 = size_basket(basket, portfolio_value=10000, max_position_pct=0.05)
    s2 = size_basket(basket, portfolio_value=20000, max_position_pct=0.05)
    assert s2["AAPL"] == pytest.approx(2 * s1["AAPL"], rel=1e-6)


def test_velocity_at_threshold_gives_1x_multiplier() -> None:
    basket = make_basket(["AAPL"], confidence=1.0)
    threshold = 0.15
    base = size_basket(basket, portfolio_value=10000, max_position_pct=0.10)
    weighted = size_basket(
        basket,
        portfolio_value=10000,
        max_position_pct=0.10,
        velocity=threshold,
        velocity_threshold=threshold,
    )
    assert weighted["AAPL"] == pytest.approx(base["AAPL"], rel=1e-6)


def test_velocity_double_threshold_gives_2x_multiplier() -> None:
    basket = make_basket(["AAPL"], confidence=1.0)
    threshold = 0.15
    base = size_basket(basket, portfolio_value=10000, max_position_pct=0.10)
    weighted = size_basket(
        basket,
        portfolio_value=10000,
        max_position_pct=0.10,
        velocity=threshold * 2,
        velocity_threshold=threshold,
    )
    assert weighted["AAPL"] == pytest.approx(2 * base["AAPL"], rel=1e-6)


def test_velocity_cap_at_2x() -> None:
    basket = make_basket(["AAPL"], confidence=1.0)
    threshold = 0.15
    capped = size_basket(
        basket,
        portfolio_value=10000,
        max_position_pct=0.10,
        velocity=threshold * 100,
        velocity_threshold=threshold,
    )
    max_expected = size_basket(
        basket,
        portfolio_value=10000,
        max_position_pct=0.10,
        velocity=threshold * 2,
        velocity_threshold=threshold,
    )
    assert capped["AAPL"] == pytest.approx(max_expected["AAPL"], rel=1e-6)


def test_negative_velocity_uses_abs_value() -> None:
    basket = make_basket(["AAPL"], confidence=1.0)
    threshold = 0.15
    pos = size_basket(
        basket, portfolio_value=10000, max_position_pct=0.10,
        velocity=threshold, velocity_threshold=threshold,
    )
    neg = size_basket(
        basket, portfolio_value=10000, max_position_pct=0.10,
        velocity=-threshold, velocity_threshold=threshold,
    )
    assert pos["AAPL"] == pytest.approx(neg["AAPL"], rel=1e-6)


def test_no_velocity_defaults_to_1x() -> None:
    basket = make_basket(["AAPL"], confidence=1.0)
    no_vel = size_basket(basket, portfolio_value=10000, max_position_pct=0.10)
    with_vel_1x = size_basket(
        basket, portfolio_value=10000, max_position_pct=0.10,
        velocity=0.15, velocity_threshold=0.15,
    )
    assert no_vel["AAPL"] == pytest.approx(with_vel_1x["AAPL"], rel=1e-6)
