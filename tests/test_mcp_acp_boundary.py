from __future__ import annotations

from pathlib import Path

import pytest

from ai_orchestrator.control import McpAcpRequest, cli_args_for_operation


def test_mcp_acp_boundary_maps_operations_to_cli_json_contracts() -> None:
    repo = Path(".")

    assert cli_args_for_operation(
        McpAcpRequest(operation="start_task", repo=repo, task="Fix tests")
    ) == ["start", "--task", "Fix tests", "--repo", "."]
    assert cli_args_for_operation(
        McpAcpRequest(operation="get_status", repo=repo, task_id="task-1")
    ) == ["status", "task-1", "--repo", ".", "--json"]
    assert cli_args_for_operation(
        McpAcpRequest(operation="list_approvals", repo=repo)
    ) == ["approvals", "list", "--repo", ".", "--json"]
    assert cli_args_for_operation(
        McpAcpRequest(
            operation="approve_action",
            repo=repo,
            approval_id=7,
            resolution="operator approved",
        )
    ) == [
        "approvals",
        "approve",
        "7",
        "--repo",
        ".",
        "--resolution",
        "operator approved",
        "--json",
    ]
    assert cli_args_for_operation(
        McpAcpRequest(
            operation="reject_action",
            repo=repo,
            approval_id=8,
            resolution="operator rejected",
        )
    ) == [
        "approvals",
        "reject",
        "8",
        "--repo",
        ".",
        "--resolution",
        "operator rejected",
        "--json",
    ]
    assert cli_args_for_operation(
        McpAcpRequest(operation="retry_approval", repo=repo, approval_id=9)
    ) == ["approvals", "retry", "9", "--repo", ".", "--json"]
    assert cli_args_for_operation(
        McpAcpRequest(operation="export_trace", repo=repo, task_id="task-1")
    ) == ["export", "task-1", "--repo", ".", "--redact"]


def test_mcp_acp_boundary_validates_required_fields() -> None:
    repo = Path(".")

    with pytest.raises(ValueError, match="task is required"):
        cli_args_for_operation(McpAcpRequest(operation="start_task", repo=repo))
    with pytest.raises(ValueError, match="task_id is required"):
        cli_args_for_operation(McpAcpRequest(operation="get_status", repo=repo))
    with pytest.raises(ValueError, match="approval_id is required"):
        cli_args_for_operation(McpAcpRequest(operation="retry_approval", repo=repo))
    with pytest.raises(ValueError, match="approval_id must be positive"):
        cli_args_for_operation(
            McpAcpRequest(operation="retry_approval", repo=repo, approval_id=0)
        )
    with pytest.raises(ValueError, match="resolution is required"):
        cli_args_for_operation(
            McpAcpRequest(operation="approve_action", repo=repo, approval_id=1)
        )

