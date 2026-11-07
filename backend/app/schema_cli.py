"""Export the OpenAPI document and the typed JSON-schema contract map.

Run from ``backend``:

    python -m app.schema_cli

The generated files live under ``docs/`` and are committed as review artefacts;
CI does not require them to be regenerated.
"""

from __future__ import annotations

import json
from pathlib import Path

from .main import create_app
from .models import (
    Artifact,
    ArtifactView,
    Challenge,
    ChallengeCreate,
    Event,
    Finding,
    Hypothesis,
    ImportDetail,
    ImportFile,
    ImportRecord,
    ImportResult,
    ManualOperationCreate,
    NoteCreate,
    Project,
    ProjectUpdate,
    Scope,
    ToolApproval,
    ToolExecutionResult,
    ToolProposal,
    ToolStarted,
    Verification,
    Writeup,
    WriteupPreview,
    WriteupStatement,
)
from .providers import (
    Capabilities,
    Message,
    ModelRequest,
    ModelResponse,
    ProviderConfig,
    StreamChunk,
    ToolCall,
    ToolDefinition,
)

MODELS = (
    Scope,
    ChallengeCreate,
    Challenge,
    Event,
    NoteCreate,
    Artifact,
    ArtifactView,
    ToolProposal,
    ToolApproval,
    ToolStarted,
    ToolExecutionResult,
    Finding,
    Hypothesis,
    Verification,
    WriteupStatement,
    Writeup,
    Capabilities,
    ProviderConfig,
    Message,
    ToolDefinition,
    ToolCall,
    ModelRequest,
    ModelResponse,
    StreamChunk,
    Project,
    ProjectUpdate,
    ManualOperationCreate,
    ImportFile,
    ImportRecord,
    ImportDetail,
    ImportResult,
    WriteupPreview,
)


def _docs_directory() -> Path:
    return Path(__file__).resolve().parents[2] / "docs"


def main() -> None:
    docs = _docs_directory()
    docs.mkdir(parents=True, exist_ok=True)
    openapi_path = docs / "openapi.json"
    openapi_path.write_text(
        json.dumps(create_app().openapi(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    contracts_path = docs / "contracts.json"
    previous: dict = {}
    if contracts_path.exists():
        previous = json.loads(contracts_path.read_text(encoding="utf-8"))
    generated = {model.__name__: model.model_json_schema() for model in MODELS}
    ordered: dict = {}
    for name in previous:
        ordered[name] = generated.get(name, previous[name])
    for name, schema in generated.items():
        ordered.setdefault(name, schema)
    contracts_path.write_text(
        json.dumps(ordered, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"wrote {openapi_path}")
    print(f"wrote {contracts_path}")


if __name__ == "__main__":
    main()
