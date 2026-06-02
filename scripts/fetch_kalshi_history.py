#!/usr/bin/env python3
"""
Fetch historical Kalshi candlestick data for KXFED and KXCPI series and write
data/kalshi_history.csv.

Output CSV columns (as required by backtest/simulate.py):
    timestamp   ISO-8601 UTC datetime
    ticker      Kalshi market ticker (e.g. KXFED-25JAN29-T450)
    last_price  close price in cents (integer 0-100)
    volume      running cumulative volume per ticker (integer)

Usage:
    python scripts/fetch_kalshi_history.py
    python scripts/fetch_kalshi_history.py --days 180 --period-interval 60
    python scripts/fetch_kalshi_history.py --output data/kalshi_history.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

from dotenv import load_dotenv

load_dotenv()

import kalshi_python
from kalshi_python import KalshiClient

_API_HOST = "https://api.elections.kalshi.com/trade-api/v2"
_REQUEST_SLEEP = 0.25


def list_series_markets(client: KalshiClient, series_ticker: str) -> list[str]:
    tickers: list[str] = []
    cursor: str | None = None
    while True:
        params: dict = {"series_ticker": series_ticker, "limit": 200}
        if cursor:
            params["cursor"] = cursor
        url = _API_HOST + "/markets?" + urlencode(params)
        resp = client.call_api(
            "GET", url, header_params={"Accept": "application/json"}, _request_timeout=10
        )
        resp.read()
        data: dict = json.loads(resp.data)
        for market in data.get("markets") or []:
            if market.get("ticker"):
                tickers.append(market["ticker"])
        cursor = data.get("cursor") or None
        if not cursor:
            break
        time.sleep(_REQUEST_SLEEP)
    return tickers


def fetch_candlesticks(
    client: KalshiClient,
    series_ticker: str,
    market_ticker: str,
    start_ts: int,
    end_ts: int,
    period_interval: int,
) -> list:
    params: dict = {
        "start_ts": start_ts,
        "end_ts": end_ts,
        "period_interval": period_interval,
    }
    url = (
        _API_HOST
        + f"/series/{series_ticker}/markets/{market_ticker}/candlesticks?"
        + urlencode(params)
    )
    resp = client.call_api(
        "GET", url, header_params={"Accept": "application/json"}, _request_timeout=10
    )
    resp.read()
    data: dict = json.loads(resp.data)
    return data.get("candlesticks") or []


def candles_to_rows(ticker: str, candles: list) -> list[dict]:
    rows: list[dict] = []
    cumulative_volume = 0
    for candle in candles:
        if candle.get("end_ts") is None or candle.get("close") is None:
            continue
        ts = datetime.fromtimestamp(int(candle["end_ts"]), tz=timezone.utc)
        cumulative_volume += int(candle.get("volume") or 0)
        rows.append(
            {
                "timestamp": ts.isoformat(),
                "ticker": ticker,
                "last_price": int(candle["close"]),
                "volume": cumulative_volume,
            }
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch Kalshi historical candlesticks for backtest."
    )
    parser.add_argument(
        "--days", type=int, default=90, help="Lookback window in days (default: 90)"
    )
    parser.add_argument(
        "--output",
        default="data/kalshi_history.csv",
        help="Destination CSV path (default: data/kalshi_history.csv)",
    )
    parser.add_argument(
        "--period-interval",
        type=int,
        default=60,
        choices=[1, 60, 1440],
        help="Candle width in minutes: 1, 60, or 1440 (default: 60)",
    )
    args = parser.parse_args()

    key_id = os.getenv("KALSHI_API_KEY", "")
    key_path = os.getenv("KALSHI_PRIVATE_KEY_PATH", "")
    if not key_id or not key_path:
        print(
            "error: KALSHI_API_KEY and KALSHI_PRIVATE_KEY_PATH must be set",
            file=sys.stderr,
        )
        sys.exit(1)

    client = KalshiClient()
    client.set_kalshi_auth(key_id, key_path)
    client.configuration.host = _API_HOST

    series_slugs = ["KXFED", "KXCPI"]

    now = datetime.now(tz=timezone.utc)
    start_ts = int((now - timedelta(days=args.days)).timestamp())
    end_ts = int(now.timestamp())

    all_rows: list[dict] = []
    zero_candle_tickers: list[str] = []

    for slug in series_slugs:
        print(f"series {slug}: listing markets...")
        try:
            tickers = list_series_markets(client, slug)
        except kalshi_python.exceptions.ApiException as exc:
            print(f"  skipping {slug}: HTTP {exc.status}")
            time.sleep(_REQUEST_SLEEP)
            continue
        except Exception as exc:
            print(f"  skipping {slug}: {exc}")
            time.sleep(_REQUEST_SLEEP)
            continue

        print(f"  {len(tickers)} markets found")
        time.sleep(_REQUEST_SLEEP)

        for ticker in tickers:
            try:
                candles = fetch_candlesticks(
                    client, slug, ticker, start_ts, end_ts, args.period_interval
                )
            except kalshi_python.exceptions.ApiException as exc:
                print(f"  {ticker}: HTTP {exc.status}, skipping")
                time.sleep(_REQUEST_SLEEP)
                continue
            except Exception as exc:
                print(f"  {ticker}: {exc}, skipping")
                time.sleep(_REQUEST_SLEEP)
                continue

            rows = candles_to_rows(ticker, candles)
            if rows:
                all_rows.extend(rows)
                print(f"  {ticker}: {len(rows)} candles")
            else:
                zero_candle_tickers.append(ticker)
                print(f"  {ticker}: 0 candles")
            time.sleep(_REQUEST_SLEEP)

    if not all_rows:
        print(
            "no data fetched — check KALSHI_API_KEY/KALSHI_PRIVATE_KEY_PATH and series slugs"
        )
        sys.exit(1)

    all_rows.sort(key=lambda r: (r["timestamp"], r["ticker"]))

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=["timestamp", "ticker", "last_price", "volume"]
        )
        writer.writeheader()
        writer.writerows(all_rows)

    timestamps = [r["timestamp"] for r in all_rows]
    print(f"\nSummary:")
    print(f"  total rows written : {len(all_rows)}")
    print(f"  date range         : {min(timestamps)} → {max(timestamps)}")
    print(f"  tickers with 0 candles ({len(zero_candle_tickers)}): {', '.join(zero_candle_tickers) or 'none'}")
    print(f"  output             : {output_path}")


if __name__ == "__main__":
    main()
