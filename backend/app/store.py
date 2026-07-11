from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import IntentMandate, Purchase


class Store:
    """Single-user memory store with a readable JSON recovery snapshot."""

    def __init__(self, path: Path):
        self.path = path
        self.intents: dict[str, IntentMandate] = {}
        self.purchases: dict[str, Purchase] = {}
        self.signing_contexts: dict[str, dict[str, Any]] = {}
        self.webauthn_credentials: dict[str, dict[str, Any]] = {}
        self.registration_challenge: str | None = None
        self.counter = 0
        if path.exists():
            raw = json.loads(path.read_text())
            self.intents = {key: IntentMandate.model_validate(value) for key, value in raw.get("intents", {}).items()}
            self.purchases = {key: Purchase.model_validate(value) for key, value in raw.get("purchases", {}).items()}
            self.webauthn_credentials = raw.get("webauthn_credentials", {})
            self.counter = raw.get("counter", 0)

    def next_id(self, prefix: str) -> str:
        self.counter += 1
        return f"{prefix}_{self.counter:04d}"

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "intents": {key: value.model_dump(mode="json") for key, value in self.intents.items()},
            "purchases": {key: value.model_dump(mode="json") for key, value in self.purchases.items()},
            "webauthn_credentials": self.webauthn_credentials,
            "counter": self.counter,
        }
        self.path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))

    def reset(self) -> None:
        self.intents.clear()
        self.purchases.clear()
        self.signing_contexts.clear()
        self.webauthn_credentials.clear()
        self.registration_challenge = None
        self.counter = 0
        self.save()
