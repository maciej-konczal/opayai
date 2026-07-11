from decimal import Decimal
from opayai.data import load_offers, search_offers, load_persona


def test_offers_load_as_models():
    offers = load_offers()
    assert len(offers) >= 3
    assert all(o.price.amount > 0 for o in offers)


def test_search_filters_by_price_and_category():
    hits = search_offers(category="monitor", max_price=Decimal("300"))
    assert len(hits) >= 1
    assert all(o.price.amount <= Decimal("300") for o in hits)
    assert all("monitor" in o.specs.get("category", "") or o.title for o in hits)


def test_persona_has_spending_defaults():
    p = load_persona()
    assert "defaults" in p
    assert "budget" in p["defaults"]
