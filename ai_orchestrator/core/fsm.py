from __future__ import annotations

from enum import StrEnum


class TaskState(StrEnum):
    CREATED = "created"
    PLANNING = "planning"
    DISPATCHING = "dispatching"
    RUNNING_AGENT = "running_agent"
    COLLECTING_RESULT = "collecting_result"
    VERIFYING = "verifying"
    DECIDING = "deciding"
    WAITING_APPROVAL = "waiting_approval"
    DONE = "done"
    BLOCKED = "blocked"
    FAILED = "failed"
