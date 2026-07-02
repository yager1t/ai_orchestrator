from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ai_orchestrator.storage.db import StateStore, StoredPlanItem, StoredTask


_CHECKBOX_RE = re.compile(r"^(?P<indent>\s*)-\s+\[\s\]\s+(?P<text>.+)$")
_NUMBERED_RE = re.compile(r"^(?P<indent>\s*)\d+\.\s+(?P<text>.+)$")


@dataclass(frozen=True)
class AutopilotTask:
    source_path: Path
    line_number: int
    text: str
    section: str

    @property
    def source_label(self) -> str:
        return f"{self.source_path.as_posix()}:{self.line_number}"

    def to_prompt(self) -> str:
        return "\n".join(
            [
                "Autopilot plan item:",
                f"- Source: {self.source_label}",
                f"- Section: {self.section or 'Unsectioned'}",
                f"- Task: {self.text}",
                "",
                "Work in a small bounded step. Follow repository instructions, keep the",
                "diff minimal, run verification, and stop when the supervisor can decide",
                "whether to continue, mark done, or block.",
            ]
        )


def load_plan_tasks(plan_path: Path) -> list[AutopilotTask]:
    text = plan_path.read_text(encoding="utf-8")
    tasks: list[AutopilotTask] = []
    section = ""
    in_immediate_track = False
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        stripped = raw_line.strip()
        if stripped.startswith("#"):
            section = stripped.lstrip("#").strip()
            in_immediate_track = section == "Immediate Implementation Track"
            continue

        checkbox_match = _CHECKBOX_RE.match(raw_line)
        if checkbox_match:
            tasks.append(
                AutopilotTask(
                    source_path=plan_path,
                    line_number=line_number,
                    text=_normalize_task_text(checkbox_match.group("text")),
                    section=section,
                )
            )
            continue

        if in_immediate_track:
            numbered_match = _NUMBERED_RE.match(raw_line)
            if numbered_match:
                tasks.append(
                    AutopilotTask(
                        source_path=plan_path,
                        line_number=line_number,
                        text=_normalize_task_text(numbered_match.group("text")),
                        section=section,
                    )
                )
    return tasks


def next_task(tasks: list[AutopilotTask], store: StateStore) -> AutopilotTask | None:
    existing = store.list_tasks()
    for task in tasks:
        if not _already_started(task, existing):
            return task
    return None


def next_plan_item(
    store: StateStore,
    plan_path: Path,
) -> StoredPlanItem | None:
    """Return the next persisted plan item ready to run.

    Selects the oldest queued item with status ``created`` for the given
    *plan_path*, ordered by line number.
    """
    items = next_plan_items(store, plan_path, limit=1)
    return items[0] if items else None


def next_plan_items(
    store: StateStore,
    plan_path: Path,
    limit: int | None = None,
) -> list[StoredPlanItem]:
    """Return the next persisted plan items ready to run.

    Selects queued items with status ``created`` for the given *plan_path*,
    ordered by line number.  When *limit* is provided, returns at most that
    many items.
    """
    items = store.list_plan_items(plan_path=plan_path, status="created")
    if limit is None:
        return items
    return items[:max(0, limit)]


def plan_item_to_task(item: StoredPlanItem) -> AutopilotTask:
    """Convert a persisted plan item back into an executable task."""
    return AutopilotTask(
        source_path=Path(item.plan_path),
        line_number=item.line_number,
        text=item.text,
        section=item.section,
    )


def plan_item_status_from_supervisor(supervisor_status: str) -> str:
    """Map a supervisor result status to a persisted plan item status."""
    if supervisor_status == "done":
        return "done"
    if supervisor_status in {"blocked", "cancelled"}:
        return "blocked"
    return "blocked"


def sync_plan_items(
    plan_path: Path,
    store: StateStore,
) -> tuple[list[StoredPlanItem], list[StoredPlanItem]]:
    """Load tasks from *plan_path* and persist them without duplicates.

    Returns a tuple of (new_items, existing_items) for the plan.
    """
    tasks = load_plan_tasks(plan_path)
    existing = {item.line_number: item for item in store.list_plan_items(plan_path=plan_path)}
    new_items: list[StoredPlanItem] = []
    for task in tasks:
        if task.line_number in existing:
            continue
        new_items.append(
            store.record_plan_item(
                plan_path=plan_path,
                line_number=task.line_number,
                section=task.section,
                text=task.text,
            )
        )
    return new_items, list(existing.values())


def _already_started(task: AutopilotTask, existing: list[StoredTask]) -> bool:
    source = task.source_label
    for stored_task in existing:
        if source in stored_task.task or task.text in stored_task.task:
            return True
    return False


def _normalize_task_text(text: str) -> str:
    return " ".join(text.strip().split())
