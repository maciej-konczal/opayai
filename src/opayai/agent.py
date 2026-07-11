"""Standalone OpenAI agent host for the local opayai MCP server.

This replaces Cursor as the MCP host. It starts ``opayai.server`` as a local
stdio subprocess and lets an OpenAI model drive the existing tools.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections.abc import Sequence

from agents import Agent, Runner
from agents.mcp import MCPServerStdio


DEFAULT_MODEL = "gpt-5.4-mini"

INSTRUCTIONS = """You are the user's purchasing agent. Use the opayai MCP tools
to carry out the existing commerce workflow; do not simulate tool results.

Workflow rules:
1. Create an intent mandate before searching or proposing a cart.
2. For normal shopping requests, suggest offers, explain the shortlist, and stop
   so the user can choose. If the user explicitly asks you to choose and complete
   the purchase autonomously, you may choose the best qualifying offer.
3. Propose a cart and evaluate its policy before attempting payment.
4. Call execute_payment after policy evaluation. If it returns PENDING_APPROVAL
   or PENDING_STEP_UP, tell the user to use the authorization button in their
   browser and stop. You cannot press or bypass that human-only control.
5. After the user says they authorized, call execute_payment again. Never claim
   approval or step-up occurred unless that call succeeds.
6. Do not call advance_order. Fulfillment advances in the background.
7. Surface receipts, authorization URLs, status URLs, exceptions, tracking
   updates, and returns.
8. Be concise and make it obvious what happened and what the user must decide.
"""


def model_name() -> str:
    """Return the configured OpenAI model without baking credentials into files."""
    return os.environ.get("OPAYAI_OPENAI_MODEL", DEFAULT_MODEL)


def server_params() -> dict:
    """Build a portable stdio command using the active virtual environment."""
    env = os.environ.copy()
    env.setdefault("OPAYAI_NOTIFY", "0")
    return {
        "command": sys.executable,
        "args": ["-m", "opayai.server"],
        "env": env,
    }


def build_agent(server: MCPServerStdio) -> Agent:
    return Agent(
        name="opayai",
        model=model_name(),
        instructions=INSTRUCTIONS,
        mcp_servers=[server],
        mcp_config={"convert_schemas_to_strict": True},
    )


class AgentConversation:
    """One serialized conversation backed by one live MCP server session."""

    def __init__(self, agent: Agent):
        self.agent = agent
        self.history: list = []
        self._lock = asyncio.Lock()

    async def send(self, message: str) -> str:
        if not os.environ.get("OPENAI_API_KEY"):
            raise RuntimeError(
                "OPENAI_API_KEY is not set. Export it before starting the app."
            )

        async with self._lock:
            run_input = (
                message
                if not self.history
                else self.history + [{"role": "user", "content": message}]
            )
            result = await Runner.run(self.agent, run_input)
            self.history = result.to_input_list()
            return str(result.final_output)


async def run_chat(initial_prompt: str | None = None) -> None:
    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit(
            "OPENAI_API_KEY is not set. Export it in this terminal, then run again."
        )

    async with MCPServerStdio(
        name="opayai local server",
        params=server_params(),
        cache_tools_list=True,
    ) as server:
        conversation = AgentConversation(build_agent(server))
        pending = initial_prompt

        print(f"opayai agent ready ({model_name()}). Type /quit to exit.")
        while True:
            if pending is None:
                try:
                    pending = input("\nyou> ").strip()
                except (EOFError, KeyboardInterrupt):
                    print()
                    return

            if not pending:
                pending = None
                continue
            if pending.lower() in {"/quit", "/exit"}:
                return

            message = pending
            pending = None
            try:
                output = await conversation.send(message)
            except Exception as exc:
                print(f"\nagent error: {exc}", file=sys.stderr)
                continue

            print(f"\nopayai> {output}")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Drive the local opayai MCP workflow with an OpenAI agent."
    )
    parser.add_argument(
        "prompt",
        nargs="*",
        help="optional first prompt; omit it to start an interactive session",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    prompt = " ".join(args.prompt).strip() or None
    asyncio.run(run_chat(prompt))


if __name__ == "__main__":
    main()
