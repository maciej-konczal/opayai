"""Small CLI front door for the unified OPayAI service.

The CLI may draft a mandate, but consent and payment stay in the web UI. This
keeps the same prompt-first ergonomics as the teammate prototype without
creating a second, less-safe purchase path.
"""
from __future__ import annotations

import os
from pathlib import Path

import typer
from rich.console import Console

from opayai.server import default_service


console = Console()


def run_flow(prompt: str, service=None) -> dict:
    runtime = service or default_service()
    intent = runtime.draft_intent(prompt, agent_id="cli")
    return {
        "intent": intent.model_dump(mode="json"),
        "status": "awaiting_human_authorization",
        "web_url": os.getenv("OPAYAI_WEB_BASE", "http://localhost:8000"),
    }


def main(prompt: str = typer.Argument(
        "Buy me a 27-inch USB-C monitor under PLN 1,200 with at least 14-day returns.")) -> None:
    result = run_flow(prompt)
    intent = result["intent"]
    console.print(f"[bold cyan]Intent {intent['id']} drafted[/bold cyan]")
    console.print("OPayAI will not sign or pay from the CLI.")
    console.print(f"Open [link={result['web_url']}]{result['web_url']}[/link] to review and sign.")


if __name__ == "__main__":
    typer.run(main)
