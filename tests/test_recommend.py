from decimal import Decimal
from opayai.types import Constraint, Money
from opayai.recommend import suggest, qualifies, disqualifiers, preference_reasons


def _offer(id, price, rating, free_returns=True, compat=("macbook",),
           stock=True, est="2026-07-12"):
    return {"id": id, "title": id, "merchant": "M", "price": {"amount": price, "currency": "USD"},
            "stock_available": stock, "delivery_est_date": est, "free_returns": free_returns,
            "specs": {"compat": list(compat)}, "rating": rating}


def _constraint(max_total="300", reqs=("free_returns", "compat:macbook")):
    return Constraint(max_total=Money(amount=Decimal(max_total)), category="monitor",
                      hard_requirements=list(reqs))


def test_qualifying_offer_has_no_disqualifiers():
    assert qualifies(_offer("of_1", "289", 4.6), _constraint()) is True
    assert disqualifiers(_offer("of_1", "289", 4.6), _constraint()) == []


def test_disqualifiers_are_specific():
    c = _constraint()
    assert any("over budget" in r for r in disqualifiers(_offer("of_3", "329", 4.8), c))
    assert "out of stock" in disqualifiers(_offer("of_4", "219", 4.3, stock=False), c)
    assert "no free returns" in disqualifiers(_offer("of_2", "149", 4.0, free_returns=False), c)
    assert "not macbook-compatible" in disqualifiers(_offer("of_x", "149", 4.0, compat=()), c)


def test_suggest_ranks_qualifying_first_then_by_rating():
    offers = [
        _offer("of_1", "289", 4.6),                 # qualifies
        _offer("of_3", "329", 4.8),                 # over budget (higher rating)
        _offer("of_4", "219", 4.3, stock=False),    # out of stock
    ]
    out = suggest(offers, _constraint(), limit=3)
    assert out[0]["offer_id"] == "of_1"             # qualifying wins despite lower rating
    assert out[0]["qualifies"] is True
    assert "meets all requirements" in out[0]["match_reason"]
    # disqualified ones ranked after, by rating, with reasons
    assert out[1]["offer_id"] == "of_3" and out[1]["qualifies"] is False
    assert "over budget" in out[1]["match_reason"]


def test_suggest_respects_limit():
    offers = [_offer(f"of_{i}", "100", 4.0) for i in range(5)]
    assert len(suggest(offers, _constraint(), limit=2)) == 2


_PERSONA = {"motivations": ["quality", "time saved"],
            "defaults": {"risk_tolerance": "low"}}


def test_preference_reasons_connect_offer_to_the_user():
    offer = {"specs": {"ports": ["USB-C", "HDMI"]}, "free_returns": True,
             "rating": 4.6, "delivery_est_date": "2026-07-12", "warranty_months": 24}
    reasons = preference_reasons(offer, _PERSONA)
    joined = " | ".join(reasons)
    assert "no dongles" in joined                # USB-C -> MacBook, no dongles
    assert "free returns" in joined
    assert "you value quality" in joined          # rating + motivations
    assert "low risk tolerance" in joined         # warranty + risk tolerance


def test_suggest_attaches_preferences_when_persona_given():
    o = _offer("of_1", "289", 4.6)
    o["specs"] = {"compat": ["macbook"], "ports": ["USB-C"]}
    o["warranty_months"] = 24
    out = suggest([o], _constraint(), persona=_PERSONA)
    assert out[0]["preferences"]                  # non-empty preference reasons
    # without a persona there is no preferences field
    assert "preferences" not in suggest([o], _constraint())[0]
