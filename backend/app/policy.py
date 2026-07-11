from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .models import IntentMandate, Offer


class PolicyBlock(Exception):
    def __init__(self, clause: str, detail: str):
        self.clause, self.detail = clause, detail
        super().__init__(f"{clause}: {detail}")


def check_policy(intent: IntentMandate, action: str, offer: Offer | None = None,
                 amount: int = 0, rail: str | None = None) -> tuple[bool, str, str]:
    if intent.status != "open":
        return False, "mandate_not_open", "Mandate is not open for purchases."
    if datetime.fromisoformat(intent.constraints.expiry) <= datetime.now(timezone.utc):
        return False, "mandate_expired", "Mandate expiry has passed."
    if offer:
        if offer.category not in intent.constraints.categories:
            return False, "category_not_allowed", "Offer category is outside the mandate."
        if intent.constraints.requires_refundability and not offer.refundable:
            return False, "refundability_required", "Mandate requires a refundable offer."
        if offer.return_policy["window_days"] < intent.constraints.min_return_window_days:
            return False, "return_window_too_short", "Offer return window is shorter than mandated."
        if offer.delivery_estimate_days > 0 and intent.constraints.deliver_by:
            promised = datetime.now(timezone.utc).date().fromordinal(datetime.now(timezone.utc).date().toordinal() + offer.delivery_estimate_days).isoformat()
            if promised > intent.constraints.deliver_by:
                return False, "delivery_too_late", "Offer cannot meet the delivery deadline."
    if amount and intent.spent_total + amount > intent.constraints.max_total:
        return False, "budget_exceeded", "Cumulative mandate budget would be exceeded."
    if rail and rail not in intent.constraints.allowed_rails:
        return False, "rail_not_allowed", "Selected payment rail is not allowed by the mandate."
    return True, "policy_pass", f"{action} permitted by active mandate"
