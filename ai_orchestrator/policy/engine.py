from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class PolicyDecision:
    action: str  # allow | ask | deny
    reason: str


class PolicyEngine:
    DEFAULT_DENY_PATTERNS = ["rm -rf /", "~/.ssh", "~/.codex/auth.json"]
    DEFAULT_ASK_PATTERNS = ["git push", "rm -rf", "pip install", "npm install"]
    TRANSPARENT_WRAPPERS = {"command", "env", "nice", "nohup", "stdbuf", "sudo", "time", "xargs"}
    WRAPPER_OPTIONS_WITH_VALUES = {
        "env": {"-u", "--unset"},
        "nice": {"-n", "--adjustment"},
        "stdbuf": {"-i", "-o", "-e", "--input", "--output", "--error"},
        "sudo": {"-C", "-g", "-h", "-p", "-T", "-U", "-u"},
        "xargs": {"-E", "-I", "-L", "-P", "-n", "-s"},
    }

    def __init__(
        self,
        deny_patterns: list[str] | None = None,
        ask_patterns: list[str] | None = None,
    ) -> None:
        self.deny_patterns = self._merge_patterns(self.DEFAULT_DENY_PATTERNS, deny_patterns)
        self.ask_patterns = self._merge_patterns(self.DEFAULT_ASK_PATTERNS, ask_patterns)
        self._custom_deny_patterns = self._custom_patterns(
            self.DEFAULT_DENY_PATTERNS,
            deny_patterns,
        )
        self._custom_ask_patterns = self._custom_patterns(
            self.DEFAULT_ASK_PATTERNS,
            ask_patterns,
        )

    def evaluate_command(self, command: str) -> PolicyDecision:
        normalized = command.strip()
        tokens = self._split_command(normalized)
        return self._evaluate_tokens(tokens=tokens, normalized=normalized)

    def evaluate_argv(self, argv: list[str]) -> PolicyDecision:
        return self._evaluate_tokens(tokens=argv, normalized=subprocess.list2cmdline(argv))

    def _evaluate_tokens(self, tokens: list[str], normalized: str) -> PolicyDecision:
        segments = self._policy_segments(tokens)
        for segment in segments:
            deny_pattern = self._match_default_deny(segment)
            if deny_pattern is not None:
                return PolicyDecision("deny", f"Denied by pattern: {deny_pattern}")

        for pattern in self._custom_deny_patterns:
            if pattern in normalized:
                return PolicyDecision("deny", f"Denied by pattern: {pattern}")

        for segment in segments:
            ask_pattern = self._match_default_ask(segment)
            if ask_pattern is not None:
                return PolicyDecision("ask", f"Requires approval: {ask_pattern}")

        for pattern in self._custom_ask_patterns:
            if pattern in normalized:
                return PolicyDecision("ask", f"Requires approval: {pattern}")

        return PolicyDecision("allow", "No blocking policy matched")

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

    def _custom_patterns(
        self,
        defaults: list[str],
        configured: list[str] | None,
    ) -> list[str]:
        return [pattern for pattern in configured or [] if pattern not in defaults]

    def _split_command(self, command: str) -> list[str]:
        if not command:
            return []
        command = command.replace("\r\n", "\n").replace("\r", "\n").replace("\n", " ; ")
        try:
            return shlex.split(command)
        except ValueError:
            return command.replace("\n", " ; ").split()

    def _command_segments(self, tokens: list[str]) -> list[list[str]]:
        segments: list[list[str]] = []
        current: list[str] = []
        separators = {"&&", "||", ";", "|"}
        for token in tokens:
            if token in separators:
                if current:
                    segments.append(current)
                    current = []
                continue
            current.append(token)
        if current:
            segments.append(current)
        return segments

    def _policy_segments(self, tokens: list[str]) -> list[list[str]]:
        segments = self._command_segments(tokens)
        for token in tokens:
            if not any(char.isspace() for char in token):
                continue
            nested_tokens = self._split_command(token)
            if nested_tokens != [token]:
                segments.extend(self._command_segments(nested_tokens))
        return [self._peel_wrappers(segment) for segment in segments if segment]

    def _peel_wrappers(self, tokens: list[str]) -> list[str]:
        index = 0
        while index < len(tokens):
            token = tokens[index]
            command_name = self._command_name(token)
            if self._is_env_assignment(token):
                index += 1
                continue
            if command_name not in self.TRANSPARENT_WRAPPERS:
                break
            index += 1
            index = self._skip_wrapper_options(tokens, index, command_name)
        return tokens[index:]

    def _skip_wrapper_options(self, tokens: list[str], index: int, wrapper: str) -> int:
        options_with_values = self.WRAPPER_OPTIONS_WITH_VALUES.get(wrapper, set())
        while index < len(tokens):
            token = tokens[index]
            if self._is_env_assignment(token):
                index += 1
                continue
            if token == "--":
                return index + 1
            if not token.startswith("-") or token == "-":
                return index
            index += 1
            option_name = token.split("=", 1)[0]
            if "=" not in token and option_name in options_with_values and index < len(tokens):
                index += 1
        return index

    def _is_env_assignment(self, token: str) -> bool:
        if "=" not in token or token.startswith("-"):
            return False
        name, _value = token.split("=", 1)
        return bool(name) and all(char == "_" or char.isalnum() for char in name)

    def _match_default_deny(self, tokens: list[str]) -> str | None:
        if self._has_secret_path(tokens, "~/.codex/auth.json"):
            return "~/.codex/auth.json"
        if self._has_secret_path(tokens, "~/.ssh"):
            return "~/.ssh"
        if self._is_rm_recursive_force(tokens) and any(
            self._is_root_target(token) for token in tokens
        ):
            return "rm -rf /"
        return None

    def _match_default_ask(self, tokens: list[str]) -> str | None:
        if self._is_git_push(tokens):
            return "git push"
        if self._is_rm_recursive_force(tokens):
            return "rm -rf"
        if self._is_pip_install(tokens):
            return "pip install"
        if self._is_npm_install(tokens):
            return "npm install"
        return None

    def _has_secret_path(self, tokens: list[str], pattern: str) -> bool:
        return any(pattern in token for token in tokens)

    def _is_git_push(self, tokens: list[str]) -> bool:
        return (
            len(tokens) >= 2
            and self._command_name(tokens[0]) == "git"
            and tokens[1] == "push"
        )

    def _is_rm_recursive_force(self, tokens: list[str]) -> bool:
        if len(tokens) < 2 or self._command_name(tokens[0]) != "rm":
            return False
        return any(
            token.startswith("-") and "r" in token and "f" in token
            for token in tokens[1:]
        )

    def _is_pip_install(self, tokens: list[str]) -> bool:
        if len(tokens) >= 2 and self._command_name(tokens[0]) in {"pip", "pip3"}:
            return tokens[1] == "install"
        return (
            len(tokens) >= 4
            and self._command_name(tokens[0]) in {"python", "python3", "py"}
            and tokens[1:4] == ["-m", "pip", "install"]
        )

    def _is_npm_install(self, tokens: list[str]) -> bool:
        return (
            len(tokens) >= 2
            and self._command_name(tokens[0]) == "npm"
            and tokens[1] == "install"
        )

    def _is_root_target(self, token: str) -> bool:
        return token in {"/", "/*"}

    def _command_name(self, token: str) -> str:
        command = token.strip("\"'").replace("\\", "/").rsplit("/", maxsplit=1)[-1].lower()
        if command.endswith(".exe"):
            return command[:-4]
        return command
