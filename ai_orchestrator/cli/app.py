from __future__ import annotations

import argparse
from pathlib import Path

from ai_orchestrator.agents.base import AgentAdapter
from ai_orchestrator.agents.factory import build_agent, build_agent_candidates
from ai_orchestrator.config.loader import ProjectConfig, load_project_config
from ai_orchestrator.core.supervisor import Supervisor
from ai_orchestrator.policy.engine import PolicyEngine
from ai_orchestrator.reporting.markdown import render_task_report
from ai_orchestrator.storage.db import StateStore
from ai_orchestrator.verification.runner import VerificationRunner


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ai-orch", description="Local supervisor for CLI AI agents")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("init", help="Create local .ai-orch directories")

    start = sub.add_parser("start", help="Start a task with the mock agent")
    start.add_argument("--task", required=True)
    start.add_argument("--repo", default=".")

    status = sub.add_parser("status", help="Show stored task status")
    status.add_argument("task_id")
    status.add_argument("--repo", default=".")

    resume = sub.add_parser("resume", help="Resume a stored task")
    resume.add_argument("task_id")
    resume.add_argument("--repo", default=".")

    report = sub.add_parser("report", help="Write a markdown task report")
    report.add_argument("task_id")
    report.add_argument("--repo", default=".")

    verify = sub.add_parser("verify", help="Run default verification commands")
    verify.add_argument("--repo", default=".")

    agents = sub.add_parser("agents", help="List configured starter agents")
    agents.add_argument("--repo", default=".")
    agents.add_argument("--check", action="store_true", help="Check enabled agent availability")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

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

    if args.command == "verify":
        repo = Path(args.repo)
        config = load_project_config(repo)
        runner = _verification_runner(config)
        result = runner.run_many(config.verification_commands, cwd=repo)
        for item in result:
            print(f"{item.name}: {item.status} exit={item.exit_code}")
        return 0 if all(item.status == "passed" for item in result) else 1

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
        result = supervisor.run_existing(
            task_id=task.task_id,
            task=task.task,
            repo=Path(task.repo_path),
        )
        task_prefix = f"{result.task_id}: " if result.task_id else ""
        print(f"{task_prefix}{result.summary}")
        return 0 if result.status == "done" else 1

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
        try:
            supervisor = _build_supervisor(
                state_store=_state_store_for_repo(repo),
                config=config,
            )
        except ValueError as exc:
            print(str(exc))
            return 1
        result = supervisor.run_once(task=args.task, repo=repo)
        task_prefix = f"{result.task_id}: " if result.task_id else ""
        print(f"{task_prefix}{result.summary}")
        return 0 if result.status == "done" else 1

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


def _verification_runner(config: ProjectConfig) -> VerificationRunner:
    return VerificationRunner(policy_engine=_policy_engine(config))
