"""
python -m prism_sdk.validator --path connectors/my_connector.prism
"""
import argparse
import importlib.util
import inspect
import json
import sys
from pathlib import Path


def _check(label: str, ok: bool, detail: str = "") -> bool:
    status = "PASS" if ok else "FAIL"
    line = f"  [{status}] {label}"
    if detail:
        line += f" — {detail}"
    print(line)
    return ok


def validate_package(pkg_path: Path) -> bool:
    all_ok = True

    print(f"Validating {pkg_path}\n")

    # 1. Manifest exists and is valid
    manifest_path = pkg_path / "connector.prism"
    if not manifest_path.exists():
        _check("connector.prism exists", False, "file not found")
        return False

    _check("connector.prism exists", True)

    try:
        from connectors.base import validate_manifest
        manifest = validate_manifest(manifest_path)
        _check("manifest is valid", True)
    except ValueError as exc:
        _check("manifest is valid", False, str(exc))
        return False

    # 2. __init__.py exists
    init_path = pkg_path / "__init__.py"
    if not init_path.exists():
        _check("__init__.py exists", False)
        return False
    _check("__init__.py exists", True)

    # 3. __init__.py imports and contains a PrismConnector subclass
    slug = manifest["slug"]
    module_name = f"_prism_validator_{slug}"
    try:
        spec = importlib.util.spec_from_file_location(module_name, init_path)
        if spec is None or spec.loader is None:
            raise ImportError("failed to create spec")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        _check("__init__.py imports successfully", True)
    except Exception as exc:
        _check("__init__.py imports successfully", False, str(exc))
        all_ok = False
        return False

    from connectors.base import PrismConnector
    connector_cls = None
    for _, obj in inspect.getmembers(module, inspect.isclass):
        if (
            issubclass(obj, PrismConnector)
            and obj is not PrismConnector
            and obj.__module__ == module_name
        ):
            connector_cls = obj
            break

    all_ok = _check("PrismConnector subclass found", connector_cls is not None) and all_ok
    if connector_cls is None:
        return False

    # 4. Class metadata matches manifest
    has_meta = hasattr(connector_cls, "metadata")
    all_ok = _check("class has metadata attribute", has_meta) and all_ok
    if has_meta:
        slug_match = connector_cls.metadata.slug == manifest["slug"]
        all_ok = _check(
            f"metadata.slug matches manifest ({manifest['slug']!r})",
            slug_match,
            f"got {connector_cls.metadata.slug!r}" if not slug_match else "",
        ) and all_ok

    # 5. Auth fields described in README.md
    readme_path = pkg_path / "README.md"
    if readme_path.exists():
        readme_text = readme_path.read_text()
        for field in manifest.get("auth_fields", []):
            present = field in readme_text
            all_ok = _check(f"auth field {field!r} documented in README", present) and all_ok
    else:
        print("  [WARN] README.md not found — skipping auth documentation check")

    # 6. contract_slugs exist in contract_equity_map.json
    map_path = Path("data/contract_equity_map.json")
    if map_path.exists():
        try:
            equity_map = json.loads(map_path.read_text())
            for cs in manifest.get("contract_slugs", []):
                found = cs in equity_map or any(
                    k.startswith(cs) or cs.startswith(k) for k in equity_map
                )
                all_ok = _check(
                    f"contract_slug {cs!r} in equity map",
                    found,
                    "not found in data/contract_equity_map.json" if not found else "",
                ) and all_ok
        except Exception as exc:
            print(f"  [WARN] could not read equity map: {exc}")
    else:
        print("  [WARN] data/contract_equity_map.json not found — skipping slug check")

    return all_ok


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate a .prism connector package without running it."
    )
    parser.add_argument("--path", required=True, help="Path to the .prism package directory")
    args = parser.parse_args()

    pkg_path = Path(args.path)
    if not pkg_path.exists() or not pkg_path.is_dir():
        print(f"Error: {pkg_path} is not a directory.", file=sys.stderr)
        sys.exit(1)

    ok = validate_package(pkg_path)
    print()
    if ok:
        print("All checks passed.")
        sys.exit(0)
    else:
        print("One or more checks failed.")
        sys.exit(1)


if __name__ == "__main__":
    main()
