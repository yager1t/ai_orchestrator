from pathlib import Path

from ai_orchestrator.config.loader import load_project_config


def test_load_project_config_reads_verification_commands(tmp_path: Path) -> None:
    config_dir = tmp_path / ".ai-orch"
    config_dir.mkdir()
    (config_dir / "config.yaml").write_text(
        """
orchestrator:
  default_agent: "generic"
  fallback_agents:
    - "mock"
  max_iterations: 4
  max_no_change_iterations: 3
  max_runtime_sec: 600

agents:
  mock:
    enabled: true
    type: "mock"
  generic:
    enabled: true
    type: "generic_cli"
    command: "python"
    args:
      - "-c"
      - "print('generic')"
    timeout_sec: 12

verification:
  strict: true
  commands:
    - name: "unit"
      run: "python -m pytest"
      timeout_sec: 30
    - name: "compile"
      run: "python -m compileall ai_orchestrator"
      timeout_sec: 20

policy:
  deny:
    - "secret-tool"
  require_approval:
    - "deploy"
""".lstrip(),
        encoding="utf-8",
    )

    config = load_project_config(tmp_path)

    assert config.max_iterations == 4
    assert config.max_no_change_iterations == 3
    assert config.max_runtime_sec == 600
    assert config.default_agent == "generic"
    assert config.fallback_agents == ["mock"]
    assert config.agents["generic"].enabled is True
    assert config.agents["generic"].type == "generic_cli"
    assert config.agents["generic"].command == "python"
    assert config.agents["generic"].args == ["-c", "print('generic')"]
    assert config.agents["generic"].timeout_sec == 12
    assert config.verification_strict is True
    assert [item.name for item in config.verification_commands] == ["unit", "compile"]
    assert config.verification_commands[0].run == "python -m pytest"
    assert config.verification_commands[0].timeout_sec == 30
    assert config.policy_deny_patterns == ["secret-tool"]
    assert config.policy_ask_patterns == ["deploy"]


def test_load_project_config_uses_compile_fallback_without_config(tmp_path: Path) -> None:
    config = load_project_config(tmp_path)

    assert config.max_iterations == 2
    assert config.max_no_change_iterations == 2
    assert config.max_runtime_sec is None
    assert config.default_agent == "mock"
    assert config.agents["mock"].enabled is True
    assert len(config.verification_commands) == 1
    assert config.verification_commands[0].name == "compile"
    assert config.verification_commands[0].run == "python -m compileall ."


def test_load_project_config_strict_mode_disables_default_verification_fallback(
    tmp_path: Path,
) -> None:
    config_dir = tmp_path / ".ai-orch"
    config_dir.mkdir()
    (config_dir / "config.yaml").write_text(
        """
verification:
  strict: true
""".lstrip(),
        encoding="utf-8",
    )

    config = load_project_config(tmp_path)

    assert config.verification_strict is True
    assert config.verification_commands == []


def test_load_project_config_reads_structured_verification_argv(tmp_path: Path) -> None:
    config_dir = tmp_path / ".ai-orch"
    config_dir.mkdir()
    (config_dir / "config.yaml").write_text(
        """
verification:
  commands:
    - name: "unit"
      argv:
        - "python"
        - "-m"
        - "pytest"
      timeout_sec: 30
""".lstrip(),
        encoding="utf-8",
    )

    config = load_project_config(tmp_path)

    assert len(config.verification_commands) == 1
    assert config.verification_commands[0].name == "unit"
    assert config.verification_commands[0].run == ""
    assert config.verification_commands[0].argv == ["python", "-m", "pytest"]
    assert config.verification_commands[0].timeout_sec == 30


def test_load_project_config_reads_legacy_runtime_budget_minutes(tmp_path: Path) -> None:
    config_dir = tmp_path / ".ai-orch"
    config_dir.mkdir()
    (config_dir / "config.yaml").write_text(
        """
orchestrator:
  max_task_runtime_minutes: 2
""".lstrip(),
        encoding="utf-8",
    )

    config = load_project_config(tmp_path)

    assert config.max_runtime_sec == 120


def test_load_project_config_reads_memory_provider(tmp_path: Path) -> None:
    config_dir = tmp_path / ".ai-orch"
    config_dir.mkdir()
    (config_dir / "config.yaml").write_text(
        """
memory:
  provider: "codebase-memory-mcp"
  command:
    - "codebase-memory-mcp"
    - "cli"
  project: "demo"
  timeout_sec: 45
""".lstrip(),
        encoding="utf-8",
    )

    config = load_project_config(tmp_path)

    assert config.memory.provider == "codebase-memory-mcp"
    assert config.memory.command == ["codebase-memory-mcp", "cli"]
    assert config.memory.project == "demo"
    assert config.memory.timeout_sec == 45
