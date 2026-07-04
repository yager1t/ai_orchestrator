from __future__ import annotations

from dataclasses import dataclass, replace
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
    cleanup_status: str


def _cleanup_status(overview: WorktreeOverview) -> str:
    """Classify a worktree for operator cleanup review.

    - ``do_not_remove`` when the worktree has uncommitted/untracked changes or
      an active merge, because deletion could lose work.
    - ``candidate`` when the worktree is linked to the review repo, its branch
      is merged into HEAD, and it is clean with no merge in progress.
    - ``needs_review`` for everything else (e.g. not merged, unlinked, or
      branch status uncertain).
    """
    if overview.dirty or overview.merge_in_progress:
        return "do_not_remove"
    if overview.linked is True and overview.merged is True:
        return "candidate"
    return "needs_review"


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

    overview = WorktreeOverview(
        path=path.resolve(),
        branch=branch,
        linked=linked,
        merged=_merged_into_repo(repo, branch) if linked is not False else None,
        merge_in_progress=_merge_in_progress(path),
        dirty=dirty,
        dirty_count=dirty_count,
        untracked_count=untracked_count,
        last_modified=_last_modified(path),
        cleanup_status="needs_review",
    )
    return replace(overview, cleanup_status=_cleanup_status(overview))


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


def format_worktree_summary(
    overviews: list[WorktreeOverview],
    total_count: int,
) -> str:
    """Render a one-line read-only summary for an overview result set."""
    shown = len(overviews)
    dirty = sum(1 for overview in overviews if overview.dirty)
    unlinked = sum(1 for overview in overviews if overview.linked is False)
    return f"Summary: total={total_count} shown={shown} dirty={dirty} unlinked={unlinked}"


def format_cleanup_summary(overviews: list[WorktreeOverview]) -> str:
    """Render a one-line cleanup candidate summary for operator review."""
    candidate = sum(1 for overview in overviews if overview.cleanup_status == "candidate")
    needs_review = sum(
        1 for overview in overviews if overview.cleanup_status == "needs_review"
    )
    do_not_remove = sum(
        1 for overview in overviews if overview.cleanup_status == "do_not_remove"
    )
    return (
        f"Cleanup summary: "
        f"candidate={candidate} needs_review={needs_review} do_not_remove={do_not_remove}"
    )


_REVIEW_HINT = """
Review hint:
  The 'merged' column uses strict ancestry (git merge-base --is-ancestor <branch> HEAD).
  After a squash merge, the branch commits are usually not ancestors of HEAD, so
  'merged' can stay 'no' even when the changes are already present in the main history.
  The 'cleanup' column is a read-only heuristic only:
    candidate     = linked, merged, clean, and no merge in progress
    needs_review  = not merged, unlinked, or status uncertain
    do_not_remove = dirty or merge in progress (review manually first)
  Before cleanup, confirm the branch state with:
    git log --oneline HEAD..<branch>
    git diff --stat HEAD...<branch>
  Then review manually. This tool never deletes, prunes, or modifies worktrees.
""".strip()


def format_worktree_overview(
    overviews: list[WorktreeOverview],
    base_dir: Path,
    repo: Path | None = None,
    total_count: int | None = None,
) -> str:
    """Render *overviews* as a plain-text table for operator review.

    When *total_count* is provided, read-only summary lines are included before
    the table showing the total discovered count, the number shown after any
    filters, the dirty and unlinked counts, and cleanup candidate counts.
    """
    if not overviews:
        return f"No git worktrees found under {base_dir}"

    lines: list[str] = [
        f"Worktree overview for {base_dir}"
        + (f" (repo: {repo})" if repo else ""),
        "",
    ]
    if total_count is not None:
        lines.append(format_worktree_summary(overviews, total_count))
        lines.append(format_cleanup_summary(overviews))
        lines.append("")
    header = (
        f"{'path':<50} {'branch':<20} {'linked':<7} {'merged':<7} {'merge':<6} "
        f"{'dirty':<6} {'changes':<8} {'untracked':<10} {'cleanup':<14} {'last_modified'}"
    )
    lines.append(header)
    lines.append("-" * len(header))
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
        dirty_display = "yes" if overview.dirty else "no"
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
            f"{dirty_display:<6} {overview.dirty_count:<8} {overview.untracked_count:<10} "
            f"{overview.cleanup_status:<14} {last_modified}"
        )
    lines.append("")
    lines.append(_REVIEW_HINT)
    return "\n".join(lines)
