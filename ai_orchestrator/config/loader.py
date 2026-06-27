from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ai_orchestrator.verification.runner import VerificationCommand


@dataclass(frozen=True)
class AgentConfig:
    name: str
    type: str
    enabled: bool = False
    command: str = ""
    args: list[str] | None = None
    timeout_sec: int = 300


@dataclass(frozen=True)
class ProjectConfig:
    verification_commands: list[VerificationCommand] = field(default_factory=list)
    max_iterations: int = 2
    max_no_change_iterations: int = 2
    default_agent: str = "mock"
    fallback_agents: list[str] = field(default_factory=list)
    agents: dict[str, AgentConfig] = field(default_factory=dict)
    policy_deny_patterns: list[str] = field(default_factory=list)
    policy_ask_patterns: list[str] = field(default_factory=list)


def find_project_config(start: Path | None = None) -> Path | None:
    current = (start or Path.cwd()).resolve()
    for path in [current, *current.parents]:
        candidate = path / ".ai-orch" / "config.yaml"
        if candidate.exists():
            return candidate
    return None


def load_project_config(start: Path | None = None) -> ProjectConfig:
    config_path = find_project_config(start)
    if config_path is None:
        return ProjectConfig(
            verification_commands=default_verification_commands(),
            agents=default_agent_configs(),
        )

    parsed = _parse_minimal_config(config_path.read_text(encoding="utf-8"))
    commands = parsed.verification_commands or default_verification_commands()
    return ProjectConfig(
        verification_commands=commands,
        max_iterations=parsed.max_iterations,
        max_no_change_iterations=parsed.max_no_change_iterations,
        default_agent=parsed.default_agent,
        fallback_agents=parsed.fallback_agents,
        agents=parsed.agents or default_agent_configs(),
        policy_deny_patterns=parsed.policy_deny_patterns,
        policy_ask_patterns=parsed.policy_ask_patterns,
    )


def default_verification_commands() -> list[VerificationCommand]:
    return [
        VerificationCommand(
            "compile",
            "python -m compileall .",
            timeout_sec=120,
        )
    ]


def default_agent_configs() -> dict[str, AgentConfig]:
    return {
        "mock": AgentConfig(name="mock", type="mock", enabled=True),
    }


def _parse_minimal_config(content: str) -> ProjectConfig:
    max_iterations = 2
    max_no_change_iterations = 2
    default_agent = "mock"
    fallback_agents: list[str] = []
    agents: dict[str, AgentConfig] = {}
    current_agent_name: str | None = None
    current_agent: dict[str, object] | None = None
    in_agent_args = False
    verification_commands: list[VerificationCommand] = []
    policy_deny_patterns: list[str] = []
    policy_ask_patterns: list[str] = []
    current_command: dict[str, str] | None = None
    in_verification_argv = False
    section: str | None = None
    in_verification_commands = False
    in_fallback_agents = False
    policy_list: str | None = None

    for raw_line in content.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue

        indent = len(raw_line) - len(raw_line.lstrip(" "))
        stripped = raw_line.strip()

        if indent == 0 and stripped.endswith(":"):
            if section == "agents":
                current_agent_name, current_agent = _finish_agent(
                    current_agent_name,
                    current_agent,
                    agents,
                )
            section = stripped[:-1]
            in_verification_commands = False
            in_verification_argv = False
            in_fallback_agents = False
            policy_list = None
            in_agent_args = False
            current_command = _finish_command(current_command, verification_commands)
            continue

        if section == "agents":
            if indent == 2 and stripped.endswith(":"):
                current_agent_name, current_agent = _finish_agent(
                    current_agent_name,
                    current_agent,
                    agents,
                )
                current_agent_name = stripped[:-1]
                current_agent = {}
                in_agent_args = False
                continue

            if current_agent is not None and stripped == "args:":
                in_agent_args = True
                continue

            if current_agent is not None and in_agent_args and stripped.startswith("- "):
                args = current_agent.setdefault("args", [])
                if isinstance(args, list):
                    args.append(_strip_quotes(stripped[2:].strip()))
                continue

            if current_agent is not None and ":" in stripped:
                in_agent_args = False
                key, value = _split_key_value(stripped)
                if key:
                    current_agent[key] = value
                continue

        if section == "orchestrator" and stripped.startswith("max_iterations:"):
            in_fallback_agents = False
            value = _value_after_colon(stripped)
            try:
                max_iterations = int(value)
            except ValueError:
                max_iterations = 2
            continue

        if section == "orchestrator" and stripped.startswith("max_no_change_iterations:"):
            in_fallback_agents = False
            value = _value_after_colon(stripped)
            try:
                max_no_change_iterations = int(value)
            except ValueError:
                max_no_change_iterations = 2
            continue

        if section == "orchestrator" and stripped.startswith("default_agent:"):
            in_fallback_agents = False
            default_agent = _value_after_colon(stripped)
            continue

        if section == "orchestrator" and stripped == "fallback_agents:":
            in_fallback_agents = True
            continue

        if section == "orchestrator" and in_fallback_agents and stripped.startswith("- "):
            fallback_agents.append(_strip_quotes(stripped[2:].strip()))
            continue

        if section == "verification" and stripped == "commands:":
            in_verification_commands = True
            continue

        if section == "policy" and stripped in {"deny:", "require_approval:"}:
            policy_list = stripped[:-1]
            continue

        if section == "policy" and policy_list is not None and stripped.startswith("- "):
            value = _strip_quotes(stripped[2:].strip())
            if policy_list == "deny":
                policy_deny_patterns.append(value)
            if policy_list == "require_approval":
                policy_ask_patterns.append(value)
            continue

        if not in_verification_commands:
            continue

        if stripped.startswith("- "):
            if in_verification_argv and current_command is not None:
                argv = current_command.setdefault("argv", [])
                if isinstance(argv, list):
                    argv.append(_strip_quotes(stripped[2:].strip()))
                continue

            current_command = _finish_command(current_command, verification_commands)
            current_command = {}
            in_verification_argv = False
            remainder = stripped[2:].strip()
            if remainder:
                key, value = _split_key_value(remainder)
                if key:
                    current_command[key] = value
            continue

        if current_command is not None and stripped == "argv:":
            current_command["argv"] = []
            in_verification_argv = True
            continue

        if current_command is not None and ":" in stripped:
            in_verification_argv = False
            key, value = _split_key_value(stripped)
            if key:
                current_command[key] = value

    _finish_command(current_command, verification_commands)
    _finish_agent(current_agent_name, current_agent, agents)
    return ProjectConfig(
        verification_commands=verification_commands,
        max_iterations=max_iterations,
        max_no_change_iterations=max_no_change_iterations,
        default_agent=default_agent,
        fallback_agents=fallback_agents,
        agents=agents,
        policy_deny_patterns=policy_deny_patterns,
        policy_ask_patterns=policy_ask_patterns,
    )


