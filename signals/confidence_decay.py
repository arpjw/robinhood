import os
from collections import defaultdict, deque

_DECAY_ENABLED = os.getenv("CONFIDENCE_DECAY_ENABLED", "true").lower() not in ("0", "false", "no")


class ConfidenceDecay:
    def __init__(
        self,
        history_size: int = 10080,
        enabled: bool = _DECAY_ENABLED,
    ) -> None:
        self._history: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=history_size))
        self._enabled = enabled

    def _centrality(self, prices: list[float]) -> float:
        if len(prices) < 2:
            return 1.0
        low = min(prices)
        high = max(prices)
        if high == low:
            return 1.0
        midpoint = (high + low) / 2.0
        distance = abs(prices[-1] - midpoint)
        max_distance = (high - low) / 2.0
        return 1.0 - (distance / max_distance)

    def adjust(
        self,
        contract_slug: str,
        base_confidence: float,
        current_price: float,
    ) -> float:
        self._history[contract_slug].append(current_price)
        if not self._enabled:
            return base_confidence
        prices = list(self._history[contract_slug])
        centrality = self._centrality(prices)
        return base_confidence * (0.5 + 0.5 * centrality)
