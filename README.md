# MandateLoop

MandateLoop gives any MCP-capable agent safe purchasing capability over a
mocked Polish store, with mobile chat as the primary human surface:

intent → human approval → in-chat BLIK → tracking → keep or return → evidence.

The agent may propose and track, but it can never consent. The MandateLoop MCP
server deliberately has no `authorize_payment`, `sign_mandate`,
`approve_return`, or `confirm_delivery` tool.

## Run locally

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/uvicorn backend.app.main:app --host 0.0.0.0 --port 8000

# second terminal
cd web
npm install
npm run dev -- --host 0.0.0.0
```

Open `http://localhost:5173/?demo=1`. See [demo.md](demo.md) for the rehearsed
flows. MCP clients connect to `http://localhost:8000/mcp`.

## Implemented

- Frozen `contracts/` boundary and fixtures.
- FastAPI REST, policy-checked merchant routes, SSE ledger, and streamable MCP.
- PLN catalog with monitors and winter tires, including visibly filtered offers.
- Stable policy clauses, revocation, and cumulative per-mandate budgets.
- Real WebAuthn plus the reliable Ed25519 `demo_key` fallback; both bind approval
  to `sha256(canonical_json(body))`.
- Mobile chat from request through product choice, exact-cart approval, in-chat
  BLIK, paczkomat tracking, keep/return, exception resolution, refund, and evidence.
- Desktop audit view with QR/link as a cross-device fallback.
- Hash-chained ledger and downloadable evidence bundle.
- Dockerfile for a single process serving the built React app and backend.

## Signing modes

`AUTH_MODE=demo_key` is the default hackathon mode. Set `AUTH_MODE=webauthn` to
use Touch ID/Windows Hello on `localhost`; user verification is required. Both
modes store the complete assertion in the evidence bundle.

## Demo limitations

BLIK, merchant fulfillment, refunds, and notification delivery are local mocks.
These are AP2-shaped mandates and an MPP-shaped handshake, not a claim of wire
compatibility. There is one demo user and no delegated mode.

## Teammate prototype retained

The generic prototype remains under `src/opayai/`. The latest `main` additions
are merged here: agents present options and wait by default, Cursor receives the
same rule, and webhook subscribers receive the full event feed with action-needed
notifications. Those legacy tools are not mounted at MandateLoop's `/mcp`;
MandateLoop's contract-safe implementation lives in `backend/` and `web/`.
