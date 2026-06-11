import asyncio
import concurrent.futures
import json
import os
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol, Union

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from execution.oauth_pkce import get_valid_token

ORDER_LOG_PATH = Path(os.getenv("ORDER_LOG_PATH", "logs/orders.jsonl"))

_CANCELABLE_STATES = {"new", "queued", "confirmed", "unconfirmed", "partially_filled"}


class MCPClient(Protocol):
    def submit_order(
        self, ticker: str, side: str, size: float, strategy_id: str
    ) -> dict: ...

    def get_positions(self) -> list[dict]: ...

    def cancel_all(self, strategy_id: str) -> int: ...

    def get_quote(self, ticker: str) -> dict: ...

    def check_tradability(self, ticker: str) -> dict: ...

    def get_account_id(self) -> str: ...


class MockMCPClient:
    def __init__(self) -> None:
        self._positions: dict[str, dict] = {}

    def submit_order(
        self, ticker: str, side: str, size: float, strategy_id: str
    ) -> dict:
        order = {
            "id": str(uuid.uuid4()),
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "ticker": ticker,
            "side": side,
            "size": size,
            "strategy_id": strategy_id,
            "status": "filled",
            "mode": "mock",
        }
        _log_order(order)
        pos_key = f"{strategy_id}:{ticker}"
        if side == "buy":
            self._positions[pos_key] = {
                "ticker": ticker,
                "size": size,
                "side": side,
                "strategy_id": strategy_id,
                "entry_time": order["timestamp"],
            }
        elif side in ("sell", "sell_short") and pos_key in self._positions:
            del self._positions[pos_key]
        return order

    def get_positions(self) -> list[dict]:
        return list(self._positions.values())

    def cancel_all(self, strategy_id: str) -> int:
        keys = [k for k in list(self._positions) if k.startswith(f"{strategy_id}:")]
        for k in keys:
            del self._positions[k]
        return len(keys)

    def get_quote(self, ticker: str) -> dict:
        return {"symbol": ticker, "last_trade_price": "0.00", "mode": "mock"}

    def check_tradability(self, ticker: str) -> dict:
        return {"symbol": ticker, "tradable": True, "mode": "mock"}

    def get_account_id(self) -> str:
        return "mock-account"


