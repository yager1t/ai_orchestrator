from __future__ import annotations

from ai_orchestrator.storage.db import StateStore, StoredApprovalRequest
from ai_orchestrator.storage.redaction import redact_secrets


def render_approvals_view(store: StateStore) -> str:
    lines = ["Approvals"]
    approvals = store.list_approval_requests()

    if not approvals:
        lines.append("  No approval requests recorded.")
    else:
        lines.extend(_format_approval_lines(approvals))
    return "\n".join(lines) + "\n"


def render_current_view(store: StateStore, task_id: str) -> str | None:
    task = store.get_task(task_id)
    if task is None:
        return None

    lines = [
        f"Current iteration for {task.task_id}",
        f"Status: {task.status}",
        f"Summary: {task.task}",
    ]
    iterations = store.list_iterations(task.task_id)
    if not iterations:
        lines.append("No iterations recorded.")
        return "\n".join(lines) + "\n"

    iteration = iterations[-1]
    lines.extend(
        [
            f"Iteration: {iteration.iteration_index}",
            f"Agent: {iteration.agent_name}",
            f"Agent status: {iteration.agent_status}",
            f"Decision: {iteration.decision_status}",
            f"Reason: {iteration.decision_reason}",
            "Verification",
        ]
    )
    checks = store.list_verification_runs(task.task_id, iteration.iteration_id)
    if not checks:
        lines.append("  No verification runs recorded.")
    for check in checks:
        lines.append(f"  {check.name}: {check.status} exit={check.exit_code}")
    return "\n".join(lines) + "\n"


def render_logs_view(store: StateStore, task_id: str) -> str | None:
    task = store.get_task(task_id)
    if task is None:
        return None

    lines = [f"Logs for {task.task_id}", f"Summary: {task.task}"]
    iterations = store.list_iteration_details(task.task_id)
    if not iterations:
        lines.append("No iterations recorded.")
        return "\n".join(lines) + "\n"

    for iteration in iterations:
        lines.extend(
            [
                f"Iteration {iteration.iteration_index}",
                f"  agent: {iteration.agent_name}",
                f"  prompt: {_one_line(iteration.prompt)}",
                f"  output: {_one_line(iteration.raw_output)}",
                f"  decision: {iteration.decision_status}",
                f"  reason: {iteration.decision_reason}",
            ]
        )
    return "\n".join(lines) + "\n"


def render_tasks_view(store: StateStore) -> str:
    tasks = store.list_tasks()
    lines = ["Tasks"]
    if not tasks:
        lines.append("  No tasks recorded.")
        return "\n".join(lines) + "\n"

    for task in tasks:
        lines.append(f"  {task.task_id} [{task.status}] {task.task}")
        lines.append(f"     updated: {task.updated_at}")

    return "\n".join(lines) + "\n"


def _one_line(value: str, limit: int = 160) -> str:
    rendered = " ".join(value.splitlines())
    if len(rendered) <= limit:
        return rendered
    return f"{rendered[:limit]}..."


def render_status_view(store: StateStore, task_id: str) -> str | None:
    task = store.get_task(task_id)
    if task is None:
        return None

    lines = [
        f"Task {task.task_id}",
        f"Status: {task.status}",
        f"Repo: {task.repo_path}",
        f"Summary: {task.task}",
        "",
        "Approvals",
    ]
    approvals = store.list_approval_requests(task.task_id)
    if approvals:
        lines.extend(_format_approval_lines(approvals))
    else:
        lines.append("  No approval requests recorded.")

    lines.extend(["", "Iterations"])
    iterations = store.list_iterations(task.task_id)
    if not iterations:
        lines.append("  No iterations recorded.")
        return "\n".join(lines) + "\n"

    for iteration in iterations:
        lines.extend(
            [
                f"  {iteration.iteration_index}. {iteration.agent_name}",
                f"     agent_status: {iteration.agent_status}",
                f"     decision: {iteration.decision_status}",
                f"     reason: {iteration.decision_reason}",
            ]
        )
        checks = store.list_verification_runs(task.task_id, iteration.iteration_id)
        for check in checks:
            lines.append(f"     check: {check.name} {check.status} exit={check.exit_code}")

    return "\n".join(lines) + "\n"


def _format_approval_lines(approvals: list[StoredApprovalRequest]) -> list[str]:
    lines: list[str] = []
    for approval in approvals:
        iteration = "none" if approval.iteration_id is None else str(approval.iteration_id)
        lines.extend(
            [
                (
                    f"  approval={approval.approval_id} status={approval.status} "
                    f"source={approval.source} task={approval.task_id} iteration={iteration}"
                ),
                f"     command: {redact_secrets(approval.command_string) or ''}",
                f"     reason: {redact_secrets(approval.reason) or ''}",
            ]
        )
        if approval.resolved_at is not None:
            lines.append(f"     resolved_at: {approval.resolved_at}")
        if approval.resolution:
            lines.append(f"     resolution: {redact_secrets(approval.resolution) or ''}")
    return lines
