from __future__ import annotations
import json
from decimal import Decimal
from importlib import resources
from opayai.types import Offer


def _read(name: str):
    return json.loads(resources.files("opayai.data").joinpath(name).read_text())


def load_offers() -> list[Offer]:
    return [Offer.model_validate(o) for o in _read("offers.json")]


def search_offers(category: str | None = None, max_price: Decimal | None = None) -> list[Offer]:
    out = load_offers()
    if category:
        out = [o for o in out if o.specs.get("category") == category]
    if max_price is not None:
        out = [o for o in out if o.price.amount <= max_price]
    return out


def load_persona() -> dict:
    return _read("persona.json")


def load_conversations() -> list[dict]:
    return _read("conversations.json")


def load_seed_orders() -> list[dict]:
    return _read("orders.json")
