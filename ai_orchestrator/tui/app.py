from __future__ import annotations

from ai_orchestrator.storage.db import StateStore


def render_approvals_view(store: StateStore) -> str:
    lines = ["Approvals"]
    pending: list[str] = []
    for task in store.list_tasks():
        for iteration in store.list_iterations(task.task_id):
            checks = store.list_verification_details(task.task_id, iteration.iteration_id)
            for check in checks:
                if check.status != "needs_approval":
                    continue
                pending.extend(
                    [
                        f"  {task.task_id} iteration={iteration.iteration_index} check={check.name}",
                        f"     task: {task.task}",
                        f"     reason: {check.error or 'approval required'}",
                    ]
                )

    if not pending:
        lines.append("  No pending approvals.")
    else:
        lines.extend(pending)
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
