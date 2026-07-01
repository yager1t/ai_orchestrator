from pathlib import Path

from ai_orchestrator.reporting.markdown import render_task_report
from ai_orchestrator.storage.db import StateStore
from ai_orchestrator.verification.runner import VerificationResult


def test_render_task_report_includes_iterations_and_checks(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
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

    report = render_task_report(store, task.task_id)

    assert report is not None
    assert f"# ai-orch report: {task.task_id}" in report
    assert "- Status: `done`" in report
    assert "- Iterations: `1`" in report
    assert "- Verification runs: `1` (`passed`: 1)" in report
    assert "- Verification verdict: `verified`" in report
    assert "final supervisor decision is backed by passing checks: `unit`" in report
    assert "- Final decision: `done`" in report
    assert "- Final reason: Verification passed: unit" in report
    assert "### Iteration 1" in report
    assert "- `unit`: `passed` exit=`0`" in report


def test_render_task_report_returns_none_for_missing_task(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")

    assert render_task_report(store, "missing-task") is None


def test_render_task_report_includes_failed_verification_excerpt(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    task = store.create_task("demo failure", repo_path=tmp_path)
    iteration = store.add_iteration(
        task_id=task.task_id,
        iteration_index=1,
        agent_name="mock",
        agent_status="success",
        prompt="demo failure",
        raw_output="done",
        decision_status="blocked",
        decision_reason="Verification failed after 1 iteration(s): unit: failed exit=1",
    )
    store.add_verification_run(
        task_id=task.task_id,
        iteration_id=iteration.iteration_id,
        result=VerificationResult(
            name="unit",
            status="failed",
            exit_code=1,
            stdout="ignored stdout",
            stderr="assertion failed on line 10",
        ),
    )

    report = render_task_report(store, task.task_id)

    assert report is not None
    assert "- `unit`: `failed` exit=`1`" in report
    assert "- Verification verdict: `not_verified`" in report
    assert "final verification is not fully passing (`unit`: `failed`)" in report
    assert "assertion failed on line 10" in report
    assert "```text" in report


def test_render_task_report_includes_approval_history(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    task = store.create_task("demo approval report", repo_path=tmp_path)
    iteration = store.add_iteration(
        task_id=task.task_id,
        iteration_index=1,
        agent_name="mock",
        agent_status="success",
        prompt="demo approval report",
        raw_output="done",
        decision_status="blocked",
        decision_reason="Approval required",
    )
    approval = store.add_approval_request(
        task_id=task.task_id,
        iteration_id=iteration.iteration_id,
        source="verification",
        command_string="git push origin main",
        reason="Policy requires approval",
    )
    store.resolve_approval_request(
        approval.approval_id,
        "approved",
        resolution="Approved by operator",
    )
    store.record_approval_retry(
        approval.approval_id,
        status="failed",
        exit_code=1,
        error="retry failed",
    )

    report = render_task_report(store, task.task_id)

    assert report is not None
    assert "- Approval requests: `1` (`approved`: 1)" in report
    assert "## Approvals" in report
    assert f"- `{approval.approval_id}`: `approved`" in report
    assert "source=`verification` iteration=`1`" in report
    assert "- Command: `git push origin main`" in report
    assert "- Reason: Policy requires approval" in report
    assert "- Resolution: Approved by operator" in report
    assert "- Retry count: `1`" in report
    assert "- Last retry: `failed` exit=`1`" in report
    assert "- Last retry error: retry failed" in report


def test_render_task_report_redacts_secret_like_verification_output(tmp_path: Path) -> None:
    secret = "ghp_abcdefghijklmnopqrstuvwxyz123456"
    store = StateStore(tmp_path / "state.db")
    task = store.create_task("demo secret", repo_path=tmp_path)
    iteration = store.add_iteration(
        task_id=task.task_id,
        iteration_index=1,
        agent_name="mock",
        agent_status="success",
        prompt="demo secret",
        raw_output="done",
        decision_status="blocked",
        decision_reason="Verification failed after 1 iteration(s): unit: failed exit=1",
    )
    store.add_verification_run(
        task_id=task.task_id,
        iteration_id=iteration.iteration_id,
        result=VerificationResult(
            name="unit",
            status="failed",
            exit_code=1,
            stdout="",
            stderr=f"leaked {secret}",
        ),
    )

    report = render_task_report(store, task.task_id)

    assert report is not None
    assert secret not in report
    assert "***REDACTED***" in report


def test_render_task_report_includes_unavailable_agent_blocker(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    task = store.create_task("demo unavailable", repo_path=tmp_path)
    store.add_iteration(
        task_id=task.task_id,
        iteration_index=1,
        agent_name="generic",
        agent_status="unavailable",
        prompt="demo unavailable",
        raw_output="",
        decision_status="blocked",
        decision_reason="Agent is not available",
    )
    store.update_task_status(task.task_id, "blocked")

    report = render_task_report(store, task.task_id)

    assert report is not None
    assert "- Status: `blocked`" in report
    assert "- Iterations: `1`" in report
    assert "- Verification runs: `0`" in report
    assert "- Verification verdict: `not_verified`" in report
    assert "- Verification note: no final verification run was recorded" in report
    assert "- Final decision: `blocked`" in report
    assert "- Agent: `generic`" in report
    assert "- Agent status: `unavailable`" in report
    assert "- Reason: Agent is not available" in report
    assert "- No verification runs recorded." in report
