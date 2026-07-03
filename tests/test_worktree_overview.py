from __future__ import annotations

import subprocess
from pathlib import Path

from ai_orchestrator.autopilot.worktree_overview import (
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
    assert "No dirty git worktrees found under" in output
