"""Keep reviewable API contracts tied to the actual application, without startup."""

import json
from pathlib import Path

from app.ai_assistant import AIChatRequest, AIChatResponse, AIConnectivityTestRequest
from app.main import create_app


DOCS = Path(__file__).resolve().parents[2] / "docs"


def test_exported_openapi_matches_application(tmp_path):
    # Building the schema must not start lifespan or create an acceptance database.
    root = tmp_path / "unused"
    actual = create_app(root).openapi()
    assert not root.exists()
    assert json.loads((DOCS / "openapi.json").read_text(encoding="utf-8")) == actual


def test_ai_contracts_include_challenge_bound_consent():
    contracts = json.loads((DOCS / "contracts.json").read_text(encoding="utf-8"))
    for model in (AIChatRequest, AIChatResponse, AIConnectivityTestRequest):
        assert contracts[model.__name__] == model.model_json_schema()
    assert "consent_challenge_id" in contracts["AIChatRequest"]["required"]
    assert contracts["AIChatRequest"]["additionalProperties"] is False
