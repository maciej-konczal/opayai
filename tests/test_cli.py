from pathlib import Path

from opayai.commerce.service import OPayAIService
from opayai.cli import run_flow


def test_cli_drafts_but_never_consents_or_pays(tmp_path: Path):
    service = OPayAIService(tmp_path)
    result = run_flow(
        "Buy winter tires under PLN 1,600 with at least 14-day returns.", service)
    intent = service.store.intents[result["intent"]["id"]]
    assert result["status"] == "awaiting_human_authorization"
    assert intent.status == "draft"
    assert intent.signing is None
    assert service.store.purchases == {}
