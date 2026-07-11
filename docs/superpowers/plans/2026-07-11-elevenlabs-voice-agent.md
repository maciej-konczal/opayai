# ElevenLabs Voice Agent Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose the existing `opayai` FastMCP server over Streamable HTTP (behind an optional bearer token) so an ElevenLabs voice agent can drive all 13 tools via a public tunnel, without changing stdio/CLI/web behavior.

**Architecture:** Add an opt-in HTTP serve-mode to `opayai.server.run()`, gated by `OPAYAI_TRANSPORT=http`. In HTTP mode we build FastMCP's Streamable-HTTP ASGI app (`app.streamable_http_app()`), wrap it in a tiny pure-ASGI bearer-auth middleware, and serve it with uvicorn on a dedicated port (8787). stdio stays the default path (`app.run()`), so Cursor/CLI/web/tests are untouched. A `cloudflared` quick tunnel provides the public URL registered in the ElevenLabs dashboard.

**Tech Stack:** Python 3.11+, `mcp` (FastMCP), `uvicorn`, `starlette`, `cloudflared` (external CLI), pytest.

## Global Constraints

- Copy rule: use only the regular hyphen (`-`) everywhere (code, comments, docs, commits). No em/en dash. Numeric ranges use a hyphen (e.g. `400-1000`).
- Dependency floor already in `pyproject.toml`: `mcp>=1.2.0`. `uvicorn` (0.51.0) and `starlette` (1.3.1) are already installed transitively via `mcp`; do NOT add them to `pyproject.toml` dependencies (YAGNI - they arrive with `mcp`).
- Env var names are exact: `OPAYAI_TRANSPORT` (`stdio` default | `http`), `OPAYAI_MCP_PORT` (default `8787`), `OPAYAI_MCP_TOKEN` (unset = no auth).
- Streamable-HTTP endpoint path stays FastMCP's default `/mcp`.
- Bind host in HTTP mode is `0.0.0.0` (tunnel needs a non-loopback bind).
- stdio behavior (`app.run()` when `OPAYAI_TRANSPORT` is unset/`stdio`) MUST remain byte-for-byte the current behavior.
- Use the repo venv for every command: `./.venv/bin/...`.
- Regression gate for every task: `./.venv/bin/pytest -q` stays green (currently 47 passed).

---

### Task 1: Bearer-auth ASGI middleware + HTTP app builder

Adds the two testable building blocks: a pure-ASGI middleware that enforces `Authorization: Bearer <token>` on HTTP requests when a token is configured, and a builder that wraps FastMCP's streamable-http app with it. No `run()` wiring yet (that is Task 2), so this task is fully unit-testable without opening a socket.

**Files:**
- Modify: `src/opayai/server.py` (add `_bearer_auth_asgi(inner, token)` and `_http_asgi_app()` near the bottom, above `def run()`)
- Test: `tests/test_http_transport.py` (create)

**Interfaces:**
- Consumes: `app` (the module-level `FastMCP("opayai-mcp", ...)` already defined at top of `server.py`); `os` (already imported).
- Produces:
  - `_bearer_auth_asgi(inner_app, token: str | None) -> ASGIApp` - returns `inner_app` unchanged when `token` is falsy; otherwise returns an ASGI callable `async def (scope, receive, send)` that, for `scope["type"] == "http"`, returns HTTP 401 (`text/plain` body `b"unauthorized"`) unless the request carries header `authorization: Bearer <token>`, and for any other scope type (e.g. `"lifespan"`, `"websocket"`) delegates to `inner_app` untouched.
  - `_http_asgi_app() -> ASGIApp` - returns `_bearer_auth_asgi(app.streamable_http_app(), os.environ.get("OPAYAI_MCP_TOKEN"))`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_http_transport.py`:

```python
from __future__ import annotations

import asyncio

from opayai.server import _bearer_auth_asgi


class _InnerSpy:
    """Minimal ASGI app that records it was reached and returns 200."""

    def __init__(self) -> None:
        self.called = False

    async def __call__(self, scope, receive, send) -> None:
        self.called = True
        if scope["type"] == "http":
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})


