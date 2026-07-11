# opayai-mcp

Agent commerce backbone: turn a prompt into a **signed, policy-checked purchase**
across pluggable payment adapters, with an approval gate, a simulated trusted-
surface/passkey step-up, and an audit event trail. Ships as an **MCP server** (any assistant can plug
in), a **CLI demo**, and a **web status site**.

The challenge is not recommendations - it is the transaction workflow for agents:
the part between product research and a completed order.

```
prompt ─▶ Intent Mandate (signed) ─▶ offers ─▶ Cart Mandate (signed)
        ─▶ policy check ─▶ [approve] ─▶ [passkey step-up] ─▶ pay ─▶ order ─▶ track ─▶ return
                                    every step ─▶ one event bus = live view + audit trail
```

Agent steps: **discover → decide → approve → purchase → track → resolve.**

---

## 1. Setup (once)

```bash
cd /Users/maciejkonczal/Documents/Projects/opayai
python3 -m venv .venv
./.venv/bin/pip install -e ".[dev]"
```

(This repo already has a `.venv` set up. Everything below uses `./.venv/bin/...`
so you never need to activate it.)

## 2. Run the tests

```bash
./.venv/bin/pytest -q
# 73 passed
```

## 3. Quickstart A - the CLI demo (fastest way to see it)

Each `#N` line is one agent step, printed live.

```bash
# happy path: buy, track, then return
./.venv/bin/python -m opayai.cli --return

# require a passkey for anything at/above $250 (the $289 monitor triggers step-up)
./.venv/bin/python -m opayai.cli --step-up 250

# a custom request
./.venv/bin/python -m opayai.cli "best keyboard under $120 with free returns"
```

Reading the output:

| line | agent step | what happens |
|---|---|---|
| `intent.created` | discover/decide | prompt → signed Intent Mandate (constraints + spending limits) |
| `cart.proposed` | decide | agent picks an offer → signed Cart Mandate |
| `policy.evaluated` | approve | signature + hard requirements + budget + spending limits + step-up |
| `stepup.authorized` | approve | (only over threshold) the demo device signs a fresh challenge |
| `payment.settled` | purchase | selected mock adapter succeeds → receipt |
| `order.created/advanced` | track | PAID → SHIPPED → DELIVERED |
| `order.return_requested` | resolve | `--return` files a return |

## 4. Quickstart B - the MCP server + Cursor

Run it as a server any MCP host can drive:

```bash
./.venv/bin/python -m opayai.server        # stdio transport
```

**Cursor** (config already committed at `.cursor/mcp.json`):

1. Open this folder as the Cursor workspace - Cursor auto-detects `.cursor/mcp.json`.
2. Settings → MCP → toggle the **`opayai`** server on (or off/on to reload tools).
   You should see 12 tools.
3. In Agent chat, a plain prompt drives the whole flow (the tools describe
   themselves, so you do NOT need to spell out each call):

   > Buy me a monitor under $300 that works with my MacBook and has free returns,
   > and require my passkey for anything over $250. Complete the purchase and give
   > me the link to track it.

   The agent will use the correct requirement tokens, run the passkey step-up, and
   return a clickable `status_url`.

Same server also works in Claude Desktop / VS Code / Claude Code - that is the
generality point: one server, many hosts.

### Run with the standalone OpenAI agent (no Cursor)

The local agent host starts the same MCP server as a subprocess and lets an
OpenAI model drive its tools. Keep the API key in your shell, not in this repo:

```bash
export OPENAI_API_KEY="your-key"
./.venv/bin/python -m opayai.agent
```

You can also supply the first request directly:

```bash
./.venv/bin/python -m opayai.agent \
  "buy a monitor under $300 with free returns for my MacBook"
```

The default model is `gpt-5.4-mini`. Override it with
`OPAYAI_OPENAI_MODEL` if needed. Keep the terminal session open when the agent
asks you to choose an offer or approve a purchase; your next message continues
the same MCP session.

For the same agent in a browser, run:

```bash
export OPENAI_API_KEY="your-key"
./.venv/bin/python -m opayai.browser
```

Then open http://127.0.0.1:8080. This page is the MCP host: keep its terminal
process running while you use the browser. It preserves one conversation and one
local MCP workflow session until the process stops. Approval and passkey step-up
buttons appear directly on this page when needed; clicking one records the human
authorization and automatically asks the agent to retry payment. Orders, profiles,
receipts, and audit trails are also linked from the same local site.

