# HTTP contract notes

## Signing

`POST /api/webauthn/register/options` returns either:

- `{auth_mode:"demo_key", credential_id}`; or
- `{auth_mode:"webauthn", options: PublicKeyCredentialCreationOptionsJSON}`.

`POST /api/webauthn/register/verify` accepts `{credential}` and persists the
verified credential public key and sign counter.

`POST /api/webauthn/auth/options` accepts
`{context_id, context_type:"intent"|"cart"|"resolution"}`. WebAuthn options use
`challenge = sha256(canonical_json(context_body))` and require user verification.
The verification endpoint accepts the full `{assertion}` object and stores that
whole assertion, base64-encoded, in the signing record.

## Internal merchant

- `POST /merchant/checkout/proposal {intent_id,line_items,agent_id}`
- `POST /merchant/checkout/confirm {purchase_id}`
- `GET /merchant/orders/{order_id}`
- `POST /merchant/orders/{order_id}/returns {purchase_id,reason}`
- `POST /merchant/orders/{order_id}/refund {purchase_id}`

All write routes call the policy proxy. Confirmation additionally requires a
verified cart signature, unchanged proposal totals, and a succeeded payment.
Return and refund require a human-signed resolution and the matching order state.
