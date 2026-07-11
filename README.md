# opayai-mcp

Agent commerce backbone: prompt -> signed, policy-checked purchase across pluggable
payment rails, with an approval gate and an audit trail. MCP server + CLI demo.

## Setup

    pip install -e ".[dev]"

## Run the demo

    python -m opayai.cli --return

## Run as an MCP server (stdio)

    python -m opayai.server

Register `opayai-mcp` -> command `python -m opayai.server` in any MCP host. A
ready-made Cursor config lives at `.cursor/mcp.json`.

The server writes every event to a tail-able log (`OPAYAI_EVENT_LOG`, default
`~/.opayai/events.jsonl`) and mirrors it to stderr (the host's MCP log panel):

    tail -f opayai-events.jsonl

## Status site (click a link to see order status)

A tiny read-only web page that reads the same event log and shows order status +
the signed audit trail. Point it at the same log the server writes:

    OPAYAI_EVENT_LOG=./opayai-events.jsonl python -m opayai.web
    # open http://localhost:8000

`execute_payment` / `get_order` return a `status_url` so the agent can hand the
user a clickable link. Pages auto-refresh, so they update live as the agent acts.

## Test

    pytest -v

## Flow

discover -> decide -> approve -> purchase -> track -> resolve. Every step publishes to
one event bus that is both the live view and the audit trail.
