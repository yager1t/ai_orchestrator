import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ai_orchestrator import __version__
from ai_orchestrator.autopilot import load_plan_tasks
from ai_orchestrator.cli.app import main
from ai_orchestrator.core.supervisor import Supervisor, SupervisorResult
from ai_orchestrator.process.runner import ProcessResult, ProcessRunner, RunOptions
from ai_orchestrator.storage.db import StateStore
from ai_orchestrator.verification.release import ReleaseCheckResult, run_release_checks
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


def test_metrics_prints_local_summary(capsys, tmp_path: Path) -> None:
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    task = store.create_task("demo task", repo_path=tmp_path)
    iteration = store.add_iteration(
        task_id=task.task_id,
        iteration_index=1,
        agent_name="generic",
        agent_status="failed",
        prompt="demo task",
        raw_output="failed",
        decision_status="blocked",
        decision_reason="agent failed",
    )
    store.add_verification_run(
        task_id=task.task_id,
        iteration_id=iteration.iteration_id,
        result=VerificationResult(
            name="unit",
            status="failed",
            exit_code=1,
            stdout="",
            stderr="failed",
        ),
    )
    approval = store.add_approval_request(
        task_id=task.task_id,
        iteration_id=iteration.iteration_id,
        source="verification",
        command_string="git push",
        reason="approval required",
    )
    store.resolve_approval_request(approval.approval_id, status="approved")

    exit_code = main(["metrics", "--repo", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Metrics" in output
    assert "tasks: 1" in output
    assert "iterations: 1" in output
    assert "verification: total=1 passed=0 not_passed=1 pass_rate=0.0%" in output
    assert "approvals: total=1 pending=0 approved=1 rejected=0 stale=0" in output
    assert "adapter_failures: 1" in output


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


def test_export_writes_json_trace_file(capsys, tmp_path: Path) -> None:
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    task = store.create_task("demo export", repo_path=tmp_path)
    iteration = store.add_iteration(
        task_id=task.task_id,
        iteration_index=1,
        agent_name="mock",
        agent_status="success",
        prompt="demo export",
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
    approval = store.add_approval_request(
        task_id=task.task_id,
        iteration_id=iteration.iteration_id,
        source="verification",
        command_string="git push",
        reason="approval required",
    )
    store.resolve_approval_request(approval.approval_id, status="approved")
    store.update_task_status(task.task_id, "done")

    exit_code = main(["export", task.task_id, "--repo", str(tmp_path)])
    output = capsys.readouterr().out
    trace_path = tmp_path / ".ai-orch" / "traces" / f"{task.task_id}.json"

    assert exit_code == 0
    assert f"Trace: {trace_path}" in output
    assert trace_path.exists()

    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    assert trace["metadata"]["schema_version"] == "1.0"
    assert trace["metadata"]["task_id"] == task.task_id
    assert trace["metadata"]["redaction_mode"] == "none"
    assert "exported_at" in trace["metadata"]
    assert trace["task"]["task_id"] == task.task_id
    assert trace["task"]["status"] == "done"
    assert len(trace["iterations"]) == 1
    assert trace["iterations"][0]["prompt"] == "demo export"
    assert trace["iterations"][0]["decision_status"] == "done"
    assert len(trace["verification_runs"]) == 1
    assert trace["verification_runs"][0]["name"] == "unit"
    assert trace["verification_runs"][0]["status"] == "passed"
    assert trace["verification_runs"][0]["stdout"] == "ok"
    assert len(trace["approvals"]) == 1
    assert trace["approvals"][0]["status"] == "approved"


def test_export_returns_error_for_missing_task(capsys, tmp_path: Path) -> None:
    exit_code = main(["export", "missing-task", "--repo", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "Task not found: missing-task" in output


def test_export_writes_to_custom_output_path(capsys, tmp_path: Path) -> None:
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    task = store.create_task("custom export", repo_path=tmp_path)
    store.update_task_status(task.task_id, "blocked")

    custom_path = tmp_path / "trace.json"
    exit_code = main(
        ["export", task.task_id, "--repo", str(tmp_path), "--output", str(custom_path)]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert f"Trace: {custom_path}" in output
    assert custom_path.exists()

    trace = json.loads(custom_path.read_text(encoding="utf-8"))
    assert trace["task"]["task_id"] == task.task_id
    assert trace["task"]["status"] == "blocked"


def test_export_redact_flag_omits_bulky_fields(capsys, tmp_path: Path) -> None:
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    task = store.create_task("redacted export", repo_path=tmp_path)
    iteration = store.add_iteration(
        task_id=task.task_id,
        iteration_index=1,
        agent_name="mock",
        agent_status="success",
        prompt="demo redact",
        raw_output="bulky raw output",
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
            stdout="bulky stdout",
            stderr="bulky stderr",
        ),
    )
    store.update_task_status(task.task_id, "done")

    exit_code = main(["export", task.task_id, "--repo", str(tmp_path), "--redact"])
    output = capsys.readouterr().out
    trace_path = tmp_path / ".ai-orch" / "traces" / f"{task.task_id}.json"

    assert exit_code == 0
    assert f"Trace: {trace_path}" in output
    assert trace_path.exists()

    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    assert trace["metadata"]["redaction_mode"] == "redacted"
    assert trace["iterations"][0]["prompt"] == "demo redact"
    assert "raw_output" not in trace["iterations"][0]
    assert trace["verification_runs"][0]["name"] == "unit"
    assert trace["verification_runs"][0]["status"] == "passed"
    assert "stdout" not in trace["verification_runs"][0]
    assert "stderr" not in trace["verification_runs"][0]

    loaded_iteration = store.list_iteration_details(task.task_id)[0]
    assert loaded_iteration.raw_output == "bulky raw output"
    loaded_run = store.list_verification_details(task.task_id)[0]
    assert loaded_run.stdout == "bulky stdout"
    assert loaded_run.stderr == "bulky stderr"


def test_export_without_redact_keeps_bulky_fields(capsys, tmp_path: Path) -> None:
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    task = store.create_task("full export", repo_path=tmp_path)
    iteration = store.add_iteration(
        task_id=task.task_id,
        iteration_index=1,
        agent_name="mock",
        agent_status="success",
        prompt="demo full",
        raw_output="raw agent output",
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
            stdout="verification stdout",
            stderr="verification stderr",
        ),
    )

    exit_code = main(["export", task.task_id, "--repo", str(tmp_path)])
    output = capsys.readouterr().out
    trace_path = tmp_path / ".ai-orch" / "traces" / f"{task.task_id}.json"

    assert exit_code == 0
    assert f"Trace: {trace_path}" in output
    assert trace_path.exists()

    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    assert trace["iterations"][0]["raw_output"] == "raw agent output"
    assert trace["verification_runs"][0]["stdout"] == "verification stdout"
    assert trace["verification_runs"][0]["stderr"] == "verification stderr"


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


def test_agents_lists_adapter_profile(capsys, tmp_path: Path) -> None:
    config_dir = tmp_path / ".ai-orch"
    config_dir.mkdir()
    (config_dir / "config.yaml").write_text(
        """
orchestrator:
  default_agent: "generic"

adapter_profiles:
  python-profile:
    type: "generic_cli"
    command: "python"

agents:
  generic:
    enabled: true
    profile: "python-profile"
""".lstrip(),
        encoding="utf-8",
    )

    exit_code = main(["agents", "--repo", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "generic: enabled type=generic_cli profile=python-profile" in output


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


def test_ci_runs_verification_and_release_checks(
    capsys, monkeypatch, tmp_path: Path
) -> None:
    write_config(tmp_path)
    monkeypatch.setattr(
        "ai_orchestrator.cli.app.run_release_checks",
        lambda repo: [
            ReleaseCheckResult(name="pyproject", status="passed", detail="ok"),
            ReleaseCheckResult(name="version", status="passed", detail="ok"),
        ],
    )

    exit_code = main(["ci", "--repo", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "verification:" in output
    assert "custom: passed exit=0" in output
    assert "release:" in output
    assert "pyproject: passed" in output
    assert "version: passed" in output


def test_ci_fails_when_verification_fails(capsys, tmp_path: Path) -> None:
    write_config(tmp_path, command_run="python -c 'import sys; sys.exit(1)'")

    exit_code = main(["ci", "--repo", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "custom: failed exit=1" in output
    assert "release:" in output


def test_ci_fails_when_release_check_fails(
    capsys, monkeypatch, tmp_path: Path
) -> None:
    write_config(tmp_path)
    monkeypatch.setattr(
        "ai_orchestrator.cli.app.run_release_checks",
        lambda repo: [
            ReleaseCheckResult(
                name="release-docs",
                status="failed",
                detail="Missing docs: CHANGELOG.md",
            ),
        ],
    )

    exit_code = main(["ci", "--repo", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "custom: passed exit=0" in output
    assert "release-docs: failed" in output


def test_ci_approves_exact_verification_command(
    capsys, monkeypatch, tmp_path: Path
) -> None:
    command = "python -c \"print('approval-token ok')\""
    write_config(
        tmp_path,
        command_name="approval",
        command_run=command,
        require_approval_patterns=["approval-token"],
    )
    monkeypatch.setattr(
        "ai_orchestrator.cli.app.run_release_checks",
        lambda repo: [
            ReleaseCheckResult(name="pyproject", status="passed", detail="ok"),
        ],
    )

    exit_code = main(
        [
            "ci",
            "--repo",
            str(tmp_path),
            "--approve-command",
            command,
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "approval: passed exit=0" in output
    assert "release:" in output


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


def test_start_uses_opt_in_worktree_isolation(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    write_config(tmp_path)
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    captured_repos: list[Path] = []

    def fake_validate(repo: Path, candidate: Path) -> str | None:
        assert repo == tmp_path
        assert candidate == worktree.resolve()
        return None

    def fake_run_once(
        self, task: str, repo: Path, planning_context=None
    ) -> SupervisorResult:
        captured_repos.append(repo)
        return SupervisorResult(
            status="done", summary="Verification passed: custom", task_id="task-1"
        )

    monkeypatch.setattr(
        "ai_orchestrator.cli.app._validate_autopilot_worktree", fake_validate
    )
    monkeypatch.setattr("ai_orchestrator.cli.app.Supervisor.run_once", fake_run_once)

    exit_code = main(
        [
            "start",
            "--task",
            "demo",
            "--repo",
            str(tmp_path),
            "--worktree",
            str(worktree),
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "task-1: Verification passed: custom" in output
    assert captured_repos == [worktree.resolve()]


def test_start_blocks_invalid_worktree_before_execution(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    write_config(tmp_path)
    worktree = tmp_path / "not-worktree"

    def fake_validate(repo: Path, candidate: Path) -> str | None:
        return f"worktree path does not exist: {candidate}"

    def fake_run_once(
        self, task: str, repo: Path, planning_context=None
    ) -> SupervisorResult:
        raise AssertionError("supervisor should not start with an invalid worktree")

    monkeypatch.setattr(
        "ai_orchestrator.cli.app._validate_autopilot_worktree", fake_validate
    )
    monkeypatch.setattr("ai_orchestrator.cli.app.Supervisor.run_once", fake_run_once)

    exit_code = main(
        [
            "start",
            "--task",
            "demo",
            "--repo",
            str(tmp_path),
            "--worktree",
            str(worktree),
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "Execution blocked: worktree path does not exist:" in output


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
    assert "preflight summary: area=adapter total=6 passed=6 failed=0" in output
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


def test_autopilot_queue_sync_loads_plan_items_without_duplicates(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text(
        "\n".join(
            [
                "# Roadmap",
                "",
                "- [ ] First task",
                "- [ ] Second task",
            ]
        ),
        encoding="utf-8",
    )

    exit_code = main(
        ["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Synced" in output
    assert "new: 2" in output
    assert "existing: 0" in output
    assert "+ " in output

    exit_code = main(
        ["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "new: 0" in output
    assert "existing: 2" in output


def test_autopilot_queue_sync_backlog_loads_open_priority_items(
    capsys,
    tmp_path: Path,
) -> None:
    backlog = tmp_path / "BACKLOG.md"
    backlog.write_text(
        "\n".join(
            [
                "# Backlog",
                "",
                "## P2",
                "",
                "- Add deeper queue history filters if recent status summaries are not enough",
                "  for daily operation.",
                "",
                "## P3 / Deferred",
                "",
                "- Defer web dashboard.",
            ]
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "autopilot",
            "queue",
            "sync-backlog",
            "--repo",
            str(tmp_path),
            "--backlog",
            str(backlog),
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Synced backlog" in output
    assert "priorities: P0, P1, P2" in output
    assert "new: 1" in output
    assert "existing: 0" in output
    assert "Add deeper queue history filters" in output
    assert "Defer web dashboard" not in output

    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    items = store.list_plan_items(plan_path=backlog)
    assert len(items) == 1
    assert items[0].section == "P2"

    exit_code = main(
        [
            "autopilot",
            "queue",
            "sync-backlog",
            "--repo",
            str(tmp_path),
            "--backlog",
            str(backlog),
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "new: 0" in output
    assert "existing: 1" in output


def test_autopilot_queue_list_shows_status_without_running_execution(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Add approval CLI\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])

    exit_code = main(
        ["autopilot", "queue", "list", "--repo", str(tmp_path), "--plan", str(plan)]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Queue status" in output
    assert "total: 1" in output
    assert "[created]" in output
    assert "Add approval CLI" in output
    assert "Autopilot selected:" not in output
    assert "Dry run" not in output


def test_autopilot_queue_list_filters_by_status_and_limit(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text(
        "\n".join(
            [
                "- [ ] Created task",
                "- [ ] Done task",
                "- [ ] Blocked task",
            ]
        ),
        encoding="utf-8",
    )

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    items = {item.text: item for item in store.list_plan_items(plan_path=plan)}
    store.update_plan_item_status(items["Done task"].plan_item_id, "done")
    store.update_plan_item_status(items["Blocked task"].plan_item_id, "blocked")
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "list",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--status",
            "done",
            "--status",
            "blocked",
            "--limit",
            "1",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "total: 3" in output
    assert "filtered: 2 status=done,blocked" in output
    assert "limit: 1" in output
    assert "showing: 1" in output
    assert "[done]" in output
    assert "Done task" in output
    assert "Blocked task" not in output
    assert "Created task" not in output


def test_autopilot_queue_list_all_plans_filters_across_sources(
    capsys,
    tmp_path: Path,
) -> None:
    roadmap = tmp_path / "ROADMAP.md"
    backlog = tmp_path / "BACKLOG.md"
    roadmap.write_text("- [ ] Roadmap done task\n", encoding="utf-8")
    backlog.write_text("- [ ] Backlog created task\n", encoding="utf-8")

    main(
        [
            "autopilot",
            "queue",
            "sync",
            "--repo",
            str(tmp_path),
            "--plan",
            str(roadmap),
        ]
    )
    main(
        [
            "autopilot",
            "queue",
            "sync",
            "--repo",
            str(tmp_path),
            "--plan",
            str(backlog),
        ]
    )
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    roadmap_item = store.list_plan_items(plan_path=roadmap)[0]
    store.update_plan_item_status(roadmap_item.plan_item_id, "done")
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "list",
            "--repo",
            str(tmp_path),
            "--all-plans",
            "--status",
            "done",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Queue status for all persisted plans" in output
    assert "total: 2" in output
    assert "filtered: 1 status=done" in output
    assert f"[done] {roadmap}:" in output
    assert "Roadmap done task" in output
    assert "Backlog created task" not in output


def test_autopilot_queue_sync_works_when_no_unstarted_task_exists(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Already started task\n", encoding="utf-8")
    tasks = load_plan_tasks(plan)
    store = StateStore(tmp_path / "state.db")
    store.create_task(tasks[0].to_prompt(), repo_path=tmp_path)

    exit_code = main(
        ["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Synced" in output
    assert "new: 1" in output
    assert "No unstarted plan items found" not in output


def test_autopilot_queue_list_handles_missing_plan(capsys, tmp_path: Path) -> None:
    missing_plan = tmp_path / "MISSING.md"

    exit_code = main(
        [
            "autopilot",
            "queue",
            "list",
            "--repo",
            str(tmp_path),
            "--plan",
            str(missing_plan),
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "Plan not found:" in output


def test_autopilot_queue_list_shows_report_path_for_completed_item(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Completed task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    item = store.list_plan_items(plan_path=plan)[0]
    task = store.create_task(
        "Completed task", repo_path=tmp_path, task_id="task-report-list"
    )
    iteration = store.add_iteration(
        task_id=task.task_id,
        iteration_index=1,
        agent_name="mock",
        agent_status="success",
        prompt="Completed task",
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
    worktree = tmp_path / "worktrees" / "task-1"
    store.update_plan_item_status(
        item.plan_item_id,
        "done",
        task_id=task.task_id,
        selected_worktree_path=worktree,
    )
    report_path = tmp_path / ".ai-orch" / "reports" / f"{task.task_id}.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("# report", encoding="utf-8")

    exit_code = main(
        ["autopilot", "queue", "list", "--repo", str(tmp_path), "--plan", str(plan)]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "[done]" in output
    assert f"worktree={worktree}" in output
    assert f"report={report_path}" in output


def test_autopilot_queue_list_and_status_show_persisted_item_id(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("# Roadmap\n\n- [ ] Trackable task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    item = store.list_plan_items(plan_path=plan)[0]

    main(
        ["autopilot", "queue", "list", "--repo", str(tmp_path), "--plan", str(plan)]
    )
    list_output = capsys.readouterr().out
    assert f"id={item.plan_item_id}" in list_output
    assert item.line_number != item.plan_item_id
    assert f"id={item.line_number} " not in list_output

    main(
        ["autopilot", "queue", "status", "--repo", str(tmp_path), "--plan", str(plan)]
    )
    status_output = capsys.readouterr().out
    assert f"id={item.plan_item_id}" in status_output
    assert f"id={item.line_number} " not in status_output


def test_autopilot_queue_run_next_defaults_to_dry_run(capsys, tmp_path: Path) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Add approval CLI\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    plan_item_id = store.list_plan_items(plan_path=plan)[0].plan_item_id

    exit_code = main(
        ["autopilot", "queue", "run-next", "--repo", str(tmp_path), "--plan", str(plan)]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Autopilot selected:" in output
    assert "Task: Add approval CLI" in output
    assert f"Queue item: {plan_item_id}" in output
    assert "Dry run: add --execute" in output
    item = store.get_plan_item(plan_item_id)
    assert item is not None
    assert item.status == "created"
    assert item.task_id is None


def test_autopilot_queue_run_next_executes_one_item_and_updates_status(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text(
        "\n".join(
            [
                "- [ ] First task",
                "- [ ] Second task",
            ]
        ),
        encoding="utf-8",
    )

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    first_item = store.list_plan_items(plan_path=plan)[0]

    def fake_run_once(
        self: Supervisor,
        task: str,
        repo: Path,
        planning_context=None,
    ) -> SupervisorResult:
        stored = self.state_store.create_task(task, repo_path=repo, task_id="task-1")
        return SupervisorResult(
            status="done",
            summary="Verification passed: custom",
            task_id=stored.task_id,
        )

    monkeypatch.setattr("ai_orchestrator.cli.app.Supervisor.run_once", fake_run_once)

    exit_code = main(
        [
            "autopilot",
            "queue",
            "run-next",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--execute",
            "--allow-mock-agent",
            "--allow-dirty",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert f"Queue item: {first_item.plan_item_id}" in output
    assert "status=done" in output

    items = {item.text: item for item in store.list_plan_items(plan_path=plan)}
    assert items["First task"].status == "done"
    assert items["First task"].task_id == "task-1"
    assert items["Second task"].status == "created"


def test_autopilot_queue_run_next_writes_report_and_prints_path(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] First task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])

    def fake_run_once(
        self: Supervisor,
        task: str,
        repo: Path,
        planning_context=None,
    ) -> SupervisorResult:
        stored = self.state_store.create_task(task, repo_path=repo, task_id="task-report-1")
        iteration = self.state_store.add_iteration(
            task_id=stored.task_id,
            iteration_index=1,
            agent_name="mock",
            agent_status="success",
            prompt=task,
            raw_output="done",
            decision_status="done",
            decision_reason="Verification passed: unit",
        )
        self.state_store.add_verification_run(
            task_id=stored.task_id,
            iteration_id=iteration.iteration_id,
            result=VerificationResult(
                name="unit",
                status="passed",
                exit_code=0,
                stdout="ok",
                stderr="",
            ),
        )
        self.state_store.update_task_status(stored.task_id, "done")
        return SupervisorResult(
            status="done",
            summary="Verification passed: custom",
            task_id=stored.task_id,
        )

    monkeypatch.setattr("ai_orchestrator.cli.app.Supervisor.run_once", fake_run_once)

    exit_code = main(
        [
            "autopilot",
            "queue",
            "run-next",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--execute",
            "--allow-mock-agent",
            "--allow-dirty",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    report_path = tmp_path / ".ai-orch" / "reports" / "task-report-1.md"
    assert report_path.exists()
    assert f"Report: {report_path}" in output
    report_text = report_path.read_text(encoding="utf-8")
    assert "# ai-orch report: task-report-1" in report_text
    assert "- Status: `done`" in report_text


def test_autopilot_queue_run_next_stops_on_blocked_result(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] First task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])

    def fake_run_once(
        self: Supervisor,
        task: str,
        repo: Path,
        planning_context=None,
    ) -> SupervisorResult:
        stored = self.state_store.create_task(task, repo_path=repo, task_id="task-2")
        return SupervisorResult(
            status="blocked",
            summary="Agent failed",
            task_id=stored.task_id,
        )

    monkeypatch.setattr("ai_orchestrator.cli.app.Supervisor.run_once", fake_run_once)

    exit_code = main(
        [
            "autopilot",
            "queue",
            "run-next",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--execute",
            "--allow-mock-agent",
            "--allow-dirty",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "Queue item" in output
    assert "status=blocked" in output

    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    item = store.list_plan_items(plan_path=plan)[0]
    assert item.status == "blocked"
    assert item.task_id == "task-2"


def test_autopilot_queue_run_next_returns_zero_when_no_ready_items(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Only task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    item = store.list_plan_items(plan_path=plan)[0]
    store.update_plan_item_status(item.plan_item_id, "done")

    exit_code = main(
        ["autopilot", "queue", "run-next", "--repo", str(tmp_path), "--plan", str(plan)]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "No queued plan items ready" in output


def test_autopilot_queue_run_next_passes_timeout_and_records_blocked_reason_when_budget_exhausted(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] First task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])

    captured_budgets: list[int | None] = []

    def fake_run_once(
        self: Supervisor,
        task: str,
        repo: Path,
        planning_context=None,
    ) -> SupervisorResult:
        captured_budgets.append(self.max_runtime_sec)
        stored = self.state_store.create_task(
            task, repo_path=repo, task_id="task-budget-1"
        )
        return SupervisorResult(
            status="blocked",
            summary="Runtime budget exhausted",
            task_id=stored.task_id,
        )

    monkeypatch.setattr("ai_orchestrator.cli.app.Supervisor.run_once", fake_run_once)

    exit_code = main(
        [
            "autopilot",
            "queue",
            "run-next",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--execute",
            "--allow-mock-agent",
            "--allow-dirty",
            "--max-runtime-sec",
            "42",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "Queue item" in output
    assert "status=blocked" in output
    assert captured_budgets == [42]

    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    item = store.list_plan_items(plan_path=plan)[0]
    assert item.status == "blocked"
    assert item.task_id == "task-budget-1"
    assert item.blocked_reason == "Runtime budget exhausted"


def test_autopilot_queue_run_next_uses_config_runtime_budget_by_default(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] First task\n", encoding="utf-8")
    write_config(tmp_path, max_runtime_sec=17)

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])

    captured_budgets: list[int | None] = []

    def fake_run_once(
        self: Supervisor,
        task: str,
        repo: Path,
        planning_context=None,
    ) -> SupervisorResult:
        captured_budgets.append(self.max_runtime_sec)
        stored = self.state_store.create_task(
            task, repo_path=repo, task_id="task-default-budget"
        )
        return SupervisorResult(
            status="done",
            summary="Verification passed: custom",
            task_id=stored.task_id,
        )

    monkeypatch.setattr("ai_orchestrator.cli.app.Supervisor.run_once", fake_run_once)

    exit_code = main(
        [
            "autopilot",
            "queue",
            "run-next",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--execute",
            "--allow-mock-agent",
            "--allow-dirty",
        ]
    )
    capsys.readouterr()

    assert exit_code == 0
    assert captured_budgets == [17]


def test_autopilot_queue_run_next_rejects_non_positive_runtime_budget(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] First task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])

    exit_code = main(
        [
            "autopilot",
            "queue",
            "run-next",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--execute",
            "--allow-mock-agent",
            "--allow-dirty",
            "--max-runtime-sec",
            "0",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "--max-runtime-sec must be greater than 0" in output

    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    item = store.list_plan_items(plan_path=plan)[0]
    assert item.status == "created"


def test_autopilot_queue_run_batch_passes_timeout_and_records_blocked_reason_when_budget_exhausted(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text(
        "\n".join(
            [
                "- [ ] First task",
                "- [ ] Second task",
            ]
        ),
        encoding="utf-8",
    )

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])

    captured_budgets: list[int | None] = []

    def fake_run_once(
        self: Supervisor,
        task: str,
        repo: Path,
        planning_context=None,
    ) -> SupervisorResult:
        captured_budgets.append(self.max_runtime_sec)
        stored = self.state_store.create_task(
            task, repo_path=repo, task_id="batch-budget-1"
        )
        return SupervisorResult(
            status="blocked",
            summary="Runtime budget exhausted",
            task_id=stored.task_id,
        )

    monkeypatch.setattr("ai_orchestrator.cli.app.Supervisor.run_once", fake_run_once)

    exit_code = main(
        [
            "autopilot",
            "queue",
            "run-batch",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--execute",
            "--allow-mock-agent",
            "--allow-dirty",
            "--max-items",
            "2",
            "--max-runtime-sec",
            "99",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "Queue item" in output
    assert "status=blocked" in output
    assert "Batch stopped after 1 item(s): status=blocked" in output
    assert captured_budgets == [99]

    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    items = {item.text: item for item in store.list_plan_items(plan_path=plan)}
    assert items["First task"].status == "blocked"
    assert items["First task"].task_id == "batch-budget-1"
    assert items["First task"].blocked_reason == "Runtime budget exhausted"
    assert items["Second task"].status == "created"


def test_autopilot_queue_run_batch_rejects_non_positive_runtime_budget(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] First task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])

    exit_code = main(
        [
            "autopilot",
            "queue",
            "run-batch",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--execute",
            "--allow-mock-agent",
            "--allow-dirty",
            "--max-runtime-sec",
            "-1",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "--max-runtime-sec must be greater than 0" in output

    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    item = store.list_plan_items(plan_path=plan)[0]
    assert item.status == "created"


def test_autopilot_queue_run_batch_defaults_to_dry_run(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text(
        "\n".join(
            [
                "- [ ] First task",
                "- [ ] Second task",
            ]
        ),
        encoding="utf-8",
    )

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    exit_code = main(
        [
            "autopilot",
            "queue",
            "run-batch",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--max-items",
            "2",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Autopilot selected:" in output
    assert "Task: First task" in output
    assert "Task: Second task" in output
    assert "Dry run: add --execute" in output
    assert "Dry run: would process 2 item(s)" in output

    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    items = {item.text: item for item in store.list_plan_items(plan_path=plan)}
    assert f"Queue item: {items['First task'].plan_item_id}" in output
    assert f"Queue item: {items['Second task'].plan_item_id}" in output
    assert items["First task"].status == "created"
    assert items["Second task"].status == "created"
    assert "=== Batch summary ===" in output
    assert "Selected: 2 item(s)" in output
    assert "Status counts: created=2" in output
    assert (
        f"First non-done queue item: {items['First task'].plan_item_id} (status=created)"
        in output
    )


def test_autopilot_queue_run_batch_summary_ignores_terminal_items(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text(
        "\n".join(
            [
                "- [ ] Old skipped task",
                "- [ ] Ready task",
            ]
        ),
        encoding="utf-8",
    )

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    items = {item.text: item for item in store.list_plan_items(plan_path=plan)}
    skipped_item = items["Old skipped task"]
    ready_item = items["Ready task"]
    store.update_plan_item_status(skipped_item.plan_item_id, "skipped")
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "run-batch",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--max-items",
            "1",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert f"Queue item: {ready_item.plan_item_id}" in output
    assert "Status counts: created=1" in output
    assert (
        f"First non-done queue item: {ready_item.plan_item_id} (status=created)"
        in output
    )
    assert (
        f"First non-done queue item: {skipped_item.plan_item_id} (status=skipped)"
        not in output
    )


def test_autopilot_queue_run_batch_executes_up_to_max_items(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text(
        "\n".join(
            [
                "- [ ] First task",
                "- [ ] Second task",
                "- [ ] Third task",
            ]
        ),
        encoding="utf-8",
    )

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    queued_items = store.list_plan_items(plan_path=plan)

    call_count = 0

    def fake_run_once(
        self: Supervisor,
        task: str,
        repo: Path,
        planning_context=None,
    ) -> SupervisorResult:
        nonlocal call_count
        call_count += 1
        stored = self.state_store.create_task(
            task, repo_path=repo, task_id=f"batch-task-{call_count}"
        )
        return SupervisorResult(
            status="done",
            summary=f"Verification passed: {call_count}",
            task_id=stored.task_id,
        )

    monkeypatch.setattr("ai_orchestrator.cli.app.Supervisor.run_once", fake_run_once)

    exit_code = main(
        [
            "autopilot",
            "queue",
            "run-batch",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--execute",
            "--allow-mock-agent",
            "--allow-dirty",
            "--max-items",
            "2",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert f"Queue item: {queued_items[0].plan_item_id}" in output
    assert f"Queue item: {queued_items[1].plan_item_id}" in output
    assert "Batch complete: processed 2 item(s)" in output
    assert call_count == 2

    items = {item.text: item for item in store.list_plan_items(plan_path=plan)}
    assert items["First task"].status == "done"
    assert items["First task"].task_id == "batch-task-1"
    assert items["Second task"].status == "done"
    assert items["Second task"].task_id == "batch-task-2"
    assert items["Third task"].status == "created"
    assert items["Third task"].task_id is None

    report_dir = tmp_path / ".ai-orch" / "reports"
    assert (report_dir / "batch-task-1.md").exists()
    assert (report_dir / "batch-task-2.md").exists()
    assert "=== Batch summary ===" in output
    assert "Processed: 2 item(s)" in output
    assert "Status counts: done=2" in output
    assert (
        f"First non-done queue item: {items['Third task'].plan_item_id} (status=created)"
        in output
    )
    assert f"Reports:\n  {report_dir / 'batch-task-1.md'}\n  {report_dir / 'batch-task-2.md'}" in output


def test_autopilot_queue_run_batch_stops_on_blocked_result(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text(
        "\n".join(
            [
                "- [ ] First task",
                "- [ ] Second task",
                "- [ ] Third task",
            ]
        ),
        encoding="utf-8",
    )

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])

    call_count = 0

    def fake_run_once(
        self: Supervisor,
        task: str,
        repo: Path,
        planning_context=None,
    ) -> SupervisorResult:
        nonlocal call_count
        call_count += 1
        stored = self.state_store.create_task(
            task, repo_path=repo, task_id=f"batch-task-{call_count}"
        )
        status = "done" if call_count == 1 else "blocked"
        return SupervisorResult(
            status=status,
            summary=f"Result {call_count}",
            task_id=stored.task_id,
        )

    monkeypatch.setattr("ai_orchestrator.cli.app.Supervisor.run_once", fake_run_once)

    exit_code = main(
        [
            "autopilot",
            "queue",
            "run-batch",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--execute",
            "--allow-mock-agent",
            "--allow-dirty",
            "--max-items",
            "3",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "Queue item" in output
    assert "status=done" in output
    assert "status=blocked" in output
    assert "Batch stopped after 2 item(s): status=blocked" in output
    assert call_count == 2

    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    items = {item.text: item for item in store.list_plan_items(plan_path=plan)}
    assert items["First task"].status == "done"
    assert items["Second task"].status == "blocked"
    assert items["Third task"].status == "created"

    report_dir = tmp_path / ".ai-orch" / "reports"
    assert (report_dir / "batch-task-1.md").exists()
    assert (report_dir / "batch-task-2.md").exists()
    assert "=== Batch summary ===" in output
    assert "Processed: 2 item(s)" in output
    assert "Status counts: blocked=1, done=1" in output
    assert (
        f"First non-done queue item: {items['Second task'].plan_item_id} (status=blocked)"
        in output
    )
    assert f"Reports:\n  {report_dir / 'batch-task-1.md'}\n  {report_dir / 'batch-task-2.md'}" in output
    assert not (report_dir / "batch-task-3.md").exists()


def test_autopilot_queue_run_batch_returns_zero_when_no_ready_items(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [x] Completed task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    exit_code = main(
        [
            "autopilot",
            "queue",
            "run-batch",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--max-items",
            "2",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "No queued plan items ready" in output


def test_autopilot_queue_run_batch_rejects_non_positive_max_items(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] First task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    exit_code = main(
        [
            "autopilot",
            "queue",
            "run-batch",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--max-items",
            "0",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "--max-items must be at least 1" in output


def test_autopilot_queue_run_batch_rotate_worktrees_rejects_worktree(
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] First task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    with pytest.raises(SystemExit) as exc:
        main(
            [
                "autopilot",
                "queue",
                "run-batch",
                "--repo",
                str(tmp_path),
                "--plan",
                str(plan),
                "--worktree",
                "../wt",
                "--rotate-worktrees",
                "../pool",
            ]
        )

    assert exc.value.code == 2


def test_autopilot_queue_run_batch_rotate_worktrees_blocks_missing_base_dir(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] First task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    missing = tmp_path / "pool"
    exit_code = main(
        [
            "autopilot",
            "queue",
            "run-batch",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--rotate-worktrees",
            str(missing),
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "Rotation base directory does not exist" in output
    assert str(missing) in output


def test_autopilot_queue_run_batch_rotate_worktrees_dry_run_selects_worktrees(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text(
        "\n".join(
            [
                "- [ ] First task",
                "- [ ] Second task",
            ]
        ),
        encoding="utf-8",
    )

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])

    pool = tmp_path / "pool"
    pool.mkdir()
    wt1 = pool / "wt1"
    wt1.mkdir()
    wt2 = pool / "wt2"
    wt2.mkdir()

    monkeypatch.setattr(
        "ai_orchestrator.cli.app._validate_autopilot_worktree",
        lambda _repo, _wt: None,
    )
    monkeypatch.setattr(
        "ai_orchestrator.cli.app._repo_has_uncommitted_changes",
        lambda _repo: False,
    )

    exit_code = main(
        [
            "autopilot",
            "queue",
            "run-batch",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--rotate-worktrees",
            str(pool),
            "--max-items",
            "2",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Autopilot selected:" in output
    assert "Task: First task" in output
    assert "Task: Second task" in output
    assert f"Worktree: {wt1.resolve()}" in output
    assert f"Worktree: {wt2.resolve()}" in output
    assert "Dry run: would process 2 item(s) using rotated worktrees" in output

    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    items = {item.text: item for item in store.list_plan_items(plan_path=plan)}
    assert f"Queue item: {items['First task'].plan_item_id}" in output
    assert f"Queue item: {items['Second task'].plan_item_id}" in output
    assert items["First task"].status == "created"
    assert items["Second task"].status == "created"
    assert "=== Batch summary ===" in output
    assert "Selected: 2 item(s)" in output
    assert "Status counts: created=2" in output
    assert "Selected worktrees:" in output
    assert f"  {wt1.resolve()}" in output
    assert f"  {wt2.resolve()}" in output


def test_autopilot_queue_run_batch_rotate_worktrees_blocks_when_too_few_worktrees(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text(
        "\n".join(
            [
                "- [ ] First task",
                "- [ ] Second task",
            ]
        ),
        encoding="utf-8",
    )

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])

    pool = tmp_path / "pool"
    pool.mkdir()
    wt1 = pool / "wt1"
    wt1.mkdir()

    monkeypatch.setattr(
        "ai_orchestrator.cli.app._validate_autopilot_worktree",
        lambda _repo, _wt: None,
    )
    monkeypatch.setattr(
        "ai_orchestrator.cli.app._repo_has_uncommitted_changes",
        lambda _repo: False,
    )

    exit_code = main(
        [
            "autopilot",
            "queue",
            "run-batch",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--rotate-worktrees",
            str(pool),
            "--max-items",
            "2",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "Execution blocked: not enough clean, available worktrees" in output


def test_autopilot_queue_run_batch_rotate_worktrees_skips_busy_worktree(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text(
        "\n".join(
            [
                "- [ ] First task",
                "- [ ] Second task",
            ]
        ),
        encoding="utf-8",
    )

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    pool = tmp_path / "pool"
    pool.mkdir()
    busy_wt = pool / "busy"
    busy_wt.mkdir()
    free_wt = pool / "free"
    free_wt.mkdir()

    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    first_item = store.list_plan_items(plan_path=plan)[0]
    busy_task = store.create_task(
        "busy task",
        repo_path=busy_wt.resolve(),
        task_id="busy-task",
    )
    store.update_plan_item_status(
        first_item.plan_item_id,
        "in_progress",
        task_id=busy_task.task_id,
    )

    monkeypatch.setattr(
        "ai_orchestrator.cli.app._validate_autopilot_worktree",
        lambda _repo, _wt: None,
    )
    monkeypatch.setattr(
        "ai_orchestrator.cli.app._repo_has_uncommitted_changes",
        lambda _repo: False,
    )

    exit_code = main(
        [
            "autopilot",
            "queue",
            "run-batch",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--rotate-worktrees",
            str(pool),
            "--max-items",
            "1",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert f"Worktree: {free_wt.resolve()}" in output
    assert f"Worktree: {busy_wt.resolve()}" not in output


def test_autopilot_queue_run_batch_rotate_worktrees_executes_in_selected_worktrees(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text(
        "\n".join(
            [
                "- [ ] First task",
                "- [ ] Second task",
            ]
        ),
        encoding="utf-8",
    )

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    pool = tmp_path / "pool"
    pool.mkdir()
    wt1 = pool / "wt1"
    wt1.mkdir()
    wt2 = pool / "wt2"
    wt2.mkdir()

    monkeypatch.setattr(
        "ai_orchestrator.cli.app._validate_autopilot_worktree",
        lambda _repo, _wt: None,
    )
    monkeypatch.setattr(
        "ai_orchestrator.cli.app._repo_has_uncommitted_changes",
        lambda _repo: False,
    )
    captured_repos: list[Path] = []

    def fake_run_once(
        self: Supervisor,
        task: str,
        repo: Path,
        planning_context=None,
    ) -> SupervisorResult:
        captured_repos.append(repo.resolve())
        stored = self.state_store.create_task(
            task,
            repo_path=repo,
            task_id=f"rotated-task-{len(captured_repos)}",
        )
        return SupervisorResult(
            status="done",
            summary=f"Verification passed: {stored.task_id}",
            task_id=stored.task_id,
        )

    monkeypatch.setattr("ai_orchestrator.cli.app.Supervisor.run_once", fake_run_once)

    exit_code = main(
        [
            "autopilot",
            "queue",
            "run-batch",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--rotate-worktrees",
            str(pool),
            "--execute",
            "--allow-mock-agent",
            "--max-items",
            "2",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Batch complete: processed 2 item(s)" in output
    assert f"Worktree: {wt1.resolve()}" in output
    assert f"Worktree: {wt2.resolve()}" in output
    assert captured_repos == [wt1.resolve(), wt2.resolve()]

    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    items = {item.text: item for item in store.list_plan_items(plan_path=plan)}
    assert items["First task"].status == "done"
    assert items["First task"].task_id == "rotated-task-1"
    assert items["First task"].selected_worktree_path == str(wt1.resolve())
    assert items["Second task"].status == "done"
    assert items["Second task"].task_id == "rotated-task-2"
    assert items["Second task"].selected_worktree_path == str(wt2.resolve())

    first_report = tmp_path / ".ai-orch" / "reports" / "rotated-task-1.md"
    second_report = tmp_path / ".ai-orch" / "reports" / "rotated-task-2.md"
    assert first_report.exists()
    assert second_report.exists()
    assert f"- Queue worktree: `{wt1.resolve()}`" in first_report.read_text(
        encoding="utf-8"
    )
    assert f"- Queue worktree: `{wt2.resolve()}`" in second_report.read_text(
        encoding="utf-8"
    )
    assert "=== Batch summary ===" in output
    assert "Processed: 2 item(s)" in output
    assert "Status counts: done=2" in output
    assert "Selected worktrees:" in output
    assert f"  {wt1.resolve()}" in output
    assert f"  {wt2.resolve()}" in output
    assert f"Reports:\n  {first_report}\n  {second_report}" in output


def test_autopilot_queue_run_batch_fixed_worktree_persists_and_reports(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text(
        "\n".join(
            [
                "- [ ] Fixed worktree task",
            ]
        ),
        encoding="utf-8",
    )

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    worktree = tmp_path / "fixed-wt"
    worktree.mkdir()

    monkeypatch.setattr(
        "ai_orchestrator.cli.app._validate_autopilot_worktree",
        lambda _repo, _wt: None,
    )
    monkeypatch.setattr(
        "ai_orchestrator.cli.app._repo_has_uncommitted_changes",
        lambda _repo: False,
    )
    captured_repos: list[Path] = []

    def fake_run_once(
        self: Supervisor,
        task: str,
        repo: Path,
        planning_context=None,
    ) -> SupervisorResult:
        captured_repos.append(repo.resolve())
        stored = self.state_store.create_task(
            task,
            repo_path=repo,
            task_id="fixed-task-1",
        )
        return SupervisorResult(
            status="done",
            summary=f"Verification passed: {stored.task_id}",
            task_id=stored.task_id,
        )

    monkeypatch.setattr("ai_orchestrator.cli.app.Supervisor.run_once", fake_run_once)

    exit_code = main(
        [
            "autopilot",
            "queue",
            "run-batch",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--execute",
            "--allow-mock-agent",
            "--worktree",
            str(worktree),
            "--max-items",
            "1",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Batch complete: processed 1 item(s)" in output
    assert captured_repos == [worktree.resolve()]

    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    items = list(store.list_plan_items(plan_path=plan))
    assert len(items) == 1
    item = items[0]
    assert item.status == "done"
    assert item.task_id == "fixed-task-1"
    assert item.selected_worktree_path == str(worktree.resolve())

    report_path = tmp_path / ".ai-orch" / "reports" / "fixed-task-1.md"
    assert report_path.exists()
    assert f"- Queue worktree: `{worktree.resolve()}`" in report_path.read_text(
        encoding="utf-8"
    )
    assert "=== Batch summary ===" in output
    assert "Processed: 1 item(s)" in output
    assert "Status counts: done=1" in output
    assert "Selected worktrees:" in output
    assert f"  {worktree.resolve()}" in output
    assert f"Reports:\n  {report_path}" in output

    capsys.readouterr()
    exit_code = main(
        [
            "autopilot",
            "queue",
            "show",
            "--repo",
            str(tmp_path),
            str(item.plan_item_id),
        ]
    )
    show_output = capsys.readouterr().out
    assert exit_code == 0
    assert f"selected_worktree: {worktree.resolve()}" in show_output

    capsys.readouterr()
    exit_code = main(
        [
            "autopilot",
            "queue",
            "list",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
        ]
    )
    list_output = capsys.readouterr().out
    assert exit_code == 0
    assert f"worktree={worktree.resolve()}" in list_output

    capsys.readouterr()
    exit_code = main(
        [
            "autopilot",
            "queue",
            "status",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--status",
            "done",
        ]
    )
    status_output = capsys.readouterr().out
    assert exit_code == 0
    assert f"worktree={worktree.resolve()}" in status_output


def test_autopilot_queue_status_summarizes_counts_and_recent_items(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text(
        "\n".join(
            [
                "# Roadmap",
                "",
                "- [ ] Done task",
                "- [ ] Blocked task",
                "- [ ] Skipped task",
                "- [ ] Started task",
            ]
        ),
        encoding="utf-8",
    )

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    items = {item.text: item for item in store.list_plan_items(plan_path=plan)}
    store.update_plan_item_status(items["Done task"].plan_item_id, "done")
    store.update_plan_item_status(items["Blocked task"].plan_item_id, "blocked")
    store.update_plan_item_status(items["Skipped task"].plan_item_id, "skipped")
    worktree = tmp_path / "worktrees" / "started"
    store.update_plan_item_status(
        items["Started task"].plan_item_id,
        "in_progress",
        selected_worktree_path=worktree,
    )

    exit_code = main(
        ["autopilot", "queue", "status", "--repo", str(tmp_path), "--plan", str(plan)]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Queue status" in output
    assert "total: 4" in output
    assert "by status:" in output
    assert "done=1" in output
    assert "blocked=1" in output
    assert "skipped=1" in output
    assert "in_progress=1" in output
    assert "recent started:" in output
    assert "recent done:" in output
    assert "recent blocked:" in output
    assert "recent skipped:" in output
    assert "Started task" in output
    assert f"worktree={worktree}" in output
    assert "Done task" in output
    assert "Blocked task" in output
    assert "Skipped task" in output
    assert "Autopilot selected:" not in output
    assert "Dry run" not in output


def test_autopilot_queue_status_filters_recent_items_by_status(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text(
        "\n".join(
            [
                "- [ ] Created task",
                "- [ ] Done task",
                "- [ ] Blocked task",
            ]
        ),
        encoding="utf-8",
    )

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    items = {item.text: item for item in store.list_plan_items(plan_path=plan)}
    store.update_plan_item_status(items["Done task"].plan_item_id, "done")
    store.update_plan_item_status(items["Blocked task"].plan_item_id, "blocked")
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "status",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--status",
            "created",
            "--status",
            "blocked",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "total: 3" in output
    assert "filtered: 2 status=created,blocked" in output
    assert "created=1" in output
    assert "done=1" in output
    assert "blocked=1" in output
    assert "recent created:" in output
    assert "recent blocked:" in output
    assert "recent done:" not in output
    assert "Created task" in output
    assert "Blocked task" in output
    assert "Done task" not in output


def test_autopilot_queue_status_limits_recent_items(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    tasks = [f"- [ ] Task {i}" for i in range(6)]
    plan.write_text("\n".join(["# Roadmap", ""] + tasks), encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    for item in store.list_plan_items(plan_path=plan):
        store.update_plan_item_status(item.plan_item_id, "done")

    capsys.readouterr()
    exit_code = main(
        ["autopilot", "queue", "status", "--repo", str(tmp_path), "--plan", str(plan)]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "total: 6" in output
    assert "recent done:" in output
    assert "Task 5" in output
    assert "Task 4" in output
    assert "Task 3" in output
    assert "Task 2" in output
    assert "Task 1" in output
    assert "Task 0" not in output

    capsys.readouterr()
    exit_code = main(
        [
            "autopilot",
            "queue",
            "status",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--limit",
            "2",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Task 5" in output
    assert "Task 4" in output
    assert "Task 3" not in output
    assert "Task 2" not in output
    assert "Task 1" not in output
    assert "Task 0" not in output


def test_autopilot_queue_status_handles_missing_plan(
    capsys,
    tmp_path: Path,
) -> None:
    missing_plan = tmp_path / "MISSING.md"

    exit_code = main(
        [
            "autopilot",
            "queue",
            "status",
            "--repo",
            str(tmp_path),
            "--plan",
            str(missing_plan),
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "Plan not found:" in output


def test_autopilot_queue_status_all_plans_ignores_missing_plan_arg(
    capsys,
    tmp_path: Path,
) -> None:
    roadmap = tmp_path / "ROADMAP.md"
    backlog = tmp_path / "BACKLOG.md"
    missing_plan = tmp_path / "MISSING.md"
    roadmap.write_text("- [ ] Roadmap blocked task\n", encoding="utf-8")
    backlog.write_text("- [ ] Backlog created task\n", encoding="utf-8")

    main(
        [
            "autopilot",
            "queue",
            "sync",
            "--repo",
            str(tmp_path),
            "--plan",
            str(roadmap),
        ]
    )
    main(
        [
            "autopilot",
            "queue",
            "sync",
            "--repo",
            str(tmp_path),
            "--plan",
            str(backlog),
        ]
    )
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    roadmap_item = store.list_plan_items(plan_path=roadmap)[0]
    store.update_plan_item_status(roadmap_item.plan_item_id, "blocked")
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "status",
            "--repo",
            str(tmp_path),
            "--plan",
            str(missing_plan),
            "--all-plans",
            "--status",
            "blocked",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Queue status for all persisted plans" in output
    assert "Plan not found:" not in output
    assert "total: 2" in output
    assert "filtered: 1 status=blocked" in output
    assert "recent blocked:" in output
    assert f"{roadmap}:" in output
    assert "Roadmap blocked task" in output
    assert "Backlog created task" not in output


def test_autopilot_queue_status_problem_summary_groups_by_reason_and_latest_ids(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text(
        "\n".join(
            [
                "# Roadmap",
                "",
                "- [ ] Done task",
                "- [ ] In progress task",
                "- [ ] Blocked task A1",
                "- [ ] Blocked task A2",
                "- [ ] Blocked task B",
            ]
        ),
        encoding="utf-8",
    )

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    items = {item.text: item for item in store.list_plan_items(plan_path=plan)}
    store.update_plan_item_status(items["Done task"].plan_item_id, "done")
    store.update_plan_item_status(
        items["Blocked task A1"].plan_item_id,
        "blocked",
        blocked_reason="needs approval",
    )
    store.update_plan_item_status(
        items["Blocked task A2"].plan_item_id,
        "blocked",
        blocked_reason="needs approval",
    )
    store.update_plan_item_status(
        items["Blocked task B"].plan_item_id,
        "blocked",
        blocked_reason="runtime budget exhausted",
    )
    store.update_plan_item_status(
        items["In progress task"].plan_item_id,
        "in_progress",
    )
    expected_in_progress = items["In progress task"].plan_item_id
    expected_a_ids = [
        items["Blocked task A2"].plan_item_id,
        items["Blocked task A1"].plan_item_id,
    ]
    expected_b_id = items["Blocked task B"].plan_item_id
    capsys.readouterr()

    exit_code = main(
        ["autopilot", "queue", "status", "--repo", str(tmp_path), "--plan", str(plan)]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Problem summary:" in output
    assert f"in_progress ((no reason)): count=1 latest=[{expected_in_progress}]" in output
    assert (
        f"blocked (needs approval): count=2 latest=[{expected_a_ids[0]}, {expected_a_ids[1]}]"
        in output
    )
    assert (
        f"blocked (runtime budget exhausted): count=1 latest=[{expected_b_id}]"
        in output
    )
    # State must be preserved (read-only summary).
    refreshed = {item.text: item for item in store.list_plan_items(plan_path=plan)}
    assert refreshed["In progress task"].status == "in_progress"
    assert refreshed["Blocked task A1"].status == "blocked"
    assert refreshed["Blocked task A2"].blocked_reason == "needs approval"


def test_autopilot_queue_list_problem_summary_respects_status_filter(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text(
        "\n".join(
            [
                "- [ ] Created task",
                "- [ ] Blocked task",
            ]
        ),
        encoding="utf-8",
    )

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    items = {item.text: item for item in store.list_plan_items(plan_path=plan)}
    store.update_plan_item_status(
        items["Blocked task"].plan_item_id,
        "blocked",
        blocked_reason="policy denied",
    )
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "list",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--status",
            "done",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Problem summary:" not in output
    assert "Blocked task" not in output


def test_autopilot_queue_list_problem_summary_groups_problem_items(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text(
        "\n".join(
            [
                "- [ ] Blocked task",
                "- [ ] In progress task",
            ]
        ),
        encoding="utf-8",
    )

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    items = {item.text: item for item in store.list_plan_items(plan_path=plan)}
    blocked_item = items["Blocked task"]
    in_progress_item = items["In progress task"]
    store.update_plan_item_status(
        blocked_item.plan_item_id,
        "blocked",
        blocked_reason="needs review",
    )
    store.update_plan_item_status(in_progress_item.plan_item_id, "in_progress")
    capsys.readouterr()

    exit_code = main(
        ["autopilot", "queue", "list", "--repo", str(tmp_path), "--plan", str(plan)]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Problem summary:" in output
    assert (
        f"blocked (needs review): count=1 latest=[{blocked_item.plan_item_id}]"
        in output
    )
    assert (
        "in_progress ((no reason)): count=1 "
        f"latest=[{in_progress_item.plan_item_id}]"
    ) in output
    refreshed = {item.text: item for item in store.list_plan_items(plan_path=plan)}
    assert refreshed["Blocked task"].status == "blocked"
    assert refreshed["In progress task"].status == "in_progress"


def test_autopilot_queue_status_problem_summary_limits_latest_ids(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text(
        "\n".join([f"- [ ] Blocked task {i}" for i in range(4)]),
        encoding="utf-8",
    )

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    item_ids: list[int] = []
    for item in store.list_plan_items(plan_path=plan):
        store.update_plan_item_status(
            item.plan_item_id,
            "blocked",
            blocked_reason="same reason",
        )
        item_ids.append(item.plan_item_id)
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "status",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--limit",
            "2",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Problem summary:" in output
    latest_two = ", ".join(str(plan_item_id) for plan_item_id in reversed(item_ids[-2:]))
    excluded = str(item_ids[0])
    assert f"blocked (same reason): count=4 latest=[{latest_two}]" in output
    assert excluded not in output.split("Problem summary:")[1].split("\n")[1]


def test_autopilot_queue_reconcile_dry_run_reports_stale_created_items(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Stale task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    plan.write_text("- [x] Stale task\n", encoding="utf-8")
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "reconcile",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
        ]
    )
    output = capsys.readouterr().out
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    item = store.list_plan_items(plan_path=plan)[0]

    assert exit_code == 0
    assert "Queue reconcile for" in output
    assert "total: 1" in output
    assert "stale_created: 1" in output
    assert "dry_run: use --apply to mark stale items skipped" in output
    assert "[stale]" in output
    assert "Stale task" in output
    assert item.status == "created"


def test_autopilot_queue_reconcile_all_plans_apply_skips_only_stale_created_items(
    capsys,
    tmp_path: Path,
) -> None:
    stale_plan = tmp_path / "STALE.md"
    current_plan = tmp_path / "CURRENT.md"
    stale_plan.write_text("- [ ] Stale task\n", encoding="utf-8")
    current_plan.write_text("- [ ] Current task\n", encoding="utf-8")

    main(
        [
            "autopilot",
            "queue",
            "sync",
            "--repo",
            str(tmp_path),
            "--plan",
            str(stale_plan),
        ]
    )
    main(
        [
            "autopilot",
            "queue",
            "sync",
            "--repo",
            str(tmp_path),
            "--plan",
            str(current_plan),
        ]
    )
    stale_plan.write_text("- [x] Stale task\n", encoding="utf-8")
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "reconcile",
            "--repo",
            str(tmp_path),
            "--all-plans",
            "--apply",
        ]
    )
    output = capsys.readouterr().out
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    items = {item.text: item for item in store.list_plan_items()}

    assert exit_code == 0
    assert "Queue reconcile for all persisted plans" in output
    assert "total: 2" in output
    assert "stale_created: 1" in output
    assert "skipped: 1" in output
    assert f"[stale] {stale_plan}:" in output
    assert "Stale task" in output
    assert "Current task" not in output
    assert items["Stale task"].status == "skipped"
    assert items["Current task"].status == "created"


def test_autopilot_queue_recover_in_progress_dry_run_reports_stale_items(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Orphan task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    item = store.list_plan_items(plan_path=plan)[0]
    store.update_plan_item_status(item.plan_item_id, "in_progress")
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "recover-in-progress",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
        ]
    )
    output = capsys.readouterr().out
    loaded = store.get_plan_item(item.plan_item_id)

    assert exit_code == 0
    assert "Queue recover for" in output
    assert "stale_in_progress: 1" in output
    assert "dry_run: use --apply --reason" in output
    assert "[stale_in_progress]" in output
    assert "Orphan task" in output
    assert loaded is not None
    assert loaded.status == "in_progress"
    assert loaded.blocked_reason is None


def test_autopilot_queue_recover_in_progress_apply_blocks_with_reason(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Orphan task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    item = store.list_plan_items(plan_path=plan)[0]
    store.update_plan_item_status(item.plan_item_id, "in_progress")
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "recover-in-progress",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--apply",
            "--reason",
            "batch run timed out",
        ]
    )
    output = capsys.readouterr().out
    loaded = store.get_plan_item(item.plan_item_id)

    assert exit_code == 0
    assert "stale_in_progress: 1" in output
    assert "blocked: 1" in output
    assert "batch run timed out" in output
    assert loaded is not None
    assert loaded.status == "blocked"
    assert loaded.blocked_reason == "batch run timed out"

    exit_code = main(
        [
            "autopilot",
            "queue",
            "list",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--status",
            "blocked",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "reason=batch run timed out" in output


def test_autopilot_queue_recover_in_progress_apply_requires_reason(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Orphan task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    item = store.list_plan_items(plan_path=plan)[0]
    store.update_plan_item_status(item.plan_item_id, "in_progress")
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "recover-in-progress",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--apply",
        ]
    )
    output = capsys.readouterr().out
    loaded = store.get_plan_item(item.plan_item_id)

    assert exit_code == 1
    assert "--reason is required when --apply is set" in output
    assert loaded is not None
    assert loaded.status == "in_progress"


def test_autopilot_queue_recover_in_progress_all_plans_blocks_only_in_progress(
    capsys,
    tmp_path: Path,
) -> None:
    roadmap = tmp_path / "ROADMAP.md"
    backlog = tmp_path / "BACKLOG.md"
    roadmap.write_text("- [ ] Roadmap stuck task\n", encoding="utf-8")
    backlog.write_text("\n".join(["# Backlog", "", "## P2", "", "- Backlog stuck task"]), encoding="utf-8")

    main(
        [
            "autopilot",
            "queue",
            "sync",
            "--repo",
            str(tmp_path),
            "--plan",
            str(roadmap),
        ]
    )
    main(
        [
            "autopilot",
            "queue",
            "sync-backlog",
            "--repo",
            str(tmp_path),
            "--backlog",
            str(backlog),
        ]
    )
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    items = {item.text: item for item in store.list_plan_items()}
    store.update_plan_item_status(items["Roadmap stuck task"].plan_item_id, "in_progress")
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "recover-in-progress",
            "--repo",
            str(tmp_path),
            "--all-plans",
            "--apply",
            "--reason",
            "interrupted",
        ]
    )
    output = capsys.readouterr().out
    loaded = {item.text: item for item in store.list_plan_items()}

    assert exit_code == 0
    assert "Queue recover for all persisted plans" in output
    assert "stale_in_progress: 1" in output
    assert "blocked: 1" in output
    assert loaded["Roadmap stuck task"].status == "blocked"
    assert loaded["Roadmap stuck task"].blocked_reason == "interrupted"
    assert loaded["Backlog stuck task"].status == "created"


def test_autopilot_queue_reconcile_stale_row_includes_refs(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Stale task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    item = store.list_plan_items(plan_path=plan)[0]
    task = store.create_task("stale task", repo_path=tmp_path)
    worktree = tmp_path / "wt"
    store.update_plan_item_status(
        item.plan_item_id,
        "created",
        task_id=task.task_id,
        selected_worktree_path=worktree,
    )
    report_path = tmp_path / ".ai-orch" / "reports" / f"{task.task_id}.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("report", encoding="utf-8")
    plan.write_text("- [x] Stale task\n", encoding="utf-8")
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "reconcile",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
        ]
    )
    output = capsys.readouterr().out
    loaded = store.get_plan_item(item.plan_item_id)

    assert exit_code == 0
    assert loaded is not None
    assert loaded.status == "created"
    assert f"task={task.task_id}" in output
    assert f"worktree={worktree}" in output
    assert f"report={report_path}" in output


def test_autopilot_queue_recover_in_progress_stale_row_includes_refs_and_reason(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Orphan task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    item = store.list_plan_items(plan_path=plan)[0]
    task = store.create_task("orphan task", repo_path=tmp_path)
    worktree = tmp_path / "wt"
    store.update_plan_item_status(
        item.plan_item_id,
        "in_progress",
        task_id=task.task_id,
        selected_worktree_path=worktree,
    )
    report_path = tmp_path / ".ai-orch" / "reports" / f"{task.task_id}.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("report", encoding="utf-8")
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "recover-in-progress",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--apply",
            "--reason",
            "interrupted",
        ]
    )
    output = capsys.readouterr().out
    loaded = store.get_plan_item(item.plan_item_id)

    assert exit_code == 0
    assert loaded is not None
    assert loaded.status == "blocked"
    assert loaded.blocked_reason == "interrupted"
    assert f"task={task.task_id}" in output
    assert f"worktree={worktree}" in output
    assert f"report={report_path}" in output
    assert "reason=interrupted" in output


def test_autopilot_queue_reconcile_stale_row_omits_refs_when_unset(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Stale task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    plan.write_text("- [x] Stale task\n", encoding="utf-8")
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "reconcile",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "[stale]" in output
    assert "task=" not in output
    assert "worktree=" not in output
    assert "report=" not in output


def test_autopilot_queue_status_shows_report_path_for_completed_item(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Completed task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    item = store.list_plan_items(plan_path=plan)[0]
    task = store.create_task(
        "Completed task", repo_path=tmp_path, task_id="task-report-status"
    )
    iteration = store.add_iteration(
        task_id=task.task_id,
        iteration_index=1,
        agent_name="mock",
        agent_status="success",
        prompt="Completed task",
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
    store.update_plan_item_status(item.plan_item_id, "done", task_id=task.task_id)
    report_path = tmp_path / ".ai-orch" / "reports" / f"{task.task_id}.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("# report", encoding="utf-8")

    exit_code = main(
        ["autopilot", "queue", "status", "--repo", str(tmp_path), "--plan", str(plan)]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "recent done:" in output
    assert f"report={report_path}" in output


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
    assert "preflight summary: area=release total=2 passed=1 failed=1" in output
    assert "failures:\n  impact: failed" in output
    assert calls == 2


def test_autopilot_queue_show_prints_item_details_without_changing_state(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Created task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    item = store.list_plan_items(plan_path=plan)[0]
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "show",
            "--repo",
            str(tmp_path),
            str(item.plan_item_id),
        ]
    )
    output = capsys.readouterr().out
    loaded = store.get_plan_item(item.plan_item_id)

    assert exit_code == 0
    assert f"Queue item: {item.plan_item_id}" in output
    assert "status: created" in output
    assert f"source: {plan}:1" in output
    assert "task: Created task" in output
    assert "task_id: none" in output
    assert "report_path: none" in output
    assert "selected_worktree: none" in output
    assert "reason: none" in output
    assert loaded is not None
    assert loaded.status == "created"


def test_autopilot_queue_show_prints_blocked_reason_and_report_path(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Done task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    item = store.list_plan_items(plan_path=plan)[0]
    task = store.create_task("Done task", repo_path=tmp_path)
    report_path = tmp_path / ".ai-orch" / "reports" / f"{task.task_id}.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("report", encoding="utf-8")
    store.update_plan_item_status(
        item.plan_item_id,
        "blocked",
        task_id=task.task_id,
        selected_worktree_path=tmp_path / "worktree",
        blocked_reason="needs operator review",
    )
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "show",
            "--repo",
            str(tmp_path),
            str(item.plan_item_id),
        ]
    )
    output = capsys.readouterr().out
    loaded = store.get_plan_item(item.plan_item_id)

    assert exit_code == 0
    assert "status: blocked" in output
    assert f"task_id: {task.task_id}" in output
    assert f"report_path: {report_path}" in output
    assert f"selected_worktree: {tmp_path / 'worktree'}" in output
    assert "reason: needs operator review" in output
    assert loaded is not None
    assert loaded.status == "blocked"


def test_autopilot_queue_show_reports_missing_item(capsys, tmp_path: Path) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "show",
            "--repo",
            str(tmp_path),
            "9999",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "Queue item not found: 9999" in output


def test_autopilot_queue_show_with_plan_validates_matching_plan(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Created task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    item = store.list_plan_items(plan_path=plan)[0]
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "show",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            str(item.plan_item_id),
        ]
    )
    output = capsys.readouterr().out
    loaded = store.get_plan_item(item.plan_item_id)

    assert exit_code == 0
    assert f"Queue item: {item.plan_item_id}" in output
    assert "status: created" in output
    assert loaded is not None
    assert loaded.status == "created"


def test_autopilot_queue_show_with_plan_rejects_mismatched_plan(
    capsys,
    tmp_path: Path,
) -> None:
    plan_a = tmp_path / "ROADMAP.md"
    plan_a.write_text("- [ ] Plan A task\n", encoding="utf-8")
    plan_b = tmp_path / "BACKLOG.md"
    plan_b.write_text("- Plan B task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan_a)])
    main(
        ["autopilot", "queue", "sync-backlog", "--repo", str(tmp_path), "--backlog", str(plan_b)]
    )
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    item_a = store.list_plan_items(plan_path=plan_a)[0]
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "show",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan_b),
            str(item_a.plan_item_id),
        ]
    )
    output = capsys.readouterr().out
    loaded = store.get_plan_item(item_a.plan_item_id)

    assert exit_code == 1
    assert f"Queue item {item_a.plan_item_id} does not belong to plan {plan_b}" in output
    assert loaded is not None
    assert loaded.status == "created"


def test_autopilot_queue_requeue_dry_run_reports_blocked_item(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Blocked task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    item = store.list_plan_items(plan_path=plan)[0]
    store.update_plan_item_status(
        item.plan_item_id,
        "blocked",
        blocked_reason="needs operator review",
    )
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "requeue",
            "--repo",
            str(tmp_path),
            str(item.plan_item_id),
        ]
    )
    output = capsys.readouterr().out
    loaded = store.get_plan_item(item.plan_item_id)

    assert exit_code == 0
    assert f"Requeue queue item {item.plan_item_id}" in output
    assert "blocked_reason: needs operator review" in output
    assert "dry_run: use --apply to move this item back to created" in output
    assert loaded is not None
    assert loaded.status == "blocked"
    assert loaded.blocked_reason == "needs operator review"


def test_autopilot_queue_requeue_apply_clears_metadata_and_moves_to_created(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Blocked task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    item = store.list_plan_items(plan_path=plan)[0]
    task = store.create_task("Blocked task", repo_path=tmp_path, task_id="task-old")
    store.update_plan_item_status(
        item.plan_item_id,
        "blocked",
        task_id=task.task_id,
        selected_worktree_path=tmp_path / "old-worktree",
        blocked_reason="agent timed out",
    )
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "requeue",
            "--repo",
            str(tmp_path),
            "--apply",
            str(item.plan_item_id),
        ]
    )
    output = capsys.readouterr().out
    loaded = store.get_plan_item(item.plan_item_id)

    assert exit_code == 0
    assert f"Requeue queue item {item.plan_item_id}" in output
    assert "status: created" in output
    assert "cleared: blocked_reason, task_id, selected_worktree_path" in output
    assert loaded is not None
    assert loaded.status == "created"
    assert loaded.blocked_reason is None
    assert loaded.task_id is None
    assert loaded.selected_worktree_path is None


def test_autopilot_queue_requeue_apply_requires_blocked_status(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Created task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    item = store.list_plan_items(plan_path=plan)[0]
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "requeue",
            "--repo",
            str(tmp_path),
            "--apply",
            str(item.plan_item_id),
        ]
    )
    output = capsys.readouterr().out
    loaded = store.get_plan_item(item.plan_item_id)

    assert exit_code == 1
    assert f"Queue item {item.plan_item_id} is not blocked (status=created)" in output
    assert loaded is not None
    assert loaded.status == "created"


def test_autopilot_queue_requeue_reports_missing_item(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "requeue",
            "--repo",
            str(tmp_path),
            "--apply",
            "9999",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "Queue item not found: 9999" in output


def test_autopilot_queue_requeue_with_plan_dry_run_reports_blocked_item(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Blocked task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    item = store.list_plan_items(plan_path=plan)[0]
    store.update_plan_item_status(
        item.plan_item_id,
        "blocked",
        blocked_reason="needs operator review",
    )
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "requeue",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            str(item.plan_item_id),
        ]
    )
    output = capsys.readouterr().out
    loaded = store.get_plan_item(item.plan_item_id)

    assert exit_code == 0
    assert f"Requeue queue item {item.plan_item_id}" in output
    assert "dry_run: use --apply to move this item back to created" in output
    assert loaded is not None
    assert loaded.status == "blocked"
    assert loaded.blocked_reason == "needs operator review"


def test_autopilot_queue_requeue_with_plan_apply_moves_blocked_item_to_created(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Blocked task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    item = store.list_plan_items(plan_path=plan)[0]
    store.update_plan_item_status(
        item.plan_item_id,
        "blocked",
        blocked_reason="needs operator review",
    )
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "requeue",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--apply",
            str(item.plan_item_id),
        ]
    )
    output = capsys.readouterr().out
    loaded = store.get_plan_item(item.plan_item_id)

    assert exit_code == 0
    assert f"Requeue queue item {item.plan_item_id}" in output
    assert "status: created" in output
    assert loaded is not None
    assert loaded.status == "created"
    assert loaded.blocked_reason is None


def test_autopilot_queue_requeue_with_plan_rejects_mismatched_plan(
    capsys,
    tmp_path: Path,
) -> None:
    plan_a = tmp_path / "ROADMAP.md"
    plan_a.write_text("- [ ] Plan A task\n", encoding="utf-8")
    plan_b = tmp_path / "BACKLOG.md"
    plan_b.write_text("- Plan B task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan_a)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    item_a = store.list_plan_items(plan_path=plan_a)[0]
    store.update_plan_item_status(
        item_a.plan_item_id,
        "blocked",
        blocked_reason="needs operator review",
    )
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "requeue",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan_b),
            "--apply",
            str(item_a.plan_item_id),
        ]
    )
    output = capsys.readouterr().out
    loaded = store.get_plan_item(item_a.plan_item_id)

    assert exit_code == 1
    assert f"Queue item {item_a.plan_item_id} does not belong to plan {plan_b}" in output
    assert loaded is not None
    assert loaded.status == "blocked"
    assert loaded.blocked_reason == "needs operator review"


def test_autopilot_queue_skip_dry_run_reports_created_item(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Created task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    item = store.list_plan_items(plan_path=plan)[0]
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "skip",
            "--repo",
            str(tmp_path),
            "--reason",
            "operator reviewed: out of scope",
            str(item.plan_item_id),
        ]
    )
    output = capsys.readouterr().out
    loaded = store.get_plan_item(item.plan_item_id)

    assert exit_code == 0
    assert f"Skip queue item {item.plan_item_id}" in output
    assert "current_status: created" in output
    assert "reason: operator reviewed: out of scope" in output
    assert "dry_run: use --apply to mark this item skipped" in output
    assert loaded is not None
    assert loaded.status == "created"
    assert loaded.blocked_reason is None


def test_autopilot_queue_skip_apply_skips_created_item(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Created task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    item = store.list_plan_items(plan_path=plan)[0]
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "skip",
            "--repo",
            str(tmp_path),
            "--reason",
            "operator reviewed: out of scope",
            "--apply",
            str(item.plan_item_id),
        ]
    )
    output = capsys.readouterr().out
    loaded = store.get_plan_item(item.plan_item_id)

    assert exit_code == 0
    assert f"Skip queue item {item.plan_item_id}" in output
    assert "status: skipped" in output
    assert loaded is not None
    assert loaded.status == "skipped"
    assert loaded.blocked_reason == "operator reviewed: out of scope"


def test_autopilot_queue_skip_apply_skips_blocked_item(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Blocked task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    item = store.list_plan_items(plan_path=plan)[0]
    store.update_plan_item_status(
        item.plan_item_id,
        "blocked",
        blocked_reason="needs external dependency",
    )
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "skip",
            "--repo",
            str(tmp_path),
            "--reason",
            "operator reviewed: defer until next quarter",
            "--apply",
            str(item.plan_item_id),
        ]
    )
    output = capsys.readouterr().out
    loaded = store.get_plan_item(item.plan_item_id)

    assert exit_code == 0
    assert f"Skip queue item {item.plan_item_id}" in output
    assert "current_status: blocked" in output
    assert "blocked_reason: needs external dependency" in output
    assert "status: skipped" in output
    assert loaded is not None
    assert loaded.status == "skipped"
    assert loaded.blocked_reason == "operator reviewed: defer until next quarter"


def test_autopilot_queue_skip_apply_requires_reason(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Created task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    item = store.list_plan_items(plan_path=plan)[0]
    capsys.readouterr()

    with pytest.raises(SystemExit) as exc:
        main(
            [
                "autopilot",
                "queue",
                "skip",
                "--repo",
                str(tmp_path),
                "--apply",
                str(item.plan_item_id),
            ]
        )
    output = capsys.readouterr().err
    loaded = store.get_plan_item(item.plan_item_id)

    assert exc.value.code == 2
    assert "--reason" in output
    assert loaded is not None
    assert loaded.status == "created"


def test_autopilot_queue_skip_apply_rejects_non_skippable_status(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Done task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    item = store.list_plan_items(plan_path=plan)[0]
    store.update_plan_item_status(item.plan_item_id, "done")
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "skip",
            "--repo",
            str(tmp_path),
            "--reason",
            "operator reviewed",
            "--apply",
            str(item.plan_item_id),
        ]
    )
    output = capsys.readouterr().out
    loaded = store.get_plan_item(item.plan_item_id)

    assert exit_code == 1
    assert f"Queue item {item.plan_item_id} cannot be skipped (status=done)" in output
    assert loaded is not None
    assert loaded.status == "done"


def test_autopilot_queue_skip_reports_missing_item(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "skip",
            "--repo",
            str(tmp_path),
            "--reason",
            "operator reviewed",
            "--apply",
            "9999",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "Queue item not found: 9999" in output


def test_autopilot_queue_skip_with_plan_dry_run_and_apply(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Created task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    item = store.list_plan_items(plan_path=plan)[0]
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "skip",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--reason",
            "operator reviewed: out of scope",
            str(item.plan_item_id),
        ]
    )
    output = capsys.readouterr().out
    loaded = store.get_plan_item(item.plan_item_id)

    assert exit_code == 0
    assert f"Skip queue item {item.plan_item_id}" in output
    assert "current_status: created" in output
    assert "dry_run: use --apply to mark this item skipped" in output
    assert loaded is not None
    assert loaded.status == "created"

    exit_code = main(
        [
            "autopilot",
            "queue",
            "skip",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--reason",
            "operator reviewed: out of scope",
            "--apply",
            str(item.plan_item_id),
        ]
    )
    output = capsys.readouterr().out
    loaded = store.get_plan_item(item.plan_item_id)

    assert exit_code == 0
    assert "status: skipped" in output
    assert loaded is not None
    assert loaded.status == "skipped"


def test_autopilot_queue_skip_with_plan_apply_skips_blocked_item(
    capsys,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Blocked task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    item = store.list_plan_items(plan_path=plan)[0]
    store.update_plan_item_status(
        item.plan_item_id,
        "blocked",
        blocked_reason="needs operator review",
    )
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "skip",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan),
            "--reason",
            "operator reviewed: out of scope",
            "--apply",
            str(item.plan_item_id),
        ]
    )
    output = capsys.readouterr().out
    loaded = store.get_plan_item(item.plan_item_id)

    assert exit_code == 0
    assert f"Skip queue item {item.plan_item_id}" in output
    assert "current_status: blocked" in output
    assert "status: skipped" in output
    assert loaded is not None
    assert loaded.status == "skipped"
    assert loaded.blocked_reason == "operator reviewed: out of scope"


def test_autopilot_queue_skip_with_plan_rejects_mismatched_plan(
    capsys,
    tmp_path: Path,
) -> None:
    plan_a = tmp_path / "ROADMAP.md"
    plan_a.write_text("- [ ] Plan A task\n", encoding="utf-8")
    plan_b = tmp_path / "BACKLOG.md"
    plan_b.write_text("- Plan B task\n", encoding="utf-8")

    main(["autopilot", "queue", "sync", "--repo", str(tmp_path), "--plan", str(plan_a)])
    store = StateStore(tmp_path / ".ai-orch" / "state" / "ai-orch.db")
    item_a = store.list_plan_items(plan_path=plan_a)[0]
    capsys.readouterr()

    exit_code = main(
        [
            "autopilot",
            "queue",
            "skip",
            "--repo",
            str(tmp_path),
            "--plan",
            str(plan_b),
            "--reason",
            "operator reviewed: out of scope",
            "--apply",
            str(item_a.plan_item_id),
        ]
    )
    output = capsys.readouterr().out
    loaded = store.get_plan_item(item_a.plan_item_id)

    assert exit_code == 1
    assert f"Queue item {item_a.plan_item_id} does not belong to plan {plan_b}" in output
    assert loaded is not None
    assert loaded.status == "created"


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
    max_runtime_sec: int | None = None,
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
    runtime_section = ""
    if max_runtime_sec is not None:
        runtime_section = f"  max_runtime_sec: {max_runtime_sec}\n"
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
{fallback_section}{runtime_section}  max_iterations: 3

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
