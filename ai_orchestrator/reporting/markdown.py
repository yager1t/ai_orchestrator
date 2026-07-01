from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from ai_orchestrator.storage.db import (
    StateStore,
    StoredApprovalRequest,
    StoredIteration,
    StoredVerificationRun,
)
from ai_orchestrator.storage.redaction import redact_secrets


def render_task_report(store: StateStore, task_id: str) -> str | None:
    task = store.get_task(task_id)
    if task is None:
        return None

    iterations = store.list_iterations(task.task_id)
    verification_runs = store.list_verification_runs(task.task_id)
    approvals = store.list_approval_requests(task.task_id)
    final_iteration = iterations[-1] if iterations else None
    final_verification_runs = (
        store.list_verification_runs(task.task_id, final_iteration.iteration_id)
        if final_iteration is not None
        else []
    )

    lines = [
        f"# ai-orch report: {task.task_id}",
        "",
        "## Summary",
        "",
        f"- Status: `{task.status}`",
        f"- Repository: `{task.repo_path}`",
        f"- Task: {task.task}",
        f"- Iterations: `{len(iterations)}`",
        f"- Verification runs: `{len(verification_runs)}`{_status_summary(verification_runs)}",
        f"- Approval requests: `{len(approvals)}`{_approval_status_summary(approvals)}",
        *_verification_verdict_lines(final_iteration, final_verification_runs),
        f"- Created: `{task.created_at}`",
        f"- Updated: `{task.updated_at}`",
    ]

    if final_iteration is not None:
        lines.extend(
            [
                f"- Final decision: `{final_iteration.decision_status}`",
                f"- Final reason: {final_iteration.decision_reason}",
            ]
        )

    lines.extend(["", "## Approvals", ""])
    lines.extend(_render_approval_lines(approvals, iterations))

    lines.extend(["", "## Iterations", ""])

    if not iterations:
        lines.append("No iterations recorded.")
        return "\n".join(lines) + "\n"

    for iteration in iterations:
        lines.extend(
            [
                f"### Iteration {iteration.iteration_index}",
                "",
                f"- Agent: `{iteration.agent_name}`",
                f"- Agent status: `{iteration.agent_status}`",
                f"- Decision: `{iteration.decision_status}`",
                f"- Reason: {iteration.decision_reason}",
                "",
                "Verification:",
                "",
            ]
        )
        checks = store.list_verification_details(task.task_id, iteration.iteration_id)
        if not checks:
            lines.extend(["- No verification runs recorded.", ""])
            continue

        for check in checks:
            exit_code = "none" if check.exit_code is None else str(check.exit_code)
            lines.append(f"- `{check.name}`: `{check.status}` exit=`{exit_code}`")
            excerpt = _verification_excerpt(check.stderr, check.stdout, check.error)
            if check.status != "passed" and excerpt:
                lines.extend(
                    [
                        "",
                        "  ```text",
                        _indent(excerpt, "  "),
                        "  ```",
                    ]
                )
        lines.append("")

    return "\n".join(lines) + "\n"


def _verification_excerpt(stderr: str, stdout: str, error: str | None, limit: int = 1200) -> str:
    excerpt = redact_secrets(error or stderr or stdout) or ""
    if len(excerpt) <= limit:
        return excerpt
    return f"{excerpt[:limit]}\n... truncated ..."


def _indent(text: str, prefix: str) -> str:
    return "\n".join(f"{prefix}{line}" for line in text.splitlines())


def _status_summary(verification_runs: Sequence[StoredVerificationRun]) -> str:
    if not verification_runs:
        return ""

    counts = Counter(run.status for run in verification_runs)
    summary = ", ".join(f"`{status}`: {count}" for status, count in sorted(counts.items()))
    return f" ({summary})"


def _approval_status_summary(approvals: Sequence[StoredApprovalRequest]) -> str:
    if not approvals:
        return ""

    counts = Counter(approval.status for approval in approvals)
    summary = ", ".join(f"`{status}`: {count}" for status, count in sorted(counts.items()))
    return f" ({summary})"


def _verification_verdict_lines(
    final_iteration: StoredIteration | None,
    final_verification_runs: Sequence[StoredVerificationRun],
) -> list[str]:
    verified = (
        final_iteration is not None
        and final_iteration.decision_status == "done"
        and bool(final_verification_runs)
        and all(run.status == "passed" for run in final_verification_runs)
    )
    if verified:
        checks = ", ".join(f"`{run.name}`" for run in final_verification_runs)
        return [
            "- Verification verdict: `verified`",
            f"- Verification note: final supervisor decision is backed by passing checks: {checks}",
        ]
    if not final_verification_runs:
        note = "no final verification run was recorded"
    else:
        statuses = ", ".join(
            f"`{run.name}`: `{run.status}`" for run in final_verification_runs
        )
        note = f"final verification is not fully passing ({statuses})"
    return [
        "- Verification verdict: `not_verified`",
        f"- Verification note: {note}",
    ]


def _render_approval_lines(
    approvals: Sequence[StoredApprovalRequest],
    iterations: Sequence[StoredIteration],
) -> list[str]:
    if not approvals:
        return ["No approval requests recorded."]

    iteration_indexes = {
        iteration.iteration_id: iteration.iteration_index for iteration in iterations
    }
    lines: list[str] = []
    for approval in approvals:
        iteration_label = _approval_iteration_label(approval, iteration_indexes)
        lines.extend(
            [
                (
                    f"- `{approval.approval_id}`: `{approval.status}` "
                    f"source=`{approval.source}` iteration=`{iteration_label}`"
                ),
                f"  - Command: `{redact_secrets(approval.command_string) or ''}`",
                f"  - Reason: {redact_secrets(approval.reason) or ''}",
            ]
        )
        if approval.resolved_at is not None:
            lines.append(f"  - Resolved: `{approval.resolved_at}`")
        if approval.resolution:
            lines.append(f"  - Resolution: {redact_secrets(approval.resolution) or ''}")
        if approval.retry_count:
            exit_code = (
                "none"
                if approval.last_retry_exit_code is None
                else str(approval.last_retry_exit_code)
            )
            lines.append(f"  - Retry count: `{approval.retry_count}`")
            lines.append(f"  - Last retry: `{approval.last_retry_status}` exit=`{exit_code}`")
            if approval.last_retry_at is not None:
                lines.append(f"  - Last retry at: `{approval.last_retry_at}`")
            if approval.last_retry_error:
                lines.append(
                    f"  - Last retry error: {redact_secrets(approval.last_retry_error) or ''}"
                )
    return lines


def _approval_iteration_label(
    approval: StoredApprovalRequest,
    iteration_indexes: dict[int, int],
) -> str:
    if approval.iteration_id is None:
        return "none"
    iteration_index = iteration_indexes.get(approval.iteration_id)
    if iteration_index is None:
        return f"id={approval.iteration_id}"
    return str(iteration_index)