class LiveMCPClient:
    def __init__(self, mcp_url: str) -> None:
        self._mcp_url = mcp_url
        self._account_number: str | None = None

    def _resolve_token(self) -> str:
        try:
            raw = subprocess.run(
                ["security", "find-generic-password", "-s", "Claude Code-credentials", "-w"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            creds = json.loads(raw)
            for entry in creds.get("mcpOAuth", {}).values():
                if isinstance(entry, dict) and entry.get("serverName") == "robinhood-trading":
                    token = entry.get("accessToken", "")
                    if token:
                        return token
        except Exception:
            pass
        static = os.getenv("ROBINHOOD_MCP_TOKEN")
        if static:
            return static
        if os.getenv("ROBINHOOD_CLIENT_ID"):
            return get_valid_token()
        raise RuntimeError(
            "No Robinhood OAuth token found. Authenticate via Claude Code MCP "
            "or set ROBINHOOD_MCP_TOKEN / ROBINHOOD_CLIENT_ID."
        )

    def _run(self, coro):
        try:
            asyncio.get_running_loop()
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(asyncio.run, coro).result()
        except RuntimeError:
            return asyncio.run(coro)

    async def _call_tool(self, tool_name: str, arguments: dict):
        headers = {"Authorization": f"Bearer {self._resolve_token()}"}
        async with streamablehttp_client(self._mcp_url, headers=headers) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await session.call_tool(tool_name, arguments=arguments)

    def _parse(self, result) -> dict | list:
        content = result.content[0].text if result.content else "{}"
        return json.loads(content) if isinstance(content, str) else content

    def get_account_id(self) -> str:
        if self._account_number:
            return self._account_number
        data = self._parse(self._run(self._call_tool("get_accounts", {})))
        accounts: list[dict] = []
        if isinstance(data, dict):
            accounts = data.get("accounts", [data])
        elif isinstance(data, list):
            accounts = data
        for acct in accounts:
            if acct.get("agentic_allowed"):
                self._account_number = acct["account_number"]
                return self._account_number
        if accounts:
            self._account_number = accounts[0]["account_number"]
            return self._account_number
        raise RuntimeError("No brokerage accounts found")

    def submit_order(
        self, ticker: str, side: str, size: float, strategy_id: str
    ) -> dict:
        account_number = self.get_account_id()
        order_args = {
            "account_number": account_number,
            "symbol": ticker,
            "side": side,
            "type": "market",
            "dollar_amount": f"{size:.2f}",
        }
        self._run(self._call_tool("review_equity_order", order_args))
        ref_id = str(uuid.uuid4())
        result = self._run(
            self._call_tool("place_equity_order", {**order_args, "ref_id": ref_id})
        )
        response = self._parse(result)
        if isinstance(response, list):
            response = response[0] if response else {}
        order = {
            "id": response.get("id", ref_id),
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "ticker": ticker,
            "side": side,
            "size": size,
            "strategy_id": strategy_id,
            "status": response.get("state", "submitted"),
            "mode": "live",
            "mcp_response": response,
        }
        _log_order(order)
        return order

    def get_positions(self) -> list[dict]:
        account_number = self.get_account_id()
        data = self._parse(
            self._run(
                self._call_tool("get_equity_positions", {"account_number": account_number})
            )
        )
        if isinstance(data, dict):
            return data.get("results", data.get("positions", []))
        return data if isinstance(data, list) else []

    def cancel_all(self, strategy_id: str) -> int:
        account_number = self.get_account_id()
        data = self._parse(
            self._run(
                self._call_tool(
                    "get_equity_orders",
                    {"account_number": account_number, "placed_agent": "agentic"},
                )
            )
        )
        if isinstance(data, dict):
            orders = data.get("orders", data.get("results", []))
        else:
            orders = data if isinstance(data, list) else []
        cancelled = 0
        for order in orders:
            if order.get("state") in _CANCELABLE_STATES:
                self._run(
                    self._call_tool(
                        "cancel_equity_order",
                        {"account_number": account_number, "order_id": order["id"]},
                    )
                )
                cancelled += 1
        return cancelled

    def get_quote(self, ticker: str) -> dict:
        data = self._parse(
            self._run(self._call_tool("get_equity_quotes", {"symbols": [ticker]}))
        )
        if isinstance(data, dict):
            quotes = data.get("quotes", data.get("results", [data]))
            return quotes[0] if quotes else {}
        if isinstance(data, list):
            return data[0] if data else {}
        return data if isinstance(data, dict) else {}

    def check_tradability(self, ticker: str) -> dict:
        account_number = self.get_account_id()
        data = self._parse(
            self._run(
                self._call_tool(
                    "get_equity_tradability",
                    {"account_number": account_number, "symbols": [ticker]},
                )
            )
        )
        if isinstance(data, dict):
            results = data.get("results", [data])
            return results[0] if results else {}
        if isinstance(data, list):
            return data[0] if data else {}
        return data if isinstance(data, dict) else {}


def _log_order(order: dict) -> None:
    ORDER_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with ORDER_LOG_PATH.open("a") as f:
        f.write(json.dumps(order) + "\n")


def make_client() -> Union[MockMCPClient, LiveMCPClient]:
    mode = os.getenv("EXECUTION_MODE", "mock")
    if mode == "live":
        mcp_url = os.getenv("ROBINHOOD_MCP_URL")
        if not mcp_url:
            raise RuntimeError(
                "EXECUTION_MODE=live requires ROBINHOOD_MCP_URL to be set"
            )
        return LiveMCPClient(mcp_url=mcp_url)
    return MockMCPClient()
