from __future__ import annotations

from ai_orchestrator.agents.base import AgentAdapter
from ai_orchestrator.agents.claude import ClaudeHeadlessAdapter
from ai_orchestrator.agents.codex import CodexExecAdapter
from ai_orchestrator.agents.generic import GenericCLIAdapter
from ai_orchestrator.agents.mock import MockAgentAdapter
from ai_orchestrator.config.loader import AgentConfig, ProjectConfig
from ai_orchestrator.policy.engine import PolicyEngine


def build_agent(config: ProjectConfig, policy_engine: PolicyEngine | None = None) -> AgentAdapter:
    agent_config = config.agents.get(config.default_agent)
    if agent_config is None:
        raise ValueError(f"Default agent is not configured: {config.default_agent}")
    if not agent_config.enabled:
        raise ValueError(f"Default agent is disabled: {config.default_agent}")
    return _build_agent_from_config(agent_config, policy_engine)


def build_agent_candidates(
    config: ProjectConfig,
    policy_engine: PolicyEngine | None = None,
) -> list[AgentAdapter]:
    candidates: list[AgentAdapter] = []
    for name in _ordered_agent_names(config):
        agent_config = config.agents.get(name)
        if agent_config is None or not agent_config.enabled:
            continue
        candidates.append(_build_agent_from_config(agent_config, policy_engine))

    if not candidates:
        raise ValueError("No enabled agents are configured")
    return candidates


def _ordered_agent_names(config: ProjectConfig) -> list[str]:
    names = [config.default_agent, *config.fallback_agents]
    ordered: list[str] = []
    for name in names:
        if name and name not in ordered:
            ordered.append(name)
    return ordered


def _build_agent_from_config(
    agent_config: AgentConfig,
    policy_engine: PolicyEngine | None,
) -> AgentAdapter:
    if agent_config.type == "mock":
        return MockAgentAdapter()
    if agent_config.type == "generic_cli":
        return _build_generic(agent_config, policy_engine)
    if agent_config.type in {"kimi", "kimi_cli"}:
        return _build_cli_alias(
            agent_config,
            policy_engine,
            default_command="kimi",
            default_args=["{prompt}"],
        )
    if agent_config.type in {"gemini", "gemini_cli"}:
        return _build_cli_alias(
            agent_config,
            policy_engine,
            default_command="gemini",
            default_args=["-p", "{prompt}"],
        )
    if agent_config.type == "codex_exec":
        return _build_codex(agent_config, policy_engine)
    if agent_config.type in {"claude", "claude_headless"}:
        return _build_claude(agent_config, policy_engine)

    raise ValueError(f"Unsupported agent type: {agent_config.type}")


def _build_generic(
    config: AgentConfig,
    policy_engine: PolicyEngine | None = None,
) -> GenericCLIAdapter:
    if not config.command:
        raise ValueError(f"Generic agent has no command: {config.name}")
    return GenericCLIAdapter(
        name=config.name,
        command=config.command,
        args=config.args or [],
        timeout_sec=config.timeout_sec,
        policy_engine=policy_engine or PolicyEngine(),
    )


def _build_cli_alias(
    config: AgentConfig,
    policy_engine: PolicyEngine | None,
    default_command: str,
    default_args: list[str],
) -> GenericCLIAdapter:
    return GenericCLIAdapter(
        name=config.name,
        command=config.command or default_command,
        args=config.args if config.args is not None else default_args,
        timeout_sec=config.timeout_sec,
        policy_engine=policy_engine or PolicyEngine(),
    )


def _build_codex(
    config: AgentConfig,
    policy_engine: PolicyEngine | None = None,
) -> CodexExecAdapter:
    return CodexExecAdapter(
        name=config.name,
        command=config.command or "codex",
        args=config.args if config.args is not None else [
            "exec",
            "--json",
            "--sandbox",
            "workspace-write",
            "{prompt}",
        ],
        timeout_sec=config.timeout_sec,
        policy_engine=policy_engine or PolicyEngine(),
    )


def _build_claude(
    config: AgentConfig,
    policy_engine: PolicyEngine | None = None,
) -> ClaudeHeadlessAdapter:
    return ClaudeHeadlessAdapter(
        name=config.name,
        command=config.command or "claude",
        args=config.args if config.args is not None else [
            "-p",
            "{prompt}",
            "--output-format",
            "json",
        ],
        timeout_sec=config.timeout_sec,
        policy_engine=policy_engine or PolicyEngine(),
    )
