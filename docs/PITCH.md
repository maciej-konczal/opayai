# opayai - Pitch

The transaction layer a proactive agent plugs into to actually **buy** - safely,
with the user in control.

---

## Value proposition

> opayai turns a proactive agent's "I found some options" dead-end into
> "I bought it, here's the receipt, and I only pinged you when I needed you."

The challenge is not recommendations. It is the **transaction workflow for
agents**: the part between product research and a completed order. That part is
brittle today - product data is messy, checkout is UI-bound, and consent is
unclear. opayai owns exactly that part.

## Why this fits Boski specifically

Boski is a **proactive** agent that works in the background and pings you only
when it needs input, approval, or a decision. The hardest, riskiest piece of
"the agent buys for you while you are away" is not the research - it is the
**transaction + consent**. That is what opayai is.

- Boski does discovery, voice, coordination. opayai does **authorize -> pay ->
  track -> resolve**, with signed mandates, spending limits, simulated trusted-
  surface step-up, and an audit event trail. It is the missing half, not a competing whole.
- opayai's proactive notifications map 1:1 onto Boski's ping model: `needs_action`
  notifications (approve / passkey / choose an option) route straight to Boski's
  push channel.
- It connects over **MCP**, so it drops into Boski (or any assistant) with no
  rebuild - the same server already runs in Cursor.

## The moat

Anyone can rank products. Almost no one builds the **consent + trust rails**:
signed mandates, a policy engine, authorization proofs, and an audit event trail - the
boring, hard, regulated part that makes an agent *allowed* to spend your money.
That is the defensible core, and it is what opayai is.

## How it is implemented (the mental model)

Three layers. Being explicit about what is real vs mocked removes the "blurry"
feeling.

| Layer | What | In this build |
|---|---|---|
| **Proactive shell** (Boski) | voice in, background execution, push notifications | their product - we emit the notifications it would push |
| **Transaction backbone** (opayai) | mandates, policy, authorization proofs, orders, audit events, notifications | executable deterministic controls; trusted user surface remains simulated |
| **Rails + catalog** | payment settlement + agent-readable merchant offers | mocked, behind a pluggable interface |

The LLM only touches the fuzzy front door: prompt -> Intent Mandate, choose an
offer. **Everything after is deterministic tools** - which is why it is reliable
and auditable.

## Payments are pluggable - AP2 is the direction

The consent layer sits **above** the rail, so settlement mechanisms swap without
touching the mandate/policy logic (`PaymentRail` interface):

- **AP2-inspired adapter** - opayai demonstrates the same product concern:
  deterministic delegated authorization for human-not-present purchases and
  trusted-surface step-up above a threshold. It currently uses custom Intent and
  Cart objects plus a mock adapter; it is not wire-compatible with AP2's official
  versioned Checkout and Payment Mandates yet.
- **x402** - HTTP 402 machine-payable endpoints (stablecoin). A different rail,
  same mandate.
- **Stripe ACP** - card via a PSP token. A different rail, same mandate.

Demo the AP2-inspired adapter only, so it stays concrete; mention x402/Stripe as "other adapters we drop
in" to prove generality.

## Scenario runbook

Each scenario = one prompt -> one proactive ping -> one visible outcome, and each
hits a judging criterion. Prompts are for the Cursor (MCP) demo; toggle the
`opayai` server off/on first so the self-describing tools load.

### 1. Autonomous, in-policy (prompt -> purchase)
> Buy me a monitor under $300 that works with my MacBook and has free returns.
> Complete the purchase and give me the link to track it.

Ping: "Payment complete." Proves: the agent goes from prompt to a completed,
signed purchase within the demo Intent Mandate (AP2-inspired autonomous flow). No babysitting.

### 2. Decision needed (the user picks the product)
> I want a monitor for my MacBook, budget around $300, free returns preferred.
> Show me a shortlist with the tradeoffs and let me pick before buying.

Ping: "Options ready to choose." The agent presents qualifying + disqualified
(over budget / out of stock) options with reasons, waits for the pick, then buys
it. Proves: the user controls the product choice.

### 3. Approval needed (over spending limit)
> Buy me a MacBook monitor under $300 with free returns, but cap any single
> purchase at $200. Ask me before paying if it goes over.

Ping: "Approval needed." Policy returns ESCALATE; payment is refused until you
approve. Proves: spending limits + human-in-the-loop.

### 4. Passkey step-up (high value) - the money moment
> Buy me a MacBook monitor under $300 with free returns, and require my passkey
> for anything over $250.

Ping: "Confirm with your passkey." A fresh, challenge-bound device signature is
required before payment. Proves: challenge-bound, expiring step-up evidence - the clearest
"trust, safety & consent" story.

### 5. After-purchase (resolve)
> Mark it shipped, then delivered. Actually, return it - I changed my mind.

Pings: "Order delivered" -> "Return filed." Proves: the agent resolves what
happens after the purchase (tracking, returns), not just the buy.

### 6. Blocked (safety) - optional
> Buy the ViewPro 27 monitor for my MacBook, but my total budget is only $250.

Ping: "Purchase blocked - over budget." Policy REJECTs (fail-closed). Proves:
the trust engine refuses out-of-policy and malformed requests.

## What is built (executable and tested; integrations mocked)

- Ed25519-signed custom **Intent Mandate** + **Cart Mandate** (AP2-inspired model)
- **Policy engine** (fail-closed): signature, hard requirements, budget, spending
  limits, step-up requirement
- **Simulated trusted-surface/passkey step-up** over a threshold
- **Approval gate** for over-limit carts
- **suggest_offers**: ranked shortlist with match reasons for user selection
- **Pluggable rails**: `ap2` + `card` behind one interface
- **Order lifecycle**: track -> cancel -> return
- **Audit trail = event bus = live view** (one substrate)
- **Proactive notifications**: action-needed pings (incl. native desktop ping) +
  web inbox
- Surfaces: **MCP server** (any host), **CLI demo**, **web status site**
- 73 passing tests

See `README.md` for how to run everything.
