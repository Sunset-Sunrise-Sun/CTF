"""Server-side AI permission matrix.

The matrix is explicit and fail-closed: the model prompt and the frontend are
never authorities for what may be sent, proposed, approved or executed.

| Level   | Model calls | Challenge context | Attachment contents | Tool proposals | Tool execution |
|---------|-------------|-------------------|---------------------|----------------|----------------|
| unknown | no          | no                | no                  | no             | no             |
| A0      | no          | no                | no                  | no             | no             |
| A1      | yes (text)  | yes (text)        | no                  | no             | no             |
| A2      | yes         | yes               | yes (selected)      | yes            | yes (approved) |
"""
from __future__ import annotations

from dataclasses import dataclass

from .models import AiUsageLevel


@dataclass(frozen=True)
class AIPolicy:
    model_calls: bool
    challenge_context: bool
    attachment_content: bool
    tool_proposals: bool
    tool_execution: bool


_POLICIES: dict[str, AIPolicy] = {
    "unknown": AIPolicy(False, False, False, False, False),
    "A0": AIPolicy(False, False, False, False, False),
    # A1 may use the model for advice over explicitly selected text, but must
    # not externalize attachment bytes, propose tools or execute tools.
    "A1": AIPolicy(True, True, False, False, False),
    # A2 allows bounded attachment context and tool proposals; approval and
    # execution remain separate human actions.
    "A2": AIPolicy(True, True, True, True, True),
}


def policy_for(level: AiUsageLevel | str | None) -> AIPolicy:
    """Return the fail-closed policy for a challenge AI usage level."""
    return _POLICIES.get(str(level), _POLICIES["unknown"])


def model_calls_allowed(level: AiUsageLevel | str | None) -> bool:
    return policy_for(level).model_calls


def attachment_content_allowed(level: AiUsageLevel | str | None) -> bool:
    return policy_for(level).attachment_content


def tool_proposals_allowed(level: AiUsageLevel | str | None) -> bool:
    return policy_for(level).tool_proposals


def tool_execution_allowed(level: AiUsageLevel | str | None) -> bool:
    return policy_for(level).tool_execution
