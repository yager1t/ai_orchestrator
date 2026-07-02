from pathlib import Path

from ai_orchestrator.autopilot import load_plan_tasks, next_task
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
