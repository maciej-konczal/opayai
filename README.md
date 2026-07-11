# opayai-mcp

Agent commerce backbone: turn a prompt into a **signed, policy-checked purchase**
across pluggable payment rails, with an approval gate, human-present passkey
step-up, and an audit trail. Ships as an **MCP server** (any assistant can plug
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
# 47 passed
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
| `stepup.authorized` | approve | (only over threshold) passkey signs a fresh challenge |
| `payment.settled` | purchase | selected rail charges → receipt |
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
   You should see 13 tools.
3. In Agent chat, a plain prompt drives the whole flow (the tools describe
   themselves, so you do NOT need to spell out each call):

   > Buy me a monitor under $300 that works with my MacBook and has free returns,
   > and require my passkey for anything over $250. Complete the purchase and give
   > me the link to track it.

   The agent will use the correct requirement tokens, run the passkey step-up, and
   return a clickable `status_url`.

Same server also works in Claude Desktop / VS Code / Claude Code - that is the
generality point: one server, many hosts.

## 5. Quickstart C - the web status site + live logs

The server writes every event to a log; the web site reads that same log and
renders order status + the signed audit trail (auto-refreshing).

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
| `request_approval` | record a yes/no for an escalated (over-limit) cart |
| `authorize_step_up` | run the passkey ceremony for an over-threshold cart |
| `execute_payment` | charge the rail and create the order (enforces all gates) |
| `advance_order` | PAID → SHIPPED → DELIVERED |
| `get_order` | current status + timeline (+ `status_url`) |
| `cancel_order` | cancel before shipment |
| `create_return` | return a delivered order within its window |
| `get_audit_trail` | the full signed event trail for an intent (the receipt) |

## Key concepts

- **Mandates (AP2-aligned).** The **Intent Mandate** is the user's pre-authorization
  (human-not-present): buy within these constraints and limits. The **Cart Mandate**
  is the specific proposed purchase. Both are Ed25519-signed.
- **Policy engine (fail-closed).** Checks signature, hard requirements
  (`free_returns`, `compat:<tag>`, `arrives_by:YYYY-MM-DD`), budget, and spending
  limits. Unknown/typo'd requirements are REJECTED, not silently passed.
- **Human-present step-up (passkey).** Carts at/above `step_up_threshold` require a
  fresh, challenge-bound signature from the user's registered device credential
  (passkey) - AP2's human-present path. Payment is refused until it verifies.
- **Pluggable rails.** `ap2` (the headline - Google Agent Payments Protocol) and
  `card` behind one `PaymentRail` interface. Adding another rail (real AP2/PSP,
  x402, Stripe ACP) is a single class - this is the generality story.
- **Audit trail = event bus = live view.** One append-only stream: the CLI renders
  it, the web site renders it, and `get_audit_trail` returns it as the receipt of
  exactly what the user agreed to and what happened.

## Environment variables

| var | default | used by |
|---|---|---|
| `OPAYAI_EVENT_LOG` | `~/.opayai/events.jsonl` | server (writes), web (reads) |
| `OPAYAI_WEB_PORT` | `8000` | web |
| `OPAYAI_WEB_BASE` | `http://localhost:8000` | server (builds `status_url`) |
| `ANTHROPIC_API_KEY` | unset | CLI front door: real Claude parse when set, offline heuristic otherwise |
| `OPAYAI_MODEL` | `claude-sonnet-5` | CLI front door model id |
| `OPAYAI_NOTIFY` | `1` | desktop ping on action-needed (macOS); `0` to disable |
| `OPAYAI_WEBHOOK_URL` | unset | POST each action-needed notification here (the Boski push seam) |
| `RESEND_API_KEY` + `OPAYAI_NOTIFY_EMAIL` | unset | email an action-needed notification via Resend |
| `OPAYAI_EMAIL_FROM` | `opayai <onboarding@resend.dev>` | email sender |

### Proactive notifications (channels)

The server generates user-facing notifications from the event stream and tags them
`needs_action` (approve / passkey / choose) vs progress updates - the "pings you
only when it needs input, approval, or a decision" behavior. Action-needed ones fan
out to every enabled **channel** (`src/opayai/channels.py`):

- **Desktop** - native macOS banner (on by default; `OPAYAI_NOTIFY=0` to mute).
- **Webhook** - `OPAYAI_WEBHOOK_URL` gets a JSON POST per action-needed notification.
  This is the integration seam a host like Boski uses to push to the user's phone.
  Demo it against any listener (e.g. `webhook.site`).
- **Email** - set `RESEND_API_KEY` + `OPAYAI_NOTIFY_EMAIL` to email the user. Note
  the default `onboarding@resend.dev` sender is a Resend sandbox: it only delivers to
  your own Resend account email until you verify a domain and set `OPAYAI_EMAIL_FROM`.

The agent can also pull the feed with the `get_notifications` tool, and the web order
page shows a Notifications inbox. Same notification, many channels.

## Project layout

```
src/opayai/
  types.py       frozen Pydantic types (mandates, decision, order, receipt)
  signing.py     Ed25519: user key + device (passkey) key
  data/          mock catalog, persona, conversations, orders (JSON)
  events.py      append-only event bus (audit trail + live view)
  mandate.py     build + sign intent and cart mandates
  policy.py      the policy engine (fail-closed) + step-up requirement
  stepup.py      human-present passkey ceremony
  rails.py       PaymentRail interface + MockX402Rail + MockCardRail
  orders.py      order lifecycle state machine (+ cancel/return)
  server.py      the opayai-mcp server (13 tools)
  front_door.py  prompt -> Intent Mandate (Claude or offline heuristic)
  cli.py         CLI host + live renderer + demo
  web.py         read-only status site
tests/           42 tests
docs/superpowers/  design spec + implementation plan
```

## Notes

- The demo dataset dates work on 2026-07-11 (`arrives tomorrow` = 2026-07-12). If
  demoing later, compute "tomorrow" from the clock in `front_door.heuristic_parse`
  and the offer fixtures.
- Payment is mocked (pluggable rails). The consent layer - mandates, policy,
  step-up, audit - is fully real; that is where agent commerce is actually hard.
```
