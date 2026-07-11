from types import SimpleNamespace

from opayai import server
from opayai.cli import run_flow


def setup_function():
    server.reset_session()


def test_run_flow_completes_purchase_and_return():
    result = run_flow(
        prompt="Find me the best monitor under $300 that works with my MacBook, "
               "arrives tomorrow, and has good return terms. Buy it if you're confident.",
        approve=lambda cart, decision: True,
        do_return=True,
        client=None)
    assert result["order"]["status"] in ("RETURN_REQUESTED",)
    assert result["decision"]["result"] in ("AUTO_APPROVE", "ESCALATE")
    assert result["receipt_reference"].startswith(("ap2_", "card_"))


class _FakeMessages:
    def __init__(self, text: str) -> None:
        self._text = text

    def create(self, **kwargs):
        return SimpleNamespace(content=[SimpleNamespace(text=self._text)])


class _FakeClient:
    """Minimal stand-in for an Anthropic client, forcing parse_prompt down the
    LLM-parsed path so we can set per_transaction/per_period below the cart
    total and deterministically trip the ESCALATE branch."""

    def __init__(self, text: str) -> None:
        self.messages = _FakeMessages(text)


def test_declined_escalation_returns_no_order():
    # max_total is generous so the budget check passes, but per_transaction and
    # per_period are far below any monitor's price, so evaluate_policy will
    # ESCALATE rather than REJECT or AUTO_APPROVE.
    fake_client = _FakeClient(
        '{"category": "monitor", "max_total": 1000, "hard_requirements": [], '
        '"per_transaction": 10, "per_period": 10}')
    result = run_flow(
        prompt="Find me a monitor.",
        approve=lambda cart, decision: False,
        do_return=False,
        client=fake_client)
    assert result["order"] is None
    assert result["decision"]["result"] == "ESCALATE"


def test_no_matching_offer_returns_no_order():
    # "keyboard" has no offers in the fixture data at all, so auto_pick
    # returns an empty list and run_flow must bail out before propose_cart.
    result = run_flow(
        prompt="Find me the best keyboard under $50.",
        approve=lambda cart, decision: True,
        do_return=False,
        client=None)
    assert result["order"] is None
    assert result["decision"] is None
