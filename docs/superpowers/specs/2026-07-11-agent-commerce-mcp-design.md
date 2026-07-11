# Agent Commerce MCP - Historical prototype design

> Superseded by the unified OPayAI server. The active contract is
> `contracts/mcp-tools.md`; the only server entrypoint is `opayai.server`.

**Date:** 2026-07-11
**Challenge:** BOSKI hackathon - "Agent Commerce: purchasing when the user is not in the tab."
**Team:** 3 people
**Prize context:** best working purchase flow for agents (up to 1000 PLN).

---

## 1. Pitch

**`opayai-mcp`** - an MCP commerce backbone that turns a user's prompt into a
**signed, policy-checked purchase** across pluggable payment rails - keeping the user in control via mandates,
approval gates, and an audit trail that doubles as the live event stream. Any agent can
plug in; ours is a CLI.

The deliverable is **not** a chatbot and **not** a rebuilt store. It is the transaction
workflow *between product research and a completed order*, exposed as a protocol any
assistant can connect to.

## 2. Goals & non-goals (mapped to judging)

| Judging reward | How we hit it |
|---|---|
| Useful buying flow (buying, not browsing) | Research is mocked; 100% of the build is the transaction |
| Clear agent steps | discover -> decide -> approve -> purchase -> track -> resolve, each a visible event |
| Trust, safety & consent | Signed mandates + policy engine + approval gate + append-only audit trail |
| Working demo, realistic data | Mock catalog, persona, conversations, orders, cart, receipts, returns via JSON + Pydantic |
| Generality | MCP server = works beyond one brand/store/assistant; two swappable payment rails |

**Non-goals:** product recommendation quality, a real storefront, real money movement
(Stripe test-mode is a stretch only), a GUI.

## 3. Architecture

```
+-----------------------------------+
|  CLI demo client (MCP host)       |   simple prompt input
|  - LLM front door (hybrid)        |   prompt -> IntentMandate; cart selection
|  - MCP client                     |
|  - live event renderer (rich)     |   the visualization
|  - approval prompt (y/n)          |   human-in-the-loop
+----------------+------------------+
                 | MCP (stdio)
+----------------v------------------+
|  opayai-mcp  (THE BACKBONE)       |
|  tools:                           |
|   search_offers        -> data/   (mock)
|   create_intent_mandate -> mandate/
|   propose_cart         -> mandate/
|   evaluate_policy      -> policy/  (differentiator)
|   request_approval     -> emits ESCALATE event
|   execute_payment      -> rails/  (MockX402 | MockCard | Stripe)
|   get_order / track    -> orders/
|   create_return/cancel -> orders/
|  every call -> event bus -> audit/ + CLI stream
+-----------------------------------+
```

**Hybrid boundary:** the LLM touches only `create_intent_mandate` (prompt -> structured
constraints) and cart selection (`propose_cart` reasoning). Everything from policy
evaluation onward is deterministic, inspectable tool calls. This keeps the demo reliable.

## 4. Core types (Pydantic)

Frozen in hour 1 by all three people; everything else builds against these.

