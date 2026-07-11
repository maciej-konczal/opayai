# MandateLoop

MandateLoop gives an AI agent a safe purchasing capability over a mocked Polish
store: intent → **human passkey approval** → BLIK confirmation → paczkomat
tracking → keep or return → hash-chained evidence bundle.

The design point is deliberately narrow: an agent may propose and track, but
can never consent. The MCP server deliberately has no `authorize_payment`,
`sign_mandate`, `approve_return`, or `confirm_delivery` tool.

## Run

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/uvicorn backend.app.main:app --host 0.0.0.0 --port 8000

# second terminal
cd web && npm install && npm run dev -- --host 0.0.0.0
```

Open `http://localhost:5173/?demo=1`. See [demo.md](demo.md) for the rehearsed
flow. MCP clients connect to `http://localhost:8000/mcp`.

## What is implemented

- Frozen `contracts/` boundary and fixtures.
- FastAPI API, streamable MCP mount, mock merchant catalog and SSE ledger feed.
- PLN integer-grosze catalog: monitors and winter tire sets, with visibly
  filtered 7-day-return and non-refundable alternatives.
- Policy proxy with stable clauses, including revocation and cumulative mandate
  budget. Every pass/block is recorded in the ledger.
- Approval challenge binding: `sha256(canonical_json(body))`; full signing
  assertion goes to the mandate/evidence bundle. `AUTH_MODE=demo_key` is the
  reliable hackathon fallback, using an Ed25519 demo key with the same body
  binding.
- BLIK Lite out-of-band phone page, decline/retry fault, paczkomat notification,
  deterministic wrong-item diff, human-authorized return, refund and evidence
  download.
- React/Vite interface with chat rail, lifecycle ledger, permission-slip
  mandate panel, revoke control and demo controls.

## Demo limitations

The BLIK rail, merchant and refund are local mocks. These are AP2-shaped
mandates and an MPP-shaped payment handshake, not a claim of wire
compatibility. The default signing mode is `demo_key` so the loop is reliable
without an enrolled platform authenticator; the evidence shape remains the
same for a real WebAuthn assertion.