def _drive(app, scope) -> list[dict]:
    """Run an ASGI app once against a fixed scope, capturing sent messages."""

    sent: list[dict] = []

    async def receive() -> dict:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict) -> None:
        sent.append(message)

    asyncio.run(app(scope, receive, send))
    return sent


def _http_scope(auth: str | None) -> dict:
    headers = []
    if auth is not None:
        headers.append((b"authorization", auth.encode()))
    return {"type": "http", "headers": headers}


def test_no_token_passes_through() -> None:
    inner = _InnerSpy()
    wrapped = _bearer_auth_asgi(inner, None)
    # No token configured -> identity: same object, inner reached regardless of header.
    assert wrapped is inner
    sent = _drive(wrapped, _http_scope(None))
    assert inner.called is True
    assert sent[0]["status"] == 200


def test_correct_token_reaches_inner() -> None:
    inner = _InnerSpy()
    wrapped = _bearer_auth_asgi(inner, "s3cret")
    sent = _drive(wrapped, _http_scope("Bearer s3cret"))
    assert inner.called is True
    assert sent[0]["status"] == 200


def test_missing_token_is_rejected() -> None:
    inner = _InnerSpy()
    wrapped = _bearer_auth_asgi(inner, "s3cret")
    sent = _drive(wrapped, _http_scope(None))
    assert inner.called is False
    assert sent[0]["status"] == 401


def test_wrong_token_is_rejected() -> None:
    inner = _InnerSpy()
    wrapped = _bearer_auth_asgi(inner, "s3cret")
    sent = _drive(wrapped, _http_scope("Bearer nope"))
    assert inner.called is False
    assert sent[0]["status"] == 401


def test_lifespan_scope_bypasses_auth() -> None:
    inner = _InnerSpy()
    wrapped = _bearer_auth_asgi(inner, "s3cret")

    async def run() -> None:
        await wrapped({"type": "lifespan"}, None, None)  # type: ignore[arg-type]

    # Non-http scope must delegate to inner even with a token set.
    asyncio.run(run())
    assert inner.called is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/bin/pytest tests/test_http_transport.py -q`
Expected: FAIL - `ImportError: cannot import name '_bearer_auth_asgi' from 'opayai.server'`.

- [ ] **Step 3: Implement the middleware + builder**

In `src/opayai/server.py`, add the following directly above `def run() -> None:` (after `_install_event_logging`):

```python
def _bearer_auth_asgi(inner_app, token: str | None):
    """Wrap an ASGI app to require `Authorization: Bearer <token>` on HTTP requests.

    When `token` is falsy, returns `inner_app` unchanged (no auth). Non-HTTP
    scopes (lifespan, websocket) always pass through so the app's session-manager
    lifespan still runs.
    """
    if not token:
        return inner_app

    expected = f"Bearer {token}".encode()

    async def _app(scope, receive, send):
        if scope["type"] == "http":
            headers = dict(scope.get("headers") or [])
            if headers.get(b"authorization") != expected:
                await send({
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [(b"content-type", b"text/plain")],
                })
                await send({"type": "http.response.body", "body": b"unauthorized"})
                return
        await inner_app(scope, receive, send)

    return _app


def _http_asgi_app():
    """Streamable-HTTP ASGI app for the MCP server, behind optional bearer auth."""
    return _bearer_auth_asgi(app.streamable_http_app(), os.environ.get("OPAYAI_MCP_TOKEN"))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/bin/pytest tests/test_http_transport.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Run the full suite (regression gate)**

Run: `./.venv/bin/pytest -q`
Expected: PASS (52 passed - 47 existing + 5 new).

- [ ] **Step 6: Commit**

```bash
git add src/opayai/server.py tests/test_http_transport.py
git commit -m "feat(server): bearer-auth ASGI middleware + streamable-http app builder"
```

---

### Task 2: Wire the HTTP transport into run() + voice instructions

