import os

from signals.velocity import VELOCITY_THRESHOLD

PORTFOLIO_VALUE = float(os.getenv("PORTFOLIO_VALUE", "10000"))
MAX_POSITION_PCT = float(os.getenv("MAX_POSITION_PCT", "0.05"))


def size_basket(
    basket: dict,
    portfolio_value: float = PORTFOLIO_VALUE,
    max_position_pct: float = MAX_POSITION_PCT,
    velocity: float | None = None,
    velocity_threshold: float = VELOCITY_THRESHOLD,
) -> dict[str, float]:
    confidence = float(basket.get("confidence", 0.5))
    tickers = basket.get("basket", [])
    if not tickers:
        return {}
    velocity_multiplier = 1.0
    if velocity is not None and velocity_threshold > 0:
        velocity_multiplier = min(abs(velocity) / velocity_threshold, 2.0)
    total_dollars = portfolio_value * max_position_pct * confidence * velocity_multiplier
    per_ticker = total_dollars / len(tickers)
    return {ticker: round(per_ticker, 2) for ticker in tickers}
