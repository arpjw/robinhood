#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

import httpx

REQUIRED_VARS = [
    "KALSHI_API_KEY",
    "KALSHI_PRIVATE_KEY_PATH",
    "POLYMARKET_API_KEY",
    "POLYMARKET_ADDRESS",
    "EXECUTION_MODE",
    "PORTFOLIO_VALUE",
    "MAX_POSITION_PCT",
]

KALSHI_PROBE_URL = "https://api.elections.kalshi.com/trade-api/v2/exchange/status"
POLYMARKET_PROBE_URL = "https://clob.polymarket.com/markets?limit=1"


def check(label: str, ok: bool, detail: str = "") -> bool:
    status = "PASS" if ok else "FAIL"
    line = f"  [{status}] {label}"
    if detail:
        line += f" — {detail}"
    print(line)
    return ok


def warn(label: str, detail: str = "") -> None:
    line = f"  [WARN] {label}"
    if detail:
        line += f" — {detail}"
    print(line)


def main() -> None:
    all_ok = True

    print("=== Robinhood Velocity Signal — Health Check ===\n")

    print("1. Required environment variables")
    for var in REQUIRED_VARS:
        val = os.getenv(var)
        ok = bool(val)
        all_ok = check(var, ok, "(not set)" if not ok else "") and all_ok

    print("\n2. Kalshi private key file")
    key_path = os.getenv("KALSHI_PRIVATE_KEY_PATH", "")
    if key_path:
        p = Path(key_path)
        exists = p.exists()
        all_ok = check("key file exists", exists, key_path if not exists else "") and all_ok
        if exists:
            content = p.read_text()
            is_pem = content.strip().startswith("-----BEGIN")
            all_ok = check("key file is valid PEM", is_pem) and all_ok
    else:
        all_ok = check("key file (skipped — path not set)", False) and all_ok

    print("\n3. Kalshi API reachability")
    try:
        resp = httpx.get(KALSHI_PROBE_URL, timeout=5.0)
        ok = resp.status_code == 200
        all_ok = check("Kalshi API", ok, f"HTTP {resp.status_code}") and all_ok
    except Exception as exc:
        all_ok = check("Kalshi API", False, str(exc)) and all_ok

    print("\n4. Polymarket CLOB API reachability")
    try:
        resp = httpx.get(POLYMARKET_PROBE_URL, timeout=5.0)
        ok = resp.status_code == 200
        all_ok = check("Polymarket CLOB API", ok, f"HTTP {resp.status_code}") and all_ok
    except Exception as exc:
        all_ok = check("Polymarket CLOB API", False, str(exc)) and all_ok

    print("\n5. Live mode MCP URL")
    mode = os.getenv("EXECUTION_MODE", "mock")
    if mode == "live":
        mcp_url = os.getenv("ROBINHOOD_MCP_URL", "")
        ok = bool(mcp_url)
        all_ok = check("ROBINHOOD_MCP_URL (required for live)", ok) and all_ok
    else:
        check("ROBINHOOD_MCP_URL (not required in mock mode)", True)

    print("\n6. Logs directory")
    logs_dir = Path("logs")
    logs_dir.mkdir(parents=True, exist_ok=True)
    writable = os.access(logs_dir, os.W_OK)
    all_ok = check("logs/ exists and writable", writable) and all_ok

    print("\n7. Contract equity map")
    map_path = Path("data/contract_equity_map.json")
    exists = map_path.exists()
    all_ok = check("data/contract_equity_map.json exists", exists) and all_ok
    if exists:
        try:
            data = json.loads(map_path.read_text())
            has_entries = isinstance(data, dict) and len(data) > 0
            all_ok = check(
                f"contract map has entries ({len(data)})", has_entries
            ) and all_ok
        except json.JSONDecodeError as exc:
            all_ok = check("contract map is valid JSON", False, str(exc)) and all_ok

    print("\n8. Prism connectors")
    connectors_path = Path("connectors")
    if not connectors_path.exists():
        warn("connectors/ directory not found — no prism connectors available")
    else:
        from connectors.base import validate_manifest

        prism_pkgs = sorted(
            e for e in connectors_path.iterdir()
            if e.is_dir() and e.name.endswith(".prism")
        )
        if not prism_pkgs:
            warn("no .prism packages found in connectors/")
        for pkg in prism_pkgs:
            manifest_path = pkg / "connector.prism"
            if not manifest_path.exists():
                warn(f"{pkg.name}: missing connector.prism manifest")
                continue
            try:
                manifest = validate_manifest(manifest_path)
                check(f"{pkg.name}: manifest valid", True)
            except ValueError as exc:
                check(f"{pkg.name}: manifest valid", False, str(exc))
                continue

            if manifest.get("auth_required"):
                missing = [f for f in manifest.get("auth_fields", []) if not os.getenv(f)]
                if missing:
                    warn(
                        f"{pkg.name}: auth fields missing ({', '.join(missing)}) — connector will be skipped at runtime"
                    )
                else:
                    check(f"{pkg.name}: auth fields present", True)
            else:
                check(f"{pkg.name}: auth not required", True)

    print("\n9. Oracle output")
    oracle_scores = Path("oracle/output/scores.json")
    if not oracle_scores.exists():
        print("  [INFO] oracle/output/scores.json not found — oracle is optional, run scripts/run_oracle.py to enable")
    else:
        try:
            data = json.loads(oracle_scores.read_text())
            computed_at_str = data.get("computed_at", "")
            if computed_at_str:
                from datetime import datetime, timezone
                computed_at = datetime.fromisoformat(computed_at_str)
                if computed_at.tzinfo is None:
                    computed_at = computed_at.replace(tzinfo=timezone.utc)
                age_minutes = (datetime.now(tz=timezone.utc) - computed_at).total_seconds() / 60
                if age_minutes > 60:
                    warn("oracle output stale", f"last updated {age_minutes:.0f}m ago")
                else:
                    check("oracle output fresh", True, f"last updated {age_minutes:.0f}m ago")
            else:
                check("oracle output", True, "computed_at missing")
        except Exception as exc:
            warn("oracle output unreadable", str(exc))

    print("\n10. Gatekeeper (Anthropic API)")
    gatekeeper_enabled = os.getenv("GATEKEEPER_ENABLED", "true").lower() not in ("0", "false", "no")
    if not gatekeeper_enabled:
        print("  [INFO] GATEKEEPER_ENABLED=false — skipping Anthropic API check")
    else:
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key:
            warn("ANTHROPIC_API_KEY not set — gatekeeper will fail at runtime")
        else:
            check("ANTHROPIC_API_KEY present", True)
            try:
                import anthropic
                from datetime import datetime, timezone
                from signals.velocity import VelocitySignal

                client = anthropic.Anthropic(api_key=api_key)
                probe_signal = {
                    "contract_id": "HEALTHCHECK",
                    "source": "healthcheck",
                    "velocity": 0.20,
                    "threshold": 0.15,
                    "velocity_window_minutes": 5,
                    "dedup_window_minutes": 30,
                    "equity_basket": [],
                }
                response = client.messages.create(
                    model="claude-sonnet-4-6",
                    max_tokens=64,
                    system='Respond with JSON only: {"approved": true, "confidence": 1.0, "reason": "healthcheck"}',
                    messages=[{"role": "user", "content": json.dumps(probe_signal)}],
                )
                text = next((b.text for b in response.content if b.type == "text"), "").strip()
                parsed = json.loads(text)
                ok = "approved" in parsed and "confidence" in parsed
                all_ok = check("Anthropic API reachable and gatekeeper response valid", ok) and all_ok
            except Exception as exc:
                all_ok = check("Anthropic API reachable", False, str(exc)) and all_ok

    print()
    if all_ok:
        print("All checks passed.")
        sys.exit(0)
    else:
        print("One or more checks failed. Fix the issues above before running live.")
        sys.exit(1)


if __name__ == "__main__":
    main()