Adds the `OPAYAI_TRANSPORT` branch to `run()` so the server can actually serve HTTP, and appends a voice-oriented line to the server instructions. There is no automated test for `run()` (it blocks on a socket / stdio), so this task is verified by a manual boot + `curl` smoke check and the regression suite.

**Files:**
- Modify: `src/opayai/server.py` (the `_INSTRUCTIONS` string near the top; the `run()` function at the bottom)

**Interfaces:**
- Consumes: `_http_asgi_app()` (Task 1), `app`, `_install_event_logging`, `channels.install`, `os` (all already in module).
- Produces: updated `run()` - when `OPAYAI_TRANSPORT=http`, serves Streamable HTTP via uvicorn on `0.0.0.0:$OPAYAI_MCP_PORT` (default 8787); otherwise calls `app.run()` (stdio, unchanged).

- [ ] **Step 1: Append a voice line to `_INSTRUCTIONS`**

In `src/opayai/server.py`, the `_INSTRUCTIONS` string currently ends with item 5
(`5. Do NOT call advance_order ...`) whose last line is `in the background, and the
user is notified proactively. Just hand over the status_url."""`. Add a 6th item.
Change that closing line so the string does NOT terminate, then append the new item.
The final lines of `_INSTRUCTIONS` must read exactly:

```python
5. Do NOT call advance_order - fulfillment (shipped, then delivered) happens on its own
   in the background, and the user is notified proactively. Just hand over the status_url.
6. VOICE: if you are speaking, say the choose and authorize moments out loud - present
   the ranked options and wait for the user to pick, and when execute_payment returns a
   PENDING status tell them out loud that it needs their approval/passkey and to authorize
   at the returned authorize_url, then call execute_payment again. Keep spoken replies short."""
```

- [ ] **Step 2: Replace `run()` with the transport-aware version**

In `src/opayai/server.py`, replace the existing:

```python
def run() -> None:
    _install_event_logging()
    channels.install(bus)   # webhook = full event feed; desktop/email = action pings
    fulfillment.start()     # orders ship/deliver on a timer -> proactive notifications
    app.run()
```

with (keep all three setup lines, including `fulfillment.start()`, unchanged):

```python
def run() -> None:
    _install_event_logging()
    channels.install(bus)   # webhook = full event feed; desktop/email = action pings
    fulfillment.start()     # orders ship/deliver on a timer -> proactive notifications
    if os.environ.get("OPAYAI_TRANSPORT", "stdio") == "http":
        import uvicorn
        host = "0.0.0.0"
        port = int(os.environ.get("OPAYAI_MCP_PORT", "8787"))
        app.settings.host = host
        app.settings.port = port
        print(f"[opayai] serving MCP over streamable-http at http://{host}:{port}"
              f"{app.settings.streamable_http_path}", file=sys.stderr, flush=True)
        uvicorn.run(_http_asgi_app(), host=host, port=port, log_level="info")
    else:
        app.run()
```

- [ ] **Step 3: Verify stdio still boots (unchanged path)**

Run: `OPAYAI_TRANSPORT= ./.venv/bin/python -m opayai.server </dev/null`
Expected: it starts, prints the `[opayai] #.. ` style startup with no traceback, and exits cleanly on the closed stdin (stdio transport). No uvicorn/HTTP output. Ctrl-C not needed since stdin is closed.

- [ ] **Step 4: Boot the HTTP server in the background for a smoke test**

```bash
OPAYAI_TRANSPORT=http OPAYAI_MCP_PORT=8787 OPAYAI_MCP_TOKEN=demo-token \
  ./.venv/bin/python -m opayai.server &
sleep 2
```
Expected stderr line: `[opayai] serving MCP over streamable-http at http://0.0.0.0:8787/mcp` and uvicorn `Application startup complete`.

- [ ] **Step 5: Smoke-test the endpoint with curl (auth + initialize)**

First confirm a missing token is rejected:

