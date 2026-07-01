import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ai_orchestrator import __version__
from ai_orchestrator.cli.app import main
from ai_orchestrator.core.supervisor import SupervisorResult
from ai_orchestrator.process.runner import ProcessResult, ProcessRunner, RunOptions
from ai_orchestrator.storage.db import StateStore
from ai_orchestrator.verification.release import run_release_checks
from ai_orchestrator.verification.runner import VerificationResult, VerificationRunner


def test_version_command(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])

    output = capsys.readouterr().out
    assert exc.value.code == 0
    assert output == f"ai-orch {__version__}\n"


def test_log_level_configures_logging(monkeypatch, tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []

    def fake_basic_config(**kwargs) -> None:
        calls.append(kwargs)

    monkeypatch.setattr("ai_orchestrator.cli.app.logging.basicConfig", fake_basic_config)

    exit_code = main(["--log-level", "debug", "agents", "--repo", str(tmp_path)])

    assert exit_code == 0
    assert calls
    assert calls[0]["level"] == 10


def test_autopilot_next_prints_next_plan_item(capsys, tmp_path: Path) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Add approval CLI\n", encoding="utf-8")

    exit_code = main(["autopilot", "next", "--repo", str(tmp_path), "--plan", str(plan)])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Task: Add approval CLI" in output
    assert "Source:" in output


def test_autopilot_run_defaults_to_dry_run(capsys, tmp_path: Path) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Add approval CLI\n", encoding="utf-8")

    exit_code = main(["autopilot", "run", "--repo", str(tmp_path), "--plan", str(plan)])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Autopilot selected:" in output
    assert "Agent profile:" in output
    assert "name: mock" in output
    assert "mode: mock" in output
    assert "available: yes" in output
    assert "Dry run: add --execute" in output


def test_autopilot_run_blocks_unavailable_real_agent_before_execution(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Add approval CLI\n", encoding="utf-8")
    write_config(
        tmp_path,
        default_agent="generic",
        include_generic_agent=True,
        generic_command="missing-ai-orch-agent-binary",
    )

    exit_code = main(
        [
            "autopilot",
            "run",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--execute",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "Agent profile:" in output
    assert "name: generic" in output
    assert "type: generic_cli" in output
    assert "mode: real" in output
    assert "command: missing-ai-orch-agent-binary" in output
    assert "available: no" in output
    assert "Execution blocked: selected agent is unavailable: generic" in output


def test_autopilot_run_blocks_mock_agent_without_explicit_allow(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Add approval CLI\n", encoding="utf-8")

    exit_code = main(
        [
            "autopilot",
            "run",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--execute",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "Execution blocked: mock agent selected" in output


def test_autopilot_run_uses_opt_in_worktree_for_execution(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    worktree = tmp_path / "autopilot-worktree"
    plan.write_text("- [ ] Add approval CLI\n", encoding="utf-8")
    worktree.mkdir()
    captured_repos: list[Path] = []

    def fake_validate(repo: Path, candidate: Path) -> str | None:
        assert repo == tmp_path
        assert candidate == worktree.resolve()
        return None

    def fake_dirty(repo: Path) -> bool:
        assert repo == worktree.resolve()
        return False

    def fake_run_once(self, task: str, repo: Path, planning_context=None) -> SupervisorResult:
        captured_repos.append(repo)
        return SupervisorResult(status="done", summary="Verification passed: custom", task_id="task-1")

    monkeypatch.setattr("ai_orchestrator.cli.app._validate_autopilot_worktree", fake_validate)
    monkeypatch.setattr("ai_orchestrator.cli.app._repo_has_uncommitted_changes", fake_dirty)
    monkeypatch.setattr("ai_orchestrator.cli.app.Supervisor.run_once", fake_run_once)

    exit_code = main(
        [
            "autopilot",
            "run",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--execute",
            "--allow-mock-agent",
            "--worktree",
            str(worktree),
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert f"Execution repo: {worktree.resolve()}" in output
    assert "task-1: Verification passed: custom" in output
    assert captured_repos == [worktree.resolve()]


def test_autopilot_run_blocks_invalid_worktree_before_execution(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    worktree = tmp_path / "not-worktree"
    plan.write_text("- [ ] Add approval CLI\n", encoding="utf-8")

    def fake_validate(repo: Path, candidate: Path) -> str | None:
        return f"worktree path does not exist: {candidate}"

    def fake_run_once(self, task: str, repo: Path, planning_context=None) -> SupervisorResult:
        raise AssertionError("supervisor should not start with an invalid worktree")

    monkeypatch.setattr("ai_orchestrator.cli.app._validate_autopilot_worktree", fake_validate)
    monkeypatch.setattr("ai_orchestrator.cli.app.Supervisor.run_once", fake_run_once)

    exit_code = main(
        [
            "autopilot",
            "run",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--execute",
            "--allow-mock-agent",
            "--worktree",
            str(worktree),
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "Execution blocked: worktree path does not exist:" in output


def test_status_prints_stored_task(capsys, tmp_path: Path) -> None:
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    task = store.create_task("demo task", repo_path=tmp_path)
    iteration = store.add_iteration(
        task_id=task.task_id,
        iteration_index=1,
        agent_name="mock",
        agent_status="success",
        prompt="demo task",
        raw_output="done",
        decision_status="done",
        decision_reason="Verification passed: unit",
    )
    store.add_verification_run(
        task_id=task.task_id,
        iteration_id=iteration.iteration_id,
        result=VerificationResult(
            name="unit",
            status="passed",
            exit_code=0,
            stdout="ok",
            stderr="",
        ),
    )
    store.update_task_status(task.task_id, "done")

    exit_code = main(["status", task.task_id, "--repo", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert f"Task: {task.task_id}" in output
    assert "Status: done" in output
    assert "Iterations: 1" in output
    assert "check=unit status=passed exit=0" in output


def test_status_returns_error_for_missing_task(capsys, tmp_path: Path) -> None:
    exit_code = main(["status", "missing-task", "--repo", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "Task not found: missing-task" in output


def test_cancel_marks_task_cancelled(capsys, tmp_path: Path) -> None:
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    task = store.create_task("cancel me", repo_path=tmp_path)

    exit_code = main(["cancel", task.task_id, "--repo", str(tmp_path)])
    output = capsys.readouterr().out
    loaded = store.get_task(task.task_id)

    assert exit_code == 0
    assert f"Cancelled: {task.task_id}" in output
    assert loaded is not None
    assert loaded.status == "cancelled"


def test_cancel_returns_error_for_missing_task(capsys, tmp_path: Path) -> None:
    exit_code = main(["cancel", "missing-task", "--repo", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "Task not found: missing-task" in output


def test_approvals_list_prints_pending_requests(capsys, tmp_path: Path) -> None:
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    task = store.create_task("demo task", repo_path=tmp_path)
    approval = store.add_approval_request(
        task_id=task.task_id,
        iteration_id=None,
        source="verification",
        command_string="git push origin main",
        reason="policy requires approval",
    )

    exit_code = main(["approvals", "list", "--repo", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert f"{approval.approval_id}: status=pending" in output
    assert "source=verification" in output
    assert "command=git push origin main" in output


def test_approvals_list_prints_empty_state(capsys, tmp_path: Path) -> None:
    exit_code = main(["approvals", "list", "--repo", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "No approval requests found." in output


def test_approvals_show_prints_details(capsys, tmp_path: Path) -> None:
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    task = store.create_task("demo task", repo_path=tmp_path)
    approval = store.add_approval_request(
        task_id=task.task_id,
        iteration_id=None,
        source="memory",
        command_string="codebase-memory-mcp cli index_repository",
        reason="memory indexing requires approval",
    )

    exit_code = main(
        ["approvals", "show", str(approval.approval_id), "--repo", str(tmp_path)]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert f"Approval: {approval.approval_id}" in output
    assert "Status: pending" in output
    assert "Source: memory" in output
    assert "Reason: memory indexing requires approval" in output


def test_approvals_approve_resolves_request(capsys, tmp_path: Path) -> None:
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    task = store.create_task("demo task", repo_path=tmp_path)
    approval = store.add_approval_request(
        task_id=task.task_id,
        iteration_id=None,
        source="verification",
        command_string="git push origin main",
        reason="policy requires approval",
    )

    exit_code = main(
        [
            "approvals",
            "approve",
            str(approval.approval_id),
            "--repo",
            str(tmp_path),
            "--resolution",
            "looks safe",
        ]
    )
    output = capsys.readouterr().out
    loaded = store.get_approval_request(approval.approval_id)

    assert exit_code == 0
    assert f"{approval.approval_id}: status=approved" in output
    assert loaded is not None
    assert loaded.status == "approved"
    assert loaded.resolution == "looks safe"


def test_approvals_reject_resolves_request(capsys, tmp_path: Path) -> None:
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    task = store.create_task("demo task", repo_path=tmp_path)
    approval = store.add_approval_request(
        task_id=task.task_id,
        iteration_id=None,
        source="verification",
        command_string="pip install demo",
        reason="package install requires approval",
    )

    exit_code = main(
        [
            "approvals",
            "reject",
            str(approval.approval_id),
            "--repo",
            str(tmp_path),
            "--resolution",
            "not needed",
        ]
    )
    output = capsys.readouterr().out
    loaded = store.get_approval_request(approval.approval_id)

    assert exit_code == 0
    assert f"{approval.approval_id}: status=rejected" in output
    assert loaded is not None
    assert loaded.status == "rejected"
    assert loaded.resolution == "not needed"


def test_approvals_retry_runs_approved_request(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    captured: list[tuple[list[str], Path | None]] = []

    def fake_run(
        self: ProcessRunner,
        argv: list[str],
        cwd: Path | None = None,
        timeout_sec: int = 300,
        should_cancel=None,
        options: RunOptions | None = None,
    ) -> ProcessResult:
        captured.append((argv, cwd))
        return ProcessResult(
            status="success",
            exit_code=0,
            stdout="retry ok",
            stderr="",
        )

    monkeypatch.setattr(ProcessRunner, "run", fake_run)
    write_config(
        tmp_path,
        command_name="approval",
        command_run="retry-token command",
        require_approval_patterns=["retry-token"],
    )
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    task = store.create_task("demo task", repo_path=tmp_path)
    approval = store.add_approval_request(
        task_id=task.task_id,
        iteration_id=None,
        source="verification",
        command_string="retry-token command",
        reason="policy requires approval",
    )
    store.resolve_approval_request(
        approval.approval_id,
        "approved",
        resolution="looks safe",
    )

    exit_code = main(
        ["approvals", "retry", str(approval.approval_id), "--repo", str(tmp_path)]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "retry: passed exit=0" in output
    assert "retry history: count=1 last_status=passed last_exit=0" in output
    assert "retry ok" in output
    assert captured == [(["retry-token", "command"], tmp_path)]
    loaded = store.get_approval_request(approval.approval_id)
    assert loaded is not None
    assert loaded.retry_count == 1
    assert loaded.last_retry_status == "passed"
    assert loaded.last_retry_exit_code == 0


def test_approvals_retry_requires_approved_request(
    capsys,
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    task = store.create_task("demo task", repo_path=tmp_path)
    approval = store.add_approval_request(
        task_id=task.task_id,
        iteration_id=None,
        source="verification",
        command_string="retry-token command",
        reason="policy requires approval",
    )

    exit_code = main(
        ["approvals", "retry", str(approval.approval_id), "--repo", str(tmp_path)]
    )
    output = capsys.readouterr().out

    assert exit_code == 1
    assert f"Approval request is not approved: {approval.approval_id} status=pending" in output


def test_approvals_stale_marks_old_pending_requests(
    capsys,
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    task = store.create_task("demo task", repo_path=tmp_path)
    old_approval = store.add_approval_request(
        task_id=task.task_id,
        iteration_id=None,
        source="verification",
        command_string="old command",
        reason="old approval",
    )
    fresh_approval = store.add_approval_request(
        task_id=task.task_id,
        iteration_id=None,
        source="verification",
        command_string="fresh command",
        reason="fresh approval",
    )
    old_created_at = (datetime.now(UTC) - timedelta(hours=48)).isoformat()
    with store._connect() as connection:
        connection.execute(
            "UPDATE approval_requests SET created_at = ? WHERE approval_id = ?",
            (old_created_at, old_approval.approval_id),
        )

    exit_code = main(
        [
            "approvals",
            "stale",
            "--repo",
            str(tmp_path),
            "--older-than-hours",
            "24",
            "--resolution",
            "too old",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert f"{old_approval.approval_id}: status=stale" in output
    assert "old command" in output
    assert "fresh command" not in output
    assert store.list_approval_requests(status="pending") == [fresh_approval]
    stale = store.list_approval_requests(status="stale")
    assert len(stale) == 1
    assert stale[0].resolution == "too old"


def test_approvals_retry_does_not_override_deny_rules(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    calls: list[list[str]] = []

    def fake_run(self: ProcessRunner, argv: list[str], **kwargs) -> ProcessResult:
        calls.append(argv)
        return ProcessResult(status="success", exit_code=0, stdout="ran", stderr="")

    monkeypatch.setattr(ProcessRunner, "run", fake_run)
    write_config(
        tmp_path,
        command_name="danger",
        command_run="dangerous command",
        deny_patterns=["dangerous"],
        require_approval_patterns=["dangerous"],
    )
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    task = store.create_task("demo task", repo_path=tmp_path)
    approval = store.add_approval_request(
        task_id=task.task_id,
        iteration_id=None,
        source="verification",
        command_string="dangerous command",
        reason="policy requires approval",
    )
    store.resolve_approval_request(
        approval.approval_id,
        "approved",
        resolution="operator approved",
    )

    exit_code = main(
        ["approvals", "retry", str(approval.approval_id), "--repo", str(tmp_path)]
    )
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "retry: policy_denied exit=None" in output
    assert "Denied by pattern: dangerous" in output
    assert calls == []


def test_approvals_returns_error_for_missing_request(capsys, tmp_path: Path) -> None:
    exit_code = main(["approvals", "show", "404", "--repo", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "Approval request not found: 404" in output


def test_tui_status_prints_read_only_task_view(capsys, tmp_path: Path) -> None:
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    task = store.create_task("demo task", repo_path=tmp_path)
    iteration = store.add_iteration(
        task_id=task.task_id,
        iteration_index=1,
        agent_name="mock",
        agent_status="success",
        prompt="demo task",
        raw_output="done",
        decision_status="done",
        decision_reason="Verification passed: unit",
    )
    store.add_verification_run(
        task_id=task.task_id,
        iteration_id=iteration.iteration_id,
        result=VerificationResult(
            name="unit",
            status="passed",
            exit_code=0,
            stdout="ok",
            stderr="",
        ),
    )

    exit_code = main(["tui", "status", task.task_id, "--repo", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert f"Task {task.task_id}" in output
    assert "Status: created" in output
    assert "Iterations" in output
    assert "check: unit passed exit=0" in output


def test_tui_status_prints_task_approval_history(capsys, tmp_path: Path) -> None:
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    task = store.create_task("demo approval task", repo_path=tmp_path)
    iteration = store.add_iteration(
        task_id=task.task_id,
        iteration_index=1,
        agent_name="mock",
        agent_status="success",
        prompt="demo approval task",
        raw_output="done",
        decision_status="blocked",
        decision_reason="Approval required",
    )
    approval = store.add_approval_request(
        task_id=task.task_id,
        iteration_id=iteration.iteration_id,
        source="verification",
        command_string="deploy production",
        reason="Policy requires approval",
    )
    store.resolve_approval_request(
        approval.approval_id,
        "rejected",
        resolution="Not safe enough",
    )

    exit_code = main(["tui", "status", task.task_id, "--repo", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Approvals" in output
    assert f"approval={approval.approval_id} status=rejected" in output
    assert f"task={task.task_id} iteration={iteration.iteration_id}" in output
    assert "command: deploy production" in output
    assert "reason: Policy requires approval" in output
    assert "resolution: Not safe enough" in output


def test_tui_status_returns_error_for_missing_task(capsys, tmp_path: Path) -> None:
    exit_code = main(["tui", "status", "missing-task", "--repo", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "Task not found: missing-task" in output


def test_tui_tasks_prints_read_only_task_list(capsys, tmp_path: Path) -> None:
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    first = store.create_task("first task", repo_path=tmp_path, task_id="task-1")
    second = store.create_task("second task", repo_path=tmp_path, task_id="task-2")
    store.update_task_status(first.task_id, "done")
    store.update_task_status(second.task_id, "blocked")

    exit_code = main(["tui", "tasks", "--repo", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Tasks" in output
    assert "task-2 [blocked] second task" in output
    assert "task-1 [done] first task" in output
    assert output.index("task-2") < output.index("task-1")


def test_tui_tasks_prints_empty_state(capsys, tmp_path: Path) -> None:
    exit_code = main(["tui", "tasks", "--repo", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "No tasks recorded." in output


def test_tui_approvals_prints_pending_verification_approvals(
    capsys,
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    task = store.create_task("needs approval", repo_path=tmp_path, task_id="task-approval")
    iteration = store.add_iteration(
        task_id=task.task_id,
        iteration_index=1,
        agent_name="mock",
        agent_status="success",
        prompt="needs approval",
        raw_output="done",
        decision_status="blocked",
        decision_reason="Approval required",
    )
    approval = store.add_approval_request(
        task_id=task.task_id,
        iteration_id=iteration.iteration_id,
        source="verification",
        command_string="deploy production",
        reason="Requires approval: deploy",
    )

    exit_code = main(["tui", "approvals", "--repo", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Approvals" in output
    assert f"approval={approval.approval_id} status=pending" in output
    assert f"task=task-approval iteration={iteration.iteration_id}" in output
    assert "command: deploy production" in output
    assert "reason: Requires approval: deploy" in output


def test_tui_approvals_prints_empty_state(capsys, tmp_path: Path) -> None:
    exit_code = main(["tui", "approvals", "--repo", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "No approval requests recorded." in output


def test_tui_current_prints_latest_iteration(capsys, tmp_path: Path) -> None:
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    task = store.create_task("current task", repo_path=tmp_path, task_id="task-current")
    first = store.add_iteration(
        task_id=task.task_id,
        iteration_index=1,
        agent_name="mock",
        agent_status="success",
        prompt="current task",
        raw_output="done",
        decision_status="continue",
        decision_reason="Needs another pass",
    )
    store.add_verification_run(
        task_id=task.task_id,
        iteration_id=first.iteration_id,
        result=VerificationResult(
            name="unit",
            status="failed",
            exit_code=1,
            stdout="",
            stderr="failed",
        ),
    )
    second = store.add_iteration(
        task_id=task.task_id,
        iteration_index=2,
        agent_name="mock",
        agent_status="success",
        prompt="current task",
        raw_output="done",
        decision_status="done",
        decision_reason="Verification passed: unit",
    )
    store.add_verification_run(
        task_id=task.task_id,
        iteration_id=second.iteration_id,
        result=VerificationResult(
            name="unit",
            status="passed",
            exit_code=0,
            stdout="ok",
            stderr="",
        ),
    )

    exit_code = main(["tui", "current", task.task_id, "--repo", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Current iteration for task-current" in output
    assert "Iteration: 2" in output
    assert "Decision: done" in output
    assert "unit: passed exit=0" in output


def test_tui_current_returns_error_for_missing_task(capsys, tmp_path: Path) -> None:
    exit_code = main(["tui", "current", "missing-task", "--repo", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "Task not found: missing-task" in output


def test_tui_current_prints_empty_iteration_state(capsys, tmp_path: Path) -> None:
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    task = store.create_task("empty current", repo_path=tmp_path, task_id="task-empty")

    exit_code = main(["tui", "current", task.task_id, "--repo", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Current iteration for task-empty" in output
    assert "No iterations recorded." in output


def test_tui_logs_prints_iteration_prompt_and_output(capsys, tmp_path: Path) -> None:
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    task = store.create_task("log task", repo_path=tmp_path, task_id="task-logs")
    store.add_iteration(
        task_id=task.task_id,
        iteration_index=1,
        agent_name="mock",
        agent_status="success",
        prompt="please finish",
        raw_output="done output",
        decision_status="done",
        decision_reason="Verification passed: unit",
    )

    exit_code = main(["tui", "logs", task.task_id, "--repo", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Logs for task-logs" in output
    assert "prompt: please finish" in output
    assert "output: done output" in output


def test_tui_logs_returns_error_for_missing_task(capsys, tmp_path: Path) -> None:
    exit_code = main(["tui", "logs", "missing-task", "--repo", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "Task not found: missing-task" in output


def test_report_writes_markdown_file(capsys, tmp_path: Path) -> None:
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    task = store.create_task("demo report", repo_path=tmp_path)
    iteration = store.add_iteration(
        task_id=task.task_id,
        iteration_index=1,
        agent_name="mock",
        agent_status="success",
        prompt="demo report",
        raw_output="done",
        decision_status="done",
        decision_reason="Verification passed: unit",
    )
    store.add_verification_run(
        task_id=task.task_id,
        iteration_id=iteration.iteration_id,
        result=VerificationResult(
            name="unit",
            status="passed",
            exit_code=0,
            stdout="ok",
            stderr="",
        ),
    )
    store.update_task_status(task.task_id, "done")

    exit_code = main(["report", task.task_id, "--repo", str(tmp_path)])
    output = capsys.readouterr().out
    report_path = tmp_path / ".ai-orch" / "reports" / f"{task.task_id}.md"

    assert exit_code == 0
    assert f"Report: {report_path}" in output
    assert report_path.exists()
    report = report_path.read_text(encoding="utf-8")
    assert f"# ai-orch report: {task.task_id}" in report
    assert "- `unit`: `passed` exit=`0`" in report


def test_report_returns_error_for_missing_task(capsys, tmp_path: Path) -> None:
    exit_code = main(["report", "missing-task", "--repo", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "Task not found: missing-task" in output


def test_agents_lists_project_config(capsys, tmp_path: Path) -> None:
    write_config(
        tmp_path,
        default_agent="generic",
        fallback_agents=["mock"],
        include_generic_agent=True,
    )

    exit_code = main(["agents", "--repo", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "default: generic" in output
    assert "fallbacks: mock" in output
    assert "generic: enabled type=generic_cli" in output


def test_agents_check_reports_availability(capsys, tmp_path: Path) -> None:
    write_config(
        tmp_path,
        default_agent="generic",
        include_generic_agent=True,
    )

    exit_code = main(["agents", "--repo", str(tmp_path), "--check"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "mock: enabled type=mock available=yes" in output
    assert "generic: enabled type=generic_cli available=yes" in output


def test_agents_check_reports_missing_binary(capsys, tmp_path: Path) -> None:
    write_config(
        tmp_path,
        default_agent="generic",
        include_generic_agent=True,
        generic_command="missing-ai-orch-agent-binary",
    )

    exit_code = main(["agents", "--repo", str(tmp_path), "--check"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "generic: enabled type=generic_cli available=no" in output


@pytest.mark.parametrize(
    ("agent_name", "agent_type", "expected_command"),
    [
        ("kimi", "kimi", "kimi"),
        ("kimi", "kimi_cli", "kimi"),
        ("gemini", "gemini", "gemini"),
        ("gemini", "gemini_cli", "gemini"),
    ],
)
def test_agents_check_uses_cli_alias_default_command(
    capsys,
    monkeypatch,
    tmp_path: Path,
    agent_name: str,
    agent_type: str,
    expected_command: str,
) -> None:
    checked_commands: list[str] = []

    def fake_check_available(self: ProcessRunner, command: str) -> bool:
        checked_commands.append(command)
        return command == expected_command

    monkeypatch.setattr(ProcessRunner, "check_available", fake_check_available)
    write_config(
        tmp_path,
        default_agent=agent_name,
        cli_alias_agents={agent_name: agent_type},
        cli_alias_commands={agent_name: None},
    )

    exit_code = main(["agents", "--repo", str(tmp_path), "--check"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert f"{agent_name}: enabled type={agent_type} available=yes" in output
    assert checked_commands == [expected_command]


def test_resume_runs_existing_task_and_appends_iteration(capsys, tmp_path: Path) -> None:
    write_config(tmp_path)
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    task = store.create_task("demo task", repo_path=tmp_path)
    store.update_task_status(task.task_id, "blocked")

    exit_code = main(["resume", task.task_id, "--repo", str(tmp_path)])
    output = capsys.readouterr().out
    loaded = store.get_task(task.task_id)
    iterations = store.list_iterations(task.task_id)

    assert exit_code == 0
    assert f"{task.task_id}: Iteration 1: Verification passed: custom" in output
    assert loaded is not None
    assert loaded.status == "done"
    assert len(iterations) == 1
    assert iterations[0].decision_status == "done"


def test_resume_returns_error_for_missing_task(capsys, tmp_path: Path) -> None:
    exit_code = main(["resume", "missing-task", "--repo", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "Task not found: missing-task" in output


def test_verify_uses_project_config(capsys, tmp_path: Path) -> None:
    write_config(tmp_path)

    exit_code = main(["verify", "--repo", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "custom: passed exit=0" in output


def test_verify_strict_mode_fails_without_commands(capsys, tmp_path: Path) -> None:
    config_dir = tmp_path / ".ai-orch"
    config_dir.mkdir()
    (config_dir / "config.yaml").write_text(
        """
verification:
  strict: true
""".lstrip(),
        encoding="utf-8",
    )

    exit_code = main(["verify", "--repo", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "No verification commands configured." in output


def test_release_check_reports_packaging_status(capsys) -> None:
    exit_code = main(["release-check", "--repo", "."])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "pyproject: passed" in output
    assert "version: passed" in output
    assert "entrypoints: passed" in output
    assert "release-docs: passed" in output
    assert all(item.status == "passed" for item in run_release_checks(Path(".")))


def test_start_uses_project_config(capsys, tmp_path: Path) -> None:
    write_config(tmp_path)

    exit_code = main(["start", "--task", "demo", "--repo", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Verification passed: custom" in output


def test_start_strict_mode_blocks_without_verification_commands(
    capsys,
    tmp_path: Path,
) -> None:
    config_dir = tmp_path / ".ai-orch"
    config_dir.mkdir()
    (config_dir / "config.yaml").write_text(
        """
verification:
  strict: true
""".lstrip(),
        encoding="utf-8",
    )

    exit_code = main(["start", "--task", "demo", "--repo", str(tmp_path)])
    output = capsys.readouterr().out
    task_id = output.split(":", 1)[0]
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    task = store.get_task(task_id)

    assert exit_code == 1
    assert "No verification commands configured" in output
    assert task is not None
    assert task.status == "blocked"


def test_start_with_use_memory_enriches_initial_prompt(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    memory_argv: list[list[str]] = []

    def fake_run(self: ProcessRunner, argv: list[str], **kwargs) -> ProcessResult:
        if argv[:2] == ["codebase-memory-mcp", "cli"]:
            memory_argv.append(argv)
            return ProcessResult(
                status="success",
                exit_code=0,
                stdout=f"memory output for {argv[2]}",
                stderr="",
            )
        return ProcessResult(status="success", exit_code=0, stdout="ok", stderr="")

    monkeypatch.setattr(ProcessRunner, "check_available", lambda self, command: True)
    monkeypatch.setattr(ProcessRunner, "run", fake_run)
    write_config(tmp_path, include_memory=True, memory_project="demo")

    exit_code = main(
        [
            "start",
            "--task",
            "demo",
            "--repo",
            str(tmp_path),
            "--use-memory",
            "--memory-area",
            "release",
        ]
    )
    output = capsys.readouterr().out
    task_id = output.split(":", 1)[0]
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    task = store.get_task(task_id)
    iterations = store.list_iteration_details(task_id)

    assert exit_code == 0
    assert task is not None
    assert task.task == "demo"
    assert "Planning context (read-only, non-authoritative)" in iterations[0].prompt
    assert "memory preflight area=release" in iterations[0].prompt
    assert "memory output for get_architecture" in iterations[0].prompt
    assert "memory output for detect_changes" in iterations[0].prompt
    assert [item[2] for item in memory_argv] == ["get_architecture", "detect_changes"]


def test_start_uses_generic_agent_from_project_config(capsys, tmp_path: Path) -> None:
    write_config(tmp_path, default_agent="generic", include_generic_agent=True)

    exit_code = main(["start", "--task", "hello generic", "--repo", str(tmp_path)])
    output = capsys.readouterr().out
    task_id = output.split(":", 1)[0]
    iterations = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db").list_iterations(
        task_id
    )

    assert exit_code == 0
    assert "Verification passed: custom" in output
    assert iterations[0].agent_name == "generic"


def test_start_uses_codex_agent_from_project_config(capsys, tmp_path: Path) -> None:
    write_config(tmp_path, default_agent="codex", include_codex_agent=True)

    exit_code = main(["start", "--task", "hello codex", "--repo", str(tmp_path)])
    output = capsys.readouterr().out
    task_id = output.split(":", 1)[0]
    iterations = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db").list_iterations(
        task_id
    )

    assert exit_code == 0
    assert "Verification passed: custom" in output
    assert iterations[0].agent_name == "codex"


def test_start_uses_claude_agent_from_project_config(capsys, tmp_path: Path) -> None:
    write_config(tmp_path, default_agent="claude", include_claude_agent=True)

    exit_code = main(["start", "--task", "hello claude", "--repo", str(tmp_path)])
    output = capsys.readouterr().out
    task_id = output.split(":", 1)[0]
    iterations = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db").list_iterations(
        task_id
    )

    assert exit_code == 0
    assert "Verification passed: custom" in output
    assert iterations[0].agent_name == "claude"


@pytest.mark.parametrize(
    ("agent_name", "agent_type"),
    [
        ("kimi", "kimi_cli"),
        ("gemini", "gemini_cli"),
    ],
)
def test_start_uses_cli_alias_agent_from_project_config(
    capsys,
    tmp_path: Path,
    agent_name: str,
    agent_type: str,
) -> None:
    write_config(
        tmp_path,
        default_agent=agent_name,
        cli_alias_agents={agent_name: agent_type},
    )

    exit_code = main(["start", "--task", f"hello {agent_name}", "--repo", str(tmp_path)])
    output = capsys.readouterr().out
    task_id = output.split(":", 1)[0]
    iterations = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db").list_iterations(
        task_id
    )

    assert exit_code == 0
    assert "Verification passed: custom" in output
    assert iterations[0].agent_name == agent_name


@pytest.mark.parametrize(
    ("agent_name", "agent_type", "expected_argv"),
    [
        ("kimi", "kimi_cli", ["kimi", "hello kimi"]),
        ("gemini", "gemini_cli", ["gemini", "-p", "hello gemini"]),
    ],
)
def test_start_uses_cli_alias_default_argv(
    capsys,
    monkeypatch,
    tmp_path: Path,
    agent_name: str,
    agent_type: str,
    expected_argv: list[str],
) -> None:
    captured_argv: list[list[str]] = []

    def fake_check_available(self: ProcessRunner, command: str) -> bool:
        return command == expected_argv[0]

    def fake_run(
        self: ProcessRunner,
        argv: list[str],
        cwd: Path | None = None,
        timeout_sec: int = 300,
        should_cancel=None,
        options: RunOptions | None = None,
    ) -> ProcessResult:
        captured_argv.append(argv)
        return ProcessResult(
            status="success",
            exit_code=0,
            stdout=f"{agent_name} ok",
            stderr="",
        )

    def fake_run_many(self: VerificationRunner, commands, cwd=None):
        return [
            VerificationResult(
                name="custom",
                status="passed",
                exit_code=0,
                stdout="",
                stderr="",
            )
        ]

    monkeypatch.setattr(ProcessRunner, "check_available", fake_check_available)
    monkeypatch.setattr(ProcessRunner, "run", fake_run)
    monkeypatch.setattr(VerificationRunner, "run_many", fake_run_many)
    write_config(
        tmp_path,
        default_agent=agent_name,
        cli_alias_agents={agent_name: agent_type},
        cli_alias_commands={agent_name: None},
        cli_alias_args={agent_name: None},
    )

    exit_code = main(["start", "--task", f"hello {agent_name}", "--repo", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Verification passed: custom" in output
    assert captured_argv == [expected_argv]


def test_start_uses_fallback_agent_when_default_unavailable(
    capsys,
    tmp_path: Path,
) -> None:
    write_config(
        tmp_path,
        default_agent="generic",
        fallback_agents=["mock"],
        include_generic_agent=True,
        generic_command="missing-ai-orch-agent-binary",
    )

    exit_code = main(["start", "--task", "hello fallback", "--repo", str(tmp_path)])
    output = capsys.readouterr().out
    task_id = output.split(":", 1)[0]
    iterations = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db").list_iterations(
        task_id
    )

    assert exit_code == 0
    assert "Verification passed: custom" in output
    assert iterations[0].agent_name == "mock"


def test_start_blocks_generic_agent_command_from_project_policy(
    capsys,
    tmp_path: Path,
) -> None:
    marker = tmp_path / "generic-ran.txt"
    write_config(
        tmp_path,
        default_agent="generic",
        include_generic_agent=True,
        generic_args=[
            "-c",
            (
                "import pathlib, sys; "
                "pathlib.Path(sys.argv[1]).joinpath('generic-ran.txt').write_text('ran')"
            ),
            "{repo}",
        ],
        deny_patterns=["write_text"],
    )

    exit_code = main(["start", "--task", "dangerous generic", "--repo", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "Denied by pattern: write_text" in output
    assert not marker.exists()


def test_verify_blocks_command_that_requires_approval(capsys, tmp_path: Path) -> None:
    write_config(
        tmp_path,
        command_name="push",
        command_run="git push origin main",
    )

    exit_code = main(["verify", "--repo", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "push: needs_approval exit=None" in output


def test_verify_uses_policy_rules_from_project_config(capsys, tmp_path: Path) -> None:
    write_config(
        tmp_path,
        command_name="deploy",
        command_run="deploy production",
        require_approval_patterns=["deploy"],
    )

    exit_code = main(["verify", "--repo", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "deploy: needs_approval exit=None" in output


def test_verify_approves_exact_command_from_cli(capsys, tmp_path: Path) -> None:
    command = "python -c \"print('approval-token ok')\""
    write_config(
        tmp_path,
        command_name="approval",
        command_run=command,
        require_approval_patterns=["approval-token"],
    )

    exit_code = main(
        [
            "verify",
            "--repo",
            str(tmp_path),
            "--approve-command",
            command,
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "approval: passed exit=0" in output


def test_memory_status_prints_provider_config(capsys, monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(ProcessRunner, "check_available", lambda self, command: True)
    write_config(tmp_path, include_memory=True, memory_project="demo")

    exit_code = main(["memory", "status", "--repo", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "provider: codebase-memory-mcp" in output
    assert "command: codebase-memory-mcp cli" in output
    assert "project: demo" in output
    assert "available: yes" in output


def test_memory_search_runs_read_only_tool(capsys, monkeypatch, tmp_path: Path) -> None:
    captured_argv: list[list[str]] = []

    def fake_run(
        self: ProcessRunner,
        argv: list[str],
        cwd: Path | None = None,
        timeout_sec: int = 300,
        terminate_grace_sec: int = 5,
        should_cancel=None,
        options: RunOptions | None = None,
    ) -> ProcessResult:
        captured_argv.append(argv)
        return ProcessResult(
            status="success",
            exit_code=0,
            stdout='{"results":[]}',
            stderr="",
        )

    monkeypatch.setattr(ProcessRunner, "run", fake_run)
    write_config(tmp_path, include_memory=True, memory_project="demo")

    exit_code = main(
        [
            "memory",
            "search",
            "--repo",
            str(tmp_path),
            "--pattern",
            ".*Supervisor.*",
            "--label",
            "Class",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "search_graph: passed exit=0" in output
    assert captured_argv == [
        [
            "codebase-memory-mcp",
            "cli",
            "search_graph",
            '{"label": "Class", "limit": 20, "name_pattern": ".*Supervisor.*", "project": "demo"}',
        ]
    ]


def test_memory_index_requires_explicit_approval(capsys, monkeypatch, tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def fake_run(self: ProcessRunner, argv: list[str], **kwargs) -> ProcessResult:
        calls.append(argv)
        return ProcessResult(status="success", exit_code=0, stdout="indexed", stderr="")

    monkeypatch.setattr(ProcessRunner, "run", fake_run)
    write_config(tmp_path, include_memory=True)

    exit_code = main(["memory", "index", "--repo", str(tmp_path)])
    output = capsys.readouterr().out
    approvals = StateStore(
        tmp_path / ".ai-orch" / "state" / "ai-orch.db"
    ).list_approval_requests(status="pending")

    assert exit_code == 1
    assert "approval_request:" in output
    assert "index_repository: needs_approval exit=None" in output
    assert "Codebase Memory tool requires approval: index_repository" in output
    assert calls == []
    assert len(approvals) == 1
    assert approvals[0].source == "memory"
    assert approvals[0].command_string.startswith("codebase-memory-mcp cli index_repository")
    assert "repo_path" in approvals[0].command_string
    assert approvals[0].reason == "Codebase Memory tool requires approval: index_repository"


def test_memory_index_runs_with_approve_flag(capsys, monkeypatch, tmp_path: Path) -> None:
    captured_argv: list[list[str]] = []

    def fake_run(self: ProcessRunner, argv: list[str], **kwargs) -> ProcessResult:
        captured_argv.append(argv)
        return ProcessResult(status="success", exit_code=0, stdout="indexed", stderr="")

    monkeypatch.setattr(ProcessRunner, "run", fake_run)
    write_config(tmp_path, include_memory=True)

    exit_code = main(["memory", "index", "--repo", str(tmp_path), "--approve"])
    output = capsys.readouterr().out
    approvals = StateStore(
        tmp_path / ".ai-orch" / "state" / "ai-orch.db"
    ).list_approval_requests()

    assert exit_code == 0
    assert "index_repository: passed exit=0" in output
    assert approvals == []
    assert captured_argv == [
        [
            "codebase-memory-mcp",
            "cli",
            "index_repository",
            json.dumps({"repo_path": str(tmp_path.resolve())}, sort_keys=True),
        ]
    ]


def test_memory_preflight_adapter_runs_read_only_steps(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    captured_argv: list[list[str]] = []

    def fake_run(self: ProcessRunner, argv: list[str], **kwargs) -> ProcessResult:
        captured_argv.append(argv)
        return ProcessResult(status="success", exit_code=0, stdout="{}", stderr="")

    monkeypatch.setattr(ProcessRunner, "check_available", lambda self, command: True)
    monkeypatch.setattr(ProcessRunner, "run", fake_run)
    write_config(tmp_path, include_memory=True, memory_project="demo")

    exit_code = main(
        [
            "memory",
            "preflight",
            "--repo",
            str(tmp_path),
            "--area",
            "adapter",
            "--limit",
            "7",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "preflight: area=adapter" in output
    assert "available: yes" in output
    assert captured_argv == [
        [
            "codebase-memory-mcp",
            "cli",
            "get_architecture",
            '{"aspects": ["all"], "project": "demo"}',
        ],
        [
            "codebase-memory-mcp",
            "cli",
            "search_graph",
            '{"limit": 7, "name_pattern": ".*Adapter.*", "project": "demo"}',
        ],
        [
            "codebase-memory-mcp",
            "cli",
            "search_graph",
            '{"label": "Class", "limit": 7, "name_pattern": ".*CLI.*", "project": "demo"}',
        ],
        [
            "codebase-memory-mcp",
            "cli",
            "search_graph",
            '{"limit": 7, "name_pattern": ".*ProcessRunner.*", "project": "demo"}',
        ],
        [
            "codebase-memory-mcp",
            "cli",
            "search_graph",
            '{"label": "Class", "limit": 7, "name_pattern": ".*Policy.*", "project": "demo"}',
        ],
        [
            "codebase-memory-mcp",
            "cli",
            "detect_changes",
            '{"project": "demo"}',
        ],
    ]


def test_memory_preflight_returns_failure_when_any_step_fails(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    calls = 0

    def fake_run(self: ProcessRunner, argv: list[str], **kwargs) -> ProcessResult:
        nonlocal calls
        calls += 1
        if calls == 2:
            return ProcessResult(status="failed", exit_code=2, stdout="", stderr="bad")
        return ProcessResult(status="success", exit_code=0, stdout="ok", stderr="")

    monkeypatch.setattr(ProcessRunner, "check_available", lambda self, command: True)
    monkeypatch.setattr(ProcessRunner, "run", fake_run)
    write_config(tmp_path, include_memory=True)

    exit_code = main(["memory", "preflight", "--repo", str(tmp_path), "--area", "release"])
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "detect_changes: failed exit=2" in output
    assert calls == 2


def write_config(
    repo: Path,
    command_name: str = "custom",
    command_run: str = "python -c \"print('ok')\"",
    deny_patterns: list[str] | None = None,
    require_approval_patterns: list[str] | None = None,
    default_agent: str = "mock",
    fallback_agents: list[str] | None = None,
    include_generic_agent: bool = False,
    include_codex_agent: bool = False,
    include_claude_agent: bool = False,
    cli_alias_agents: dict[str, str] | None = None,
    cli_alias_commands: dict[str, str | None] | None = None,
    cli_alias_args: dict[str, list[str] | None] | None = None,
    generic_command: str = "python",
    generic_args: list[str] | None = None,
    include_memory: bool = False,
    memory_project: str = "",
) -> None:
    config_dir = repo / ".ai-orch"
    config_dir.mkdir(parents=True, exist_ok=True)
    deny_patterns = deny_patterns or []
    require_approval_patterns = require_approval_patterns or []
    policy_section = ""
    if deny_patterns or require_approval_patterns:
        deny_lines = "\n".join(f'    - "{pattern}"' for pattern in deny_patterns)
        approval_lines = "\n".join(
            f'    - "{pattern}"' for pattern in require_approval_patterns
        )
        policy_section = "\npolicy:\n"
        if deny_patterns:
            policy_section += f"  deny:\n{deny_lines}\n"
        if require_approval_patterns:
            policy_section += f"  require_approval:\n{approval_lines}\n"
    agent_blocks = [
        """
  mock:
    enabled: true
    type: "mock"
""".rstrip()
    ]
    if include_generic_agent:
        rendered_args = generic_args or [
            "-c",
            "import sys; print(sys.argv[1])",
            "{prompt}",
        ]
        generic_arg_lines = "\n".join(f'      - "{arg}"' for arg in rendered_args)
        agent_blocks.append(
            """
  generic:
    enabled: true
    type: "generic_cli"
    command: "{generic_command}"
    args:
{generic_arg_lines}
    timeout_sec: 30
""".format(
                generic_command=generic_command,
                generic_arg_lines=generic_arg_lines,
            ).rstrip()
        )
    if include_codex_agent:
        agent_blocks.append(
            """
  codex:
    enabled: true
    type: "codex_exec"
    command: "python"
    args:
      - "-c"
      - "print('codex ok')"
    timeout_sec: 30
""".rstrip()
        )
    if include_claude_agent:
        agent_blocks.append(
            """
  claude:
    enabled: true
    type: "claude_headless"
    command: "python"
    args:
      - "-c"
      - "print('claude ok')"
    timeout_sec: 30
""".rstrip()
        )
    cli_alias_commands = cli_alias_commands or {}
    cli_alias_args = cli_alias_args or {}
    for agent_name, agent_type in (cli_alias_agents or {}).items():
        command = cli_alias_commands.get(agent_name, "python")
        command_line = f'    command: "{command}"\n' if command is not None else ""
        args = cli_alias_args.get(
            agent_name,
            [
                "-c",
                f"print('{agent_name} ok')",
            ],
        )
        args_lines = ""
        if args is not None:
            rendered_args = "\n".join(f'      - "{arg}"' for arg in args)
            args_lines = f"    args:\n{rendered_args}\n"
        agent_blocks.append(
            f"""
  {agent_name}:
    enabled: true
    type: "{agent_type}"
{command_line}{args_lines}    timeout_sec: 30
""".rstrip()
        )
    agents_section = "agents:\n" + "\n".join(agent_blocks)
    fallback_section = ""
    if fallback_agents:
        fallback_lines = "\n".join(f'    - "{agent}"' for agent in fallback_agents)
        fallback_section = f"  fallback_agents:\n{fallback_lines}\n"
    memory_section = ""
    if include_memory:
        memory_section = f"""

memory:
  provider: "codebase-memory-mcp"
  command:
    - "codebase-memory-mcp"
    - "cli"
  project: "{memory_project}"
  timeout_sec: 45
"""

    (config_dir / "config.yaml").write_text(
        f"""
orchestrator:
  default_agent: "{default_agent}"
{fallback_section}  max_iterations: 3

{agents_section}

verification:
  commands:
    - name: "{command_name}"
      run: "{command_run}"
      timeout_sec: 30
{policy_section}
{memory_section}
""".lstrip(),
        encoding="utf-8",
    )
