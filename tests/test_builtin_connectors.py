import asyncio
import os
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from connectors.base import PrismConnector, PrismRegistry, validate_manifest


# ---------------------------------------------------------------------------
# Helpers to load connector classes without triggering validate_auth
# ---------------------------------------------------------------------------

def _load_connector(pkg_name: str) -> PrismConnector:
    return PrismConnector.from_prism_package(Path(f"connectors/{pkg_name}"))


# ---------------------------------------------------------------------------
# 1. MetaculusConnector metadata is valid
# ---------------------------------------------------------------------------

def test_metaculus_metadata_valid():
    connector = _load_connector("metaculus_macro.prism")
    m = connector.metadata
    assert m.slug == "metaculus_macro"
    assert m.source_type == "prediction_market"
    assert m.transport == "rest"
    assert m.auth_required is False
    assert m.poll_interval_seconds == 300.0
    assert "velocity" in m.capabilities


# ---------------------------------------------------------------------------
# 2. MetaculusConnector skips gracefully when METACULUS_QUESTION_IDS not set
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_metaculus_no_op_without_ids():
    connector = _load_connector("metaculus_macro.prism")
    tracker = MagicMock()
    mapper = MagicMock()
    handle_signal = AsyncMock()

    env = {k: v for k, v in os.environ.items() if k != "METACULUS_QUESTION_IDS"}
    with patch.dict(os.environ, env, clear=True):
        task = asyncio.create_task(connector.start(tracker, mapper, handle_signal))
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    assert "idle" in connector.health_check()["message"] or connector.health_check()["message"] == "not started"
    handle_signal.assert_not_called()


# ---------------------------------------------------------------------------
# 3. MetaculusConnector parses API response correctly
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_metaculus_parses_response():
    connector = _load_connector("metaculus_macro.prism")
    tracker = MagicMock()
    tracker.update = MagicMock(return_value=None)
    mapper = MagicMock()
    handle_signal = AsyncMock()

    fake_response = {
        "id": 12345,
        "community_prediction": {"full": {"q2": 0.72}},
        "nr_forecasters": 150,
    }

    import httpx
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = MagicMock(return_value=fake_response)

    with patch.dict(os.environ, {
        "METACULUS_QUESTION_IDS": "12345",
        "METACULUS_SLUG_MAP": "12345:KXFED",
    }):
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_resp)

            task = asyncio.create_task(connector.start(tracker, mapper, handle_signal))
            await asyncio.sleep(0.05)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    tracker.update.assert_called()
    call_args = tracker.update.call_args
    assert call_args[0][0] == "KXFED"
    assert abs(call_args[0][1].price - 0.72) < 0.001
    assert call_args[0][1].volume == 150


# ---------------------------------------------------------------------------
# 4. ManifoldConnector metadata is valid
# ---------------------------------------------------------------------------

def test_manifold_metadata_valid():
    connector = _load_connector("manifold_macro.prism")
    m = connector.metadata
    assert m.slug == "manifold_macro"
    assert m.source_type == "prediction_market"
    assert m.transport == "rest"
    assert m.auth_required is False
    assert m.poll_interval_seconds == 120.0
    assert "volume" in m.capabilities


# ---------------------------------------------------------------------------
# 5. ManifoldConnector parses probability correctly
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_manifold_parses_probability():
    connector = _load_connector("manifold_macro.prism")
    tracker = MagicMock()
    tracker.update = MagicMock(return_value=None)
    mapper = MagicMock()
    handle_signal = AsyncMock()

    fake_response = {
        "id": "abc123",
        "probability": 0.38,
        "volume": 5000,
    }

    import httpx
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = MagicMock(return_value=fake_response)

    with patch.dict(os.environ, {
        "MANIFOLD_MARKET_IDS": "will-the-fed-cut",
        "MANIFOLD_SLUG_MAP": "will-the-fed-cut:KXFED",
    }):
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_resp)

            task = asyncio.create_task(connector.start(tracker, mapper, handle_signal))
            await asyncio.sleep(0.05)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    tracker.update.assert_called()
    call_args = tracker.update.call_args
    assert call_args[0][0] == "KXFED"
    assert abs(call_args[0][1].price - 0.38) < 0.001
    assert call_args[0][1].volume == 5000


# ---------------------------------------------------------------------------
# 6. FREDConnector metadata is valid
# ---------------------------------------------------------------------------

def test_fred_metadata_valid():
    connector = _load_connector("fred_macro.prism")
    m = connector.metadata
    assert m.slug == "fred_macro"
    assert m.source_type == "alternative_data"
    assert m.transport == "rest"
    assert m.auth_required is True
    assert "FRED_API_KEY" in m.auth_fields
    assert m.poll_interval_seconds == 3600.0


# ---------------------------------------------------------------------------
# 7. FREDConnector rolling min-max normalization edge cases
# ---------------------------------------------------------------------------

def test_fred_normalize_single_observation():
    connector = _load_connector("fred_macro.prism")
    result = connector.normalize("FEDFUNDS", 5.25)
    assert result == 1.0


def test_fred_normalize_flat_series():
    connector = _load_connector("fred_macro.prism")
    for _ in range(10):
        result = connector.normalize("FEDFUNDS", 5.25)
    assert result == 1.0


def test_fred_normalize_range():
    connector = _load_connector("fred_macro.prism")
    connector.normalize("CPIAUCSL", 300.0)
    connector.normalize("CPIAUCSL", 310.0)
    result = connector.normalize("CPIAUCSL", 305.0)
    assert abs(result - 0.5) < 0.01


def test_fred_normalize_52_plus_observations():
    connector = _load_connector("fred_macro.prism")
    for i in range(60):
        connector.normalize("UNRATE", float(i))
    result = connector.normalize("UNRATE", 59.0)
    assert 0.0 <= result <= 1.0
    result_low = connector.normalize("UNRATE", 8.0)
    assert result_low < result


# ---------------------------------------------------------------------------
# 8. FREDConnector raises on missing FRED_API_KEY
# ---------------------------------------------------------------------------

def test_fred_validate_auth_raises():
    connector = _load_connector("fred_macro.prism")
    env = {k: v for k, v in os.environ.items() if k != "FRED_API_KEY"}
    with patch.dict(os.environ, env, clear=True):
        with pytest.raises(RuntimeError, match="FRED_API_KEY"):
            connector.validate_auth()


# ---------------------------------------------------------------------------
# 9. All three connectors load via PrismRegistry.load_directory
# ---------------------------------------------------------------------------

def test_all_builtin_connectors_load(tmp_path):
    registry = PrismRegistry()
    env = {k: v for k, v in os.environ.items() if k not in ("FRED_API_KEY",)}
    with patch.dict(os.environ, env, clear=True):
        n = registry.load_directory(Path("connectors"))

    slugs = {c.metadata.slug for c in registry.get_all()}
    assert "metaculus_macro" in slugs
    assert "manifold_macro" in slugs
    assert "polymarket_macro" in slugs


# ---------------------------------------------------------------------------
# 10. All three connector.prism manifests pass validate_manifest
# ---------------------------------------------------------------------------

def test_metaculus_manifest_valid():
    result = validate_manifest(Path("connectors/metaculus_macro.prism/connector.prism"))
    assert result["slug"] == "metaculus_macro"


def test_manifold_manifest_valid():
    result = validate_manifest(Path("connectors/manifold_macro.prism/connector.prism"))
    assert result["slug"] == "manifold_macro"


def test_fred_manifest_valid():
    result = validate_manifest(Path("connectors/fred_macro.prism/connector.prism"))
    assert result["slug"] == "fred_macro"
    assert result["auth_required"] is True
