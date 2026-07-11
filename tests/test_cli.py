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
    assert result["receipt_reference"].startswith(("x402_", "card_"))
