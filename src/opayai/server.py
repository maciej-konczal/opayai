from __future__ import annotations
import json
import os
import sys
from decimal import Decimal
from mcp.server.fastmcp import FastMCP
from opayai.types import Constraint, Money, SpendingLimit
from opayai import mandate as mandate_mod
from opayai import data, rails as rails_mod
from opayai.mandate import create_intent_mandate as _create_intent, propose_cart as _propose
from opayai.policy import evaluate_policy as _evaluate
from opayai.orders import store as order_store
from opayai.events import bus
from opayai import stepup, recommend, notify, channels

app = FastMCP("opayai-mcp")

SESSION: dict = {}


def reset_session() -> None:
    SESSION.clear()
    SESSION.update({"intents": {}, "carts": {}, "offers": {}, "decisions": {},
                    "approved": set(), "stepped_up": set(), "paid": {},
                    "period_spent": Decimal("0")})
    mandate_mod.reset_ids()
    rails_mod.reset_rail_ids()


reset_session()


@app.tool()
def search_offers(category: str | None = None, max_price: str | None = None) -> list[dict]:
    """Search the catalog for agent-readable offers.

    Returns structured offers (price, stock, delivery date, return policy, specs,
    rating) the agent can reason over. Call this after create_intent_mandate to
    find candidate products. `max_price` is a decimal string (e.g. "300").
    """
    mp = Decimal(max_price) if max_price is not None else None
    offers = data.search_offers(category=category, max_price=mp)
    for o in offers:
        SESSION["offers"][o.id] = o
    return [o.model_dump(mode="json") for o in offers]


@app.tool()
def create_intent_mandate(user_id: str, category: str, max_total: str,
                          hard_requirements: list[str], per_transaction: str,
                          per_period: str, step_up_threshold: str | None = None) -> dict:
    """Create and sign the user's Intent Mandate: what the agent is authorized to buy.

    Call this FIRST, before any other tool. It encodes the user's constraints and
    spending limits and is cryptographically signed. `hard_requirements` use the
    tokens "free_returns", "compat:<tag>" (e.g. "compat:macbook"), and
    "arrives_by:YYYY-MM-DD". `max_total`, `per_transaction`, `per_period` are
    decimal strings. `step_up_threshold` (optional decimal string): carts at or
    above it need a fresh passkey authorization (call authorize_step_up before
    execute_payment). Returns the signed mandate; use its `id` in later calls.
    """
    threshold = Money(amount=Decimal(step_up_threshold)) if step_up_threshold else None
    im = _create_intent(
        user_id,
        Constraint(max_total=Money(amount=Decimal(max_total)), category=category,
                   hard_requirements=hard_requirements),
        SpendingLimit(per_transaction=Money(amount=Decimal(per_transaction)),
                      per_period=Money(amount=Decimal(per_period)),
                      step_up_threshold=threshold))
    SESSION["intents"][im.id] = im
    return im.model_dump(mode="json")


@app.tool()
def suggest_offers(intent_id: str, limit: int = 3) -> list[dict]:
    """Return a ranked shortlist of candidate offers for an intent, with reasons.

    Each item has qualifies (bool) and match_reason (why it fits, or why not -
    over budget / out of stock / missing free returns / not compatible). Present
    this list to the user and let them pick which offer_id to buy BEFORE calling
    propose_cart. This does not purchase anything. Searches the whole category
    (including over-budget/out-of-stock options) so the user sees the tradeoffs.
    """
    intent = SESSION["intents"][intent_id]
    offers = data.search_offers(category=intent.constraint.category)
    for o in offers:
        SESSION["offers"][o.id] = o
    shortlist = recommend.suggest([o.model_dump(mode="json") for o in offers],
                                  intent.constraint, limit)
    bus.publish("suggestions.ready", "agent",
                {"count": len(shortlist),
                 "qualifying": sum(1 for s in shortlist if s["qualifies"])},
                mandate_ref=intent_id)
    return shortlist


