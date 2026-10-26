#!/usr/bin/env python3
"""Smoke-test Cursor SDK: project rules load + submit_picks custom tool."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from dotenv import load_dotenv

load_dotenv(REPO / ".env")

API_KEY = os.environ.get("CURSOR_API_KEY", "").strip()


async def main() -> int:
    if not API_KEY:
        print("SKIP: CURSOR_API_KEY not set - add to .env and re-run")
        print("Get a key: https://cursor.com/dashboard/integrations")
        return 0

    from cursor_sdk import AsyncClient, AgentOptions, CustomTool, CustomToolContext, LocalAgentOptions

    received: list[dict] = []

    def submit_picks(args: dict, _ctx: CustomToolContext) -> str:
        received.append(args)
        return f"accepted test payload with keys: {list(args.keys())}"

    tool = CustomTool(
        description="Test submit_picks",
        input_schema={
            "type": "object",
            "properties": {"summary": {"type": "string"}},
            "required": ["summary"],
        },
        execute=submit_picks,
    )

    print("Starting SDK bridge...")
    async with await AsyncClient.launch_bridge(workspace=str(REPO)) as client:
        async with await client.agents.create(
            AgentOptions(
                model=os.environ.get("PREDICTOR_MODEL", "composer-2.5"),
                api_key=API_KEY,
                local=LocalAgentOptions(
                    cwd=str(REPO),
                    setting_sources=["project"],
                    custom_tools={"submit_picks": tool},
                ),
                disallowed_tools=["shell", "edit"],
            ),
        ) as agent:
            print(f"Agent: {agent.agent_id}")
            prompt = (
                "Read `.cursor/rules/soccer-prediction-core.mdc` first line only, "
                "then call submit_picks with summary='sdk spike ok'."
            )
            run = await agent.send(prompt)
            async for msg in run.messages():
                mtype = getattr(msg, "type", None) or (msg.get("type") if isinstance(msg, dict) else None)
                if mtype == "tool_call":
                    name = getattr(msg, "name", "") or msg.get("name", "")
                    status = getattr(msg, "status", "") or msg.get("status", "")
                    print(f"  tool: {name} ({status})")
            result = await run.wait()
            print(f"Run status: {result.status}")
            if received:
                print("submit_picks called:", json.dumps(received[0], indent=2)[:200])
                print("SDK spike PASSED")
                return 0
            print("SDK spike: agent finished but submit_picks not called")
            return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
