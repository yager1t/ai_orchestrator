import pytest
from pathlib import Path

from ai_orchestrator.agents.base import TaskContext
from ai_orchestrator.agents.factory import build_agent, build_agent_candidates
from ai_orchestrator.agents.claude import ClaudeHeadlessAdapter
from ai_orchestrator.agents.codex import CodexExecAdapter
from ai_orchestrator.agents.gemini import GeminiCLIAdapter
from ai_orchestrator.agents.generic import GenericCLIAdapter
from ai_orchestrator.agents.kimi import KimiCLIAdapter
from ai_orchestrator.agents.mock import MockAgentAdapter
from ai_orchestrator.config.loader import AgentConfig, ProjectConfig
from ai_orchestrator.policy.engine import PolicyEngine


def test_build_agent_creates_mock_adapter() -> None:
    config = ProjectConfig(
        default_agent="mock",
        agents={"mock": AgentConfig(name="mock", type="mock", enabled=True)},
    )

    assert isinstance(build_agent(config), MockAgentAdapter)


def test_build_agent_creates_generic_adapter() -> None:
    config = ProjectConfig(
        default_agent="generic",
        agents={
            "generic": AgentConfig(
                name="generic",
                type="generic_cli",
                enabled=True,
                command="python",
                args=["-c", "print('ok')"],
                timeout_sec=12,
            )
        },
    )

    agent = build_agent(config)

    assert isinstance(agent, GenericCLIAdapter)
    assert agent.command == "python"
    assert agent.timeout_sec == 12


def test_build_agent_creates_codex_exec_adapter() -> None:
    config = ProjectConfig(
        default_agent="codex",
        agents={
            "codex": AgentConfig(
                name="codex",
                type="codex_exec",
                enabled=True,
                command="codex",
                args=["exec", "--json", "{prompt}"],
                timeout_sec=99,
            )
        },
    )

    agent = build_agent(config)

    assert isinstance(agent, CodexExecAdapter)
    assert agent.command == "codex"
    assert agent.args == ["exec", "--json", "{prompt}"]
    assert agent.timeout_sec == 99


def test_build_agent_creates_claude_headless_adapter() -> None:
    config = ProjectConfig(
        default_agent="claude",
        agents={
            "claude": AgentConfig(
                name="claude",
                type="claude_headless",
                enabled=True,
                command="claude",
                args=["-p", "{prompt}"],
                timeout_sec=77,
            )
        },
    )

    agent = build_agent(config)

    assert isinstance(agent, ClaudeHeadlessAdapter)
    assert agent.command == "claude"
    assert agent.args == ["-p", "{prompt}"]
    assert agent.timeout_sec == 77


def test_build_agent_creates_kimi_cli_alias() -> None:
    config = ProjectConfig(
        default_agent="kimi",
        agents={
            "kimi": AgentConfig(
                name="kimi",
                type="kimi_cli",
                enabled=True,
                command="kimi",
                args=["--prompt", "{prompt}"],
                timeout_sec=55,
            )
        },
    )

    agent = build_agent(config)

    assert isinstance(agent, KimiCLIAdapter)
    assert agent.name == "kimi"
    assert agent.command == "kimi"
    assert agent.args == ["--prompt", "{prompt}"]
    assert agent.timeout_sec == 55


def test_build_agent_creates_gemini_cli_alias_with_defaults() -> None:
    config = ProjectConfig(
        default_agent="gemini",
        agents={
            "gemini": AgentConfig(
                name="gemini",
                type="gemini_cli",
                enabled=True,
            )
        },
    )

    agent = build_agent(config)

    assert isinstance(agent, GeminiCLIAdapter)
    assert agent.name == "gemini"
    assert agent.command == "gemini"
    assert agent.args == ["-p", "{prompt}"]


def test_build_agent_preserves_empty_cli_alias_args() -> None:
    config = ProjectConfig(
        default_agent="kimi",
        agents={
            "kimi": AgentConfig(
                name="kimi",
                type="kimi_cli",
                enabled=True,
                args=[],
            )
        },
    )

    agent = build_agent(config)

    assert isinstance(agent, GenericCLIAdapter)
    assert agent.args == []


