import json
import os
import tempfile

import pytest

from execution.exposure_manager import ExposureManager


def _make_map(entries: dict) -> str:
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False
    ) as f:
        json.dump(entries, f)
        return f.name


_MAP = {
    "KXFED": {
        "basket": ["JPM", "BAC"],
        "sector": "financials",
        "macro_factors": ["rates", "credit"],
    },
    "KXCPI": {
        "basket": ["TLT", "GLD"],
        "sector": "commodities",
        "macro_factors": ["inflation", "rates"],
    },
    "KXOIL": {
        "basket": ["XOM", "XLE"],
        "sector": "energy",
        "macro_factors": ["energy", "inflation"],
    },
    "KXSPY": {
        "basket": ["SPY"],
        "sector": "broad_market",
        "macro_factors": ["risk_off"],
    },
}


@pytest.fixture(autouse=True)
def reset_env(monkeypatch):
    monkeypatch.setenv("PORTFOLIO_VALUE", "10000")
    monkeypatch.setenv("MAX_FACTOR_EXPOSURE_PCT", "0.15")
    monkeypatch.setenv("MAX_TOTAL_EXPOSURE_PCT", "0.40")


@pytest.fixture
def mgr():
    path = _make_map(_MAP)
    return ExposureManager(map_path=path)


def test_can_open_empty_portfolio(mgr):
    ok, reason = mgr.can_open("KXFED", 500.0)
    assert ok
    assert reason == ""


def test_factor_exposure_accumulates(mgr):
    mgr.register_open("KXFED", "JPM", 600.0)
    mgr.register_open("KXFED", "BAC", 600.0)
    exposure = mgr.get_factor_exposure()
    assert exposure["rates"] == pytest.approx(0.12)
    assert exposure["credit"] == pytest.approx(0.12)


def test_factor_cap_enforced(mgr):
    mgr.register_open("KXFED", "JPM", 800.0)
    mgr.register_open("KXFED", "BAC", 700.0)
    ok, reason = mgr.can_open("KXFED", 100.0)
    assert not ok
    assert "rates" in reason or "credit" in reason


def test_total_exposure_cap_enforced(mgr):
    mgr.register_open("KXSPY", "SPY", 3900.0)
    ok, reason = mgr.can_open("KXSPY", 200.0)
    assert not ok
    assert "MAX_TOTAL_EXPOSURE_PCT" in reason


def test_total_cap_independent_of_factor_caps(mgr):
    mgr.register_open("KXSPY", "SPY", 3900.0)
    ok, reason = mgr.can_open("KXSPY", 200.0)
    assert not ok


def test_close_deregisters_exposure(mgr):
    mgr.register_open("KXFED", "JPM", 800.0)
    mgr.register_open("KXFED", "BAC", 700.0)
    mgr.register_close("KXFED", "JPM")
    mgr.register_close("KXFED", "BAC")
    ok, _ = mgr.can_open("KXFED", 1000.0)
    assert ok
    assert mgr.get_factor_exposure() == {}


def test_multi_factor_position_counted_in_both(mgr):
    mgr.register_open("KXFED", "JPM", 500.0)
    exposure = mgr.get_factor_exposure()
    assert "rates" in exposure
    assert "credit" in exposure
    assert exposure["rates"] == pytest.approx(0.05)
    assert exposure["credit"] == pytest.approx(0.05)


def test_multi_factor_cap_checked_independently(mgr):
    mgr.register_open("KXCPI", "TLT", 700.0)
    mgr.register_open("KXCPI", "GLD", 700.0)
    ok, reason = mgr.can_open("KXCPI", 200.0)
    assert not ok
    assert "inflation" in reason or "rates" in reason


def test_different_factors_dont_interfere(mgr):
    mgr.register_open("KXFED", "JPM", 300.0)
    ok, _ = mgr.can_open("KXOIL", 300.0)
    assert ok


def test_register_multiple_tickers_same_slug(mgr):
    mgr.register_open("KXFED", "JPM", 300.0)
    mgr.register_open("KXFED", "BAC", 300.0)
    mgr.register_open("KXFED", "WFC", 300.0)
    exposure = mgr.get_factor_exposure()
    assert exposure["rates"] == pytest.approx(0.09)


def test_close_nonexistent_is_noop(mgr):
    mgr.register_close("KXFED", "JPM")


def test_partial_close_updates_exposure(mgr):
    mgr.register_open("KXFED", "JPM", 800.0)
    mgr.register_open("KXFED", "BAC", 800.0)
    mgr.register_close("KXFED", "JPM")
    exposure = mgr.get_factor_exposure()
    assert exposure["rates"] == pytest.approx(0.08)


def test_total_exposure_fraction(mgr):
    mgr.register_open("KXFED", "JPM", 1000.0)
    assert mgr.get_total_exposure() == pytest.approx(0.10)
