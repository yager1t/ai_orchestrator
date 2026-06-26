from __future__ import annotations

from ai_orchestrator.storage.db import StateStore


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
        "Iterations",
    ]
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