@app.tool()
def propose_cart(intent_id: str, offer_ids: list[str], rail: str, rationale: str) -> dict:
    """Build and sign a Cart Mandate: the specific offers the agent wants to buy.

    Call after search_offers, once you have chosen offer_ids that satisfy the
    intent's hard requirements and budget. `rail` is the payment rail: "ap2" or
    "card". `rationale` is a short human-readable reason shown to the user. The
    cart MUST be checked with evaluate_policy before execute_payment.
    """
    intent = SESSION["intents"][intent_id]
    offers = [SESSION["offers"][oid] for oid in offer_ids]
    cart = _propose(intent, offers, rail=rail, rationale=rationale)
    SESSION["carts"][cart.id] = cart
    return cart.model_dump(mode="json")


@app.tool()
def evaluate_policy(cart_id: str) -> dict:
    """Check a proposed cart against its intent mandate and spending limits.

    Returns a decision: "AUTO_APPROVE" (safe to pay), "ESCALATE" (needs user
    approval via request_approval), or "REJECT" (a hard rule failed), plus a
    per-rule breakdown. You MUST call this before execute_payment.
    """
    cart = SESSION["carts"][cart_id]
    intent = SESSION["intents"][cart.intent_mandate_id]
    dec = _evaluate(intent, cart, SESSION["offers"], period_spent=SESSION["period_spent"])
    SESSION["decisions"][cart_id] = dec
    return dec.model_dump(mode="json")


@app.tool()
def request_approval(cart_id: str, approved: bool) -> dict:
    """Record the user's approval decision for an escalated cart.

    Call this only when evaluate_policy returned "ESCALATE", after you have asked
    the user. execute_payment will refuse an escalated cart until approved=true
    has been recorded here.
    """
    if approved:
        SESSION["approved"].add(cart_id)
    bus.publish("approval.recorded", "user", {"cart_id": cart_id, "approved": approved},
                mandate_ref=SESSION["carts"][cart_id].intent_mandate_id)
    return {"cart_id": cart_id, "approved": approved}


@app.tool()
def authorize_step_up(cart_id: str) -> dict:
    """Run the human-present passkey ceremony for a cart that requires step-up.

    Call this when evaluate_policy returned step_up_required=true, before
    execute_payment. Simulates the user's registered device (passkey) signing a
    fresh challenge bound to this cart and amount, and verifies it. Returns
    {authorized, device_pubkey}. execute_payment stays refused until this succeeds.
    """
    cart = SESSION["carts"][cart_id]
    res = stepup.authorize(cart_id, str(cart.total.amount), cart.intent_mandate_id)
    if res["authorized"]:
        SESSION["stepped_up"].add(cart_id)
    return res


@app.tool()
def execute_payment(cart_id: str) -> dict:
    """Charge the selected rail for an approved cart and create the order.

    Only succeeds when the policy decision is AUTO_APPROVE, or an ESCALATE that
    has a recorded approval. If the decision is step_up_required, a successful
    authorize_step_up (passkey) is also required. Refuses REJECTs, unapproved
    escalations, missing step-up, and a repeat payment of the same cart
    (idempotency guard). Returns the created order (status PAID) with its receipt
    and a `status_url` the user can click to view live order status - surface that
    link to the user.
    """
    cart = SESSION["carts"][cart_id]
    if cart_id in SESSION["paid"]:
        raise ValueError("cart already paid")
    dec = SESSION["decisions"].get(cart_id)
    if dec is None:
        raise ValueError("evaluate_policy must run before payment")
    if dec.result == "REJECT":
        raise ValueError("policy rejected this cart")
    if dec.result == "ESCALATE" and cart_id not in SESSION["approved"]:
        raise ValueError("cart requires user approval before payment")
    if dec.step_up_required and cart_id not in SESSION["stepped_up"]:
        raise ValueError("cart requires passkey step-up authorization before payment")
    receipt = rails_mod.get_rail(cart.selected_rail).charge(cart)
    order = order_store.create(cart, receipt)
    SESSION["paid"][cart_id] = order.id
    SESSION["period_spent"] += cart.total.amount
    d = order.model_dump(mode="json")
    d["status_url"] = f"{_web_base()}/order/{order.id}"
    return d


