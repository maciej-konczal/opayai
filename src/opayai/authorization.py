"""Signed, expiring evidence for demo approval and step-up gates.

The MCP demo still simulates the trusted user surface. These proof objects make
the backend gate explicit and bind authorization to one immutable cart, amount,
currency, purpose, and expiry. A production trusted surface would issue the
same shape after a real user gesture/WebAuthn ceremony.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
import json
import secrets
from opayai.signing import default_signer
from opayai.types import CartMandate


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _payload_bytes(proof: dict) -> bytes:
    unsigned = {k: v for k, v in proof.items() if k != "signature"}
    return json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()


def issue(kind: str, cart: CartMandate, ttl_minutes: int = 5,
          now: datetime | None = None) -> dict:
    if kind not in {"approval", "step_up"}:
        raise ValueError("unsupported authorization kind")
    now = now or _now()
    proof = {
        "id": "auth_" + secrets.token_hex(8),
        "kind": kind,
        "cart_id": cart.id,
        "intent_id": cart.intent_mandate_id,
        "amount": str(cart.total.amount),
        "currency": cart.total.currency,
        "issued_at": now.isoformat(),
        "expires_at": (now + timedelta(minutes=ttl_minutes)).isoformat(),
        "nonce": secrets.token_hex(16),
    }
    proof["signature"] = default_signer().sign_bytes(_payload_bytes(proof))
    return proof


def verify(proof: dict | None, kind: str, cart: CartMandate,
           now: datetime | None = None) -> bool:
    if not proof:
        return False
    now = now or _now()
    expected = (
        proof.get("kind") == kind
        and proof.get("cart_id") == cart.id
        and proof.get("intent_id") == cart.intent_mandate_id
        and proof.get("amount") == str(cart.total.amount)
        and proof.get("currency") == cart.total.currency
    )
    if not expected:
        return False
    try:
        expires = datetime.fromisoformat(proof["expires_at"])
        signature_ok = default_signer().verify_bytes(
            _payload_bytes(proof), proof["signature"])
        return signature_ok and now <= expires
    except (KeyError, TypeError, ValueError):
        return False
