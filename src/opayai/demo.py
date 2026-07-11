"""One-command end-to-end demo: prompt -> authorize -> pay -> delivered.

Runs the web trusted surface and the fulfillment ticker in-process and drives the
whole scenario, printing each event as it happens. By default it pauses for YOU to
click Authorize on the web page (the real human step); pass --auto to authorize
automatically.

  python -m opayai.demo          # interactive - you click Authorize
  python -m opayai.demo --auto    # fully scripted, no interaction
"""
from __future__ import annotations
import argparse
import os
import tempfile
import threading
import time
from http.server import ThreadingHTTPServer
from rich.console import Console
from opayai import server, fulfillment, web

console = Console()


def _render(event) -> None:
    e = event.model_dump(mode="json")
    console.print(f"  [dim]#{e['seq']:>2}[/dim] [cyan]{e['type']:<22}[/cyan]"
                  f"[magenta]{e['actor']:<9}[/magenta] {e['payload']}")


def run(auto: bool) -> None:
    os.environ.setdefault("OPAYAI_AUTH_STORE", tempfile.mkdtemp(prefix="opayai-demo-auth-"))
    os.environ.setdefault("OPAYAI_SHIP_SECONDS", "3")
    os.environ.setdefault("OPAYAI_DELIVER_SECONDS", "7")
    port = int(os.environ.get("OPAYAI_WEB_PORT", "8000"))
    os.environ["OPAYAI_WEB_BASE"] = f"http://localhost:{port}"

    srv = ThreadingHTTPServer(("127.0.0.1", port), web._Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    server.bus.subscribe(_render)
    fulfillment.start(interval=0.5)
    server.reset_session()

    console.rule("[bold]opayai - prompt to purchase, with authorization")
    console.print('[bold]USER:[/bold] "Buy me a MacBook monitor under $300 with free returns."\n')
    im = server.create_intent_mandate(
        user_id="u_1", category="monitor", max_total="300",
        hard_requirements=["free_returns", "compat:macbook"],
        per_transaction="400", per_period="1000")
    console.print(f"[green]AGENT:[/green] passkey threshold from profile = "
                  f"${im['spending_limit']['step_up_threshold']['amount']} (not stated by the user)\n")
    offers = server.search_offers(category="monitor", max_price="300")
    pick = [o["id"] for o in offers if o["free_returns"] and "macbook" in o["specs"]["compat"]][:1]
    cart = server.propose_cart(intent_id=im["id"], offer_ids=pick, rail="ap2", rationale="best fit")
    server.evaluate_policy(cart_id=cart["id"])

    result = server.execute_payment(cart_id=cart["id"])
    if str(result.get("status", "")).startswith("PENDING"):
        console.print(f"\n[yellow]AGENT: I can't authorize this myself.[/yellow] "
                      f"Open [bold underline]{result['authorize_url']}[/bold underline] and click Authorize.\n")
        if auto:
            time.sleep(1)
            web.authorize(cart["id"], result["kind"])
            console.print("[dim](auto-authorized on the trusted surface)[/dim]\n")
        else:
            input("   ...then press Enter here to continue. ")
            console.print()
        result = server.execute_payment(cart_id=cart["id"])

    console.print(f"\n[bold green]PAID[/bold green] - order {result['id']}  "
                  f"track: {result['status_url']}")
    console.print("[dim]\nBackground fulfillment now ships and delivers on its own "
                  "(watch the events, and the 'delivered' push)...\n[/dim]")
    time.sleep(float(os.environ["OPAYAI_DELIVER_SECONDS"]) + 2)
    console.rule("[bold green]done")


def main() -> None:
    ap = argparse.ArgumentParser(description="opayai end-to-end demo")
    ap.add_argument("--auto", action="store_true",
                    help="authorize automatically instead of waiting for you to click")
    run(ap.parse_args().auto)


if __name__ == "__main__":
    main()
