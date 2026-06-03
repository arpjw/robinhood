import os
import sys
import textwrap
from pathlib import Path
from typing import Callable
from unittest.mock import patch

import pytest
import yaml

from connectors.base import (
    PrismConnector,
    PrismMetadata,
    PrismRegistry,
    validate_manifest,
)


def _make_manifest_dict(**overrides) -> dict:
    base = {
        "prism": "1.0",
        "name": "Test Connector",
        "slug": "test_conn",
        "version": "1.0.0",
        "author": "tester",
        "source_type": "custom",
        "transport": "rest",
        "description": "A test connector.",
        "auth_required": False,
        "auth_fields": [],
        "contract_slugs": ["KXFED"],
        "poll_interval_seconds": None,
        "capabilities": ["velocity"],
    }
    base.update(overrides)
    return base


def _write_manifest(path: Path, data: dict) -> None:
    path.write_text(yaml.dump(data))


def _make_prism_package(
    parent: Path,
    slug: str = "test_conn",
    *,
    manifest_overrides: dict | None = None,
    init_content: str | None = None,
) -> Path:
    pkg = parent / f"{slug}.prism"
    pkg.mkdir()

    manifest = _make_manifest_dict(slug=slug, **(manifest_overrides or {}))
    _write_manifest(pkg / "connector.prism", manifest)

    if init_content is None:
        init_content = textwrap.dedent(f"""
            import asyncio
            from typing import Callable
            from connectors.base import PrismConnector, PrismMetadata

            class _Connector(PrismConnector):
                metadata = PrismMetadata(
                    name="Test Connector",
                    slug="{slug}",
                    version="1.0.0",
                    author="tester",
                    source_type="custom",
                    transport="rest",
                    description="A test connector.",
                    auth_required=False,
                    auth_fields=[],
                    contract_slugs=["KXFED"],
                    poll_interval_seconds=60.0,
                    capabilities=["velocity"],
                )

                async def start(self, tracker, mapper, handle_signal: Callable) -> None:
                    pass

                async def stop(self) -> None:
                    pass

                def health_check(self) -> dict:
                    return {{"status": "ok", "message": "test", "last_update": None}}
        """)

    (pkg / "__init__.py").write_text(init_content)
    return pkg


# ---------------------------------------------------------------------------
# 1. PrismMetadata field validation
# ---------------------------------------------------------------------------

def test_prism_metadata_valid():
    m = PrismMetadata(
        name="X",
        slug="x",
        version="1.0.0",
        author="a",
        source_type="custom",
        transport="rest",
        description="desc",
        auth_required=False,
        auth_fields=[],
        contract_slugs=["KXFED"],
        poll_interval_seconds=None,
        capabilities=["velocity"],
    )
    assert m.slug == "x"
    assert m.auth_required is False
    assert m.poll_interval_seconds is None


# ---------------------------------------------------------------------------
# 2. validate_manifest — valid
# ---------------------------------------------------------------------------

def test_validate_manifest_valid(tmp_path):
    p = tmp_path / "connector.prism"
    _write_manifest(p, _make_manifest_dict())
    result = validate_manifest(p)
    assert result["slug"] == "test_conn"
    assert result["source_type"] == "custom"
    assert result["poll_interval_seconds"] is None


# ---------------------------------------------------------------------------
# 3. validate_manifest — missing required fields
# ---------------------------------------------------------------------------

def test_validate_manifest_missing_field(tmp_path):
    data = _make_manifest_dict()
    del data["slug"]
    p = tmp_path / "connector.prism"
    _write_manifest(p, data)
    with pytest.raises(ValueError, match="missing required fields"):
        validate_manifest(p)


def test_validate_manifest_missing_multiple_fields(tmp_path):
    data = _make_manifest_dict()
    del data["name"]
    del data["author"]
    p = tmp_path / "connector.prism"
    _write_manifest(p, data)
    with pytest.raises(ValueError, match="missing required fields"):
        validate_manifest(p)


# ---------------------------------------------------------------------------
# 4. validate_manifest — wrong type
# ---------------------------------------------------------------------------

def test_validate_manifest_wrong_type_auth_required(tmp_path):
    data = _make_manifest_dict(auth_required="yes")
    p = tmp_path / "connector.prism"
    _write_manifest(p, data)
    with pytest.raises(ValueError, match="auth_required must be a boolean"):
        validate_manifest(p)


