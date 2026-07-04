from __future__ import annotations

import subprocess
from pathlib import Path

from ai_orchestrator.autopilot.worktree_overview import (
    format_cleanup_summary,
    format_worktree_overview,
    gather_worktree_overviews,
    inspect_worktree,
)
from ai_orchestrator.cli.app import main


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def _init_repo(repo: Path) -> None:
    subprocess.run(["git", "init", "--initial-branch=main"], cwd=repo, check=True, capture_output=True)
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "file.txt").write_text("main\n", encoding="utf-8")
    _git(repo, "add", "file.txt")
    _git(repo, "commit", "-m", "initial")


def _create_worktrees(repo: Path, base_dir: Path) -> tuple[Path, Path]:
    base_dir.mkdir(parents=True, exist_ok=True)
    wt1 = base_dir / "wt-main"
    wt2 = base_dir / "wt-feature"
    _git(repo, "worktree", "add", "-b", "wt1", str(wt1), "main")
    _git(repo, "worktree", "add", "-b", "feature", str(wt2), "main")
    return wt1, wt2


def test_inspect_worktree_returns_none_for_non_git_directory(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    assert inspect_worktree(plain) is None


def test_gather_worktree_overviews_empty_base_dir(tmp_path: Path) -> None:
    base = tmp_path / "empty"
    base.mkdir()
    assert gather_worktree_overviews(base) == []


def test_gather_worktree_overviews_skips_non_git_directories(tmp_path: Path) -> None:
    base = tmp_path / "base"
    base.mkdir()
    (base / "not-a-worktree").mkdir()
    assert gather_worktree_overviews(base) == []


def test_gather_worktree_overviews_reports_branches_and_dirty_state(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    base = tmp_path / "worktrees"
    wt1, wt2 = _create_worktrees(repo, base)

    (wt1 / "tracked.txt").write_text("change\n", encoding="utf-8")
    _git(wt1, "add", "tracked.txt")
    (wt1 / "new.txt").write_text("untracked\n", encoding="utf-8")
    (wt2 / "feature.txt").write_text("feature\n", encoding="utf-8")
    _git(wt2, "add", "feature.txt")
    _git(wt2, "commit", "-m", "feature change")

    overviews = gather_worktree_overviews(base, repo=repo)
    assert len(overviews) == 2

    by_path = {str(o.path): o for o in overviews}
    main_overview = by_path[str(wt1.resolve())]
    feature_overview = by_path[str(wt2.resolve())]

    assert main_overview.branch == "wt1"
    assert main_overview.linked is True
    assert main_overview.merged is True
    assert main_overview.dirty is True
    assert main_overview.dirty_count == 2
    assert main_overview.untracked_count == 1
    assert main_overview.merge_in_progress is False
    assert main_overview.last_modified is not None

    assert feature_overview.branch == "feature"
    assert feature_overview.linked is True
    assert feature_overview.merged is False
    assert feature_overview.dirty is False
    assert feature_overview.dirty_count == 0
    assert feature_overview.untracked_count == 0
    assert feature_overview.merge_in_progress is False


def test_inspect_worktree_cleanup_status_for_candidate(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    base = tmp_path / "worktrees"
    wt1, _wt2 = _create_worktrees(repo, base)

    overview = inspect_worktree(wt1, repo=repo)
    assert overview is not None
    assert overview.cleanup_status == "candidate"


def test_inspect_worktree_cleanup_status_for_needs_review(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    base = tmp_path / "worktrees"
    _wt1, wt2 = _create_worktrees(repo, base)
    (wt2 / "feature.txt").write_text("feature\n", encoding="utf-8")
    _git(wt2, "add", "feature.txt")
    _git(wt2, "commit", "-m", "feature change")

    overview = inspect_worktree(wt2, repo=repo)
    assert overview is not None
    assert overview.cleanup_status == "needs_review"


def test_inspect_worktree_cleanup_status_for_do_not_remove(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    base = tmp_path / "worktrees"
    wt1, _wt2 = _create_worktrees(repo, base)
    (wt1 / "dirty.txt").write_text("dirty\n", encoding="utf-8")

    overview = inspect_worktree(wt1, repo=repo)
    assert overview is not None
    assert overview.cleanup_status == "do_not_remove"


def test_inspect_worktree_cleanup_status_for_merge_in_progress(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    base = tmp_path / "worktrees"
    wt1, _wt2 = _create_worktrees(repo, base)
    (wt1 / "file.txt").write_text("wt1 change\n", encoding="utf-8")
    _git(wt1, "add", "file.txt")
    _git(wt1, "commit", "-m", "wt1 change")
    (repo / "file.txt").write_text("main update\n", encoding="utf-8")
    _git(repo, "add", "file.txt")
    _git(repo, "commit", "-m", "main update")

    result = subprocess.run(
        ["git", "merge", "--no-commit", "main"],
        cwd=wt1,
        capture_output=True,
        text=True,
    )
    # A merge conflict is expected; we only need MERGE_HEAD to exist.
    assert result.returncode != 0 or (wt1 / ".git" / "MERGE_HEAD").exists()

    overview = inspect_worktree(wt1, repo=repo)
    assert overview is not None
    assert overview.merge_in_progress is True
    assert overview.cleanup_status == "do_not_remove"


def test_gather_worktree_overviews_unlinked_repo_reports_linked_false(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    other_repo = tmp_path / "other-repo"
    other_repo.mkdir()
    _init_repo(other_repo)

    base = tmp_path / "worktrees"
    wt = base / "wt-other"
    _git(other_repo, "worktree", "add", "-b", "wt-other", str(wt), "main")

    overviews = gather_worktree_overviews(base, repo=repo)
    assert len(overviews) == 1
    assert overviews[0].linked is False


def test_format_worktree_overview_includes_cleanup_summary(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    base = tmp_path / "worktrees"
    wt1, wt2 = _create_worktrees(repo, base)
    (wt1 / "dirty.txt").write_text("dirty\n", encoding="utf-8")

    overviews = gather_worktree_overviews(base, repo=repo)
    output = format_worktree_overview(overviews, base, repo=repo, total_count=len(overviews))

    assert "Cleanup summary:" in output
    assert "candidate=1 needs_review=0 do_not_remove=1" in output


def test_format_cleanup_summary_counts_by_status() -> None:
    from ai_orchestrator.autopilot.worktree_overview import WorktreeOverview

    overviews = [
        WorktreeOverview(
            path=Path("/a"),
            branch="a",
            linked=True,
            merged=True,
            merge_in_progress=False,
            dirty=False,
            dirty_count=0,
            untracked_count=0,
            last_modified=None,
            cleanup_status="candidate",
        ),
        WorktreeOverview(
            path=Path("/b"),
            branch="b",
            linked=True,
            merged=False,
            merge_in_progress=False,
            dirty=False,
            dirty_count=0,
            untracked_count=0,
            last_modified=None,
            cleanup_status="needs_review",
        ),
        WorktreeOverview(
            path=Path("/c"),
            branch="c",
            linked=False,
            merged=None,
            merge_in_progress=False,
            dirty=True,
            dirty_count=1,
            untracked_count=0,
            last_modified=None,
            cleanup_status="do_not_remove",
        ),
    ]
    assert format_cleanup_summary(overviews) == "Cleanup summary: candidate=1 needs_review=1 do_not_remove=1"


def test_format_worktree_overview_table(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    base = tmp_path / "worktrees"
    wt1, wt2 = _create_worktrees(repo, base)
    (wt1 / "dirty.txt").write_text("dirty\n", encoding="utf-8")

    overviews = gather_worktree_overviews(base, repo=repo)
    output = format_worktree_overview(overviews, base, repo=repo)

    assert "Worktree overview" in output
    assert "wt1" in output
    assert "feature" in output
    assert "yes" in output
    assert "dirty.txt" not in output  # table does not list filenames


def test_format_worktree_overview_empty(tmp_path: Path) -> None:
    base = tmp_path / "base"
    base.mkdir()
    output = format_worktree_overview([], base)
    assert output == f"No git worktrees found under {base}"


def test_format_worktree_overview_includes_review_hint(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    base = tmp_path / "worktrees"
    _create_worktrees(repo, base)

    overviews = gather_worktree_overviews(base, repo=repo)
    output = format_worktree_overview(overviews, base, repo=repo)

    assert "Review hint:" in output
    assert "squash merge" in output
    assert "strict ancestry" in output
    assert "git log --oneline HEAD..<branch>" in output
    assert "git diff --stat HEAD...<branch>" in output
    assert "never deletes, prunes, or modifies" in output
    assert "candidate" in output
    assert "needs_review" in output
    assert "do_not_remove" in output


def test_cli_worktree_overview(capsys, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    base = tmp_path / "worktrees"
    _create_worktrees(repo, base)

    exit_code = main([
        "autopilot",
        "worktree-overview",
        "--repo",
        str(repo),
        "--base-dir",
        str(base),
    ])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Worktree overview" in output
    assert "wt-main" in output
    assert "wt-feature" in output
    assert "Cleanup summary:" in output


def test_cli_worktree_overview_missing_base_dir(capsys, tmp_path: Path) -> None:
    exit_code = main([
        "autopilot",
        "worktree-overview",
        "--repo",
        str(tmp_path),
        "--base-dir",
        str(tmp_path / "missing"),
    ])
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "Base directory does not exist" in output


def test_cli_worktree_overview_dirty_only(capsys, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    base = tmp_path / "worktrees"
    wt1, wt2 = _create_worktrees(repo, base)
    (wt1 / "dirty.txt").write_text("dirty\n", encoding="utf-8")

    exit_code = main([
        "autopilot",
        "worktree-overview",
        "--repo",
        str(repo),
        "--base-dir",
        str(base),
        "--dirty-only",
    ])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "wt-main" in output
    assert "wt-feature" not in output


def test_cli_worktree_overview_unlinked_only(capsys, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    other_repo = tmp_path / "other-repo"
    other_repo.mkdir()
    _init_repo(other_repo)

    base = tmp_path / "worktrees"
    wt_linked = base / "wt-linked"
    wt_unlinked = base / "wt-unlinked"
    _git(repo, "worktree", "add", "-b", "wt-linked", str(wt_linked), "main")
    _git(other_repo, "worktree", "add", "-b", "wt-unlinked", str(wt_unlinked), "main")

    exit_code = main([
        "autopilot",
        "worktree-overview",
        "--repo",
        str(repo),
        "--base-dir",
        str(base),
        "--unlinked-only",
    ])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "wt-unlinked" in output
    assert "wt-linked" not in output
    assert "Summary: total=2 shown=1 dirty=0 unlinked=1" in output


def test_cli_worktree_overview_unlinked_only_empty(capsys, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    base = tmp_path / "worktrees"
    wt = base / "wt-linked"
    _git(repo, "worktree", "add", "-b", "wt-linked", str(wt), "main")

    exit_code = main([
        "autopilot",
        "worktree-overview",
        "--repo",
        str(repo),
        "--base-dir",
        str(base),
        "--unlinked-only",
    ])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Summary: total=1 shown=0 dirty=0 unlinked=0" in output
    assert "No unlinked git worktrees found under" in output


def test_cli_worktree_overview_merged_only(capsys, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    base = tmp_path / "worktrees"
    wt1, wt2 = _create_worktrees(repo, base)
    (wt2 / "feature.txt").write_text("feature\n", encoding="utf-8")
    _git(wt2, "add", "feature.txt")
    _git(wt2, "commit", "-m", "feature change")

    exit_code = main([
        "autopilot",
        "worktree-overview",
        "--repo",
        str(repo),
        "--base-dir",
        str(base),
        "--merged-only",
    ])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "wt-main" in output
    assert "wt-feature" not in output
    assert "Summary: total=2 shown=1 dirty=0 unlinked=0" in output


def test_cli_worktree_overview_merged_only_empty(capsys, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    base = tmp_path / "worktrees"
    wt = base / "wt-feature"
    _git(repo, "worktree", "add", "-b", "feature", str(wt), "main")
    (wt / "feature.txt").write_text("feature\n", encoding="utf-8")
    _git(wt, "add", "feature.txt")
    _git(wt, "commit", "-m", "feature change")

    exit_code = main([
        "autopilot",
        "worktree-overview",
        "--repo",
        str(repo),
        "--base-dir",
        str(base),
        "--merged-only",
    ])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Summary: total=1 shown=0 dirty=0 unlinked=0" in output
    assert "No merged git worktrees found under" in output


def test_cli_worktree_overview_branch_filter(capsys, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    base = tmp_path / "worktrees"
    _create_worktrees(repo, base)

    exit_code = main([
        "autopilot",
        "worktree-overview",
        "--repo",
        str(repo),
        "--base-dir",
        str(base),
        "--branch-filter",
        "fea",
    ])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "feature" in output
    assert "wt1" not in output


def test_cli_worktree_overview_branch_filter_empty(capsys, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    base = tmp_path / "worktrees"
    _create_worktrees(repo, base)

    exit_code = main([
        "autopilot",
        "worktree-overview",
        "--repo",
        str(repo),
        "--base-dir",
        str(base),
        "--branch-filter",
        "nonexistent",
    ])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Summary: total=2 shown=0 dirty=0 unlinked=0" in output
    assert "No git worktrees matching branch filter 'nonexistent'" in output


def test_cli_worktree_overview_dirty_only_empty(capsys, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    base = tmp_path / "worktrees"
    _create_worktrees(repo, base)

    exit_code = main([
        "autopilot",
        "worktree-overview",
        "--repo",
        str(repo),
        "--base-dir",
        str(base),
        "--dirty-only",
    ])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Summary: total=2 shown=0 dirty=0 unlinked=0" in output
    assert "No dirty git worktrees found under" in output


def test_format_worktree_overview_summary_line(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    base = tmp_path / "worktrees"
    wt1, wt2 = _create_worktrees(repo, base)
    (wt1 / "dirty.txt").write_text("dirty\n", encoding="utf-8")

    overviews = gather_worktree_overviews(base, repo=repo)
    output = format_worktree_overview(overviews, base, repo=repo, total_count=len(overviews))

    assert "Summary: total=2 shown=2 dirty=1 unlinked=0" in output


def test_cli_worktree_overview_includes_summary_line(capsys, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    base = tmp_path / "worktrees"
    wt1, wt2 = _create_worktrees(repo, base)
    (wt1 / "dirty.txt").write_text("dirty\n", encoding="utf-8")

    exit_code = main([
        "autopilot",
        "worktree-overview",
        "--repo",
        str(repo),
        "--base-dir",
        str(base),
    ])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Summary: total=2 shown=2 dirty=1 unlinked=0" in output


def test_cli_worktree_overview_summary_reflects_filters(capsys, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    base = tmp_path / "worktrees"
    wt1, wt2 = _create_worktrees(repo, base)
    (wt1 / "dirty.txt").write_text("dirty\n", encoding="utf-8")

    exit_code = main([
        "autopilot",
        "worktree-overview",
        "--repo",
        str(repo),
        "--base-dir",
        str(base),
        "--dirty-only",
    ])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Summary: total=2 shown=1 dirty=1 unlinked=0" in output
    assert "wt-feature" not in output


def test_cli_worktree_overview_unlinked_summary_count(capsys, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    other_repo = tmp_path / "other-repo"
    other_repo.mkdir()
    _init_repo(other_repo)

    base = tmp_path / "worktrees"
    wt = base / "wt-other"
    _git(other_repo, "worktree", "add", "-b", "wt-other", str(wt), "main")

    exit_code = main([
        "autopilot",
        "worktree-overview",
        "--repo",
        str(repo),
        "--base-dir",
        str(base),
    ])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Summary: total=1 shown=1 dirty=0 unlinked=1" in output


def test_cli_worktree_overview_cleanup_status_candidate(capsys, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    base = tmp_path / "worktrees"
    _wt1, wt2 = _create_worktrees(repo, base)
    (wt2 / "feature.txt").write_text("feature\n", encoding="utf-8")
    _git(wt2, "add", "feature.txt")
    _git(wt2, "commit", "-m", "feature change")

    exit_code = main([
        "autopilot",
        "worktree-overview",
        "--repo",
        str(repo),
        "--base-dir",
        str(base),
        "--cleanup-status",
        "candidate",
    ])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "wt-main" in output
    assert "wt-feature" not in output
    assert "Summary: total=2 shown=1 dirty=0 unlinked=0" in output


def test_cli_worktree_overview_cleanup_status_needs_review(capsys, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    base = tmp_path / "worktrees"
    _wt1, wt2 = _create_worktrees(repo, base)
    (wt2 / "feature.txt").write_text("feature\n", encoding="utf-8")
    _git(wt2, "add", "feature.txt")
    _git(wt2, "commit", "-m", "feature change")

    exit_code = main([
        "autopilot",
        "worktree-overview",
        "--repo",
        str(repo),
        "--base-dir",
        str(base),
        "--cleanup-status",
        "needs_review",
    ])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "wt-feature" in output
    assert "wt-main" not in output
    assert "Summary: total=2 shown=1 dirty=0 unlinked=0" in output


def test_cli_worktree_overview_cleanup_status_do_not_remove(capsys, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    base = tmp_path / "worktrees"
    wt1, _wt2 = _create_worktrees(repo, base)
    (wt1 / "dirty.txt").write_text("dirty\n", encoding="utf-8")

    exit_code = main([
        "autopilot",
        "worktree-overview",
        "--repo",
        str(repo),
        "--base-dir",
        str(base),
        "--cleanup-status",
        "do_not_remove",
    ])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "wt-main" in output
    assert "wt-feature" not in output
    assert "Summary: total=2 shown=1 dirty=1 unlinked=0" in output


def test_cli_worktree_overview_cleanup_status_empty(capsys, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    base = tmp_path / "worktrees"
    wt = base / "wt-main"
    _git(repo, "worktree", "add", "-b", "wt1", str(wt), "main")

    exit_code = main([
        "autopilot",
        "worktree-overview",
        "--repo",
        str(repo),
        "--base-dir",
        str(base),
        "--cleanup-status",
        "needs_review",
    ])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Summary: total=1 shown=0 dirty=0 unlinked=0" in output
    assert "No git worktrees matching cleanup status 'needs_review'" in output
