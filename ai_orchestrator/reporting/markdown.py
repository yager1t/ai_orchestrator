from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from ai_orchestrator.storage.db import StateStore, StoredVerificationRun
from ai_orchestrator.storage.redaction import redact_secrets


def render_task_report(store: StateStore, task_id: str) -> str | None:
    task = store.get_task(task_id)
    if task is None:
        return None

    iterations = store.list_iterations(task.task_id)
    verification_runs = store.list_verification_runs(task.task_id)
    final_iteration = iterations[-1] if iterations else None

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

    lines.extend(
        [
        "",
        "## Iterations",
        "",
        ]
    )

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
