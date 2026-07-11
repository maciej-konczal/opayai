from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timezone
from nacl.signing import SigningKey

_DEMO_KEY = SigningKey(bytes.fromhex("192837465564738291aabbccddeeff00192837465564738291aabbccddeeff00"))


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def challenge_for(body: object) -> bytes:
    return hashlib.sha256(canonical_json(body).encode()).digest()


def challenge_b64(body: object) -> str:
    return base64.urlsafe_b64encode(challenge_for(body)).rstrip(b"=").decode()


def demo_assertion(body: object) -> str:
    signature = _DEMO_KEY.sign(challenge_for(body)).signature
    return base64.b64encode(signature).decode()


def verify_demo_assertion(body: object, assertion_b64: str) -> bool:
    try:
        _DEMO_KEY.verify_key.verify(challenge_for(body), base64.b64decode(assertion_b64))
        return True
    except Exception:
        return False