def _finish_command(
    current_command: dict[str, object] | None,
    commands: list[VerificationCommand],
) -> None:
    if current_command is None:
        return None

    name = current_command.get("name")
    run = current_command.get("run", "")
    raw_argv = current_command.get("argv")
    argv = [str(item) for item in raw_argv] if isinstance(raw_argv, list) else None
    if not isinstance(name, str) or (not run and not argv):
        return None

    timeout_value = current_command.get("timeout_sec", "300")
    try:
        timeout_sec = int(timeout_value)
    except ValueError:
        timeout_sec = 300

    commands.append(
        VerificationCommand(
            name=name,
            run=str(run),
            timeout_sec=timeout_sec,
            argv=argv,
        )
    )
    return None


def _finish_agent(
    name: str | None,
    current_agent: dict[str, object] | None,
    agents: dict[str, AgentConfig],
) -> tuple[None, None]:
    if name is None or current_agent is None:
        return None, None

    agent_type = _as_str(current_agent.get("type"), default=name)
    enabled = _as_bool(current_agent.get("enabled"), default=False)
    command = _as_str(current_agent.get("command"), default="")
    timeout_sec = _as_int(current_agent.get("timeout_sec"), default=300)
    if "args" in current_agent:
        raw_args = current_agent.get("args", [])
        args = [str(item) for item in raw_args] if isinstance(raw_args, list) else []
    else:
        args = None
    agents[name] = AgentConfig(
        name=name,
        type=agent_type,
        enabled=enabled,
        command=command,
        args=args,
        timeout_sec=timeout_sec,
    )
    return None, None


def _split_key_value(line: str) -> tuple[str, str]:
    if ":" not in line:
        return "", ""
    key, value = line.split(":", 1)
    return key.strip(), _strip_quotes(value.strip())


def _value_after_colon(line: str) -> str:
    return _strip_quotes(line.split(":", 1)[1].strip())


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _as_str(value: object, default: str) -> str:
    if isinstance(value, str):
        return value
    return default


def _as_bool(value: object, default: bool) -> bool:
    if not isinstance(value, str):
        return default
    return value.lower() == "true"


def _as_int(value: object, default: int) -> int:
    if not isinstance(value, str):
        return default
    try:
        return int(value)
    except ValueError:
        return default
