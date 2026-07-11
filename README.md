# OPayAI

OPayAI is one agent-commerce server for the full Polish purchase lifecycle:

intent → suggest → human approval → in-chat BLIK → tracking → keep or return → evidence.

It combines the teammate prototype's MCP vocabulary, ranked suggestions, CLI
front door, and proactive notification channels with the mobile UI, real
WebAuthn option, PLN/BLIK rail, paczkomat lifecycle, deterministic policy,
exceptions, refunds, and hash-chained evidence.

There is now one installable package (`src/opayai`), one MCP implementation
(`opayai.server`), and one process for the web app, REST/SSE, BLIK page, merchant
mock, and streamable HTTP MCP.

## Trust boundary

The agent can search, suggest, propose, evaluate, track, and propose a return.
It cannot sign, approve, confirm BLIK, advance fulfillment, or approve a
resolution. Those actions are deliberately absent from MCP and remain on the
human UI or internal merchant/demo surfaces.

Both signing modes bind consent to
`sha256(canonical_json(body))`:

- `AUTH_MODE=demo_key` — deterministic Ed25519 hackathon mode.
- `AUTH_MODE=webauthn` — platform WebAuthn with user verification.

## Run locally

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/uvicorn opayai.server:create_app --factory --host 0.0.0.0 --port 8000

# second terminal
cd web
npm install
npm run dev -- --host 0.0.0.0
```

Open `http://localhost:5173/?demo=1`. MCP clients connect to
`http://localhost:8000/mcp`. Cursor uses the same implementation over stdio via
the committed `.cursor/mcp.json`.

## Single MCP surface

| Tool | Role |
|---|---|
| `draft_intent` | Draft constraints; waits for the human signature |
| `search_offers` | Search PLN offers and expose policy-blocked alternatives |
| `suggest_offers` | Deterministic shortlist with match/block reasons |
| `propose_cart` | Propose the exact cart; waits for human authorization |
| `evaluate_policy` | Read the deterministic policy result |
| `get_order` | Track lifecycle events and exceptions |
| `create_return` | Propose a return; waits for a signed resolution |
| `list_purchases` | List current purchases |
| `get_audit_trail` | Read and validate the hash-chained trail |
| `get_notifications` | Pull action-needed and progress notifications |
| `get_evidence_bundle` | Export signed, dispute-grade close-out evidence |

## Implemented

- PLN catalog with monitors and winter tires, including visible rejected offers.
- Stable policy clauses, revocation, and cumulative mandate budgets.
- Cart-bound delivery and return-policy snapshots.
- BLIK Lite with an in-chat human prompt and separate-phone fallback.
- Paczkomat pickup, keep/return decision, wrong-item diff, return, and refund.
- Full-stream webhook plus desktop/email action-needed notification adapters.
- Hash-chained ledger, SSE event feed, and downloadable evidence bundle.
- English OPayAI mobile chat and desktop audit interface.
- Docker single-process build.

See [demo.md](demo.md) for the rehearsed scenarios and
[contracts/mcp-tools.md](contracts/mcp-tools.md) for the source-of-truth MCP
contract.

## Honest limitations

BLIK, merchant fulfillment, refunds, and notification delivery are local mocks.
The mandates are AP2-inspired and the payment handshake is MPP-shaped; OPayAI
does not claim wire compatibility with either protocol. There is one demo user
and no delegated or human-not-present purchase mode.
