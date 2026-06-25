from __future__ import annotations

from ai_orchestrator.storage.db import StateStore


def render_task_report(store: StateStore, task_id: str) -> str | None:
    task = store.get_task(task_id)
    if task is None:
        return None

    lines = [
        f"# ai-orch report: {task.task_id}",
        "",
        "## Summary",
        "",
        f"- Status: `{task.status}`",
        f"- Repository: `{task.repo_path}`",
        f"- Task: {task.task}",
        f"- Created: `{task.created_at}`",
        f"- Updated: `{task.updated_at}`",
        "",
        "## Iterations",
        "",
    ]

    iterations = store.list_iterations(task.task_id)
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
    excerpt = error or stderr or stdout
    if len(excerpt) <= limit:
        return excerpt
    return f"{excerpt[:limit]}\n... truncated ..."


def _indent(text: str, prefix: str) -> str:
    return "\n".join(f"{prefix}{line}" for line in text.splitlines())
