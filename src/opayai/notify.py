"""Turn the raw event stream into proactive, user-facing notifications.

The agent works in the background; this is the "pings you only when it needs
input, approval, or a decision" layer. Each notification is derived from one
event and marked needs_action (surface first: approval, passkey, choose an
option) or a plain progress update. Pure functions over event dicts, so the
same mapping feeds the MCP tool, the web inbox, and the desktop ping.
"""
from __future__ import annotations


def _n(title: str, body: str, action: bool, event: dict) -> dict:
    return {
        "title": title, "body": body,
        "level": "action_required" if action else "update",
        "needs_action": action,
        "seq": event.get("seq"), "ts": event.get("ts"),
        "mandate_ref": event.get("mandate_ref"), "source_event": event.get("type"),
    }


def notification_for(event: dict) -> dict | None:
    """Map one event to a user-facing notification, or None if not noteworthy."""
    t = event.get("type", "")
    p = event.get("payload", {})
    if t == "suggestions.ready":
        return _n("Options ready to choose",
                  f"{p.get('count', 'A few')} options match - pick one to continue.",
                  True, event)
    if t == "authorization.pending":
        what = "passkey step-up" if p.get("kind") == "step_up" else "approval"
        return _n(f"Authorize with your {what}",
                  f"A purchase needs your {what}. Authorize at {p.get('authorize_url', '')}.",
                  True, event)
    if t == "policy.evaluated":
        if p.get("result") == "ESCALATE":
            return _n("Approval needed",
                      "A purchase is over your spending limit and needs your OK.", True, event)
        if p.get("result") == "REJECT":
            return _n("Purchase blocked",
                      "A purchase did not meet your rules (budget or requirements).", True, event)
        if p.get("step_up_required"):
            return _n("Confirm with your passkey",
                      "A purchase is over your step-up threshold - authorize it to continue.",
                      True, event)
        return None  # a clean auto-approve is not worth a ping
    if t == "approval.recorded":
        return _n("Approval recorded",
                  "You approved the purchase." if p.get("approved") else "You declined the purchase.",
                  False, event)
    if t == "stepup.authorized":
        return _n("Passkey confirmed", "You authorized the purchase with your passkey.", False, event)
    if t == "payment.settled":
        return _n("Payment complete", f"Paid {p.get('amount')} via {p.get('rail')}.", False, event)
    if t == "order.created":
        return _n("Order confirmed", "Your order has been placed.", False, event)
    if t == "order.advanced":
        return _n(f"Order {str(p.get('status', '')).lower()}",
                  f"Your order is now {p.get('status')}.", False, event)
    if t == "order.return_requested":
        return _n("Return filed", "Your return request was submitted.", False, event)
    if t == "order.cancelled":
        return _n("Order cancelled", "Your order was cancelled.", False, event)
    return None


def notifications(events: list[dict], mandate_ref: str | None = None) -> list[dict]:
    """Derive the notification feed from events (optionally for one mandate)."""
    out = []
    for e in events:
        if mandate_ref is not None and e.get("mandate_ref") != mandate_ref:
            continue
        n = notification_for(e)
        if n:
            out.append(n)
    return out
