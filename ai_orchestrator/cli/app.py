from __future__ import annotations

import argparse
import logging
from pathlib import Path

from ai_orchestrator import __version__
from ai_orchestrator.agents.base import AgentAdapter
from ai_orchestrator.agents.factory import build_agent, build_agent_candidates
from ai_orchestrator.config.loader import ProjectConfig, load_project_config
from ai_orchestrator.core.supervisor import Supervisor
from ai_orchestrator.memory import CodebaseMemoryClient, CodebaseMemoryResult
from ai_orchestrator.policy.engine import PolicyEngine
from ai_orchestrator.reporting.markdown import render_task_report
from ai_orchestrator.storage.db import StateStore
from ai_orchestrator.tui.app import (
    render_approvals_view,
    render_current_view,
    render_logs_view,
    render_status_view,
    render_tasks_view,
)
from ai_orchestrator.verification.runner import VerificationRunner


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ai-orch", description="Local supervisor for CLI AI agents")
    parser.add_argument("--version", action="version", version=f"ai-orch {__version__}")
    parser.add_argument(
        "--log-level",
        choices=["debug", "info", "warning", "error"],
        help="Enable stderr logging at the selected level",
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("init", help="Create local .ai-orch directories")

    start = sub.add_parser("start", help="Start a task with the mock agent")
    start.add_argument("--task", required=True)
    start.add_argument("--repo", default=".")
    start.add_argument(
        "--use-memory",
        action="store_true",
        help="Enrich the initial agent prompt with read-only memory preflight context",
    )
    start.add_argument(
        "--memory-area",
        choices=["supervisor", "adapter", "release"],
        default="supervisor",
        help="Memory preflight area to use with --use-memory",
    )

    status = sub.add_parser("status", help="Show stored task status")
    status.add_argument("task_id")
    status.add_argument("--repo", default=".")

    cancel = sub.add_parser("cancel", help="Mark a stored task as cancelled")
    cancel.add_argument("task_id")
    cancel.add_argument("--repo", default=".")

    resume = sub.add_parser("resume", help="Resume a stored task")
    resume.add_argument("task_id")
    resume.add_argument("--repo", default=".")

    report = sub.add_parser("report", help="Write a markdown task report")
    report.add_argument("task_id")
    report.add_argument("--repo", default=".")

    verify = sub.add_parser("verify", help="Run default verification commands")
    verify.add_argument("--repo", default=".")
    verify.add_argument(
        "--approve-command",
        action="append",
        default=[],
        help="Approve one exact verification command string that policy marked as requiring approval",
    )

    agents = sub.add_parser("agents", help="List configured starter agents")
    agents.add_argument("--repo", default=".")
    agents.add_argument("--check", action="store_true", help="Check enabled agent availability")

    memory = sub.add_parser("memory", help="Optional code memory provider helpers")
    memory_sub = memory.add_subparsers(dest="memory_command")
    memory_status = memory_sub.add_parser("status", help="Show memory provider status")
    memory_status.add_argument("--repo", default=".")
    memory_search = memory_sub.add_parser("search", help="Search indexed code symbols")
    memory_search.add_argument("--repo", default=".")
    memory_search.add_argument("--pattern", required=True)
    memory_search.add_argument("--label")
    memory_search.add_argument("--limit", type=int, default=20)
    memory_architecture = memory_sub.add_parser("architecture", help="Show indexed architecture")
    memory_architecture.add_argument("--repo", default=".")
    memory_impact = memory_sub.add_parser("impact", help="Map current git diff impact")
    memory_impact.add_argument("--repo", default=".")
    memory_preflight = memory_sub.add_parser(
        "preflight",
        help="Run a read-only memory preflight for a work area",
    )
    memory_preflight.add_argument("--repo", default=".")
    memory_preflight.add_argument(
        "--area",
        choices=["supervisor", "adapter", "release"],
        required=True,
    )
    memory_preflight.add_argument("--limit", type=int, default=20)
    memory_index = memory_sub.add_parser("index", help="Index the repository after explicit approval")
    memory_index.add_argument("--repo", default=".")
    memory_index.add_argument(
        "--approve",
        action="store_true",
        help="Approve the exact Codebase Memory index command for this invocation",
    )
    memory_index.add_argument(
        "--approve-command",
        action="append",
        default=[],
        help="Approve one exact Codebase Memory command string",
    )

    tui = sub.add_parser("tui", help="Read-only text UI helpers")
    tui_sub = tui.add_subparsers(dest="tui_command")
    tui_approvals = tui_sub.add_parser("approvals", help="Render pending verification approvals")
    tui_approvals.add_argument("--repo", default=".")
    tui_current = tui_sub.add_parser("current", help="Render the latest task iteration")
    tui_current.add_argument("task_id")
    tui_current.add_argument("--repo", default=".")
    tui_logs = tui_sub.add_parser("logs", help="Render task iteration logs")
    tui_logs.add_argument("task_id")
    tui_logs.add_argument("--repo", default=".")
    tui_tasks = tui_sub.add_parser("tasks", help="Render a read-only task list")
    tui_tasks.add_argument("--repo", default=".")
    tui_status = tui_sub.add_parser("status", help="Render a read-only task status view")
    tui_status.add_argument("task_id")
    tui_status.add_argument("--repo", default=".")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _configure_logging(args.log_level)

    if args.command == "init":
        Path(".ai-orch/state").mkdir(parents=True, exist_ok=True)
        Path(".ai-orch/reports").mkdir(parents=True, exist_ok=True)
        print("Initialized .ai-orch directories")
        return 0

    if args.command == "agents":
        config = load_project_config(Path(args.repo))
        print(f"default: {config.default_agent}")
        if config.fallback_agents:
            print(f"fallbacks: {', '.join(config.fallback_agents)}")
        for agent in config.agents.values():
            state = "enabled" if agent.enabled else "disabled"
            details = f"{agent.name}: {state} type={agent.type}"
            if args.check:
                details += f" available={_agent_availability(config, agent.name)}"
            print(details)
        return 0

    if args.command == "memory":
        return _run_memory_command(args, parser)

    if args.command == "verify":
        repo = Path(args.repo)
        config = load_project_config(repo)
        runner = _verification_runner(config, approved_commands=set(args.approve_command))
        verification_results = runner.run_many(config.verification_commands, cwd=repo)
        for item in verification_results:
            print(f"{item.name}: {item.status} exit={item.exit_code}")
        return 0 if all(item.status == "passed" for item in verification_results) else 1

    if args.command == "status":
        store = _state_store_for_repo(Path(args.repo))
        task = store.get_task(args.task_id)
        if task is None:
            print(f"Task not found: {args.task_id}")
            return 1

        iterations = store.list_iterations(task.task_id)
        print(f"Task: {task.task_id}")
        print(f"Status: {task.status}")
        print(f"Repo: {task.repo_path}")
        print(f"Summary: {task.task}")
        print(f"Iterations: {len(iterations)}")
        for iteration in iterations:
            checks = store.list_verification_runs(task.task_id, iteration.iteration_id)
            print(
                "  "
                f"{iteration.iteration_index}. "
                f"agent={iteration.agent_name} "
                f"agent_status={iteration.agent_status} "
                f"decision={iteration.decision_status}"
            )
            print(f"     reason={iteration.decision_reason}")
            for check in checks:
                print(f"     check={check.name} status={check.status} exit={check.exit_code}")
        return 0

    if args.command == "cancel":
        store = _state_store_for_repo(Path(args.repo))
        task = store.get_task(args.task_id)
        if task is None:
            print(f"Task not found: {args.task_id}")
            return 1
        store.update_task_status(task.task_id, "cancelled")
        print(f"Cancelled: {task.task_id}")
        return 0

    if args.command == "tui":
        if args.tui_command == "approvals":
            store = _state_store_for_repo(Path(args.repo))
            print(render_approvals_view(store), end="")
            return 0
        if args.tui_command == "current":
            store = _state_store_for_repo(Path(args.repo))
            view = render_current_view(store, args.task_id)
            if view is None:
                print(f"Task not found: {args.task_id}")
                return 1
            print(view, end="")
            return 0
        if args.tui_command == "logs":
            store = _state_store_for_repo(Path(args.repo))
            view = render_logs_view(store, args.task_id)
            if view is None:
                print(f"Task not found: {args.task_id}")
                return 1
            print(view, end="")
            return 0
        if args.tui_command == "tasks":
            store = _state_store_for_repo(Path(args.repo))
            print(render_tasks_view(store), end="")
            return 0
        if args.tui_command == "status":
            store = _state_store_for_repo(Path(args.repo))
            view = render_status_view(store, args.task_id)
            if view is None:
                print(f"Task not found: {args.task_id}")
                return 1
            print(view, end="")
            return 0
        parser.print_help()
        return 1

    if args.command == "resume":
        store = _state_store_for_repo(Path(args.repo))
        task = store.get_task(args.task_id)
        if task is None:
            print(f"Task not found: {args.task_id}")
            return 1

        config = load_project_config(Path(task.repo_path))
        try:
            supervisor = _build_supervisor(state_store=store, config=config)
        except ValueError as exc:
            print(str(exc))
            return 1
        supervisor_result = supervisor.run_existing(
            task_id=task.task_id,
            task=task.task,
            repo=Path(task.repo_path),
        )
        task_prefix = f"{supervisor_result.task_id}: " if supervisor_result.task_id else ""
        print(f"{task_prefix}{supervisor_result.summary}")
        return 0 if supervisor_result.status == "done" else 1

    if args.command == "report":
        repo = Path(args.repo)
        store = _state_store_for_repo(repo)
        report = render_task_report(store, args.task_id)
        if report is None:
            print(f"Task not found: {args.task_id}")
            return 1

        report_path = repo / ".ai-orch" / "reports" / f"{args.task_id}.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report, encoding="utf-8")
        print(f"Report: {report_path}")
        return 0

    if args.command == "start":
        repo = Path(args.repo)
        config = load_project_config(repo)
        planning_context = None
        if args.use_memory:
            memory_context = _load_memory_planning_context(
                config=config,
                repo=repo,
                area=args.memory_area,
            )
            if memory_context.status != "passed":
                print(f"memory context: {memory_context.status}")
                if memory_context.error:
                    print(f"error: {memory_context.error}")
                return 1
            planning_context = memory_context.stdout
        try:
            supervisor = _build_supervisor(
                state_store=_state_store_for_repo(repo),
                config=config,
            )
        except ValueError as exc:
            print(str(exc))
            return 1
        supervisor_result = supervisor.run_once(
            task=args.task,
            repo=repo,
            planning_context=planning_context,
        )
        task_prefix = f"{supervisor_result.task_id}: " if supervisor_result.task_id else ""
        print(f"{task_prefix}{supervisor_result.summary}")
        return 0 if supervisor_result.status == "done" else 1

    parser.print_help()
    return 0


def _state_store_for_repo(repo: Path) -> StateStore:
    return StateStore(repo / ".ai-orch" / "state" / "ai-orch.db")


def _build_supervisor(state_store: StateStore, config: ProjectConfig) -> Supervisor:
    policy_engine = _policy_engine(config)
    return Supervisor(
        agent=_select_agent(config, policy_engine),
        verifier=VerificationRunner(policy_engine=policy_engine),
        verification_commands=config.verification_commands,
        state_store=state_store,
        max_iterations=config.max_iterations,
        max_no_change_iterations=config.max_no_change_iterations,
        max_runtime_sec=config.max_runtime_sec,
    )


def _select_agent(config: ProjectConfig, policy_engine: PolicyEngine) -> AgentAdapter:
    candidates = build_agent_candidates(config, policy_engine=policy_engine)
    for agent in candidates:
        if agent.check_available():
            return agent
    return candidates[0]


def _agent_availability(config: ProjectConfig, agent_name: str) -> str:
    agent_config = config.agents.get(agent_name)
    if agent_config is None:
        return "missing"
    if not agent_config.enabled:
        return "skipped"

    try:
        agent = build_agent(
            ProjectConfig(
                default_agent=agent_name,
                agents={agent_name: agent_config},
                policy_deny_patterns=config.policy_deny_patterns,
                policy_ask_patterns=config.policy_ask_patterns,
            ),
            policy_engine=_policy_engine(config),
        )
    except ValueError:
        return "error"
    return "yes" if agent.check_available() else "no"


def _policy_engine(config: ProjectConfig) -> PolicyEngine:
    return PolicyEngine(
        deny_patterns=config.policy_deny_patterns or None,
        ask_patterns=config.policy_ask_patterns or None,
    )


def _verification_runner(
    config: ProjectConfig,
    approved_commands: set[str] | None = None,
) -> VerificationRunner:
    return VerificationRunner(
        policy_engine=_policy_engine(config),
        approved_commands=approved_commands,
    )


def _memory_client(
    config: ProjectConfig,
    approved_commands: set[str] | None = None,
) -> CodebaseMemoryClient:
    return CodebaseMemoryClient(
        command=config.memory.command,
        policy_engine=_policy_engine(config),
        approved_commands=approved_commands,
        timeout_sec=config.memory.timeout_sec,
    )


def _run_memory_command(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    if args.memory_command is None:
        parser.print_help()
        return 1

    repo = Path(args.repo)
    config = load_project_config(repo)
    approved_commands = set(getattr(args, "approve_command", []) or [])
    client = _memory_client(config, approved_commands=approved_commands)
    project = config.memory.project

    if args.memory_command == "status":
        print(f"provider: {config.memory.provider or 'codebase-memory-mcp'}")
        print(f"command: {' '.join(config.memory.command)}")
        print(f"project: {project or '(default)'}")
        print(f"available: {'yes' if client.check_available() else 'no'}")
        return 0

    if args.memory_command == "preflight":
        return _run_memory_preflight(args, config, client, project, repo)

    tool_args: dict[str, object]
    tool = args.memory_command
    if args.memory_command == "search":
        tool = "search_graph"
        tool_args = {"name_pattern": args.pattern, "limit": args.limit}
        if args.label:
            tool_args["label"] = args.label
        if project:
            tool_args["project"] = project
    elif args.memory_command == "architecture":
        tool = "get_architecture"
        tool_args = {"aspects": ["all"]}
        if project:
            tool_args["project"] = project
    elif args.memory_command == "impact":
        tool = "detect_changes"
        tool_args = {}
        if project:
            tool_args["project"] = project
    elif args.memory_command == "index":
        tool = "index_repository"
        tool_args = {"repo_path": str(repo.resolve())}
        if args.approve:
            approved_commands.add(client.build_command_string(tool=tool, args=tool_args))
            client = _memory_client(config, approved_commands=approved_commands)
    else:
        parser.print_help()
        return 1

    result = client.run_tool(tool, tool_args, cwd=repo)
    _print_memory_result(tool, result)
    return 0 if result.status == "passed" else 1


def _run_memory_preflight(
    args: argparse.Namespace,
    config: ProjectConfig,
    client: CodebaseMemoryClient,
    project: str,
    repo: Path,
) -> int:
    print(f"preflight: area={args.area}")
    print(f"provider: {config.memory.provider or 'codebase-memory-mcp'}")
    print(f"command: {' '.join(config.memory.command)}")
    print(f"project: {project or '(default)'}")
    print(f"available: {'yes' if client.check_available() else 'no'}")

    statuses: list[str] = []
    for label, tool, tool_args in _memory_preflight_steps(args.area, project, args.limit):
        print(f"step: {label}")
        result = client.run_tool(tool, tool_args, cwd=repo)
        _print_memory_result(tool, result)
        statuses.append(result.status)
    return 0 if all(status == "passed" for status in statuses) else 1


def _load_memory_planning_context(
    config: ProjectConfig,
    repo: Path,
    area: str,
) -> CodebaseMemoryResult:
    client = _memory_client(config)
    if not client.check_available():
        return CodebaseMemoryResult(
            tool="preflight",
            status="unavailable",
            exit_code=None,
            stdout="",
            stderr="",
            error="Memory provider is not available",
        )

    project = config.memory.project
    sections = [f"memory preflight area={area}"]
    for label, tool, tool_args in _memory_preflight_steps(area, project, limit=20):
        result = client.run_tool(tool, tool_args, cwd=repo)
        if result.status != "passed":
            return CodebaseMemoryResult(
                tool=tool,
                status=result.status,
                exit_code=result.exit_code,
                stdout="\n\n".join(sections),
                stderr=result.stderr,
                error=result.error or f"Memory preflight step failed: {label}",
            )
        output = result.stdout or result.stderr
        sections.append(f"## {label}\n{_excerpt(output, 1200) if output else '(no output)'}")
    return CodebaseMemoryResult(
        tool="preflight",
        status="passed",
        exit_code=0,
        stdout="\n\n".join(sections),
        stderr="",
    )


def _memory_preflight_steps(
    area: str,
    project: str,
    limit: int,
) -> list[tuple[str, str, dict[str, object]]]:
    steps: list[tuple[str, str, dict[str, object]]] = [
        ("architecture", "get_architecture", {"aspects": ["all"]}),
    ]
    patterns = {
        "supervisor": [
            (".*Supervisor.*", "Class"),
            (".*Policy.*", "Class"),
            (".*Verification.*", "Class"),
            (".*State.*", "Class"),
            (".*ProcessRunner.*", None),
        ],
        "adapter": [
            (".*Adapter.*", None),
            (".*CLI.*", "Class"),
            (".*ProcessRunner.*", None),
            (".*Policy.*", "Class"),
        ],
        "release": [],
    }[area]
    for pattern, label in patterns:
        search_args: dict[str, object] = {"name_pattern": pattern, "limit": limit}
        if label:
            search_args["label"] = label
        steps.append((f"search {pattern}", "search_graph", search_args))
    steps.append(("impact", "detect_changes", {}))

    if not project:
        return steps
    return [
        (label, tool, {**tool_args, "project": project})
        for label, tool, tool_args in steps
    ]


def _print_memory_result(tool: str, result: CodebaseMemoryResult) -> None:
    print(f"{tool}: {result.status} exit={result.exit_code}")
    if result.error:
        print(f"error: {result.error}")
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    if result.stderr:
        print(result.stderr, end="" if result.stderr.endswith("\n") else "\n")


def _excerpt(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    suffix = "\n... truncated ..."
    if limit <= len(suffix):
        return suffix[:limit]
    return f"{text[: limit - len(suffix)]}{suffix}"


def _configure_logging(log_level: str | None) -> None:
    if log_level is None:
        return
    level = {
        "debug": logging.DEBUG,
        "info": logging.INFO,
        "warning": logging.WARNING,
        "error": logging.ERROR,
    }[log_level]
    logging.basicConfig(level=level, format="%(levelname)s:%(name)s:%(message)s")