```bash
curl -sS -o /dev/null -w '%{http_code}\n' -X POST http://127.0.0.1:8787/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"curl","version":"0"}}}'
```
Expected: `401`.

Then confirm the correct token initializes:

```bash
curl -sS -X POST http://127.0.0.1:8787/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -H 'Authorization: Bearer demo-token' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"curl","version":"0"}}}'
```
Expected: a `200` SSE/JSON response containing `"serverInfo"` with `"name":"opayai-mcp"` and a `protocolVersion`.

- [ ] **Step 6: Stop the background server**

```bash
kill %1 2>/dev/null; wait 2>/dev/null; echo stopped
```

- [ ] **Step 7: Run the full suite (regression gate)**

Run: `./.venv/bin/pytest -q`
Expected: PASS (52 passed).

- [ ] **Step 8: Commit**

```bash
git add src/opayai/server.py
git commit -m "feat(server): OPAYAI_TRANSPORT=http serve-mode over streamable-http + voice instructions"
```

---

### Task 3: Docs - README Quickstart D (ElevenLabs voice agent) + env vars

Documents the end-to-end demo path so anyone can reproduce it: start the HTTP server, open a cloudflared tunnel, register the URL in ElevenLabs, and talk. Also adds the three new env vars to the existing Environment-variables table. Docs-only; no code, no test cycle beyond a render check.

NOTE (branch drift): the README has been edited in parallel. "Quickstart C" is ALREADY used for the web status site, and the Quickstart numbering runs 3 (CLI), 4 (Cursor), 5 (web status site), 6 (full demo). So the new section is **"## 7. Quickstart D - the ElevenLabs voice agent"**, inserted AFTER section 6 and BEFORE the `---` that precedes "## MCP tools". Re-read the README around those anchors before editing - if the numbering has shifted again, pick the next free integer and a free Quickstart letter, and keep it as the last quickstart before "## MCP tools".

**Files:**
- Modify: `README.md` (new Quickstart section after section 6 "The full end-to-end demo"; three new rows in the "## Environment variables" table)

**Interfaces:**
- Consumes: the env vars and endpoint established in Tasks 1-2 (`OPAYAI_TRANSPORT`, `OPAYAI_MCP_PORT`, `OPAYAI_MCP_TOKEN`, path `/mcp`).
- Produces: nothing consumed by later tasks (final task).

- [ ] **Step 1: Add the Quickstart D section**

In `README.md`, immediately after the end of section 6 "The full end-to-end demo (all together)" and BEFORE the `---` line that precedes "## MCP tools", insert:

````markdown
## 7. Quickstart D - the ElevenLabs voice agent

Drive the same MCP tools by voice from an ElevenLabs Conversational-AI agent. The
agent platform speaks to MCP servers over Streamable HTTP at a public URL, so we
run the server in HTTP mode and expose it with a temporary `cloudflared` tunnel.

### a. Start the server in HTTP mode

```bash
OPAYAI_TRANSPORT=http \
OPAYAI_MCP_PORT=8787 \
OPAYAI_MCP_TOKEN=pick-a-long-random-string \
OPAYAI_WEBHOOK_URL=http://127.0.0.1:9099 \
OPAYAI_EVENT_LOG="$PWD/opayai-events.jsonl" \
  ./.venv/bin/python -m opayai.server
```

The MCP endpoint is now `http://0.0.0.0:8787/mcp`. `OPAYAI_MCP_TOKEN` is optional
- if set, callers must send `Authorization: Bearer <token>`. Leave it unset to
run open (the tunnel URL is unguessable). It runs on port 8787 so it does not
collide with the web status site on 8000 - run both together for the full picture.

### b. Expose it with a tunnel

```bash
# no account needed for a quick tunnel
cloudflared tunnel --url http://127.0.0.1:8787
```

Copy the printed `https://<random>.trycloudflare.com` URL. Your MCP endpoint is
that URL plus `/mcp`, e.g. `https://<random>.trycloudflare.com/mcp`.

### c. Register the server in ElevenLabs

