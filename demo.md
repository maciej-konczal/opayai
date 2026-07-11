# OPayAI demo runbook

Run the API from the repository root:

```bash
uvicorn opayai.server:create_app --factory --host 0.0.0.0 --port 8000
```

Run the web app in another terminal:

```bash
cd web && npm install && npm run dev -- --host 0.0.0.0
```

Open `http://localhost:5173/?demo=1` in a narrow/mobile viewport. The primary
demo is one continuous agent conversation; the desktop three-panel evidence
view remains available for judges who want to inspect internals.

The default `AUTH_MODE=demo_key` is the deterministic fallback. To rehearse
Touch ID/Windows Hello, start the backend with:

```bash
AUTH_MODE=webauthn WEBAUTHN_ORIGIN=http://localhost:5173 \
  uvicorn opayai.server:create_app --factory --host 0.0.0.0 --port 8000
```

Use `localhost` for WebAuthn. On mobile, **Pay in chat** opens the BLIK
code prompt inside the chat; enter any six digits such as `482913` and confirm.
On desktop, the checkout sheet still exposes a QR/link as a cross-device fallback.

## A — web purchase

1. Submit: `Buy me a set of 205/55 R16 winter tires under PLN 1,600 with at least 14-day returns.`
2. Sign the mandate, observe the 7-day and non-refundable alternatives folded
   under the red policy clause chips, then choose Frostline.
3. Sign the exact cart. Tap **Pay in chat**, enter `482913`, and confirm
   the bank-style BLIK prompt without leaving the agent chat.
4. Use **Demo: next stage** through shipped, parcel locker and picked up.
   The parcel-locker notification shows `WAW117M` and `482913`.
5. The agent asks **Keep it / Return it** in chat. Choose **Keep it**, then
   download the evidence bundle from the close-out message.

## B — exception and refund

1. Start a monitor purchase and arm **Wrong item** after payment.
2. Advance to picked up. The deterministic diff produces `ITEM_MISMATCH`.
3. Choose resolution, sign the full return, and advance twice to refund.
4. Download evidence: it contains both signed contexts, the hash-chain,
   expected/observed items, the refund event and agent attribution.

## C — decline and revoke

1. Before confirming BLIK, arm **Decline BLIK**. The first phone confirmation
   fails; use **Try again** for a fresh BLIK session.
2. Hit **REVOKE MANDATE**. A later MCP `propose_cart` returns
   `blocked: mandate_not_open`.

## MCP smoke test

Connect an MCP client to the streamable HTTP endpoint at
`http://localhost:8000/mcp`. `propose_cart` and `create_return` only return
proposals or `awaiting_human_authorization`; approval, signing, payment,
fulfillment advancement, and return consent do not exist in the MCP surface.

## Single-process package

Once Docker Desktop is running:

```bash
docker build -t opayai:demo .
docker run --rm -p 8000:8000 opayai:demo
```

Open `http://localhost:8000/?demo=1`; the FastAPI process serves the built React
app, APIs, BLIK page, and MCP endpoint.