## 5. Quickstart C - the web status site + live logs

The server writes every event to a log; the web site reads that same log and
renders order status + the audit event trail (auto-refreshing).

```bash
# terminal 1: the status site (point it at the log the server writes)
OPAYAI_EVENT_LOG=./opayai-events.jsonl ./.venv/bin/python -m opayai.web
# -> http://localhost:8000

# terminal 2: watch raw events stream in
tail -F ./opayai-events.jsonl
```

`execute_payment` / `get_order` return a `status_url` (e.g.
`http://localhost:8000/order/ord_1`), so the agent hands the user a clickable link.

**Your context / profile:** http://localhost:8000/profile shows what the agent
knows about you before it shops - preferences, default budget, passkey threshold,
payment methods, remembered conversation, and recent orders. A natural demo start:
open the profile, then give the agent a product prompt.

## 6. The full end-to-end demo (all together)

Three panes make the strongest story:

```bash
# pane 1 - status site
OPAYAI_EVENT_LOG=./opayai-events.jsonl ./.venv/bin/python -m opayai.web

# pane 2 - live event log
tail -F ./opayai-events.jsonl

# pane 3 - Cursor (or the CLI) driving the agent
```

Then in Cursor, ask the agent to buy something with a step-up threshold. Watch the
event log fill in pane 2, click the `status_url` it returns, and see the order page
in pane 1 update live as you tell the agent to advance or return the order.

---

## MCP tools (the server surface)

| tool | purpose |
|---|---|
| `create_intent_mandate` | sign what the user authorizes (constraints, limits, `step_up_threshold`) - call FIRST |
| `search_offers` | agent-readable catalog (price, stock, delivery, returns, specs) |
| `suggest_offers` | ranked shortlist with match reasons (and why-not); user picks before `propose_cart` |
| `propose_cart` | sign the specific cart the agent wants to buy |
| `evaluate_policy` | AUTO_APPROVE / ESCALATE / REJECT + `step_up_required`, with a per-rule breakdown |
| `execute_payment` | pays if all gates are met; else returns a PENDING status with an `authorize_url` (the agent cannot self-authorize) |
| `advance_order` | PAID → SHIPPED → DELIVERED |
| `get_order` | current status + timeline (+ `status_url`) |
| `cancel_order` | cancel before shipment |
| `create_return` | return a delivered order within its window |
| `get_audit_trail` | the full audit event trail for an intent |
| `get_notifications` | proactive action-needed and progress notifications |

## Key concepts

- **Mandates (AP2-inspired).** The demo **Intent Mandate** is the user's pre-authorization
  (human-not-present): buy within these constraints and limits. The **Cart Mandate**
  is the specific proposed purchase. Both are Ed25519-signed.
- **Policy engine (fail-closed).** Checks signature, hard requirements
  (`free_returns`, `compat:<tag>`, `arrives_by:YYYY-MM-DD`), budget, and spending
  limits. Unknown/typo'd requirements are REJECTED, not silently passed.
