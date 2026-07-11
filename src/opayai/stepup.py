"""Simulated trusted-surface step-up authorization (passkey-style).

For carts at or above the intent's step_up_threshold, the pre-signed Intent
Mandate is not enough - the user must authorize this specific purchase with a
fresh, challenge-bound signature from their registered device credential
(passkey). In the offline demo we simulate both the device (signs the challenge) and the relying
party (verifies against the registered device public key). The signature is bound
to the cart id and amount, so it cannot be replayed for a different purchase.
"""
from __future__ import annotations
import secrets
from opayai.signing import device_signer
from opayai.events import bus


def challenge(cart_id: str, amount: str, nonce: str) -> bytes:
    return f"opayai-stepup|{cart_id}|{amount}|{nonce}".encode()


def authorize(cart_id: str, amount: str, intent_ref: str) -> dict:
    """Run the passkey ceremony for one cart and record the result on the audit trail.

    Returns {authorized, device_pubkey, nonce}. `authorized` is True only when the
    device signature verifies against the registered device key.
    """
    nonce = secrets.token_hex(8)
    dev = device_signer()
    payload = challenge(cart_id, amount, nonce)
    sig = dev.sign_bytes(payload)             # the device (passkey) signs
    ok = dev.verify_bytes(payload, sig)       # relying party verifies vs registered key
    bus.publish("stepup.authorized", "user",
                {"cart_id": cart_id, "amount": amount,
                 "device": "passkey:" + dev.verify_key_hex[:12],
                 "nonce": nonce, "verified": ok, "signature": sig[:16] + "..."},
                mandate_ref=intent_ref)
    return {"cart_id": cart_id, "authorized": ok, "device_pubkey": dev.verify_key_hex,
            "nonce": nonce}
