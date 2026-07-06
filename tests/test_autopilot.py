from pathlib import Path

from ai_orchestrator.autopilot import (
    load_backlog_tasks,
    load_plan_tasks,
    next_plan_item,
    next_task,
    plan_item_status_from_supervisor,
    refresh_created_backlog_item_refs,
    sync_backlog_items,
    sync_plan_items,
)
from ai_orchestrator.storage.db import StateStore


def test_load_plan_tasks_reads_checkboxes_and_immediate_track(tmp_path: Path) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text(
        "\n".join(
            [
                "# Roadmap",
                "",
                "## Phase 1",
                "",
                "- [ ] Add release docs",
                "- [x] Already done",
                "",
                "## Immediate Implementation Track",
                "",
                "1. Add approval persistence.",
                "2. Add approval CLI.",
            ]
        ),
        encoding="utf-8",
    )

    tasks = load_plan_tasks(plan)

    assert [task.text for task in tasks] == [
        "Add release docs",
        "Add approval persistence.",
        "Add approval CLI.",
    ]
    assert tasks[0].section == "Phase 1"
    assert tasks[1].section == "Immediate Implementation Track"


def test_load_backlog_tasks_reads_open_priority_bullets(tmp_path: Path) -> None:
    backlog = tmp_path / "BACKLOG.md"
    backlog.write_text(
        "\n".join(
            [
                "# Backlog",
                "",
                "## P0",
                "",
                "No open P0 items.",
                "",
                "## P1",
                "",
                "- Ship critical fix",
                "",
                "## P2",
                "",
                "- Add queue history filters if recent summaries are not enough",
                "  for daily operation.",
                "",
                "## P3 / Deferred",
                "",
                "- Defer optional dashboard.",
            ]
        ),
        encoding="utf-8",
    )

    tasks = load_backlog_tasks(backlog)

    assert [task.text for task in tasks] == [
        "Ship critical fix",
        "Add queue history filters if recent summaries are not enough for daily operation.",
    ]
    assert [task.section for task in tasks] == ["P1", "P2"]


def test_next_task_skips_existing_stored_tasks(tmp_path: Path) -> None:
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
    store = StateStore(tmp_path / "state.db")
    tasks = load_plan_tasks(plan)
    store.create_task(tasks[0].to_prompt(), repo_path=tmp_path)

    selected = next_task(tasks, store)

    assert selected is not None
    assert selected.text == "Second task"


def test_next_task_matches_started_task_by_exact_source_line(tmp_path: Path) -> None:
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
    store = StateStore(tmp_path / "state.db")
    tasks = load_plan_tasks(plan)
    stored_prompt = "\n".join(
        [
            "Autopilot plan item:",
            f"- Source: {plan.as_posix()}:30",
            "- Section: Roadmap",
            "- Task: First task",
        ]
    )
    store.create_task(stored_prompt, repo_path=tmp_path)

    selected = next_task(tasks, store)

    assert selected is not None
    assert selected.source_label == tasks[0].source_label


def test_recording_plan_items_does_not_execute_or_reorder_them(
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
                "- [ ] Third task",
            ]
        ),
        encoding="utf-8",
    )
    store = StateStore(tmp_path / "state.db")
    tasks = load_plan_tasks(plan)

    for task in tasks:
        store.record_plan_item(
            plan_path=task.source_path,
            line_number=task.line_number,
            section=task.section,
            text=task.text,
        )

    recorded = store.list_plan_items()
    assert len(recorded) == 3
    assert [item.text for item in recorded] == [
        "First task",
        "Second task",
        "Third task",
    ]

    selected = next_task(tasks, store)
    assert selected is not None
    assert selected.text == "First task"


def test_sync_plan_items_persists_without_duplicates(tmp_path: Path) -> None:
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
    store = StateStore(tmp_path / "state.db")

    new_items, existing_items = sync_plan_items(plan, store)

    assert len(new_items) == 2
    assert len(existing_items) == 0
    assert store.list_plan_items(plan_path=plan)[0].text == "First task"

    new_items, existing_items = sync_plan_items(plan, store)

    assert len(new_items) == 0
    assert len(existing_items) == 2
    assert len(store.list_plan_items(plan_path=plan)) == 2


def test_sync_plan_items_records_changed_line_as_new_item(tmp_path: Path) -> None:
    plan = tmp_path / "ROADMAP.md"
    plan.write_text("- [ ] Original task\n", encoding="utf-8")
    store = StateStore(tmp_path / "state.db")

    new_items, existing_items = sync_plan_items(plan, store)
    store.update_plan_item_status(new_items[0].plan_item_id, "skipped")
    plan.write_text("- [ ] Replacement task\n", encoding="utf-8")

    new_items, existing_items = sync_plan_items(plan, store)
    items = store.list_plan_items(plan_path=plan)

    assert len(new_items) == 1
    assert len(existing_items) == 1
    assert len(items) == 2
    assert items[0].text == "Original task"
    assert items[0].status == "skipped"
    assert items[1].text == "Replacement task"
    assert items[1].status == "created"


