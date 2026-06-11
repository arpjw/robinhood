#!/usr/bin/env python3
import asyncio
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

sys.path.insert(0, str(Path(__file__).parent.parent))
from execution.mcp_client import LiveMCPClient

load_dotenv()


async def discover() -> None:
    mcp_url = os.getenv("ROBINHOOD_MCP_URL", "https://agent.robinhood.com/mcp/trading")

    token = LiveMCPClient(mcp_url)._resolve_token()
    headers = {"Authorization": f"Bearer {token}"}

    async with streamablehttp_client(mcp_url, headers=headers) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools_result = await session.list_tools()
            tools = [
                {
                    "name": t.name,
                    "description": t.description,
                    "input_schema": t.inputSchema,
                }
                for t in tools_result.tools
            ]
            print(json.dumps(tools, indent=2))


if __name__ == "__main__":
    asyncio.run(discover())
