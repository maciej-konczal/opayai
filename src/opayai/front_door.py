from __future__ import annotations
import json
import os
import re
from decimal import Decimal
from opayai.types import Constraint, Money, SpendingLimit

_CATEGORIES = ["monitor", "keyboard", "mouse", "laptop", "headphones", "hub"]


def heuristic_parse(prompt: str, persona: dict) -> tuple[Constraint, SpendingLimit]:
    text = prompt.lower()
    m = re.search(r"\$?\s*(\d+(?:\.\d+)?)", text)
    budget = Decimal(m.group(1)) if m else Decimal(str(persona["defaults"]["budget"]["amount"]))
    category = next((c for c in _CATEGORIES if c in text), "monitor")
    reqs: list[str] = []
    if "return" in text:
        reqs.append("free_returns")
    if "macbook" in text or "mac" in text:
        reqs.append("compat:macbook")
    if "tomorrow" in text:
        reqs.append("arrives_by:2026-07-12")
    constraint = Constraint(max_total=Money(amount=budget), category=category,
                            hard_requirements=reqs)
    limit = SpendingLimit(
        per_transaction=Money(amount=budget + Decimal("50")),
        per_period=Money(amount=budget * Decimal("3")))
    return constraint, limit


def parse_prompt(prompt: str, persona: dict, client=None) -> tuple[Constraint, SpendingLimit]:
    if client is None:
        return heuristic_parse(prompt, persona)
    model = os.environ.get("OPAYAI_MODEL", "claude-sonnet-5")
    schema_hint = (
        'Return ONLY JSON: {"category": str, "max_total": number, '
        '"hard_requirements": [str], "per_transaction": number, "per_period": number}. '
        'hard_requirements use tokens: "free_returns", "compat:macbook", "arrives_by:YYYY-MM-DD". '
        "Use only the regular hyphen (-)."
    )
    try:
        msg = client.messages.create(
            model=model, max_tokens=400,
            messages=[{"role": "user",
                       "content": f"{schema_hint}\nPersona: {json.dumps(persona)}\nPrompt: {prompt}"}])
        raw = msg.content[0].text
        data = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
        constraint = Constraint(
            max_total=Money(amount=Decimal(str(data["max_total"]))),
            category=data["category"], hard_requirements=data.get("hard_requirements", []))
        limit = SpendingLimit(
            per_transaction=Money(amount=Decimal(str(data["per_transaction"]))),
            per_period=Money(amount=Decimal(str(data["per_period"]))))
        return constraint, limit
    except Exception:
        return heuristic_parse(prompt, persona)
