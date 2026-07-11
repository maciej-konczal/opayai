# MandateLoop demo runbook

Run the API from the repository root:

```bash
uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
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
  uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
```

Use `localhost` for WebAuthn. On mobile, **Zapłać w rozmowie** opens the BLIK
code prompt inside the chat; enter any six digits such as `482913` and confirm.
On desktop, the checkout sheet still exposes a QR/link as a cross-device fallback.

## A — web purchase

1. Submit: `Kup mi zestaw opon zimowych 205/55 R16 do 1600 zł, min. 14 dni na zwrot.`
2. Sign the mandate, observe the 7-day and non-refundable alternatives folded
   under the red policy clause chips, then choose Frostline.
3. Sign the exact cart. Tap **Zapłać w rozmowie**, enter `482913`, and confirm
   the bank-style BLIK prompt without leaving the agent chat.
4. Use **Demo: następny etap** through shipped, paczkomat and picked up.
   The paczkomat notification shows `WAW117M` and `482913`.
5. The agent asks **Zostawiam / Zwracam** in chat. Choose **Zostawiam**, then
   download the evidence bundle from the close-out message.

## B — exception and refund

1. Start a monitor purchase and arm **Wrong item** after payment.
2. Advance to picked up. The deterministic diff produces `ITEM_MISMATCH`.
3. Choose resolution, sign the full return, and advance twice to refund.
4. Download evidence: it contains both signed contexts, the hash-chain,
   expected/observed items, the refund event and agent attribution.

## C — decline and revoke

1. Before confirming BLIK, arm **Decline BLIK**. The first phone confirmation
   fails; use **Spróbuj ponownie** for a fresh BLIK session.
2. Hit **COFNIJ MANDAT**. A later MCP `request_purchase` returns
   `blocked: mandate_not_open`.

## MCP smoke test

Connect an MCP client to the streamable HTTP endpoint at
`http://localhost:8000/mcp`. Its only purchase tool, `request_purchase`,
returns `awaiting_human_authorization`; approval, payment and return consent do
not exist in the MCP surface.

## Single-process package

Once Docker Desktop is running:

```bash
docker build -t mandateloop:demo .
docker run --rm -p 8000:8000 mandateloop:demo
```

Open `http://localhost:8000/?demo=1`; the FastAPI process serves the built React
app, APIs, BLIK page, and MCP endpoint.