@pytest.mark.parametrize(
    ("agent_name", "agent_type", "adapter_type"),
    [
        ("codex", "codex_exec", CodexExecAdapter),
        ("claude", "claude_headless", ClaudeHeadlessAdapter),
    ],
)
def test_build_agent_preserves_empty_headless_args(
    agent_name: str,
    agent_type: str,
    adapter_type,
) -> None:
    config = ProjectConfig(
        default_agent=agent_name,
        agents={
            agent_name: AgentConfig(
                name=agent_name,
                type=agent_type,
                enabled=True,
                args=[],
            )
        },
    )

    agent = build_agent(config)

    assert isinstance(agent, adapter_type)
    assert agent.args == []


@pytest.mark.parametrize(
    ("agent_name", "agent_type"),
    [
        ("kimi", "kimi_cli"),
        ("gemini", "gemini_cli"),
    ],
)
def test_cli_alias_agents_use_policy_engine(
    tmp_path: Path,
    agent_name: str,
    agent_type: str,
) -> None:
    config = ProjectConfig(
        default_agent=agent_name,
        agents={
            agent_name: AgentConfig(
                name=agent_name,
                type=agent_type,
                enabled=True,
                command="dangerous",
                args=["{prompt}"],
            )
        },
    )
    agent = build_agent(config, policy_engine=PolicyEngine(deny_patterns=["blocked-token"]))
    session = agent.start_session(TaskContext(task="demo", repo_path=tmp_path))

    result = agent.run_step(session, "blocked-token")

    assert result.status == "blocked"
    assert result.error == "Denied by pattern: blocked-token"


@pytest.mark.parametrize(
    ("agent_name", "agent_type"),
    [
        ("kimi", "kimi_cli"),
        ("gemini", "gemini_cli"),
    ],
)
def test_cli_alias_agents_require_approval_from_policy_engine(
    tmp_path: Path,
    agent_name: str,
    agent_type: str,
) -> None:
    config = ProjectConfig(
        default_agent=agent_name,
        agents={
            agent_name: AgentConfig(
                name=agent_name,
                type=agent_type,
                enabled=True,
                command="approval",
                args=["{prompt}"],
            )
        },
    )
    agent = build_agent(config, policy_engine=PolicyEngine(ask_patterns=["approval-token"]))
    session = agent.start_session(TaskContext(task="demo", repo_path=tmp_path))

    result = agent.run_step(session, "approval-token")

    assert result.status == "needs_approval"
    assert result.error == "Requires approval: approval-token"


def test_build_agent_rejects_disabled_default_agent() -> None:
    config = ProjectConfig(
        default_agent="generic",
        agents={"generic": AgentConfig(name="generic", type="generic_cli", enabled=False)},
    )

    with pytest.raises(ValueError, match="Default agent is disabled"):
        build_agent(config)


def test_build_agent_candidates_uses_default_then_fallbacks() -> None:
    config = ProjectConfig(
        default_agent="generic",
        fallback_agents=["mock", "generic"],
        agents={
            "generic": AgentConfig(
                name="generic",
                type="generic_cli",
                enabled=True,
                command="python",
            ),
            "mock": AgentConfig(name="mock", type="mock", enabled=True),
        },
    )

    candidates = build_agent_candidates(config)

    assert [candidate.name for candidate in candidates] == ["generic", "mock"]


def test_build_agent_candidates_skips_disabled_agents() -> None:
    config = ProjectConfig(
        default_agent="generic",
        fallback_agents=["mock"],
        agents={
            "generic": AgentConfig(
                name="generic",
                type="generic_cli",
                enabled=False,
                command="python",
            ),
            "mock": AgentConfig(name="mock", type="mock", enabled=True),
        },
    )

    candidates = build_agent_candidates(config)

    assert [candidate.name for candidate in candidates] == ["mock"]
