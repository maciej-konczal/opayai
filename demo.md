# MandateLoop demo runbook

Run the API from the repository root:

```bash
uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
```

Run the web app in another terminal:

```bash
cd web && npm install && npm run dev -- --host 0.0.0.0
```

Open `http://localhost:5173/?demo=1`. The backend prints its LAN address for
the BLIK phone-confirmation page.

## A — web purchase

1. Submit: `Kup mi zestaw opon zimowych 205/55 R16 do 1600 zł, min. 14 dni na zwrot.`
2. Sign the mandate, observe the 7-day and non-refundable alternatives folded
   under the red policy clause chips, then choose Frostline.
3. Sign the exact cart. Select BLIK, open its phone URL and confirm it.
4. Use **Demo: następny etap** through shipped, paczkomat and picked up.
   The paczkomat notification shows `WAW117M` and `482913`.
5. Click **Zostawiam produkt**, then download the evidence bundle.

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
