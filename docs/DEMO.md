# opayai - Demo runbook

Two ways to demo: **one command** (self-contained), or **live in Cursor** (the real
agent driving it). For the pitch script itself, see `docs/PITCH.md`.

---

## Option A - one command (fastest)

Runs the whole scenario in a single process (embeds the web trusted surface + the
fulfillment ticker) and prints every event.

```bash
cd /Users/maciejkonczal/Documents/Projects/opayai

python -m opayai.demo           # interactive: pauses for YOU to click Authorize
python -m opayai.demo --auto     # fully scripted, no interaction
```

Use `./.venv/bin/python -m opayai.demo` if you have not activated the venv. In
interactive mode, open the printed `http://localhost:8000/authorize` link, click
**Authorize with passkey**, then press Enter.

---

## Option B - live in Cursor (the presentation)

You run only **one server** (the web trusted surface). Cursor launches the MCP
server itself from `.cursor/mcp.json`.

### What to run

**Terminal 1 - the web server** (trusted surface + status + profile + authorize):

```bash
cd /Users/maciejkonczal/Documents/Projects/opayai
rm -f opayai-events.jsonl && rm -rf opayai-auth        # clean slate (see Gotchas)
OPAYAI_EVENT_LOG=./opayai-events.jsonl OPAYAI_AUTH_STORE=./opayai-auth \
  ./.venv/bin/python -m opayai.web                      # -> http://localhost:8000
```

**Cursor** - Settings -> MCP -> toggle **`opayai`** off/on (loads the latest tools
and the pinned config). Cursor spawns the MCP server; do not run it by hand.

**Terminal 2 (optional) - the "phone"** (webhook feed, if you want to show it):

```bash
./.venv/bin/python -m opayai.webhook_sink              # .cursor/mcp.json points here (:9099)
```

### The flow

1. **Open http://localhost:8000/profile** - "here's what the agent knows about me":
   budget, the **$250 passkey threshold**, payment methods, past orders.
2. **In Cursor**, a plain prompt (no threshold - it is config):
   > Buy me a MacBook monitor under $300 that works with my MacBook and has free returns.
3. Agent tries to pay -> tells you **"I can't authorize this - approve at
   http://localhost:8000/authorize"** (a macOS banner also pops).
4. **Open /authorize**, click **Authorize with passkey**.
5. Agent completes -> **PAID**, hands you the tracking link. Open it.
6. **~12s later** -> "delivered": a desktop push, and the order page updates live.

### What each surface shows

| Surface | URL | Shows |
|---|---|---|
| Profile | `/profile` | preference-aware context before shopping |
| Authorize | `/authorize` | the trusted surface - the button the agent can't press |
| Order | `/order/<id>` | status, receipt, notifications, and the signed audit trail |
| Orders | `/` | all orders |

---

## Gotchas

- **Clear `opayai-auth` before a fresh demo.** Cart ids reset to `cm_1` when the MCP
  server restarts, so a leftover proof from a previous session could auto-satisfy the
  step-up and skip the Authorize moment. The `rm -rf opayai-auth` in setup handles it.
  (Within a single Cursor session, ids increment - repeat runs are fine.)
- **Reload the `opayai` server in Cursor** after any code or config change, or it keeps
  the stale tool definitions.
- **Shared state.** The Cursor-launched MCP server and the web server must share
  `OPAYAI_EVENT_LOG` and `OPAYAI_AUTH_STORE`. `.cursor/mcp.json` pins both to absolute
  paths; run the web server with the matching values (the commands above do).
- **Desktop banners** come from the Cursor-launched MCP server (macOS, on by default;
  `OPAYAI_NOTIFY=0` to mute). The `/authorize` and status pages come from your web
  terminal.

## Timing

Fulfillment is snappy for a demo: **SHIPPED ~5s**, **DELIVERED ~12s** after purchase.
Tune via `OPAYAI_SHIP_SECONDS` / `OPAYAI_DELIVER_SECONDS` (pinned in `.cursor/mcp.json`
for Cursor; set on the command line for the CLI/one-command demo).

## Scenarios to show

See `docs/PITCH.md` for the full scenario runbook (autonomous buy, pick-an-option,
approval-needed, passkey step-up, after-purchase return, blocked-by-policy).
