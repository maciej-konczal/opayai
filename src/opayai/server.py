from __future__ import annotations
from decimal import Decimal
from mcp.server.fastmcp import FastMCP
from opayai.types import Constraint, Money, SpendingLimit
from opayai import mandate as mandate_mod
from opayai import data, rails as rails_mod
from opayai.mandate import create_intent_mandate as _create_intent, propose_cart as _propose
from opayai.policy import evaluate_policy as _evaluate
from opayai.orders import store as order_store
from opayai.events import bus

app = FastMCP("opayai-mcp")

SESSION: dict = {}


def reset_session() -> None:
    SESSION.clear()
    SESSION.update({"intents": {}, "carts": {}, "offers": {}, "decisions": {},
                    "approved": set(), "period_spent": Decimal("0")})
    mandate_mod.reset_ids()
    rails_mod.reset_rail_ids()


reset_session()


@app.tool()
def search_offers(category: str | None = None, max_price: str | None = None) -> list[dict]:
    mp = Decimal(max_price) if max_price is not None else None
    offers = data.search_offers(category=category, max_price=mp)
    for o in offers:
        SESSION["offers"][o.id] = o
    return [o.model_dump(mode="json") for o in offers]


@app.tool()
def create_intent_mandate(user_id: str, category: str, max_total: str,
                          hard_requirements: list[str], per_transaction: str,
                          per_period: str) -> dict:
    im = _create_intent(
        user_id,
        Constraint(max_total=Money(amount=Decimal(max_total)), category=category,
                   hard_requirements=hard_requirements),
        SpendingLimit(per_transaction=Money(amount=Decimal(per_transaction)),
                      per_period=Money(amount=Decimal(per_period))))
    SESSION["intents"][im.id] = im
    return im.model_dump(mode="json")


@app.tool()
def propose_cart(intent_id: str, offer_ids: list[str], rail: str, rationale: str) -> dict:
    intent = SESSION["intents"][intent_id]
    offers = [SESSION["offers"][oid] for oid in offer_ids]
    cart = _propose(intent, offers, rail=rail, rationale=rationale)
    SESSION["carts"][cart.id] = cart
    return cart.model_dump(mode="json")


@app.tool()
def evaluate_policy(cart_id: str) -> dict:
    cart = SESSION["carts"][cart_id]
    intent = SESSION["intents"][cart.intent_mandate_id]
    dec = _evaluate(intent, cart, SESSION["offers"], period_spent=SESSION["period_spent"])
    SESSION["decisions"][cart_id] = dec
    return dec.model_dump(mode="json")


@app.tool()
def request_approval(cart_id: str, approved: bool) -> dict:
    if approved:
        SESSION["approved"].add(cart_id)
    bus.publish("approval.recorded", "user", {"cart_id": cart_id, "approved": approved},
                mandate_ref=SESSION["carts"][cart_id].intent_mandate_id)
    return {"cart_id": cart_id, "approved": approved}


@app.tool()
def execute_payment(cart_id: str) -> dict:
    cart = SESSION["carts"][cart_id]
    dec = SESSION["decisions"].get(cart_id)
    if dec is None:
        raise ValueError("evaluate_policy must run before payment")
    if dec.result == "REJECT":
        raise ValueError("policy rejected this cart")
    if dec.result == "ESCALATE" and cart_id not in SESSION["approved"]:
        raise ValueError("cart requires user approval before payment")
    receipt = rails_mod.get_rail(cart.selected_rail).charge(cart)
    order = order_store.create(cart, receipt)
    SESSION["period_spent"] += cart.total.amount
    return order.model_dump(mode="json")


@app.tool()
def advance_order(order_id: str) -> dict:
    return order_store.advance(order_id).model_dump(mode="json")


@app.tool()
def get_order(order_id: str) -> dict:
    return order_store.get(order_id).model_dump(mode="json")


@app.tool()
def cancel_order(order_id: str) -> dict:
    return order_store.cancel(order_id).model_dump(mode="json")


@app.tool()
def create_return(order_id: str, reason: str, returns_window_days: int = 30) -> dict:
    return order_store.request_return(order_id, reason, returns_window_days).model_dump(mode="json")


@app.tool()
def get_audit_trail(mandate_ref: str | None = None) -> list[dict]:
    return [e.model_dump(mode="json") for e in bus.trail(mandate_ref)]


def run() -> None:
    app.run()


if __name__ == "__main__":
    run()
