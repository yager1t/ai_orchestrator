from __future__ import annotations

import json
from collections import Counter
from collections.abc import Sequence

from ai_orchestrator.storage.db import (
    StateStore,
    StoredActionRecord,
    StoredApprovalRequest,
    StoredIteration,
    StoredMemoryInfluence,
    StoredMemoryLesson,
    StoredPlanItem,
    StoredReplanDecision,
    StoredReflectionRecord,
    StoredTaskEvent,
    StoredTimelineEntry,
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
    task_events = store.list_task_events(task.task_id)
    action_records = store.list_action_records(task.task_id)
    replan_decisions = store.list_replan_decisions(task.task_id)
    memory_lessons = [
        lesson
        for lesson in store.list_memory_lessons(include_stale=True)
        if lesson.source_task_id == task.task_id
    ]
    reflections = store.list_reflection_records(task.task_id)
    memory_influence = store.list_memory_influence(task.task_id)
    timeline_entries = store.list_task_timeline(task.task_id)
    checkpoint_events = _checkpoint_events(task_events)
    recovery_events = _recovery_events(task_events)
    plan_item = _plan_item_for_task(store, task.task_id)
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
        f"- Run id: `{store.run_id_for_task(task.task_id)}`",
        f"- Status: `{task.status}`",
        f"- Repository: `{task.repo_path}`",
        *_queue_worktree_lines(plan_item),
        f"- Task: {task.task}",
        f"- Iterations: `{len(iterations)}`",
        f"- Verification runs: `{len(verification_runs)}`{_status_summary(verification_runs)}",
        f"- Approval requests: `{len(approvals)}`{_approval_status_summary(approvals)}",
        f"- Task events: `{len(task_events)}`",
        f"- Checkpoints: `{len(checkpoint_events)}`",
        f"- Recovery events: `{len(recovery_events)}`",
        f"- Action records: `{len(action_records)}`{_action_status_summary(action_records)}",
        f"- Replan decisions: `{len(replan_decisions)}`",
        f"- Memory lessons: `{len(memory_lessons)}`",
        f"- Reflection records: `{len(reflections)}`",
        f"- Memory influences: `{len(memory_influence)}`",
        f"- Timeline entries: `{len(timeline_entries)}`",
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

    lines.extend(["", "## Timeline", ""])
    lines.extend(_render_timeline_entry_lines(timeline_entries))

    lines.extend(["", "## Recovery And Checkpoints", ""])
    lines.extend(_render_recovery_checkpoint_lines(checkpoint_events, recovery_events))

    lines.extend(["", "## Actions", ""])
    lines.extend(_render_action_record_lines(action_records))

    lines.extend(["", "## Replan Decisions", ""])
    lines.extend(_render_replan_decision_lines(replan_decisions))

    lines.extend(["", "## Memory Lessons", ""])
    lines.extend(_render_memory_lesson_lines(memory_lessons))

    lines.extend(["", "## Reflections", ""])
    lines.extend(_render_reflection_lines(reflections))

    lines.extend(["", "## Memory Influence", ""])
    lines.extend(_render_memory_influence_lines(memory_influence))

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
                f"- Agent summary: {iteration.agent_summary or 'none'}",
                f"- Files changed: `{len(iteration.files_changed)}`",
                f"- Tool actions: `{len(iteration.tool_actions)}`",
                f"- Exit reason: {iteration.exit_reason or 'none'}",
                f"- Uncertainty: {iteration.uncertainty or 'none'}",
                f"- Decision: `{iteration.decision_status}`",
                f"- Reason: {iteration.decision_reason}",
                "",
            ]
        )
        if iteration.files_changed:
            lines.extend(["Files changed:", ""])
            lines.extend(f"- `{path}`" for path in iteration.files_changed)
            lines.append("")
        if iteration.tool_actions:
            lines.extend(["Tool actions:", ""])
            lines.extend(f"- {action}" for action in iteration.tool_actions)
            lines.append("")
        lines.extend(["Verification:", ""])
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


def _plan_item_for_task(store: StateStore, task_id: str) -> StoredPlanItem | None:
    task_items = [item for item in store.list_plan_items() if item.task_id == task_id]
    if not task_items:
        return None
    return next((item for item in task_items if item.selected_worktree_path), task_items[0])


