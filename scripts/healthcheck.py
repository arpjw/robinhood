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

    print()
    if all_ok:
        print("All checks passed.")
        sys.exit(0)
    else:
        print("One or more checks failed. Fix the issues above before running live.")
        sys.exit(1)


if __name__ == "__main__":
    main()
