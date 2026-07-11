from decimal import Decimal
from opayai.data import load_persona
from opayai.front_door import heuristic_parse, parse_prompt


def test_heuristic_extracts_budget_and_requirements():
    c, limit = heuristic_parse(
        "Find me the best monitor under $300 that works with my MacBook, "
        "arrives tomorrow, and has good return terms. Buy it if you're confident.",
        load_persona())
    assert c.max_total.amount == Decimal("300")
    assert c.category == "monitor"
    assert "free_returns" in c.hard_requirements
    assert "compat:macbook" in c.hard_requirements
    assert limit.per_transaction.amount >= Decimal("300")


def test_parse_prompt_offline_uses_heuristic():
    c, _ = parse_prompt("cheap monitor under $150", load_persona(), client=None)
    assert c.max_total.amount == Decimal("150")