```python
# mandate/types.py
class Money(BaseModel):
    amount: Decimal
    currency: str = "USD"

class Constraint(BaseModel):
    max_total: Money
    category: str                       # e.g. "monitor"
    hard_requirements: list[str] = []   # ["arrives_by:2026-07-12", "free_returns", "compat:macbook"]
    soft_preferences: list[str] = []    # ["high_rating", "known_brand"]

class SpendingLimit(BaseModel):
    per_transaction: Money
    per_period: Money
    period: str = "day"

class IntentMandate(BaseModel):
    id: str
    user_id: str
    created_at: datetime
    expires_at: datetime
    human_present: bool = False         # "not in the tab"
    constraint: Constraint
    spending_limit: SpendingLimit
    signature: str                      # Ed25519 over canonical JSON

class CartItem(BaseModel):
    offer_id: str
    title: str
    qty: int
    unit_price: Money

class CartMandate(BaseModel):
    id: str
    intent_mandate_id: str
    items: list[CartItem]
    total: Money
    selected_rail: str                  # "x402" | "card"
    rationale: str                      # LLM's why (shown to user)
    created_at: datetime
    signature: str

class PolicyCheck(BaseModel):
    rule: str
    passed: bool
    detail: str

class PolicyDecision(BaseModel):
    cart_mandate_id: str
    result: Literal["AUTO_APPROVE", "ESCALATE", "REJECT"]
    checks: list[PolicyCheck]

class Event(BaseModel):
    seq: int
    ts: datetime
    type: str                           # "intent.created", "policy.evaluated", ...
    actor: Literal["user", "agent", "policy", "rail", "merchant"]
    mandate_ref: str | None
    payload: dict

class Receipt(BaseModel):
    id: str
    cart_mandate_id: str
    rail: str
    amount: Money
    paid_at: datetime
    rail_reference: str                 # mock txn id / x402 settlement id

class Order(BaseModel):
    id: str
    cart_mandate_id: str
    receipt: Receipt
    status: Literal["CREATED","PAID","SHIPPED","DELIVERED",
                    "CANCELLED","RETURN_REQUESTED","RETURNED"]
    timeline: list[Event]
    exceptions: list[str] = []
```

## 5. Mock data schemas (`data/`, JSON)

- **`offers.json`** - list of `Offer { id, title, merchant, price, stock{available,qty},
  delivery{est_date,cutoff}, policies{returns_window_days,free_returns,warranty_months},
  specs{compat:[...], ...}, rating }`. Agent-readable offers - the "structured prices,
  stock, policies, availability" from the deck.
- **`persona.json`** - `Persona { id, name, goals, motivations, communication_style,
  defaults{budget,brands,sustainability,risk_tolerance}, payment_methods, shipping }`.
- **`conversations.json`** - prior chat turns (preference-aware context).
- **`orders.json`** - prior orders (history + feedback loop seed).

## 6. MCP tools (server surface)

| Tool | Input | Output | Module |
|---|---|---|---|
| `search_offers` | query, filters | `[Offer]` | data |
| `create_intent_mandate` | constraints, limits | `IntentMandate` | mandate |
| `propose_cart` | intent_id, offer_ids | `CartMandate` | mandate |
| `evaluate_policy` | cart_id | `PolicyDecision` | policy |
| `request_approval` | cart_id, reason | approval token / event | policy+audit |
| `execute_payment` | cart_id, rail | `Receipt` + `Order` | rails+orders |
| `get_order` | order_id | `Order` | orders |
| `create_return` | order_id, reason | `Order` | orders |
| `cancel_order` | order_id | `Order` | orders |
| `get_audit_trail` | mandate_id / order_id | `[Event]` | audit |

## 7. Policy engine (the differentiator)

`evaluate_policy(cart)` runs deterministic checks of `CartMandate` against its
`IntentMandate` + persona + spending limits, returning a `PolicyDecision`:

- **Hard-requirement checks:** every `hard_requirement` satisfied by the chosen offer(s)
  (arrives_by, free_returns, compatibility). Fail -> `REJECT`.
- **Budget check:** `total <= constraint.max_total`. Fail -> `REJECT`.
- **Spending-limit check:** `total <= spending_limit.per_transaction` AND running period
  spend + total <= `per_period`. Exceed -> `ESCALATE` (needs human tap).
- **Signature check:** cart + intent signatures verify. Fail -> `REJECT`.
- All pass and within limits -> `AUTO_APPROVE`.

The decision, with per-rule pass/fail detail, is emitted as an event and shown in the CLI.

## 8. Payment rails (`rails/`)

```python
class PaymentRail(Protocol):
    name: str
    def charge(self, cart: CartMandate) -> Receipt: ...
```

- **`MockX402Rail`** - simulates HTTP 402 flow: returns a 402 "quote", agent "pays",
  rail returns a settlement id. Stablecoin/crypto flavor.
- **`MockCardRail`** - simulates a card charge, returns a mock txn id.
- **Stretch:** `StripeRail` using Stripe test mode + test cards (Person B, if time).

