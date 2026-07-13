from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal


SandboxAction = Literal["allow", "deny"]

DEFAULT_FORBIDDEN_PATH_MARKERS: tuple[str, ...] = (
    ".env",
    ".ssh",
    ".codex/auth.json",
    "auth.json",
    "id_rsa",
    "id_ed25519",
)


@dataclass(frozen=True)
class SandboxDecision:
    action: SandboxAction
    reason: str
    path: Path

    def to_payload(self) -> dict[str, object]:
        return {
            "action": self.action,
            "reason": self.reason,
            "path": str(self.path),
        }


@dataclass(frozen=True)
class WorktreeExecutionProfile:
    task_id: str
    worktree_path: Path
    branch: str | None = None
    base_ref: str | None = None
    dirty: bool | None = None
    cleanup_eligible: bool = False

    def __post_init__(self) -> None:
        if not self.task_id.strip():
            raise ValueError("Worktree task id cannot be empty")
        object.__setattr__(self, "worktree_path", self.worktree_path.resolve(strict=False))

    def to_payload(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "worktree_path": str(self.worktree_path),
            "branch": self.branch,
            "base_ref": self.base_ref,
            "dirty": self.dirty,
            "cleanup_eligible": self.cleanup_eligible,
        }


@dataclass(frozen=True)
class SandboxProfile:
    root: Path
    writable_paths: tuple[Path, ...] = ()
    forbidden_path_markers: tuple[str, ...] = DEFAULT_FORBIDDEN_PATH_MARKERS
    worktree: WorktreeExecutionProfile | None = None

    def __post_init__(self) -> None:
        root = self.root.resolve(strict=False)
        writable_paths = self.writable_paths or (root,)
        object.__setattr__(self, "root", root)
        object.__setattr__(
            self,
            "writable_paths",
            tuple(_resolve_against_root(root, path) for path in writable_paths),
        )

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "root": str(self.root),
            "writable_paths": [str(path) for path in self.writable_paths],
            "forbidden_path_markers": list(self.forbidden_path_markers),
        }
        if self.worktree is not None:
            payload["worktree"] = self.worktree.to_payload()
        return payload


class PathScopePolicy:
    """Policy-level local sandbox for file read/write path decisions."""

    def __init__(self, profile: SandboxProfile) -> None:
        self.profile = profile

    def evaluate_read(self, path: Path) -> SandboxDecision:
        resolved = self.resolve(path)
        root_decision = self._root_decision(resolved)
        if root_decision is not None:
            return root_decision
        forbidden = self._forbidden_decision(resolved)
        if forbidden is not None:
            return forbidden
        return SandboxDecision("allow", "Path is inside sandbox read scope", resolved)

    def evaluate_write(self, path: Path) -> SandboxDecision:
        resolved = self.resolve(path)
        root_decision = self._root_decision(resolved)
        if root_decision is not None:
            return root_decision
        forbidden = self._forbidden_decision(resolved)
        if forbidden is not None:
            return forbidden
        if not any(_is_relative_to(resolved, writable) for writable in self.profile.writable_paths):
            scopes = ", ".join(str(path) for path in self.profile.writable_paths)
            return SandboxDecision(
                "deny",
                f"Path is outside writable sandbox scope: {scopes}",
                resolved,
            )
        return SandboxDecision("allow", "Path is inside sandbox write scope", resolved)

    def resolve(self, path: Path) -> Path:
        return _resolve_against_root(self.profile.root, path)

    def _root_decision(self, path: Path) -> SandboxDecision | None:
        if _is_relative_to(path, self.profile.root):
            return None
        return SandboxDecision("deny", "Path is outside sandbox root", path)

    def _forbidden_decision(self, path: Path) -> SandboxDecision | None:
        normalized = path.as_posix().lower()
        for marker in self.profile.forbidden_path_markers:
            clean_marker = marker.strip().replace("\\", "/").lower()
            if clean_marker and clean_marker in normalized:
                return SandboxDecision(
                    "deny",
                    f"Path matches forbidden sandbox marker: {marker}",
                    path,
                )
        return None


def _resolve_against_root(root: Path, path: Path) -> Path:
    candidate = path if path.is_absolute() else root / path
    return candidate.resolve(strict=False)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True