def test_sync_backlog_items_persists_without_duplicates(tmp_path: Path) -> None:
    backlog = tmp_path / "BACKLOG.md"
    backlog.write_text(
        "\n".join(
            [
                "# Backlog",
                "",
                "## P2",
                "",
                "- Add queue history filters",
            ]
        ),
        encoding="utf-8",
    )
    store = StateStore(tmp_path / "state.db")

    new_items, existing_items = sync_backlog_items(backlog, store)

    assert len(new_items) == 1
    assert len(existing_items) == 0
    assert store.list_plan_items(plan_path=backlog)[0].section == "P2"

    new_items, existing_items = sync_backlog_items(backlog, store)

    assert len(new_items) == 0
    assert len(existing_items) == 1


def test_sync_backlog_items_records_changed_line_as_new_item(tmp_path: Path) -> None:
    backlog = tmp_path / "BACKLOG.md"
    backlog.write_text(
        "\n".join(["# Backlog", "", "## P2", "", "- Original backlog task"]),
        encoding="utf-8",
    )
    store = StateStore(tmp_path / "state.db")

    new_items, existing_items = sync_backlog_items(backlog, store)
    store.update_plan_item_status(new_items[0].plan_item_id, "skipped")
    backlog.write_text(
        "\n".join(["# Backlog", "", "## P2", "", "- Replacement backlog task"]),
        encoding="utf-8",
    )

    new_items, existing_items = sync_backlog_items(backlog, store)
    items = store.list_plan_items(plan_path=backlog)

    assert len(new_items) == 1
    assert len(existing_items) == 1
    assert len(items) == 2
    assert items[0].text == "Original backlog task"
    assert items[0].status == "skipped"
    assert items[1].text == "Replacement backlog task"
    assert items[1].status == "created"


def test_refresh_created_backlog_item_refs_updates_shifted_created_item(
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
                "- Completed task",
                "- Keep created task",
            ]
        ),
        encoding="utf-8",
    )
    store = StateStore(tmp_path / "state.db")
    sync_backlog_items(backlog, store)
    completed, created = store.list_plan_items(plan_path=backlog)
    store.update_plan_item_status(completed.plan_item_id, "done")

    backlog.write_text(
        "\n".join(["# Backlog", "", "## P2", "", "- Keep created task"]),
        encoding="utf-8",
    )

    refreshes = refresh_created_backlog_item_refs(backlog, store)
    dry_run_item = store.get_plan_item(created.plan_item_id)

    assert len(refreshes) == 1
    assert refreshes[0].item.plan_item_id == created.plan_item_id
    assert refreshes[0].item.line_number == 6
    assert refreshes[0].line_number == 5
    assert dry_run_item is not None
    assert dry_run_item.line_number == 6

    refresh_created_backlog_item_refs(backlog, store, apply=True)
    updated = store.get_plan_item(created.plan_item_id)
    new_items, existing_items = sync_backlog_items(backlog, store)

    assert updated is not None
    assert updated.plan_item_id == created.plan_item_id
    assert updated.status == "created"
    assert updated.text == "Keep created task"
    assert updated.line_number == 5
    assert len(new_items) == 0
    assert len(existing_items) == 1


def test_refresh_created_backlog_item_refs_skips_ambiguous_matches(
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
                "- Completed task",
                "- Duplicate task",
            ]
        ),
        encoding="utf-8",
    )
    store = StateStore(tmp_path / "state.db")
    sync_backlog_items(backlog, store)
    completed, created = store.list_plan_items(plan_path=backlog)
    store.update_plan_item_status(completed.plan_item_id, "done")

    backlog.write_text(
        "\n".join(
            [
                "# Backlog",
                "",
                "## P2",
                "",
                "- Duplicate task",
                "- Duplicate task",
            ]
        ),
        encoding="utf-8",
    )

    refreshes = refresh_created_backlog_item_refs(backlog, store, apply=True)
    unchanged = store.get_plan_item(created.plan_item_id)

    assert refreshes == []
    assert unchanged is not None
    assert unchanged.line_number == 6


def test_next_plan_item_selects_first_created_item(tmp_path: Path) -> None:
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
    store = StateStore(tmp_path / "state.db")
    sync_plan_items(plan, store)
    first, second = store.list_plan_items(plan_path=plan)
    store.update_plan_item_status(first.plan_item_id, "done")

    selected = next_plan_item(store, plan)

    assert selected is not None
    assert selected.plan_item_id == second.plan_item_id
    assert selected.text == "Second task"


def test_plan_item_status_from_supervisor_maps_result_statuses() -> None:
    assert plan_item_status_from_supervisor("done") == "done"
    assert plan_item_status_from_supervisor("blocked") == "blocked"
    assert plan_item_status_from_supervisor("cancelled") == "blocked"
    assert plan_item_status_from_supervisor("unknown") == "blocked"