Two rails behind one interface = the generality proof. Rail is selected in the
`CartMandate`; swapping it changes nothing upstream.

## 9. Order lifecycle (`orders/`)

State machine: `CREATED -> PAID -> SHIPPED -> DELIVERED`, with branches
`-> CANCELLED` and `RETURN_REQUESTED -> RETURNED`. Each transition appends an `Event`
to the order timeline. `create_return`/`cancel_order` enforce policy (e.g. within
`returns_window_days`) and update persona/history (feedback loop).

## 10. Event bus + audit trail (`audit/`)

One append-only, monotonically-sequenced `Event` log. Every tool call publishes to it.
Two consumers: (1) the CLI renderer subscribes and prints live; (2) `get_audit_trail`
returns the slice for a mandate/order = "exactly what the user agreed to and what
happened." Same substrate, satisfies both visualization and consent/receipt rewards.

## 11. CLI host (`cli/`, `agent/`)

1. Read a prompt (typed, or a canned voice-memo string).
2. **LLM front door** (Claude via Anthropic SDK, structured output) -> `Constraint` +
   `SpendingLimit` -> `create_intent_mandate`.
3. Agent loop calls MCP tools: `search_offers` -> LLM picks offers -> `propose_cart` ->
   `evaluate_policy`.
4. On `ESCALATE`, render the proposal and block on a `y/n` approval prompt.
5. On approve/auto-approve: `execute_payment` -> render `Receipt`.
6. `get_order` timeline; optional `create_return`.
7. Throughout, the event stream renders live with `rich`.

## 12. Canonical demo (3 runs = full coverage)

Prompt (from the deck): *"Find me the best monitor under $300 that works with my
MacBook, arrives tomorrow, and has good return terms. Buy it if you're confident."*

- **Run 1 - happy path:** auto-approves within limits, buys, shows receipt + order. Covers
  discover -> decide -> approve(auto) -> purchase -> track.
- **Run 2 - control:** a pricier pick trips the spending limit -> `ESCALATE` -> user taps
  yes. Shows the user staying in control.
- **Run 3 - resolve:** `create_return` on Run 1's order. Shows after-purchase resolution.
- **Flex (optional):** connect the same MCP server to Claude Desktop to prove generality.

## 13. Work split (contract-first)

**Hour 1 together:** freeze section 4 types + section 5/6 schemas. Then parallelize.

- **Person A - Consent Core (differentiator):** `mandate/` (types, Ed25519 sign/verify),
  `policy/` engine, `audit/` event bus.
- **Person B - Money & Fulfillment:** `rails/` (interface + MockX402 + MockCard, Stripe
  stretch), `orders/` state machine + returns/cancel/exceptions, receipts.
- **Person C - Agent & Experience:** MCP server wiring (registers A+B modules as tools),
  CLI host, LLM front door, `rich` event renderer, approval UX, `data/` mock JSON.

## 14. Tech stack

- **Python 3.11+**
- **MCP:** official `mcp` Python SDK (FastMCP-style server, stdio transport)
- **Validation/types:** Pydantic v2 (schemas, mandates, policy checks)
- **Signing:** PyNaCl (Ed25519)
- **LLM front door:** Anthropic SDK; model `claude-sonnet-5` (fast, cheap structured
  extraction) - verify current model id/params against the claude-api skill at build time
- **CLI/render:** `rich` (event stream, tables), `typer` or `argparse` (input)
- **Testing:** pytest (policy checks, state machine transitions, signature verify)

## 15. Stretch goals (only if core is solid)

- Real Stripe test-mode rail.
- Second MCP host demo (Claude Desktop) for a live generality flex.
- Persona feedback loop actually mutating future recommendations.
- Multi-item cart / multi-merchant order.

## 16. Testing focus

Deterministic core = easy to test: policy decisions (each rule, boundary cases at the
spending limit), order state-machine transitions (legal/illegal), signature verify
(tamper -> reject), return-window enforcement. LLM front door tested with a couple of
fixed prompts asserting the extracted `Constraint`.
