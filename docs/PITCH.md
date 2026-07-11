# OPayAI — pitch

OPayAI is the transaction layer a proactive agent plugs into to buy safely,
while keeping the human visibly in control.

## Why it fits Boski

Boski discovers and coordinates in the background. OPayAI handles the risky
part after discovery: exact-cart consent, payment, tracking, exceptions,
returns, refunds, and evidence. It pings the user only when a choice, signature,
payment confirmation, or resolution is required.

The memorable demo is one continuous mobile conversation:

1. The agent turns a request into explicit constraints.
2. Policy-filtered options appear with rejected alternatives explained.
3. The human signs the exact cart and enters BLIK without leaving chat.
4. OPayAI tracks the parcel to a paczkomat.
5. The human keeps it or returns it.
6. A wrong-item fault produces a deterministic diff, signed resolution, refund,
   and validated evidence bundle.

## What is real

- Deterministic policy, cumulative budgets, revocation, and state transitions.
- Real WebAuthn verification or a content-bound Ed25519 demo fallback.
- Cart snapshots, BLIK state machine, exception diff, return/refund lifecycle.
- Append-only hash-chained evidence and full event-stream notifications.
- One MCP server usable over stdio or streamable HTTP.

## What is mocked

- The Polish merchant, BLIK/PSP settlement, fulfillment, and refund rail.
- Desktop, email, and webhook notification delivery targets.

OPayAI uses AP2-inspired mandates and an MPP-shaped handshake. It is not
wire-compatible with those standards and does not claim to be.

## Trust story

The MCP agent can discover, suggest, propose, evaluate, track, and propose a
return. It cannot consent. No MCP tool signs a mandate, approves a cart,
confirms BLIK, advances fulfillment, or approves a return resolution. The human
completes those actions on the OPayAI surface, and each authorization is bound
to the exact canonical content stored in the evidence bundle.
