from __future__ import annotations
from datetime import datetime, timezone
from decimal import Decimal
from opayai.types import IntentMandate, CartMandate, Offer, PolicyCheck, PolicyDecision
from opayai.signing import default_signer
from opayai.events import bus


def _check_hard_requirement(req: str, offers: list[Offer]) -> PolicyCheck:
    if req == "free_returns":
        ok = all(o.free_returns for o in offers)
        return PolicyCheck(rule="hard_requirement:free_returns", passed=ok,
                           detail="all items free returns" if ok else "an item lacks free returns")
    if req.startswith("compat:"):
        tag = req.split(":", 1)[1]
        ok = all(tag in o.specs.get("compat", []) for o in offers)
        return PolicyCheck(rule=f"hard_requirement:{req}", passed=ok,
                           detail=f"compat {tag}: {'ok' if ok else 'missing'}")
    if req.startswith("arrives_by:"):
        deadline = req.split(":", 1)[1]
        ok = all(o.delivery_est_date <= deadline for o in offers)
        return PolicyCheck(rule=f"hard_requirement:{req}", passed=ok,
                           detail=f"delivery by {deadline}: {'ok' if ok else 'too late'}")
    return PolicyCheck(rule=f"hard_requirement:{req}", passed=False,
                       detail="unknown requirement, rejected (fail-closed)")


def evaluate_policy(intent: IntentMandate, cart: CartMandate,
                    offers_by_id: dict[str, Offer],
                    period_spent: Decimal = Decimal("0"),
                    now: datetime | None = None,
                    publish: bool = True) -> PolicyDecision:
    checks: list[PolicyCheck] = []
    result = "AUTO_APPROVE"

    sig_ok = (default_signer().verify(intent, intent.signature)
              and default_signer().verify(cart, cart.signature))
    checks.append(PolicyCheck(rule="signature", passed=sig_ok,
                              detail="mandates verify" if sig_ok else "signature invalid"))
    if not sig_ok:
        result = "REJECT"

    now = now or datetime.now(timezone.utc)
    expires = intent.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    expiry_ok = now <= expires
    checks.append(PolicyCheck(rule="intent_expiry", passed=expiry_ok,
                              detail="intent active" if expiry_ok else "intent expired"))
    if not expiry_ok:
        result = "REJECT"

    nonempty = bool(cart.items)
    checks.append(PolicyCheck(rule="cart_nonempty", passed=nonempty,
                              detail="cart has items" if nonempty else "cart is empty"))
    if not nonempty:
        result = "REJECT"

    offers = [offers_by_id[i.offer_id] for i in cart.items]
    stock_ok = all(o.stock_available and o.stock_qty >= item.qty
                   for item, o in zip(cart.items, offers))
    checks.append(PolicyCheck(rule="stock", passed=stock_ok,
                              detail="stock available" if stock_ok else "insufficient stock"))
    if not stock_ok:
        result = "REJECT"

    category_ok = all(o.specs.get("category") == intent.constraint.category for o in offers)
    checks.append(PolicyCheck(rule="category", passed=category_ok,
                              detail="category matches" if category_ok else "category mismatch"))
    if not category_ok:
        result = "REJECT"

    currencies = {intent.constraint.max_total.currency,
                  intent.spending_limit.per_transaction.currency,
                  intent.spending_limit.per_period.currency,
                  cart.total.currency, *(o.price.currency for o in offers)}
    if intent.spending_limit.step_up_threshold is not None:
        currencies.add(intent.spending_limit.step_up_threshold.currency)
    currency_ok = len(currencies) == 1
    checks.append(PolicyCheck(rule="currency", passed=currency_ok,
                              detail="currency consistent" if currency_ok else "currency mismatch"))
    if not currency_ok:
        result = "REJECT"

    expected_total = sum(
        (item.unit_price.amount * item.qty for item in cart.items), Decimal("0"))
    prices_ok = all(item.unit_price == offer.price for item, offer in zip(cart.items, offers))
    total_ok = prices_ok and cart.total.amount == expected_total
    checks.append(PolicyCheck(rule="cart_total", passed=total_ok,
                              detail=f"total {cart.total.amount} verified" if total_ok
                              else f"expected {expected_total}"))
    if not total_ok:
        result = "REJECT"

    rail_ok = cart.selected_rail in {"ap2", "card"}
    checks.append(PolicyCheck(rule="payment_rail", passed=rail_ok,
                              detail="rail supported" if rail_ok else "unsupported rail"))
    if not rail_ok:
        result = "REJECT"
    for req in intent.constraint.hard_requirements:
        c = _check_hard_requirement(req, offers)
        checks.append(c)
        if not c.passed:
            result = "REJECT"

    budget_ok = cart.total.amount <= intent.constraint.max_total.amount
    checks.append(PolicyCheck(rule="budget", passed=budget_ok,
                              detail=f"{cart.total.amount} <= {intent.constraint.max_total.amount}"))
    if not budget_ok:
        result = "REJECT"

    txn_ok = cart.total.amount <= intent.spending_limit.per_transaction.amount
    checks.append(PolicyCheck(rule="spending_limit:per_transaction", passed=txn_ok,
                              detail=f"{cart.total.amount} <= {intent.spending_limit.per_transaction.amount}"))
    period_ok = period_spent + cart.total.amount <= intent.spending_limit.per_period.amount
    checks.append(PolicyCheck(rule="spending_limit:per_period", passed=period_ok,
                              detail=f"{period_spent}+{cart.total.amount} <= {intent.spending_limit.per_period.amount}"))
    if result != "REJECT" and not (txn_ok and period_ok):
        result = "ESCALATE"

    threshold = intent.spending_limit.step_up_threshold
    step_up_required = threshold is not None and cart.total.amount >= threshold.amount
    if threshold is not None:
        checks.append(PolicyCheck(
            rule="step_up", passed=True,
            detail=(f"{cart.total.amount} >= {threshold.amount}: passkey required"
                    if step_up_required else f"{cart.total.amount} < {threshold.amount}: no step-up")))

    dec = PolicyDecision(cart_mandate_id=cart.id, result=result, checks=checks,
                         step_up_required=step_up_required)
    if publish:
        bus.publish("policy.evaluated", "policy",
                    {"result": result, "step_up_required": step_up_required,
                     "checks": [c.model_dump() for c in checks]},
                    mandate_ref=intent.id)
    return dec
