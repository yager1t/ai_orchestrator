"""Local control-surface helpers for external operator integrations."""

from ai_orchestrator.control.client import LocalOperatorClient, LocalOperatorResult
from ai_orchestrator.control.mcp_acp import (
    McpAcpOperation,
    McpAcpRequest,
    cli_args_for_operation,
)

__all__ = [
    "LocalOperatorClient",
    "LocalOperatorResult",
    "McpAcpOperation",
    "McpAcpRequest",
    "cli_args_for_operation",
]
