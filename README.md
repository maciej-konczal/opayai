# opayai-mcp

Agent commerce backbone: prompt -> signed, policy-checked purchase across pluggable
payment rails, with an approval gate and an audit trail. MCP server + CLI demo.

## Setup

    pip install -e ".[dev]"

## Run the demo

    python -m opayai.cli --return

## Run as an MCP server (stdio)

    python -m opayai.server

Register `opayai-mcp` -> command `python -m opayai.server` in any MCP host.

## Test

    pytest -v

## Flow

discover -> decide -> approve -> purchase -> track -> resolve. Every step publishes to
one event bus that is both the live view and the audit trail.