def _queue_worktree_lines(plan_item: StoredPlanItem | None) -> list[str]:
    if plan_item is None or not plan_item.selected_worktree_path:
        return []
    return [f"- Queue worktree: `{plan_item.selected_worktree_path}`"]


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


def _action_status_summary(action_records: Sequence[StoredActionRecord]) -> str:
    if not action_records:
        return ""

    counts = Counter(action.status for action in action_records)
    summary = ", ".join(f"`{status}`: {count}" for status, count in sorted(counts.items()))
    return f" ({summary})"


def _render_timeline_entry_lines(
    timeline_entries: Sequence[StoredTimelineEntry],
) -> list[str]:
    if not timeline_entries:
        return ["No timeline entries recorded."]

    lines: list[str] = []
    for entry in timeline_entries:
        status = f" status=`{entry.status}`" if entry.status else ""
        lines.append(
            (
                f"- `{entry.timeline_index}`: `{entry.event_type}` "
                f"at `{entry.occurred_at}` source=`{entry.source}:{entry.source_id}`"
                f"{status}"
            )
        )
        lines.append(f"  - Summary: {redact_secrets(entry.summary) or ''}")
        if entry.payload:
            payload = json.dumps(entry.payload, ensure_ascii=False, sort_keys=True)
            lines.append(f"  - Payload: `{redact_secrets(payload) or ''}`")
    return lines


def _checkpoint_events(task_events: Sequence[StoredTaskEvent]) -> list[StoredTaskEvent]:
    return [event for event in task_events if event.event_type == "checkpoint_saved"]


def _recovery_events(task_events: Sequence[StoredTaskEvent]) -> list[StoredTaskEvent]:
    return [
        event
        for event in task_events
        if event.event_type in {"task_recovered", "task.recovered"}
    ]


def _render_recovery_checkpoint_lines(
    checkpoint_events: Sequence[StoredTaskEvent],
    recovery_events: Sequence[StoredTaskEvent],
) -> list[str]:
    if not checkpoint_events and not recovery_events:
        return ["No recovery or checkpoint events recorded."]

    lines: list[str] = []
    if checkpoint_events:
        lines.append("Checkpoints:")
        for event in checkpoint_events:
            phase = event.payload.get("phase", "unknown")
            status = event.payload.get("status", "unknown")
            iteration = event.iteration_id or event.payload.get("iteration_index", "none")
            lines.append(
                (
                    f"- `{event.sequence}`: phase=`{phase}` status=`{status}` "
                    f"iteration=`{iteration}` at `{event.created_at}`"
                )
            )
    if recovery_events:
        lines.append("Recovery:")
        for event in recovery_events:
            reason = event.payload.get("reason", event.summary)
            lines.append(
                (
                    f"- `{event.sequence}`: `{event.event_type}` "
                    f"reason={redact_secrets(str(reason)) or ''} at `{event.created_at}`"
                )
            )
    return lines


def _render_action_record_lines(action_records: Sequence[StoredActionRecord]) -> list[str]:
    if not action_records:
        return ["No action records recorded."]

    lines: list[str] = []
    for action in action_records:
        iteration = "none" if action.iteration_id is None else str(action.iteration_id)
        lines.append(
            (
                f"- `{action.action_id}`: `{action.action_type}` status=`{action.status}` "
                f"iteration=`{iteration}` key=`{action.idempotency_key}`"
            )
        )
        if action.command_string:
            lines.append(f"  - Command: `{redact_secrets(action.command_string) or ''}`")
        if action.policy_action:
            lines.append(f"  - Policy: `{action.policy_action}`")
        if action.policy_reason:
            lines.append(f"  - Policy reason: {redact_secrets(action.policy_reason) or ''}")
        if action.lease_owner:
            lines.append(f"  - Lease owner: `{redact_secrets(action.lease_owner) or ''}`")
        if action.lease_expires_at:
            lines.append(f"  - Lease expires: `{action.lease_expires_at}`")
        if action.heartbeat_at:
            lines.append(f"  - Heartbeat: `{action.heartbeat_at}`")
        if action.payload:
            payload = json.dumps(action.payload, ensure_ascii=False, sort_keys=True)
            lines.append(f"  - Payload: `{redact_secrets(payload) or ''}`")
        if action.result:
            result = json.dumps(action.result, ensure_ascii=False, sort_keys=True)
            lines.append(f"  - Result: `{redact_secrets(result) or ''}`")
    return lines