- **Trusted-surface authorization (the agent can't self-authorize).** When a cart needs
  the user's approval (ESCALATE) or passkey step-up, `execute_payment` returns a PENDING
  status; the user must authorize on the **web page** (`/authorize`), which issues a
  signed, expiring proof bound to that exact cart/amount. Only then does payment go
  through. The web and MCP processes share this via a small on-disk auth store, so the
  authorization genuinely comes from the human, not the agent. Production would issue the
  same proof after a real WebAuthn gesture.
- **Pluggable payment adapters.** Mock `ap2` and `card` adapters sit behind one
  `PaymentRail` interface. Adding a real AP2/PSP, x402, or Stripe adapter is the
  next integration step.
- **Audit event trail = event bus = live view.** One append-only stream: the CLI renders
  it, the web site renders it, and `get_audit_trail` returns it as the receipt of
  exactly what the user agreed to and what happened.

## Environment variables

| var | default | used by |
|---|---|---|
| `OPAYAI_EVENT_LOG` | `~/.opayai/events.jsonl` | server (writes), web (reads) |
| `OPAYAI_AUTH_STORE` | `opayai-auth` next to the event log | shared approval/step-up proofs (server + web) |
| `OPAYAI_WEB_PORT` | `8000` | web |
| `OPAYAI_WEB_BASE` | `http://localhost:8000` | server (builds `status_url`) |
| `ANTHROPIC_API_KEY` | unset | CLI front door: real Claude parse when set, offline heuristic otherwise |
| `OPAYAI_MODEL` | `claude-sonnet-5` | CLI front door model id |
| `OPAYAI_NOTIFY` | `1` | desktop ping on action-needed (macOS); `0` to disable |
| `OPAYAI_FULFILLMENT` | `1` | background ticker advances orders over time; `0` to disable |
| `OPAYAI_SHIP_SECONDS` / `OPAYAI_DELIVER_SECONDS` | `20` / `40` | seconds after placement -> SHIPPED / DELIVERED |
| `OPAYAI_WEBHOOK_URL` | unset | POST each action-needed notification here (the Boski push seam) |
| `RESEND_API_KEY` + `OPAYAI_NOTIFY_EMAIL` | unset | email an action-needed notification via Resend |
| `OPAYAI_EMAIL_FROM` | `opayai <onboarding@resend.dev>` | email sender |

### Proactive notifications (channels)

The server generates user-facing notifications from the event stream and tags them
`needs_action` (approve / passkey / choose) vs progress updates - the "pings you
only when it needs input, approval, or a decision" behavior. Action-needed ones fan
out to every enabled **channel** (`src/opayai/channels.py`):

- **Desktop** - native macOS banner (on by default; `OPAYAI_NOTIFY=0` to mute).
- **Webhook** - `OPAYAI_WEBHOOK_URL` gets a JSON POST for **every** event (the full
  stream, same shape as the JSONL: `seq, ts, type, actor, mandate_ref, payload`), so
  an external service stays fully in sync. Action-needed events additionally carry a
  `notification` object (title/body/needs_action) it can push to the user. This is
  the integration seam a host like Boski subscribes to. Demo it against any listener
  (e.g. `webhook.site` or `python -m opayai.webhook_sink`).
- **Email** - set `RESEND_API_KEY` + `OPAYAI_NOTIFY_EMAIL` to email the user. Note
  the default `onboarding@resend.dev` sender is a Resend sandbox: it only delivers to
  your own Resend account email until you verify a domain and set `OPAYAI_EMAIL_FROM`.

The agent can also pull the feed with the `get_notifications` tool, and the web order
page shows a Notifications inbox. Same notification, many channels.

**Simulate the webhook locally** (no external service). Terminal 1 runs a receiver
that prints whatever is POSTed; terminal 2 drives a flow that needs action:

```bash
# terminal 1 - the local webhook receiver (stands in for Boski's push endpoint)
./.venv/bin/python -m opayai.webhook_sink        # -> http://127.0.0.1:9099

# terminal 2 - drive a step-up flow, pointing pings at the receiver
OPAYAI_NOTIFY=0 OPAYAI_WEBHOOK_URL=http://127.0.0.1:9099 \
  ./.venv/bin/python -m opayai.cli --step-up 250
```

Terminal 1 prints, e.g.:
`[12:38:26] ACTION  Confirm with your passkey - A purchase is over your step-up threshold ...`

For the Cursor demo, put `OPAYAI_WEBHOOK_URL` in `.cursor/mcp.json`'s `env` block
and reload the server; the MCP server POSTs to the same receiver.

## Project layout

```
src/opayai/
  types.py       frozen Pydantic types (mandates, decision, order, receipt)
  signing.py     Ed25519: user key + device (passkey) key
  data/          mock catalog, persona, conversations, orders (JSON)
  events.py      append-only event bus (audit trail + live view)
  mandate.py     build + sign intent and cart mandates
  policy.py      the policy engine (fail-closed) + step-up requirement
  stepup.py      simulated trusted-surface/passkey ceremony
  rails.py       PaymentRail interface + MockAP2Rail + MockCardRail
  orders.py      order lifecycle state machine (+ cancel/return)
  server.py      the opayai-mcp server (12 tools)
  front_door.py  prompt -> Intent Mandate (Claude or offline heuristic)
  cli.py         CLI host + live renderer + demo
  web.py         read-only status site
tests/           73 tests
docs/superpowers/  design spec + implementation plan
```

## Notes

- The demo dataset dates work on 2026-07-11 (`arrives tomorrow` = 2026-07-12). If
  demoing later, compute "tomorrow" from the clock in `front_door.heuristic_parse`
  and the offer fixtures.
- Payment adapters and the trusted user surface are mocked. The deterministic
  policy gates, signatures, expiring authorization proofs, and lifecycle state
  machine are executable. This is AP2-inspired, not wire-compatible with the
  official AP2 Checkout/Payment Mandate schemas yet.
