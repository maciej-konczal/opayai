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


def preference_reasons(offer: dict, persona: dict) -> list[str]:
    """Connect this offer's attributes to the user's stated preferences.

    Grounded in the persona's structured fields (motivations, risk tolerance) plus
    a couple of well-known standing preferences, so the shortlist can show WHY an
    option fits *this* user, not just that it meets the hard requirements.
    """
    out: list[str] = []
    specs = offer.get("specs", {})
    ports = specs.get("ports", [])
    motivations = [m.lower() for m in persona.get("motivations", [])]
    defaults = persona.get("defaults", {})
    if any(p in ("USB-C", "Thunderbolt") for p in ports):
        out.append("native USB-C/Thunderbolt - no dongles with your MacBook")
    if offer.get("free_returns"):
        out.append("free returns (your standing preference)")
    if "quality" in motivations and offer.get("rating", 0) >= 4.5:
        out.append(f"{offer.get('rating')}-star rated - you value quality")
    if "time saved" in motivations and offer.get("delivery_est_date"):
        out.append(f"arrives {offer.get('delivery_est_date')} - saves you time")
    if defaults.get("risk_tolerance") == "low" and offer.get("warranty_months", 0) >= 24:
        out.append(f"{offer.get('warranty_months')}-month warranty - fits your low risk tolerance")
    return out


def suggest(offers: list[dict], constraint: Constraint, limit: int = 3,
            persona: dict | None = None) -> list[dict]:
    """Ranked shortlist: qualifying offers first (by rating), each annotated.

    Returns dicts with offer_id, title, merchant, price, rating, qualifies, and a
    human-readable match_reason (why it fits, or why it does not). When `persona`
    is provided, each item also gets `preferences`: reasons it fits the user's
    stated preferences (not just the hard requirements).
    """
    ranked: list[dict] = []
    for o in offers:
        reasons = disqualifiers(o, constraint)
        q = not reasons
        item = {
            "offer_id": o["id"],
            "title": o["title"],
            "merchant": o["merchant"],
            "price": o["price"]["amount"],
            "rating": o["rating"],
            "qualifies": q,
            "match_reason": (f"meets all requirements, {o['rating']} rating"
                             if q else "; ".join(reasons)),
        }
        if persona is not None:
            item["preferences"] = preference_reasons(o, persona)
        ranked.append(item)
    ranked.sort(key=lambda s: (not s["qualifies"], -s["rating"]))
    return ranked[:limit]