def test_validate_manifest_wrong_source_type(tmp_path):
    data = _make_manifest_dict(source_type="blockchain")
    p = tmp_path / "connector.prism"
    _write_manifest(p, data)
    with pytest.raises(ValueError, match="source_type must be one of"):
        validate_manifest(p)


# ---------------------------------------------------------------------------
# 5. PrismRegistry.load_directory — valid package
# ---------------------------------------------------------------------------

def test_registry_load_directory_valid(tmp_path):
    _make_prism_package(tmp_path, slug="valid_conn")
    registry = PrismRegistry()
    n = registry.load_directory(tmp_path)
    assert n == 1
    assert registry.get_by_slug("valid_conn") is not None


# ---------------------------------------------------------------------------
# 6. PrismRegistry.load_directory — malformed package (warn and skip)
# ---------------------------------------------------------------------------

def test_registry_load_directory_malformed(tmp_path, caplog):
    pkg = tmp_path / "bad_conn.prism"
    pkg.mkdir()
    (pkg / "connector.prism").write_text("not: valid: yaml: [")
    (pkg / "__init__.py").write_text("")

    registry = PrismRegistry()
    import logging
    with caplog.at_level(logging.WARNING):
        n = registry.load_directory(tmp_path)
    assert n == 0
    assert any("bad_conn.prism" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# 7. PrismRegistry.load_directory — missing auth fields (warn and skip)
# ---------------------------------------------------------------------------

def test_registry_load_directory_missing_auth(tmp_path, caplog):
    pkg = _make_prism_package(
        tmp_path,
        slug="auth_conn",
        manifest_overrides={"auth_required": True, "auth_fields": ["SECRET_KEY_XYZ_TEST"]},
        init_content=textwrap.dedent("""
            import asyncio
            from typing import Callable
            from connectors.base import PrismConnector, PrismMetadata

            class _Connector(PrismConnector):
                metadata = PrismMetadata(
                    name="Auth Connector",
                    slug="auth_conn",
                    version="1.0.0",
                    author="tester",
                    source_type="custom",
                    transport="rest",
                    description="needs auth",
                    auth_required=True,
                    auth_fields=["SECRET_KEY_XYZ_TEST"],
                    contract_slugs=["KXFED"],
                    poll_interval_seconds=60.0,
                    capabilities=["velocity"],
                )

                async def start(self, tracker, mapper, handle_signal: Callable) -> None:
                    pass

                async def stop(self) -> None:
                    pass

                def health_check(self) -> dict:
                    return {"status": "ok", "message": "test", "last_update": None}
        """),
    )

    env_without_secret = {k: v for k, v in os.environ.items() if k != "SECRET_KEY_XYZ_TEST"}
    import logging
    with patch.dict(os.environ, env_without_secret, clear=True):
        with caplog.at_level(logging.WARNING):
            registry = PrismRegistry()
            n = registry.load_directory(tmp_path)
    assert n == 0
    assert registry.get_by_slug("auth_conn") is None


# ---------------------------------------------------------------------------
# 8. PrismRegistry.get_by_slug
# ---------------------------------------------------------------------------

def test_registry_get_by_slug(tmp_path):
    _make_prism_package(tmp_path, slug="slug_test")
    registry = PrismRegistry()
    registry.load_directory(tmp_path)
    assert registry.get_by_slug("slug_test") is not None
    assert registry.get_by_slug("does_not_exist") is None


# ---------------------------------------------------------------------------
# 9. PrismRegistry.get_health_report
# ---------------------------------------------------------------------------

def test_registry_get_health_report(tmp_path):
    _make_prism_package(tmp_path, slug="health_test")
    registry = PrismRegistry()
    registry.load_directory(tmp_path)
    report = registry.get_health_report()
    assert "health_test" in report
    assert report["health_test"]["status"] == "ok"
    assert "last_update" in report["health_test"]


# ---------------------------------------------------------------------------
# 10. PrismConnector.validate_auth — passes when env vars are set
# ---------------------------------------------------------------------------

def test_validate_auth_passes(tmp_path):
    pkg = _make_prism_package(
        tmp_path,
        slug="auth_pass",
        manifest_overrides={"auth_required": True, "auth_fields": ["MY_TEST_KEY_PASS"]},
        init_content=textwrap.dedent("""
            import asyncio
            from typing import Callable
            from connectors.base import PrismConnector, PrismMetadata

            class _Connector(PrismConnector):
                metadata = PrismMetadata(
                    name="Auth Pass",
                    slug="auth_pass",
                    version="1.0.0",
                    author="tester",
                    source_type="custom",
                    transport="rest",
                    description="auth pass test",
                    auth_required=True,
                    auth_fields=["MY_TEST_KEY_PASS"],
                    contract_slugs=["KXFED"],
                    poll_interval_seconds=60.0,
                    capabilities=["velocity"],
                )

                async def start(self, tracker, mapper, handle_signal: Callable) -> None:
                    pass

                async def stop(self) -> None:
                    pass

                def health_check(self) -> dict:
                    return {"status": "ok", "message": "", "last_update": None}
        """),
    )
    connector = PrismConnector.from_prism_package(pkg)
    with patch.dict(os.environ, {"MY_TEST_KEY_PASS": "secret"}):
        connector.validate_auth()


# ---------------------------------------------------------------------------
# 11. PrismConnector.validate_auth — raises when env vars are missing
# ---------------------------------------------------------------------------

def test_validate_auth_raises(tmp_path):
    pkg = _make_prism_package(
        tmp_path,
        slug="auth_fail",
        manifest_overrides={"auth_required": True, "auth_fields": ["MY_TEST_KEY_FAIL"]},
        init_content=textwrap.dedent("""
            import asyncio
            from typing import Callable
            from connectors.base import PrismConnector, PrismMetadata

            class _Connector(PrismConnector):
                metadata = PrismMetadata(
                    name="Auth Fail",
                    slug="auth_fail",
                    version="1.0.0",
                    author="tester",
                    source_type="custom",
                    transport="rest",
                    description="auth fail test",
                    auth_required=True,
                    auth_fields=["MY_TEST_KEY_FAIL"],
                    contract_slugs=["KXFED"],
                    poll_interval_seconds=60.0,
                    capabilities=["velocity"],
                )

                async def start(self, tracker, mapper, handle_signal: Callable) -> None:
                    pass

                async def stop(self) -> None:
                    pass

                def health_check(self) -> dict:
                    return {"status": "ok", "message": "", "last_update": None}
        """),
    )
    connector = PrismConnector.from_prism_package(pkg)
    env_without = {k: v for k, v in os.environ.items() if k != "MY_TEST_KEY_FAIL"}
    with patch.dict(os.environ, env_without, clear=True):
        with pytest.raises(RuntimeError, match="MY_TEST_KEY_FAIL"):
            connector.validate_auth()


# ---------------------------------------------------------------------------
# 12. KalshiFedConnector metadata matches connector.prism manifest
# ---------------------------------------------------------------------------

def test_kalshi_fed_metadata_matches_manifest():
    manifest = validate_manifest(
        Path("connectors/kalshi_fed.prism/connector.prism")
    )
    connector = PrismConnector.from_prism_package(Path("connectors/kalshi_fed.prism"))
    assert connector.metadata.slug == manifest["slug"]
    assert connector.metadata.name == manifest["name"]
    assert connector.metadata.version == manifest["version"]
    assert connector.metadata.transport == manifest["transport"]
    assert connector.metadata.auth_fields == manifest["auth_fields"]


# ---------------------------------------------------------------------------
# 13. PolymarketMacroConnector metadata matches connector.prism manifest
# ---------------------------------------------------------------------------

def test_polymarket_metadata_matches_manifest():
    manifest = validate_manifest(
        Path("connectors/polymarket_macro.prism/connector.prism")
    )
    connector = PrismConnector.from_prism_package(
        Path("connectors/polymarket_macro.prism")
    )
    assert connector.metadata.slug == manifest["slug"]
    assert connector.metadata.name == manifest["name"]
    assert connector.metadata.auth_required == manifest["auth_required"]
    assert set(connector.metadata.contract_slugs) == set(manifest["contract_slugs"])


# ---------------------------------------------------------------------------
# 14. from_prism_package loads a connector correctly
# ---------------------------------------------------------------------------

def test_from_prism_package(tmp_path):
    pkg = _make_prism_package(tmp_path, slug="load_test")
    connector = PrismConnector.from_prism_package(pkg)
    assert connector.metadata.slug == "load_test"
    assert connector.metadata.source_type == "custom"
    report = connector.health_check()
    assert report["status"] == "ok"


# ---------------------------------------------------------------------------
# 15. Full registry startup does not break when custom/ directory is absent
# ---------------------------------------------------------------------------

def test_registry_no_custom_dir(tmp_path):
    custom = tmp_path / "custom"
    assert not custom.exists()
    registry = PrismRegistry()
    if custom.exists():
        n = registry.load_directory(custom)
    else:
        n = 0
    assert n == 0
    assert registry.get_all() == []
