# ElevenLabs voice agent integration - design

Date: 2026-07-11
Status: approved, ready for implementation plan

## Goal

Let an ElevenLabs Conversational-AI agent drive the existing `opayai` MCP
server by voice, for a **live demo via a temporary public tunnel**. The agent
must be able to run the full flow (discover -> decide -> approve -> purchase ->
track -> resolve) using the same 13 tools Cursor already uses.

## Constraint that shapes everything

ElevenLabs' agent platform connects to MCP servers only over **SSE or
Streamable HTTP at a public URL** (no stdio), with an optional **Secret Token**
(Authorization header) and a per-server **tool-approval policy** (Always Ask /
Fine-grained / No Approval). The current `opayai` server serves **stdio only**
(`app.run()`), consumed by Cursor via `.cursor/mcp.json`.

So the work is: expose the existing FastMCP server over Streamable HTTP, put a
public URL in front of it, and register that URL in the ElevenLabs agent. It is
NOT a rewrite - FastMCP serves the same tools over HTTP with a transport switch.

## Non-goals

- No always-on deployment. Tunnel only; the URL dies with the tunnel.
- No multi-tenant/session isolation (see Known limitations).
- No changes to any tool, mandate, policy, rail, step-up, order, notify, web, or
  CLI logic. This integration is strictly additive.

## Approach (chosen)

Add an HTTP serve-mode to `opayai.server` using FastMCP's built-in
`streamable-http` transport, front it with `cloudflared` quick tunnel, register
the resulting `https://<tunnel>/mcp` URL in ElevenLabs. stdio stays the default.

Rejected alternatives:
- **SSE transport** - supported by ElevenLabs but the legacy transport; no reason
  to prefer it over Streamable HTTP.
- **Separate HTTP gateway process** - unnecessary; FastMCP already exposes the
  ASGI app.

## Design

### 1. HTTP serve mode (`src/opayai/server.py`, `run()` only)

`run()` gains a transport branch driven by env, default unchanged:

- `OPAYAI_TRANSPORT` = `stdio` (default) | `http`.
- `stdio` -> today's exact behavior: `app.run()`.
- `http` -> serve Streamable HTTP bound to `0.0.0.0`, port from
  `OPAYAI_MCP_PORT` (default **8787**), MCP endpoint at path `/mcp`.
- In both modes, keep the existing `_install_event_logging()` and
  `channels.install(bus)` wiring so the live event feed / status site / webhook
  channels behave identically.

Dedicated port **8787** avoids the web status site on 8000 (also FastMCP's
default) - they can run side by side during the demo.

### 2. Optional shared-secret auth

- A small ASGI middleware wraps the streamable-http app.
- If `OPAYAI_MCP_TOKEN` is set, require `Authorization: Bearer <token>`; reject
  missing/wrong token with 401.
- If unset, no auth (relies on the unguessable tunnel URL).
- Maps directly to ElevenLabs' "Secret Token" field.
- Auth applies to HTTP mode only; stdio is untouched.

### 3. Voice-oriented gates

- Keep opayai's own gates: `request_approval` and `authorize_step_up`.
- The agent voices them ("this needs your approval / a passkey") and calls the
  tool when the user says yes.
- Set the ElevenLabs server's approval policy to **No Approval** so we don't
  double-prompt (opayai's gates are the human-in-the-loop moment).
- Add one short voice-oriented sentence to the server `instructions`: speak the
  choose / approve / passkey moment aloud and keep replies brief. Guidance text
  only; no code-path change.

### 4. ElevenLabs registration (manual, dashboard)

Agent -> Tools -> add custom MCP server:
- Name: `opayai`
- Server URL: `https://<tunnel>/mcp`
- Secret Token: value of `OPAYAI_MCP_TOKEN` (if set)
- Approval policy: No Approval

### 5. Docs

New README section "Quickstart C - ElevenLabs voice agent": start the HTTP
server -> start cloudflared -> copy the URL -> register in ElevenLabs -> talk.

## Known limitations (accepted for the demo)

- The module-level `SESSION` dict is a single global -> single-speaker. Concurrent
  callers would share one cart/intent. Fine for a live demo; documented, not fixed.
- Tunnel URL is ephemeral; must be re-registered each session.

## Testing / verification

- New light test: the HTTP ASGI app builds; the auth middleware rejects a
  missing token and a wrong token (401) and accepts the correct one.
- Regression gate: `./.venv/bin/pytest -q` stays at 47+ passed.
- Manual smoke: `curl` an MCP `initialize` against `http://127.0.0.1:8787/mcp`
  (with the bearer header if a token is set) and confirm a valid response.
- Confirm stdio still boots (`OPAYAI_TRANSPORT` unset -> `python -m opayai.server`
  starts stdio for Cursor).

## Files touched

- `src/opayai/server.py` - `run()` transport branch + auth middleware + one
  instructions sentence.
- `README.md` - Quickstart C section.
- `tests/` - one new test module for the HTTP app / auth middleware.
