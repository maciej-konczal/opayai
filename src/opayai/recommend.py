"""Rank candidate offers against an intent's constraint, with match reasons.

Pure logic (offers as dicts, as search_offers returns them) so it is easy to
test and is the single source of truth for "does this offer qualify" - shared by
the suggest_offers tool and the CLI's auto-pick. Uses the same hard-requirement
grammar as the policy engine (free_returns, compat:<tag>, arrives_by:YYYY-MM-DD).
"""
from __future__ import annotations
from decimal import Decimal
from opayai.types import Constraint


def disqualifiers(offer: dict, constraint: Constraint) -> list[str]:
    """Reasons this offer does not satisfy the constraint; empty list => qualifies."""
    reasons: list[str] = []
    reqs = constraint.hard_requirements
    if "free_returns" in reqs and not offer["free_returns"]:
        reasons.append("no free returns")
    for r in reqs:
        if r.startswith("compat:"):
            tag = r.split(":", 1)[1]
            if tag not in offer["specs"].get("compat", []):
                reasons.append(f"not {tag}-compatible")
        elif r.startswith("arrives_by:"):
            deadline = r.split(":", 1)[1]
            if offer["delivery_est_date"] > deadline:
                reasons.append(f"arrives {offer['delivery_est_date']} (after {deadline})")
    if not offer["stock_available"]:
        reasons.append("out of stock")
    if Decimal(offer["price"]["amount"]) > constraint.max_total.amount:
        reasons.append(f"over budget (${offer['price']['amount']} > ${constraint.max_total.amount})")
    return reasons


def qualifies(offer: dict, constraint: Constraint) -> bool:
    return not disqualifiers(offer, constraint)


def suggest(offers: list[dict], constraint: Constraint, limit: int = 3) -> list[dict]:
    """Ranked shortlist: qualifying offers first (by rating), each annotated.

    Returns dicts with offer_id, title, merchant, price, rating, qualifies, and a
    human-readable match_reason (why it fits, or why it does not).
    """
    ranked: list[dict] = []
    for o in offers:
        reasons = disqualifiers(o, constraint)
        q = not reasons
        ranked.append({
            "offer_id": o["id"],
            "title": o["title"],
            "merchant": o["merchant"],
            "price": o["price"]["amount"],
            "rating": o["rating"],
            "qualifies": q,
            "match_reason": (f"meets all requirements, {o['rating']} rating"
                             if q else "; ".join(reasons)),
        })
    ranked.sort(key=lambda s: (not s["qualifies"], -s["rating"]))
    return ranked[:limit]
