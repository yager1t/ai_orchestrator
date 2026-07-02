from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol


def _never_cancel() -> bool:
    return False


ProgressCallback = Callable[[str], None]


@dataclass(frozen=True)
class TaskContext:
    task: str
    repo_path: Path
    metadata: dict[str, str] = field(default_factory=dict)
    cancellation_requested: Callable[[], bool] = _never_cancel
    progress_callback: ProgressCallback | None = None


@dataclass(frozen=True)
class SessionRef:
    session_id: str
    agent_name: str


@dataclass(frozen=True)
class AgentResult:
    status: str
    raw_output: str
    session_id: str
    files_changed: list[str] = field(default_factory=list)
    tool_actions: list[str] = field(default_factory=list)
    summary: str | None = None
    exit_reason: str | None = None
    uncertainty: str | None = None
    error: str | None = None


def summarize_agent_output(raw_output: str, limit: int = 300) -> str:
    rendered = " ".join(raw_output.split())
    if len(rendered) <= limit:
        return rendered
    return f"{rendered[:limit]}..."


class AgentAdapter(Protocol):
    name: str

    def check_available(self) -> bool:
        ...

    def start_session(self, context: TaskContext) -> SessionRef:
        ...

    def run_step(self, session: SessionRef, prompt: str) -> AgentResult:
        ...

    def continue_session(self, session: SessionRef, prompt: str) -> AgentResult:
        ...

    def stop_session(self, session: SessionRef) -> None:
        ...
