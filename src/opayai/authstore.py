"""File-backed shared store for cross-process authorization.

The MCP server and the web status site are separate processes. When a purchase
needs a human authorization (approval or passkey step-up), the server writes a
PENDING request here; the web page (the trusted surface) is where the user
authorizes, writing a signed PROOF here; the server reads the proof back at
payment time. The agent cannot write proofs - only the human, via the web page.

Location: OPAYAI_AUTH_STORE, or a `opayai-auth` dir next to the event log.
"""
from __future__ import annotations
import json
import os


def store_dir() -> str:
    base = os.environ.get("OPAYAI_AUTH_STORE")
    if base:
        return base
    log = os.environ.get("OPAYAI_EVENT_LOG", os.path.expanduser("~/.opayai/events.jsonl"))
    return os.path.join(os.path.dirname(log) or ".", "opayai-auth")


def _path(prefix: str, cart_id: str, kind: str) -> str:
    return os.path.join(store_dir(), f"{prefix}-{cart_id}-{kind}.json")


def _read(path: str) -> dict | None:
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def write_pending(cart_id: str, kind: str, amount: str, currency: str, intent_id: str) -> None:
    os.makedirs(store_dir(), exist_ok=True)
    with open(_path("pending", cart_id, kind), "w") as f:
        json.dump({"cart_id": cart_id, "kind": kind, "amount": amount,
                   "currency": currency, "intent_id": intent_id}, f)


def read_pending(cart_id: str, kind: str) -> dict | None:
    return _read(_path("pending", cart_id, kind))


def list_pending() -> list[dict]:
    """Pending requests that have not been authorized yet."""
    d = store_dir()
    out: list[dict] = []
    if not os.path.isdir(d):
        return out
    for name in sorted(os.listdir(d)):
        if name.startswith("pending-") and name.endswith(".json"):
            req = _read(os.path.join(d, name))
            if req and not has_proof(req["cart_id"], req["kind"]):
                out.append(req)
    return out


def has_proof(cart_id: str, kind: str) -> bool:
    return os.path.exists(_path("proof", cart_id, kind))


def write_proof(proof: dict) -> None:
    os.makedirs(store_dir(), exist_ok=True)
    with open(_path("proof", proof["cart_id"], proof["kind"]), "w") as f:
        json.dump(proof, f)


def read_proof(cart_id: str, kind: str) -> dict | None:
    return _read(_path("proof", cart_id, kind))
