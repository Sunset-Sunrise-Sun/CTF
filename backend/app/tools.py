from typing import Protocol
from .models import ToolApproval, ToolExecutionResult, ToolProposal


class ExecutionBroker(Protocol):
    async def execute(
        self, proposal: ToolProposal, approval: ToolApproval
    ) -> ToolExecutionResult: ...


class DisabledBroker:
    """P0 has an empty registry: no subprocess, network, or container execution."""

    registry: tuple[str, ...] = ()

    async def execute(
        self, proposal: ToolProposal, approval: ToolApproval
    ) -> ToolExecutionResult:
        if not approval.approved or approval.proposal_id != proposal.proposal_id:
            raise PermissionError("Matching explicit user approval required")
        raise PermissionError("No tools enabled in P0")
