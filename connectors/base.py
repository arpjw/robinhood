import importlib.util
import inspect
import logging
import os
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Literal

import yaml

logger = logging.getLogger(__name__)

PRISM_VERSION = "1.0"
_VALID_SOURCE_TYPES = {"prediction_market", "alternative_data", "news", "custom"}
_VALID_TRANSPORTS = {"websocket", "rest", "push"}
_REQUIRED_MANIFEST_FIELDS = {
    "prism", "name", "slug", "version", "author", "source_type",
    "transport", "description", "auth_required", "auth_fields",
    "contract_slugs", "capabilities",
}


def validate_manifest(path: Path) -> dict:
    try:
        raw = yaml.safe_load(path.read_text())
    except Exception as exc:
        raise ValueError(f"failed to parse {path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ValueError(f"{path}: manifest must be a YAML mapping")

    missing = _REQUIRED_MANIFEST_FIELDS - raw.keys()
    if missing:
        raise ValueError(f"{path}: missing required fields: {sorted(missing)}")

    if str(raw["prism"]) != PRISM_VERSION:
        raise ValueError(
            f"{path}: unsupported manifest version {raw['prism']!r}, expected {PRISM_VERSION!r}"
        )

    for str_field in ("name", "slug", "version", "author", "description"):
        if not isinstance(raw[str_field], str):
            raise ValueError(
                f"{path}: field {str_field!r} must be a string, got {type(raw[str_field]).__name__}"
            )

    if raw["source_type"] not in _VALID_SOURCE_TYPES:
        raise ValueError(
            f"{path}: source_type must be one of {sorted(_VALID_SOURCE_TYPES)}, got {raw['source_type']!r}"
        )

    if raw["transport"] not in _VALID_TRANSPORTS:
        raise ValueError(
            f"{path}: transport must be one of {sorted(_VALID_TRANSPORTS)}, got {raw['transport']!r}"
        )

    if not isinstance(raw["auth_required"], bool):
        raise ValueError(
            f"{path}: auth_required must be a boolean, got {type(raw['auth_required']).__name__}"
        )

    for list_field in ("auth_fields", "contract_slugs", "capabilities"):
        if not isinstance(raw[list_field], list):
            raise ValueError(
                f"{path}: field {list_field!r} must be a list, got {type(raw[list_field]).__name__}"
            )

    poll = raw.get("poll_interval_seconds")
    if poll is not None and not isinstance(poll, (int, float)):
        raise ValueError(
            f"{path}: poll_interval_seconds must be a number or null, got {type(poll).__name__}"
        )
    if poll is not None:
        raw["poll_interval_seconds"] = float(poll)

    return raw


@dataclass
class PrismMetadata:
    name: str
    slug: str
    version: str
    author: str
    source_type: Literal["prediction_market", "alternative_data", "news", "custom"]
    transport: Literal["websocket", "rest", "push"]
    description: str
    auth_required: bool
    auth_fields: list[str]
    contract_slugs: list[str]
    poll_interval_seconds: float | None
    capabilities: list[str]


class PrismConnector(ABC):
    metadata: PrismMetadata

    @abstractmethod
    async def start(self, tracker, mapper, handle_signal: Callable) -> None:
        ...

    @abstractmethod
    async def stop(self) -> None:
        ...

    @abstractmethod
    def health_check(self) -> dict:
        ...

    def validate_auth(self) -> None:
        missing = [f for f in self.metadata.auth_fields if not os.getenv(f)]
        if missing:
            raise RuntimeError(
                f"connector {self.metadata.slug!r} requires env vars: {', '.join(missing)}"
            )

    @classmethod
    def from_prism_package(cls, package_path: Path) -> "PrismConnector":
        manifest_path = package_path / "connector.prism"
        if not manifest_path.exists():
            raise ValueError(f"no connector.prism found in {package_path}")

        manifest = validate_manifest(manifest_path)

        init_path = package_path / "__init__.py"
        if not init_path.exists():
            raise ValueError(f"no __init__.py found in {package_path}")

        slug = manifest["slug"]
        module_name = f"prism_connector_{slug}"

        if module_name in sys.modules:
            module = sys.modules[module_name]
        else:
            spec = importlib.util.spec_from_file_location(module_name, init_path)
            if spec is None or spec.loader is None:
                raise ValueError(f"failed to create module spec for {init_path}")
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)

        connector_cls = None
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if (
                issubclass(obj, PrismConnector)
                and obj is not PrismConnector
                and obj.__module__ == module_name
            ):
                connector_cls = obj
                break

        if connector_cls is None:
            raise ValueError(f"no PrismConnector subclass found in {init_path}")

        if not hasattr(connector_cls, "metadata"):
            raise ValueError(f"{connector_cls.__name__} has no 'metadata' attribute")

        if connector_cls.metadata.slug != slug:
            raise ValueError(
                f"metadata.slug {connector_cls.metadata.slug!r} != manifest slug {slug!r}"
            )

        return connector_cls()


class PrismRegistry:
    def __init__(self) -> None:
        self._connectors: dict[str, PrismConnector] = {}

    def register(self, connector: PrismConnector) -> None:
        self._connectors[connector.metadata.slug] = connector

    def load_directory(self, path: Path) -> int:
        if not path.exists():
            return 0

        count = 0
        for entry in sorted(path.iterdir()):
            if not (entry.is_dir() and entry.name.endswith(".prism")):
                continue
            try:
                connector = PrismConnector.from_prism_package(entry)
                connector.validate_auth()
                self.register(connector)
                count += 1
                logger.info(
                    "loaded prism connector: %s (%s)",
                    connector.metadata.name,
                    connector.metadata.slug,
                )
            except RuntimeError as exc:
                logger.warning("skipping connector %s: %s", entry.name, exc)
            except Exception as exc:
                logger.warning("failed to load connector %s: %s", entry.name, exc)
        return count

    def get_all(self) -> list[PrismConnector]:
        return list(self._connectors.values())

    def get_by_slug(self, slug: str) -> PrismConnector | None:
        return self._connectors.get(slug)

    def get_health_report(self) -> dict[str, dict]:
        return {slug: conn.health_check() for slug, conn in self._connectors.items()}
