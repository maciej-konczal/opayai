from __future__ import annotations
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
                    period_spent: Decimal = Decimal("0")) -> PolicyDecision:
    checks: list[PolicyCheck] = []
    result = "AUTO_APPROVE"

    sig_ok = (default_signer().verify(intent, intent.signature)
              and default_signer().verify(cart, cart.signature))
    checks.append(PolicyCheck(rule="signature", passed=sig_ok,
                              detail="mandates verify" if sig_ok else "signature invalid"))
    if not sig_ok:
        result = "REJECT"

    offers = [offers_by_id[i.offer_id] for i in cart.items]
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

    dec = PolicyDecision(cart_mandate_id=cart.id, result=result, checks=checks)
    bus.publish("policy.evaluated", "policy",
                {"result": result, "checks": [c.model_dump() for c in checks]},
                mandate_ref=intent.id)
    return dec