def _render_replan_decision_lines(
    replan_decisions: Sequence[StoredReplanDecision],
) -> list[str]:
    if not replan_decisions:
        return ["No replan decisions recorded."]

    lines: list[str] = []
    for decision in replan_decisions:
        graph_ref = ""
        if decision.plan_graph_id is not None:
            graph_ref = f" graph=`{decision.plan_graph_id}`"
            if decision.plan_graph_node_id is not None:
                graph_ref += f" node=`{decision.plan_graph_node_id}`"
        lines.append(
            (
                f"- `{decision.replan_id}`: status=`{decision.status}` "
                f"source=`{decision.source}` iteration=`{decision.iteration_id}`"
                f"{graph_ref}"
            )
        )
        lines.append(f"  - Reason: {redact_secrets(decision.reason) or ''}")
        if decision.failed_checks:
            checks = ", ".join(
                f"{check.get('name')}: {check.get('status')}"
                for check in decision.failed_checks
            )
            lines.append(f"  - Failed checks: {redact_secrets(checks) or ''}")
        if decision.follow_up_prompt:
            lines.append(
                f"  - Follow-up prompt: {redact_secrets(decision.follow_up_prompt) or ''}"
            )
    return lines


def _render_memory_lesson_lines(
    memory_lessons: Sequence[StoredMemoryLesson],
) -> list[str]:
    if not memory_lessons:
        return ["No memory lessons recorded."]

    lines: list[str] = []
    for lesson in memory_lessons:
        stale = "yes" if lesson.is_stale else "no"
        lines.append(
            (
                f"- `{lesson.lesson_id}`: status=`{lesson.outcome_status}` "
                f"source_task=`{lesson.source_task_id}` stale=`{stale}`"
            )
        )
        lines.append(f"  - Lesson: {redact_secrets(lesson.lesson) or ''}")
        if lesson.failure_reason:
            lines.append(f"  - Failure reason: {redact_secrets(lesson.failure_reason) or ''}")
        if lesson.follow_up_prompt:
            lines.append(f"  - Follow-up: {redact_secrets(lesson.follow_up_prompt) or ''}")
    return lines


def _render_reflection_lines(
    reflections: Sequence[StoredReflectionRecord],
) -> list[str]:
    if not reflections:
        return ["No reflection records recorded."]

    lines: list[str] = []
    for reflection in reflections:
        iteration = "none" if reflection.iteration_id is None else str(reflection.iteration_id)
        lines.append(
            (
                f"- `{reflection.reflection_id}`: `{reflection.reflection_type}` "
                f"iteration=`{iteration}`"
            )
        )
        lines.append(f"  - Failure reason: {redact_secrets(reflection.failure_reason) or ''}")
        if reflection.failed_checks:
            checks = json.dumps(reflection.failed_checks, ensure_ascii=False, sort_keys=True)
            lines.append(f"  - Failed checks: `{redact_secrets(checks) or ''}`")
        if reflection.follow_up_prompt:
            lines.append(f"  - Follow-up: {redact_secrets(reflection.follow_up_prompt) or ''}")
    return lines


def _render_memory_influence_lines(
    memory_influence: Sequence[StoredMemoryInfluence],
) -> list[str]:
    if not memory_influence:
        return ["No memory influence recorded."]

    lines: list[str] = []
    for influence in memory_influence:
        iteration = "none" if influence.iteration_id is None else str(influence.iteration_id)
        injected = "yes" if influence.injected else "no"
        lines.append(
            (
                f"- `{influence.influence_id}`: lesson=`{influence.lesson_id}` "
                f"iteration=`{iteration}` injected=`{injected}`"
            )
        )
        lines.append(f"  - Reason: {redact_secrets(influence.reason) or ''}")
    return lines


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
