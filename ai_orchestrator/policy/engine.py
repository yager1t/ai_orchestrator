from __future__ import annotations

import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class PolicyDecision:
    action: str  # allow | ask | deny
    reason: str


class PolicyEngine:
    DEFAULT_DENY_PATTERNS = ["rm -rf /", "~/.ssh", "~/.codex/auth.json"]
    DEFAULT_ASK_PATTERNS = ["git push", "rm -rf", "pip install", "npm install"]

    def __init__(
        self,
        deny_patterns: list[str] | None = None,
        ask_patterns: list[str] | None = None,
    ) -> None:
        self.deny_patterns = self._merge_patterns(self.DEFAULT_DENY_PATTERNS, deny_patterns)
        self.ask_patterns = self._merge_patterns(self.DEFAULT_ASK_PATTERNS, ask_patterns)

    def evaluate_command(self, command: str) -> PolicyDecision:
        normalized = command.strip()
        for pattern in self.deny_patterns:
            if pattern in normalized:
                return PolicyDecision("deny", f"Denied by pattern: {pattern}")

        for pattern in self.ask_patterns:
            if pattern in normalized:
                return PolicyDecision("ask", f"Requires approval: {pattern}")

        return PolicyDecision("allow", "No blocking policy matched")

    def evaluate_argv(self, argv: list[str]) -> PolicyDecision:
        return self.evaluate_command(subprocess.list2cmdline(argv))

    def _merge_patterns(
        self,
        defaults: list[str],
        configured: list[str] | None,
    ) -> list[str]:
        merged: list[str] = []
        for pattern in [*defaults, *(configured or [])]:
            if pattern not in merged:
                merged.append(pattern)
        return merged
