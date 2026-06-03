import json
import logging
import os
from collections import defaultdict
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_PORTFOLIO_VALUE = 10000.0
_DEFAULT_MAX_FACTOR_PCT = 0.15
_DEFAULT_MAX_TOTAL_PCT = 0.40


class ExposureManager:
    def __init__(self, map_path: str = "data/contract_equity_map.json") -> None:
        self._map: dict = json.loads(Path(map_path).read_text())
        self._positions: dict[tuple[str, str], float] = {}

    def _portfolio_value(self) -> float:
        return float(os.getenv("PORTFOLIO_VALUE", str(_DEFAULT_PORTFOLIO_VALUE)))

    def _max_factor_pct(self) -> float:
        return float(os.getenv("MAX_FACTOR_EXPOSURE_PCT", str(_DEFAULT_MAX_FACTOR_PCT)))

    def _max_total_pct(self) -> float:
        return float(os.getenv("MAX_TOTAL_EXPOSURE_PCT", str(_DEFAULT_MAX_TOTAL_PCT)))

    def _get_factors(self, contract_slug: str) -> list[str]:
        return self._map.get(contract_slug, {}).get("macro_factors", [])

    def _current_factor_notional(self, factor: str) -> float:
        return sum(
            size
            for (slug, _ticker), size in self._positions.items()
            if factor in self._get_factors(slug)
        )

    def can_open(self, contract_slug: str, size_usd: float) -> tuple[bool, str]:
        portfolio = self._portfolio_value()
        max_factor_pct = self._max_factor_pct()
        max_total_pct = self._max_total_pct()

        current_total = sum(self._positions.values())
        projected_total = current_total + size_usd
        if projected_total / portfolio > max_total_pct:
            pct = projected_total / portfolio * 100
            return (
                False,
                f"would bring total exposure to ${projected_total:.2f} ({pct:.1f}%), "
                f"exceeding MAX_TOTAL_EXPOSURE_PCT={max_total_pct}",
            )

        for factor in self._get_factors(contract_slug):
            current = self._current_factor_notional(factor)
            projected = current + size_usd
            if projected / portfolio > max_factor_pct:
                pct = projected / portfolio * 100
                return (
                    False,
                    f"would bring '{factor}' exposure to ${projected:.2f} ({pct:.1f}%), "
                    f"exceeding MAX_FACTOR_EXPOSURE_PCT={max_factor_pct}",
                )

        return True, ""

    def register_open(self, contract_slug: str, ticker: str, size_usd: float) -> None:
        self._positions[(contract_slug, ticker)] = size_usd
        logger.debug(
            "exposure open slug=%s ticker=%s size=%.2f", contract_slug, ticker, size_usd
        )

    def register_close(self, contract_slug: str, ticker: str) -> None:
        key = (contract_slug, ticker)
        if key in self._positions:
            del self._positions[key]
            logger.debug("exposure close slug=%s ticker=%s", contract_slug, ticker)

    def get_factor_exposure(self) -> dict[str, float]:
        portfolio = self._portfolio_value()
        factor_totals: dict[str, float] = defaultdict(float)
        for (slug, _ticker), size in self._positions.items():
            for factor in self._get_factors(slug):
                factor_totals[factor] += size
        return {f: v / portfolio for f, v in factor_totals.items()}

    def get_total_exposure(self) -> float:
        portfolio = self._portfolio_value()
        if portfolio == 0:
            return 0.0
        return sum(self._positions.values()) / portfolio
