# MandateLoop

MandateLoop gives any MCP-capable agent safe purchasing capability over a
mocked Polish store: intent → human passkey approval → BLIK confirmation →
paczkomat tracking → keep or return → hash-chained evidence bundle.

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

## What is implemented

- Frozen `contracts/` boundary and fixtures.
- FastAPI REST, internal merchant routes, SSE ledger, and streamable HTTP MCP.
- PLN integer-grosze catalog with monitors and winter tire sets.
- Stable policy clauses, revocation, and cumulative per-mandate budget checks.
- Real WebAuthn platform-credential mode plus the reliable Ed25519 `demo_key`
  fallback; both bind approval to `sha256(canonical_json(body))`.
- BLIK Lite phone confirmation with a real QR code, decline/retry fault,
  paczkomat notification, wrong-item diff, signed return, refund, and evidence.
- React/Vite UI with chat rail, lifecycle feed, permission slip, revocation,
  approval sheets, evidence download, and `?demo=1` controls.
- Dockerfile for a single local/deployable process serving the built web app.

## Signing modes

`AUTH_MODE=demo_key` is the default and reliable hackathon fallback. Set
`AUTH_MODE=webauthn` to enroll and authenticate with Touch ID/Windows Hello on
`localhost`; user verification is required. Both modes store the complete
assertion object in the evidence bundle.

## Demo limitations

The BLIK rail, merchant, refund, and notifications are local mocks. These are
AP2-shaped mandates and an MPP-shaped handshake, not a claim of wire
compatibility. There is one demo user and no delegated mode.

## Teammate prototype retained

The original generic implementation remains under `src/opayai/`, including the
notification, profile, webhook, email, and pitch additions merged from `main`.
MandateLoop's contract-safe implementation lives in `backend/` and `web/`; the
older MCP tools are retained for reference and are not mounted at `/mcp`.
