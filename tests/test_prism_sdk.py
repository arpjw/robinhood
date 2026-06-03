import os
import subprocess
import sys
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# 1. SDK re-exports are all importable from prism_sdk
# ---------------------------------------------------------------------------

def test_sdk_imports():
    import prism_sdk
    assert hasattr(prism_sdk, "PrismConnector")
    assert hasattr(prism_sdk, "PrismMetadata")
    assert hasattr(prism_sdk, "PrismRegistry")
    assert hasattr(prism_sdk, "PricePoint")
    assert hasattr(prism_sdk, "VelocitySignal")


def test_sdk_types_are_correct():
    from prism_sdk import PrismConnector, PrismMetadata, PrismRegistry, PricePoint, VelocitySignal
    from connectors.base import PrismConnector as BasePrismConnector
    from signals.velocity import PricePoint as BasePricePoint
    assert PrismConnector is BasePrismConnector
    assert PricePoint is BasePricePoint


# ---------------------------------------------------------------------------
# 2. scaffold creates correct directory structure
# ---------------------------------------------------------------------------

def test_scaffold_creates_directory(tmp_path):
    result = subprocess.run(
        [
            sys.executable, "-m", "prism_sdk.scaffold",
            "--name", "Test Scaffold",
            "--slug", "test_scaffold",
            "--type", "custom",
            "--transport", "rest",
            "--output-dir", str(tmp_path),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    pkg = tmp_path / "test_scaffold.prism"
    assert pkg.exists()
    assert (pkg / "connector.prism").exists()
    assert (pkg / "__init__.py").exists()
    assert (pkg / "schema.json").exists()
    assert (pkg / "README.md").exists()


# ---------------------------------------------------------------------------
# 3. scaffold pre-fills manifest with provided values
# ---------------------------------------------------------------------------

def test_scaffold_prefills_manifest(tmp_path):
    import yaml
    subprocess.run(
        [
            sys.executable, "-m", "prism_sdk.scaffold",
            "--name", "My Feed",
            "--slug", "my_feed",
            "--type", "alternative_data",
            "--transport", "websocket",
            "--output-dir", str(tmp_path),
        ],
        capture_output=True,
        text=True,
    )
    manifest_path = tmp_path / "my_feed.prism" / "connector.prism"
    manifest = yaml.safe_load(manifest_path.read_text())
    assert manifest["name"] == "My Feed"
    assert manifest["slug"] == "my_feed"
    assert manifest["source_type"] == "alternative_data"
    assert manifest["transport"] == "websocket"
    assert manifest["prism"] == "1.0"


# ---------------------------------------------------------------------------
# 4. validator passes on a valid .prism package
# ---------------------------------------------------------------------------

def test_validator_passes_on_valid_package():
    result = subprocess.run(
        [
            sys.executable, "-m", "prism_sdk.validator",
            "--path", "connectors/polymarket_macro.prism",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


# ---------------------------------------------------------------------------
# 5. validator fails with clear message on missing manifest
# ---------------------------------------------------------------------------

def test_validator_fails_missing_manifest(tmp_path):
    pkg = tmp_path / "no_manifest.prism"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")

    result = subprocess.run(
        [sys.executable, "-m", "prism_sdk.validator", "--path", str(pkg)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "connector.prism" in result.stdout or "connector.prism" in result.stderr


# ---------------------------------------------------------------------------
# 6. validator fails with clear message on missing PrismConnector subclass
# ---------------------------------------------------------------------------

def test_validator_fails_missing_subclass(tmp_path):
    import yaml
    pkg = tmp_path / "no_class.prism"
    pkg.mkdir()

    manifest = {
        "prism": "1.0",
        "name": "No Class",
        "slug": "no_class",
        "version": "1.0.0",
        "author": "test",
        "source_type": "custom",
        "transport": "rest",
        "description": "test",
        "auth_required": False,
        "auth_fields": [],
        "contract_slugs": ["KXFED"],
        "poll_interval_seconds": None,
        "capabilities": ["velocity"],
    }
    (pkg / "connector.prism").write_text(yaml.dump(manifest))
    (pkg / "__init__.py").write_text("# no connector class here\n")

    result = subprocess.run(
        [sys.executable, "-m", "prism_sdk.validator", "--path", str(pkg)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1


# ---------------------------------------------------------------------------
# 7. validator fails when contract_slug not in contract_equity_map.json
# ---------------------------------------------------------------------------

def test_validator_fails_unknown_slug(tmp_path):
    import yaml
    pkg = tmp_path / "unknown_slug.prism"
    pkg.mkdir()

    manifest = {
        "prism": "1.0",
        "name": "Unknown Slug",
        "slug": "unknown_slug",
        "version": "1.0.0",
        "author": "test",
        "source_type": "custom",
        "transport": "rest",
        "description": "test",
        "auth_required": False,
        "auth_fields": [],
        "contract_slugs": ["KXDOESNOTEXIST99999"],
        "poll_interval_seconds": None,
        "capabilities": ["velocity"],
    }
    (pkg / "connector.prism").write_text(yaml.dump(manifest))
    (pkg / "__init__.py").write_text(f"""
import asyncio
from typing import Callable
from connectors.base import PrismConnector, PrismMetadata

class UnknownSlugConnector(PrismConnector):
    metadata = PrismMetadata(
        name="Unknown Slug",
        slug="unknown_slug",
        version="1.0.0",
        author="test",
        source_type="custom",
        transport="rest",
        description="test",
        auth_required=False,
        auth_fields=[],
        contract_slugs=["KXDOESNOTEXIST99999"],
        poll_interval_seconds=None,
        capabilities=["velocity"],
    )
    async def start(self, tracker, mapper, handle_signal: Callable) -> None:
        pass
    async def stop(self) -> None:
        pass
    def health_check(self) -> dict:
        return {{"status": "ok", "message": "", "last_update": None}}
""")

    result = subprocess.run(
        [sys.executable, "-m", "prism_sdk.validator", "--path", str(pkg)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "KXDOESNOTEXIST99999" in result.stdout


# ---------------------------------------------------------------------------
# 8. validator exit code 0 on pass, 1 on fail
# ---------------------------------------------------------------------------

def test_validator_exit_codes():
    pass_result = subprocess.run(
        [sys.executable, "-m", "prism_sdk.validator", "--path", "connectors/metaculus_macro.prism"],
        capture_output=True,
        text=True,
    )
    assert pass_result.returncode == 0

    fail_result = subprocess.run(
        [sys.executable, "-m", "prism_sdk.validator", "--path", "/tmp/nonexistent_prism_pkg"],
        capture_output=True,
        text=True,
    )
    assert fail_result.returncode != 0


# ---------------------------------------------------------------------------
# 9. Minimal connector example in CONTRIBUTING_CONNECTORS.md is syntactically valid
# ---------------------------------------------------------------------------

def test_contributing_doc_example_is_valid():
    doc = Path("CONTRIBUTING_CONNECTORS.md").read_text()
    # Extract the RandomWalkConnector code block
    start = doc.find("class RandomWalkConnector(PrismConnector):")
    assert start != -1, "RandomWalkConnector example not found in CONTRIBUTING_CONNECTORS.md"
    end = doc.find("\n```", start)
    code = doc[start:end]
    assert "async def start" in code
    assert "async def stop" in code
    assert "health_check" in code
    # Verify it's syntactically valid Python
    compile(code, "<contributing_example>", "exec")


# ---------------------------------------------------------------------------
# 10. scaffold --help exits 0 (smoke test)
# ---------------------------------------------------------------------------

def test_scaffold_help():
    result = subprocess.run(
        [sys.executable, "-m", "prism_sdk.scaffold", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "scaffold" in result.stdout.lower() or "slug" in result.stdout.lower()