@app.tool()
def advance_order(order_id: str) -> dict:
    """Advance an order's fulfillment state: PAID -> SHIPPED -> DELIVERED.

    Simulates and records fulfillment progress. Call twice to reach DELIVERED
    (required before create_return).
    """
    return order_store.advance(order_id).model_dump(mode="json")


@app.tool()
def get_order(order_id: str) -> dict:
    """Fetch the current status and event timeline of an order by id.

    Includes `status_url`, a link the user can open to see live order status.
    """
    d = order_store.get(order_id).model_dump(mode="json")
    d["status_url"] = f"{_web_base()}/order/{order_id}"
    return d


@app.tool()
def cancel_order(order_id: str) -> dict:
    """Cancel an order before it ships (allowed from CREATED or PAID only)."""
    return order_store.cancel(order_id).model_dump(mode="json")


@app.tool()
def create_return(order_id: str, reason: str, returns_window_days: int = 30) -> dict:
    """Request a return for a DELIVERED order within its returns window.

    This is the post-purchase "resolve" step. Fails if the order is not delivered
    or the return window has passed.
    """
    return order_store.request_return(order_id, reason, returns_window_days).model_dump(mode="json")


@app.tool()
def get_audit_trail(mandate_ref: str | None = None) -> list[dict]:
    """Return the full signed audit trail for a mandate (pass the intent id).

    Every event - intent, cart, policy decision, approval, payment, and the whole
    order lifecycle through returns - is included in order. This is the receipt of
    exactly what the user agreed to and what happened. Omit mandate_ref for all
    events.
    """
    return [e.model_dump(mode="json") for e in bus.trail(mandate_ref)]


@app.tool()
def get_notifications(mandate_ref: str | None = None) -> list[dict]:
    """Proactive, user-facing notifications derived from the event stream.

    Each has needs_action (bool) and level ("action_required" | "update"). Surface
    the needs_action items FIRST and tell the user - these are the moments the
    agent needs input, approval, a passkey, or a decision (which option to buy).
    The rest are progress updates (payment, shipped, delivered, return).
    """
    events = [e.model_dump(mode="json") for e in bus.trail(mandate_ref)]
    return notify.notifications(events)


def _web_base() -> str:
    return os.environ.get("OPAYAI_WEB_BASE", "http://localhost:8000")


def _event_log_path() -> str:
    return os.environ.get("OPAYAI_EVENT_LOG", os.path.expanduser("~/.opayai/events.jsonl"))


def _install_event_logging() -> None:
    """Mirror every event to a tail-able JSONL file and to stderr (host log panel).

    Wired only when serving (run), so tests and in-process use stay side-effect free.
    """
    path = _event_log_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)

    def _sink(event) -> None:
        try:
            with open(path, "a") as f:
                f.write(json.dumps(event.model_dump(mode="json")) + "\n")
        except OSError:
            pass
        print(f"[opayai] #{event.seq} {event.type} {event.actor} {event.payload}",
              file=sys.stderr, flush=True)

    bus.subscribe(_sink)


def _install_notifications() -> None:
    """Deliver a proactive ping to every enabled channel when action is needed.

    The "pings you only when it needs input, approval, or a decision" behavior.
    Channels (desktop / webhook / email) are env-driven; see opayai.channels.
    """
    active = channels.enabled_channels()

    def _sink(event) -> None:
        n = notify.notification_for(event.model_dump(mode="json"))
        if not n or not n["needs_action"]:
            return
        print(f"[opayai] ACTION NEEDED: {n['title']} - {n['body']}", file=sys.stderr, flush=True)
        channels.deliver(n, active)

    bus.subscribe(_sink)


def run() -> None:
    _install_event_logging()
    _install_notifications()
    app.run()


if __name__ == "__main__":
    run()
