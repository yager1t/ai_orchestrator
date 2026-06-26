from __future__ import annotations

from dataclasses import dataclass, field

from ai_orchestrator.agents.generic import GenericCLIAdapter
from ai_orchestrator.policy.engine import PolicyEngine
from ai_orchestrator.process.runner import ProcessRunner


@dataclass
class GeminiCLIAdapter(GenericCLIAdapter):
    command: str = "gemini"
    args: list[str] = field(default_factory=lambda: ["-p", "{prompt}"])
    timeout_sec: int = 300
    name: str = "gemini"
    runner: ProcessRunner = field(default_factory=ProcessRunner)
    policy_engine: PolicyEngine = field(default_factory=PolicyEngine)
