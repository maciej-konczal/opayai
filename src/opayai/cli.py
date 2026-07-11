from __future__ import annotations
from decimal import Decimal
from typing import Callable
import typer
from rich.console import Console
from rich.markup import escape
from opayai import server
from opayai.data import load_persona
from opayai.events import bus
from opayai.front_door import parse_prompt
from opayai.types import Constraint

console = Console()


def auto_pick(offers: list[dict], constraint: Constraint) -> list[str]:
    reqs = constraint.hard_requirements
    def ok(o: dict) -> bool:
        if "free_returns" in reqs and not o["free_returns"]:
            return False
        for r in reqs:
            if r.startswith("compat:") and r.split(":", 1)[1] not in o["specs"].get("compat", []):
                return False
            if r.startswith("arrives_by:") and o["delivery_est_date"] > r.split(":", 1)[1]:
                return False
        return o["stock_available"] and Decimal(o["price"]["amount"]) <= constraint.max_total.amount
    ranked = sorted((o for o in offers if ok(o)), key=lambda o: -o["rating"])
    return [ranked[0]["id"]] if ranked else []


def _render(event) -> None:
    console.print(f"[dim]#{event.seq}[/dim] [bold cyan]{event.type}[/bold cyan] "
                  f"[magenta]{event.actor}[/magenta] {escape(str(event.payload))}")


def run_flow(prompt: str, approve: Callable[[dict, dict], bool],
             do_return: bool = False, client=None) -> dict:
    persona = load_persona()
    constraint, limit = parse_prompt(prompt, persona, client=client)
    intent = server.create_intent_mandate(
        user_id=persona["id"], category=constraint.category,
        max_total=str(constraint.max_total.amount),
        hard_requirements=constraint.hard_requirements,
        per_transaction=str(limit.per_transaction.amount),
        per_period=str(limit.per_period.amount))
    offers = server.search_offers(category=constraint.category,
                                  max_price=str(constraint.max_total.amount))
    picked = auto_pick(offers, constraint)
    if not picked:
        return {"intent": intent, "cart": None, "decision": None, "order": None}
    cart = server.propose_cart(intent_id=intent["id"], offer_ids=picked,
                               rail="x402", rationale="best rated within constraints")
    decision = server.evaluate_policy(cart_id=cart["id"])
    if decision["result"] == "REJECT":
        return {"intent": intent, "cart": cart, "decision": decision, "order": None}
    if decision["result"] == "ESCALATE":
        approved = approve(cart, decision)
        server.request_approval(cart_id=cart["id"], approved=approved)
        if not approved:
            return {"intent": intent, "cart": cart, "decision": decision, "order": None}
    order = server.execute_payment(cart_id=cart["id"])
    receipt_ref = order["receipt"]["rail_reference"]
    server.advance_order(order["id"]); server.advance_order(order["id"])  # -> DELIVERED
    if do_return:
        order = server.create_return(order_id=order["id"], reason="changed my mind",
                                     returns_window_days=30)
    return {"intent": intent, "cart": cart, "decision": decision,
            "order": order, "receipt_reference": receipt_ref}


def main(prompt: str = typer.Argument(
        "Find me the best monitor under $300 that works with my MacBook, "
        "arrives tomorrow, and has good return terms. Buy it if you're confident."),
        do_return: bool = typer.Option(False, "--return")) -> None:
    def approve(cart: dict, decision: dict) -> bool:
        console.print(f"[yellow]APPROVAL NEEDED[/yellow] total={cart['total']['amount']} "
                      f"rail={cart['selected_rail']}")
        return typer.confirm("Approve this purchase?")
    bus.subscribe(_render)
    result = run_flow(prompt, approve=approve, do_return=do_return, client=None)
    console.rule("[bold green]RESULT")
    if result["order"]:
        console.print(f"Order [bold]{result['order']['id']}[/bold] "
                      f"status=[green]{result['order']['status']}[/green]")
    elif result["decision"] is None:
        console.print("[red]No purchase[/red] - No matching offer found")
    else:
        console.print(f"[red]No purchase[/red] - policy {result['decision']['result']}")


if __name__ == "__main__":
    typer.run(main)
