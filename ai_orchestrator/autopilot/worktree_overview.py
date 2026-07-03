from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ai_orchestrator.process.runner import ProcessRunner, RunOptions


@dataclass(frozen=True)
class WorktreeOverview:
    """Read-only snapshot of a single git worktree for operator review."""

    path: Path
    branch: str
    linked: bool | None
    merged: bool | None
    merge_in_progress: bool
    dirty: bool
    dirty_count: int
    untracked_count: int
    last_modified: datetime | None


def _git_output(cwd: Path, args: list[str]) -> str | None:
    result = ProcessRunner().run(
        ["git", *args],
        cwd=cwd,
        options=RunOptions(timeout_sec=30),
    )
    if result.status != "success":
        return None
    return result.stdout.strip()


def _is_git_worktree(path: Path) -> bool:
    return _git_output(path, ["rev-parse", "--is-inside-work-tree"]) == "true"


def _git_common_dir(path: Path) -> Path | None:
    output = _git_output(path, ["rev-parse", "--path-format=absolute", "--git-common-dir"])
    if not output:
        return None
    return Path(output).resolve()


def _linked_branch(path: Path) -> str:
    return _git_output(path, ["rev-parse", "--abbrev-ref", "HEAD"]) or "(unknown)"


def _merge_in_progress(path: Path) -> bool:
    result = ProcessRunner().run(
        ["git", "rev-parse", "--verify", "MERGE_HEAD"],
        cwd=path,
        options=RunOptions(timeout_sec=30),
    )
    return result.status == "success"


def _merged_into_repo(repo: Path | None, branch: str) -> bool | None:
    if repo is None or branch in {"(unknown)", "HEAD"}:
        return None
    result = ProcessRunner().run(
        ["git", "merge-base", "--is-ancestor", branch, "HEAD"],
        cwd=repo,
        options=RunOptions(timeout_sec=30),
    )
    if result.exit_code == 0:
        return True
    if result.exit_code == 1:
        return False
    return None


def _status_counts(path: Path) -> tuple[bool, int, int]:
    output = _git_output(path, ["status", "--porcelain=v1"])
    if output is None:
        # Treat git failures conservatively: we cannot confirm cleanliness.
        return True, 0, 0
    lines = [line for line in output.splitlines() if line]
    dirty = bool(lines)
    untracked = sum(1 for line in lines if line.startswith("?? "))
    return dirty, len(lines), untracked


def _last_modified(path: Path) -> datetime | None:
    try:
        mtime = path.stat().st_mtime
        return datetime.fromtimestamp(mtime, tz=timezone.utc)
    except OSError:
        return None


def inspect_worktree(path: Path, repo: Path | None = None) -> WorktreeOverview | None:
    """Return a read-only overview for *path* if it is a git worktree.

    When *repo* is provided, the ``linked`` field reports whether the worktree
    shares the same git common directory as the repo. The function never
    modifies the worktree.
    """
    if not path.is_dir():
        return None
    if not _is_git_worktree(path):
        return None

    linked: bool | None = None
    if repo is not None:
        repo_common = _git_common_dir(repo)
        worktree_common = _git_common_dir(path)
        linked = (
            repo_common is not None
            and worktree_common is not None
            and repo_common == worktree_common
        )

    dirty, dirty_count, untracked_count = _status_counts(path)
    branch = _linked_branch(path)

    return WorktreeOverview(
        path=path.resolve(),
        branch=branch,
        linked=linked,
        merged=_merged_into_repo(repo, branch) if linked is not False else None,
        merge_in_progress=_merge_in_progress(path),
        dirty=dirty,
        dirty_count=dirty_count,
        untracked_count=untracked_count,
        last_modified=_last_modified(path),
    )


def gather_worktree_overviews(
    base_dir: Path,
    repo: Path | None = None,
) -> list[WorktreeOverview]:
    """Return read-only overviews for every git worktree directory under *base_dir*.

    Non-directory entries and directories that are not git worktrees are
    silently skipped. No files are created, deleted, or modified.
    """
    if not base_dir.is_dir():
        return []

    overviews: list[WorktreeOverview] = []
    for path in sorted(base_dir.iterdir()):
        if not path.is_dir():
            continue
        overview = inspect_worktree(path, repo=repo)
        if overview is not None:
            overviews.append(overview)
    return overviews


def format_worktree_overview(
    overviews: list[WorktreeOverview],
    base_dir: Path,
    repo: Path | None = None,
) -> str:
    """Render *overviews* as a plain-text table for operator review."""
    if not overviews:
        return f"No git worktrees found under {base_dir}"

    lines: list[str] = [
        f"Worktree overview for {base_dir}"
        + (f" (repo: {repo})" if repo else ""),
        "",
        f"{'path':<50} {'branch':<20} {'linked':<7} {'merged':<7} {'merge':<6} {'dirty':<6} {'changes':<8} {'untracked':<10} {'last_modified'}",
        "-" * 133,
    ]
    for overview in overviews:
        linked = (
            "yes"
            if overview.linked is True
            else ("no" if overview.linked is False else "-")
        )
        merged = (
            "yes"
            if overview.merged is True
            else ("no" if overview.merged is False else "-")
        )
        merge = "yes" if overview.merge_in_progress else "no"
        dirty = "yes" if overview.dirty else "no"
        last_modified = (
            overview.last_modified.isoformat()
            if overview.last_modified is not None
            else "-"
        )
        path_str = str(overview.path)
        if len(path_str) > 48:
            path_str = "..." + path_str[-45:]
        lines.append(
            f"{path_str:<50} {overview.branch:<20} {linked:<7} {merged:<7} {merge:<6} "
            f"{dirty:<6} {overview.dirty_count:<8} {overview.untracked_count:<10} {last_modified}"
        )
    return "\n".join(lines)
