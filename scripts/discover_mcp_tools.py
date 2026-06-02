#!/usr/bin/env python3
import asyncio
import json
import os
import sys

from dotenv import load_dotenv
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

load_dotenv()


async def discover() -> None:
    mcp_url = os.getenv("ROBINHOOD_MCP_URL")
    if not mcp_url:
        print("error: ROBINHOOD_MCP_URL not set", file=sys.stderr)
        sys.exit(1)

    async with streamablehttp_client(mcp_url) as (read, write, _):
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