In the ElevenLabs dashboard: your agent -> Tools -> add a custom MCP server:

| field | value |
|---|---|
| Name | `opayai` |
| Server URL | `https://<random>.trycloudflare.com/mcp` |
| Secret Token | the same value you used for `OPAYAI_MCP_TOKEN` (omit if unset) |
| Approval policy | No Approval |

Use **No Approval** so ElevenLabs does not double-prompt. opayai keeps its own
human-in-the-loop gate: when a cart needs approval or a passkey, `execute_payment`
returns a PENDING status with an `authorize_url` on the web trusted surface. The
voice agent reads that moment out loud and asks the user to authorize at the link,
then calls `execute_payment` again to finish - the agent can never self-authorize.

### d. Talk to it

Say something like "buy me a good monitor under $300". The agent runs
discover -> decide -> approve -> purchase -> track, speaking the choose and
authorize moments aloud. Watch the same live event feed, status site, and
`/profile` page as the CLI/Cursor demos. The tunnel URL is ephemeral, so
re-register it in ElevenLabs whenever you restart the tunnel.
````

- [ ] **Step 2: Add the three env vars to the Environment-variables table**

In `README.md`, in the "## Environment variables" table (the one whose header is
`| var | default | used by |`), add these three rows. Put them right after the
`OPAYAI_WEB_BASE` row so the server-transport vars sit together:

```markdown
| `OPAYAI_TRANSPORT` | `stdio` | server: `http` serves Streamable HTTP (for ElevenLabs); `stdio` for Cursor/hosts |
| `OPAYAI_MCP_PORT` | `8787` | server (http transport): port for the `/mcp` endpoint |
| `OPAYAI_MCP_TOKEN` | unset | server (http transport): require `Authorization: Bearer <token>` when set |
```

- [ ] **Step 3: Render check**

Run: `./.venv/bin/python -c "import pathlib,sys; t=pathlib.Path('README.md').read_text(); ok = 'Quickstart D - the ElevenLabs voice agent' in t and 'OPAYAI_TRANSPORT' in t and t.count(chr(96)*3)%2==0; sys.exit(0 if ok else 1)"; echo $?`
Expected: `0` (section present, env var documented, all code fences balanced).

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs(readme): Quickstart D - ElevenLabs voice agent over streamable-http tunnel"
```

---

## Self-Review

**Spec coverage:**
- HTTP serve mode / `OPAYAI_TRANSPORT` / port 8787 -> Task 2 (run branch), building blocks in Task 1.
- Streamable HTTP transport, `/mcp` path -> Task 1 (`streamable_http_app()`), Task 2 (serve).
- Optional shared-secret auth / `OPAYAI_MCP_TOKEN` / 401 -> Task 1 (middleware + tests), Task 2 (smoke).
- Keep event logging + channels wiring in both modes -> Task 2 `run()` keeps `_install_event_logging()` + `channels.install(bus)` before the branch.
- Voice-oriented instructions line -> Task 2 Step 1.
- ElevenLabs registration + tunnel + No Approval -> Task 3.
- README Quickstart C -> Task 3.
- stdio unchanged (Cursor/CLI/web/tests) -> default branch in Task 2; regression gate every task; stdio boot check Task 2 Step 3.
- Known limitation (single global SESSION) -> documented in spec; no task needed (accepted, not fixed).
- Testing: middleware unit tests (Task 1), curl initialize smoke (Task 2), regression suite (all tasks).

**Placeholder scan:** No TBD/TODO; every code and command step shows exact content. The `<random>` / `<token>` tokens in Task 3 are intentional user-supplied values in documentation, not plan placeholders.

**Type consistency:** `_bearer_auth_asgi(inner_app, token)` and `_http_asgi_app()` are named identically across Task 1 (definition + tests) and Task 2 (call in `run()`). Env var names (`OPAYAI_TRANSPORT`, `OPAYAI_MCP_PORT`, `OPAYAI_MCP_TOKEN`) and port (8787) and path (`/mcp`) are consistent across Tasks 2 and 3.
