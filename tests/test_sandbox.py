from pathlib import Path

import pytest

from ai_orchestrator.policy import (
    PathScopePolicy,
    SandboxProfile,
    WorktreeExecutionProfile,
)


def test_sandbox_allows_write_inside_default_root(tmp_path: Path) -> None:
    policy = PathScopePolicy(SandboxProfile(root=tmp_path))

    decision = policy.evaluate_write(Path("src/example.py"))

    assert decision.action == "allow"
    assert decision.path == tmp_path / "src" / "example.py"
    assert decision.to_payload() == {
        "action": "allow",
        "reason": "Path is inside sandbox write scope",
        "path": str(tmp_path / "src" / "example.py"),
    }


def test_sandbox_denies_write_outside_configured_writable_scope(tmp_path: Path) -> None:
    policy = PathScopePolicy(
        SandboxProfile(root=tmp_path, writable_paths=(Path("docs"),))
    )

    decision = policy.evaluate_write(Path("src/example.py"))

    assert decision.action == "deny"
    assert "outside writable sandbox scope" in decision.reason


def test_sandbox_denies_secret_like_reads(tmp_path: Path) -> None:
    policy = PathScopePolicy(SandboxProfile(root=tmp_path))

    decision = policy.evaluate_read(Path(".env"))

    assert decision.action == "deny"
    assert "forbidden sandbox marker" in decision.reason


def test_sandbox_denies_paths_outside_root(tmp_path: Path) -> None:
    policy = PathScopePolicy(SandboxProfile(root=tmp_path))

    decision = policy.evaluate_read(tmp_path.parent / "outside.txt")

    assert decision.action == "deny"
    assert decision.reason == "Path is outside sandbox root"


def test_sandbox_denies_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    outside_file = outside / "secret.txt"
    outside_file.write_text("secret", encoding="utf-8")
    link = tmp_path / "linked-secret.txt"
    try:
        link.symlink_to(outside_file)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")
    policy = PathScopePolicy(SandboxProfile(root=tmp_path))

    decision = policy.evaluate_read(Path("linked-secret.txt"))

    assert decision.action == "deny"
    assert decision.reason == "Path is outside sandbox root"
    assert decision.path == outside_file.resolve(strict=False)


def test_worktree_execution_profile_payload_normalizes_path(tmp_path: Path) -> None:
    profile = WorktreeExecutionProfile(
        task_id="task-1",
        worktree_path=tmp_path / "wt",
        branch="codex/example",
        base_ref="main",
        dirty=False,
        cleanup_eligible=True,
    )

    assert profile.to_payload() == {
        "task_id": "task-1",
        "worktree_path": str((tmp_path / "wt").resolve(strict=False)),
        "branch": "codex/example",
        "base_ref": "main",
        "dirty": False,
        "cleanup_eligible": True,
    }


def test_worktree_execution_profile_rejects_empty_task_id(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Worktree task id cannot be empty"):
        WorktreeExecutionProfile(task_id=" ", worktree_path=tmp_path)
