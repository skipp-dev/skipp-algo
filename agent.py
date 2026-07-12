# agent.py — Claude Agents SDK + Composio

import asyncio

from claude_agent_sdk import ClaudeAgentOptions, query
from composio import Composio

composio = Composio()
user_id = "user_l3rzil"

# Create a tool router session
session = composio.create(user_id=user_id)

# Query Claude with MCP tools
async def main():
    options = ClaudeAgentOptions(
        system_prompt="You are a helpful assistant",
        permission_mode="bypassPermissions",
        mcp_servers={
            "composio": {
                "type": session.mcp.type,
                "url": session.mcp.url,
                "headers": session.mcp.headers,
            }
        },
    )

    async for message in query(
        prompt="Star the composiohq/composio repo on GitHub",
        options=options,
    ):
        print(message)

if __name__ == "__main__":
    asyncio.run(main())
