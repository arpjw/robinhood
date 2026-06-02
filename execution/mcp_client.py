import asyncio
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol, Union

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

ORDER_LOG_PATH = Path(os.getenv("ORDER_LOG_PATH", "logs/orders.jsonl"))


class MCPClient(Protocol):
    def submit_order(
        self, ticker: str, side: str, size: float, strategy_id: str
    ) -> dict: ...

    def get_positions(self) -> list[dict]: ...

    def cancel_all(self, strategy_id: str) -> int: ...


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


class LiveMCPClient:
    def __init__(self, mcp_url: str) -> None:
        self._mcp_url = mcp_url

    def _run(self, coro):
        try:
            loop = asyncio.get_running_loop()
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(asyncio.run, coro)
                return future.result()
        except RuntimeError:
            return asyncio.run(coro)

    async def _call_tool(self, tool_name: str, arguments: dict):
        async with streamablehttp_client(self._mcp_url) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments=arguments)
                return result

    def submit_order(
        self, ticker: str, side: str, size: float, strategy_id: str
    ) -> dict:
        result = self._run(
            self._call_tool(
                "place_order",
                {
                    "symbol": ticker,
                    "side": side,
                    "order_type": "market",
                    "amount": size,
                    "strategy_id": strategy_id,
                },
            )
        )
        content = result.content[0].text if result.content else "{}"
        response = json.loads(content) if isinstance(content, str) else content
        order = {
            "id": response.get("order_id", str(uuid.uuid4())),
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "ticker": ticker,
            "side": side,
            "size": size,
            "strategy_id": strategy_id,
            "status": response.get("status", "submitted"),
            "mode": "live",
            "mcp_response": response,
        }
        _log_order(order)
        return order

    def get_positions(self) -> list[dict]:
        result = self._run(self._call_tool("get_positions", {}))
        content = result.content[0].text if result.content else "[]"
        positions = json.loads(content) if isinstance(content, str) else content
        return positions if isinstance(positions, list) else []

    def cancel_all(self, strategy_id: str) -> int:
        result = self._run(
            self._call_tool("cancel_orders", {"strategy_id": strategy_id})
        )
        content = result.content[0].text if result.content else "{}"
        response = json.loads(content) if isinstance(content, str) else content
        return int(response.get("cancelled_count", 0))


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
