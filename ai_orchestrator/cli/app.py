from __future__ import annotations

import argparse
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ai_orchestrator import __version__
from ai_orchestrator.agents.base import AgentAdapter
from ai_orchestrator.agents.factory import build_agent, build_agent_candidates
from ai_orchestrator.autopilot import (
    AutopilotTask,
    load_plan_tasks,
    next_plan_item,
    next_task,
    plan_item_status_from_supervisor,
    plan_item_to_task,
    sync_plan_items,
)
from ai_orchestrator.config.loader import AgentConfig, ProjectConfig, load_project_config
from ai_orchestrator.core.supervisor import Supervisor, SupervisorResult
from ai_orchestrator.memory import CodebaseMemoryClient, CodebaseMemoryResult
from ai_orchestrator.policy.engine import PolicyEngine
from ai_orchestrator.process.runner import ProcessRunner, RunOptions
from ai_orchestrator.reporting.markdown import render_task_report
from ai_orchestrator.storage.db import StateStore, StoredApprovalRequest, StoredMetricsSummary
from ai_orchestrator.tui.app import (
    render_approvals_view,
    render_current_view,
    render_logs_view,
    render_status_view,
    render_tasks_view,
)
from ai_orchestrator.verification.release import run_release_checks
from ai_orchestrator.verification.runner import VerificationCommand, VerificationRunner


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
    start.add_argument(
        "--worktree",
        help=(
            "Run the task in an existing separate git worktree. "
            "Relative paths are resolved from --repo."
        ),
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

    release_check = sub.add_parser("release-check", help="Run release packaging readiness checks")
    release_check.add_argument("--repo", default=".")

    agents = sub.add_parser("agents", help="List configured starter agents")
    agents.add_argument("--repo", default=".")
    agents.add_argument("--check", action="store_true", help="Check enabled agent availability")

    metrics = sub.add_parser("metrics", help="Show local execution metrics")
    metrics.add_argument("--repo", default=".")

    approvals = sub.add_parser("approvals", help="Manage persisted approval requests")
    approvals_sub = approvals.add_subparsers(dest="approvals_command")
    approvals_list = approvals_sub.add_parser("list", help="List approval requests")
    approvals_list.add_argument("--repo", default=".")
    approvals_list.add_argument("--task-id")
    approvals_list.add_argument(
        "--status",
        choices=["pending", "approved", "rejected", "stale", "all"],
        default="pending",
    )
    approvals_show = approvals_sub.add_parser("show", help="Show approval request details")
    approvals_show.add_argument("approval_id", type=int)
    approvals_show.add_argument("--repo", default=".")
    approvals_approve = approvals_sub.add_parser("approve", help="Approve an approval request")
    approvals_approve.add_argument("approval_id", type=int)
    approvals_approve.add_argument("--repo", default=".")
    approvals_approve.add_argument("--resolution", default="approved by operator")
    approvals_reject = approvals_sub.add_parser("reject", help="Reject an approval request")
    approvals_reject.add_argument("approval_id", type=int)
    approvals_reject.add_argument("--repo", default=".")
    approvals_reject.add_argument("--resolution", default="rejected by operator")
    approvals_retry = approvals_sub.add_parser("retry", help="Retry an approved request")
    approvals_retry.add_argument("approval_id", type=int)
    approvals_retry.add_argument("--repo", default=".")
    approvals_stale = approvals_sub.add_parser(
        "stale",
        help="Mark old pending approval requests as stale",
    )
    approvals_stale.add_argument("--repo", default=".")
    approvals_stale.add_argument("--task-id")
    approvals_stale.add_argument("--older-than-hours", type=int, default=24)
    approvals_stale.add_argument("--resolution", default="marked stale by operator")

    autopilot = sub.add_parser("autopilot", help="Run roadmap tasks through the supervisor")
    autopilot_sub = autopilot.add_subparsers(dest="autopilot_command")
    autopilot_next = autopilot_sub.add_parser("next", help="Show the next unstarted plan item")
    autopilot_next.add_argument("--repo", default=".")
    autopilot_next.add_argument("--plan", default="docs/POST_MVP_ROADMAP.md")
    autopilot_run = autopilot_sub.add_parser("run", help="Run the next plan item")
    autopilot_run.add_argument("--repo", default=".")
    autopilot_run.add_argument("--plan", default="docs/POST_MVP_ROADMAP.md")
    autopilot_run.add_argument(
        "--execute",
        action="store_true",
        help="Actually start the next plan item; without this flag the command is a dry run",
    )
    autopilot_run.add_argument(
        "--allow-dirty",
        action="store_true",
        help="Allow execution when the repository has uncommitted changes",
    )
    autopilot_run.add_argument(
        "--allow-mock-agent",
        action="store_true",
        help="Allow execution with the mock agent for smoke tests",
    )
    autopilot_run.add_argument(
        "--worktree",
        help=(
            "Run the supervisor in an existing separate git worktree. "
            "Relative paths are resolved from --repo."
        ),
    )

    autopilot_queue = autopilot_sub.add_parser(
        "queue",
        help="Manage the persisted autopilot queue",
    )
    autopilot_queue_sub = autopilot_queue.add_subparsers(dest="autopilot_queue_command")
    autopilot_queue_sync = autopilot_queue_sub.add_parser(
        "sync",
        help="Load Markdown plan items into the persisted queue without duplicates",
    )
    autopilot_queue_sync.add_argument("--repo", default=".")
    autopilot_queue_sync.add_argument("--plan", default="docs/POST_MVP_ROADMAP.md")
    autopilot_queue_list = autopilot_queue_sub.add_parser(
        "list",
        help="Display persisted queue status without running batch execution",
    )
    autopilot_queue_list.add_argument("--repo", default=".")
    autopilot_queue_list.add_argument("--plan", default="docs/POST_MVP_ROADMAP.md")
    autopilot_queue_run_next = autopilot_queue_sub.add_parser(
        "run-next",
        help="Select and execute the next persisted queue item",
    )
    autopilot_queue_run_next.add_argument("--repo", default=".")
    autopilot_queue_run_next.add_argument("--plan", default="docs/POST_MVP_ROADMAP.md")
    autopilot_queue_run_next.add_argument(
        "--execute",
        action="store_true",
        help="Actually run the next queued item; without this flag the command is a dry run",
    )
    autopilot_queue_run_next.add_argument(
        "--allow-dirty",
        action="store_true",
        help="Allow execution when the repository has uncommitted changes",
    )
    autopilot_queue_run_next.add_argument(
        "--allow-mock-agent",
        action="store_true",
        help="Allow execution with the mock agent for smoke tests",
    )
    autopilot_queue_run_next.add_argument(
        "--worktree",
        help=(
            "Run the queued item in an existing separate git worktree. "
            "Relative paths are resolved from --repo."
        ),
    )

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
            if agent.profile:
                details += f" profile={agent.profile}"
            if args.check:
                details += f" available={_agent_availability(config, agent.name)}"
            print(details)
        return 0

    if args.command == "memory":
        return _run_memory_command(args, parser)

    if args.command == "approvals":
        return _run_approvals_command(args, parser)

    if args.command == "autopilot":
        return _run_autopilot_command(args, parser)

    if args.command == "metrics":
        store = _state_store_for_repo(Path(args.repo))
        print(_format_metrics_summary(store.metrics_summary()), end="")
        return 0

    if args.command == "verify":
        repo = Path(args.repo)
        config = load_project_config(repo)
        if not config.verification_commands:
            print("No verification commands configured.")
            return 1
        runner = _verification_runner(config, approved_commands=set(args.approve_command))
        verification_results = runner.run_many(config.verification_commands, cwd=repo)
        for item in verification_results:
            print(f"{item.name}: {item.status} exit={item.exit_code}")
        return 0 if all(item.status == "passed" for item in verification_results) else 1

    if args.command == "release-check":
        results = run_release_checks(Path(args.repo))
        for release_item in results:
            print(f"{release_item.name}: {release_item.status} - {release_item.detail}")
        return 0 if all(release_item.status == "passed" for release_item in results) else 1

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
            print(f"     summary={iteration.agent_summary or 'none'}")
            print(f"     files_changed={len(iteration.files_changed)}")
            print(f"     tool_actions={len(iteration.tool_actions)}")
            print(f"     exit_reason={iteration.exit_reason or 'none'}")
            print(f"     uncertainty={iteration.uncertainty or 'none'}")
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
        report_path = _write_task_report(store, repo, args.task_id)
        if report_path is None:
            print(f"Task not found: {args.task_id}")
            return 1
        print(f"Report: {report_path}")
        return 0

    if args.command == "start":
        repo = Path(args.repo)
        config = load_project_config(repo)
        execution_repo = _autopilot_execution_repo(repo, getattr(args, "worktree", None))
        if args.worktree:
            worktree_error = _validate_autopilot_worktree(repo, execution_repo)
            if worktree_error is not None:
                print(f"Execution blocked: {worktree_error}")
                return 1
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
            repo=execution_repo,
            planning_context=planning_context,
        )
        task_prefix = f"{supervisor_result.task_id}: " if supervisor_result.task_id else ""
        print(f"{task_prefix}{supervisor_result.summary}")
        return 0 if supervisor_result.status == "done" else 1

    parser.print_help()
    return 0


def _state_store_for_repo(repo: Path) -> StateStore:
    return StateStore(repo / ".ai-orch" / "state" / "ai-orch.db")


def _write_task_report(store: StateStore, repo: Path, task_id: str) -> Path | None:
    """Render and persist a Markdown report for *task_id*.

    Returns the report path on success, or ``None`` if the task is not found.
    """
    report = render_task_report(store, task_id)
    if report is None:
        return None
    report_path = repo / ".ai-orch" / "reports" / f"{task_id}.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")
    return report_path


def _format_metrics_summary(summary: StoredMetricsSummary) -> str:
    verification_failed_count = summary.verification_count - summary.verification_passed_count
    return "\n".join(
        [
            "Metrics",
            f"  tasks: {summary.task_count}",
            f"  iterations: {summary.iteration_count}",
            (
                "  verification: "
                f"total={summary.verification_count} "
                f"passed={summary.verification_passed_count} "
                f"not_passed={verification_failed_count} "
                f"pass_rate={summary.verification_pass_rate:.1%}"
            ),
            (
                "  approvals: "
                f"total={summary.approval_count} "
                f"pending={summary.approval_pending_count} "
                f"approved={summary.approval_approved_count} "
                f"rejected={summary.approval_rejected_count} "
                f"stale={summary.approval_stale_count}"
            ),
            f"  adapter_failures: {summary.adapter_failure_count}",
        ]
    ) + "\n"


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


def _run_approvals_command(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    if args.approvals_command is None:
        parser.print_help()
        return 1

    store = _state_store_for_repo(Path(args.repo))
    if args.approvals_command == "list":
        status = None if args.status == "all" else args.status
        approvals = store.list_approval_requests(task_id=args.task_id, status=status)
        if not approvals:
            print("No approval requests found.")
            return 0
        for approval in approvals:
            print(_format_approval_summary(approval))
        return 0

    if args.approvals_command == "show":
        shown_approval = store.get_approval_request(args.approval_id)
        if shown_approval is None:
            print(f"Approval request not found: {args.approval_id}")
            return 1
        print(_format_approval_detail(shown_approval), end="")
        return 0

    if args.approvals_command in {"approve", "reject"}:
        status = "approved" if args.approvals_command == "approve" else "rejected"
        resolved_approval = store.resolve_approval_request(
            args.approval_id,
            status=status,
            resolution=args.resolution,
        )
        if resolved_approval is None:
            print(f"Approval request not found: {args.approval_id}")
            return 1
        print(_format_approval_summary(resolved_approval))
        return 0

    if args.approvals_command == "retry":
        retried_approval = store.get_approval_request(args.approval_id)
        if retried_approval is None:
            print(f"Approval request not found: {args.approval_id}")
            return 1
        return _retry_approval_request(store, retried_approval)

    if args.approvals_command == "stale":
        if args.older_than_hours < 1:
            print("--older-than-hours must be at least 1")
            return 1
        cutoff = datetime.now(UTC) - timedelta(hours=args.older_than_hours)
        stale_approvals = store.mark_stale_approval_requests(
            cutoff_created_at=cutoff.isoformat(),
            task_id=args.task_id,
            resolution=args.resolution,
        )
        if not stale_approvals:
            print("No stale approval requests found.")
            return 0
        for stale_approval in stale_approvals:
            print(_format_approval_summary(stale_approval))
        return 0

    parser.print_help()
    return 1


def _format_approval_summary(approval: StoredApprovalRequest) -> str:
    iteration = "none" if approval.iteration_id is None else str(approval.iteration_id)
    return (
        f"{approval.approval_id}: status={approval.status} "
        f"source={approval.source} task={approval.task_id} "
        f"iteration={iteration} retries={approval.retry_count} "
        f"last_retry={approval.last_retry_status or 'none'} "
        f"command={approval.command_string}"
    )


def _format_approval_detail(approval: StoredApprovalRequest) -> str:
    iteration = "none" if approval.iteration_id is None else str(approval.iteration_id)
    lines = [
        f"Approval: {approval.approval_id}",
        f"Status: {approval.status}",
        f"Task: {approval.task_id}",
        f"Iteration: {iteration}",
        f"Source: {approval.source}",
        f"Command: {approval.command_string}",
        f"Reason: {approval.reason}",
        f"Created: {approval.created_at}",
        f"Retries: {approval.retry_count}",
    ]
    if approval.resolved_at is not None:
        lines.append(f"Resolved: {approval.resolved_at}")
    if approval.resolution is not None:
        lines.append(f"Resolution: {approval.resolution}")
    if approval.last_retry_at is not None:
        lines.append(f"Last retry: {approval.last_retry_at}")
        lines.append(f"Last retry status: {approval.last_retry_status}")
        lines.append(f"Last retry exit: {approval.last_retry_exit_code}")
    if approval.last_retry_error is not None:
        lines.append(f"Last retry error: {approval.last_retry_error}")
    return "\n".join(lines) + "\n"


def _retry_approval_request(
    store: StateStore,
    approval: StoredApprovalRequest,
) -> int:
    if approval.status != "approved":
        print(
            "Approval request is not approved: "
            f"{approval.approval_id} status={approval.status}"
        )
        return 1

    task = store.get_task(approval.task_id)
    if task is None:
        print(f"Task not found for approval request: {approval.task_id}")
        return 1

    repo = Path(task.repo_path)
    config = load_project_config(repo)
    runner = _verification_runner(
        config,
        approved_commands={approval.command_string},
    )
    result = runner.run(
        VerificationCommand(
            name=f"approval-{approval.approval_id}",
            run=approval.command_string,
        ),
        cwd=repo,
    )
    updated_approval = store.record_approval_retry(
        approval_id=approval.approval_id,
        status=result.status,
        exit_code=result.exit_code,
        error=result.error or result.stderr,
    )
    print(f"retry: {result.status} exit={result.exit_code}")
    if updated_approval is not None:
        print(
            "retry history: "
            f"count={updated_approval.retry_count} "
            f"last_status={updated_approval.last_retry_status} "
            f"last_exit={updated_approval.last_retry_exit_code}"
        )
    if result.error:
        print(f"error: {result.error}")
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    if result.stderr:
        print(result.stderr, end="" if result.stderr.endswith("\n") else "\n")
    return 0 if result.status == "passed" else 1


def _run_autopilot_command(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    if args.autopilot_command is None:
        parser.print_help()
        return 1

    repo = Path(args.repo)
    plan_path = _resolve_plan_path(repo, Path(args.plan))
    if not plan_path.exists():
        print(f"Plan not found: {plan_path}")
        return 1

    store = _state_store_for_repo(repo)
    if args.autopilot_command == "queue":
        return _run_autopilot_queue_command(args, parser)

    tasks = load_plan_tasks(plan_path)
    selected = next_task(tasks, store)
    if selected is None:
        print(f"No unstarted plan items found in {plan_path}")
        return 0

    if args.autopilot_command == "next":
        _print_autopilot_task(selected)
        return 0

    if args.autopilot_command == "run":
        result = _run_autopilot_task(selected, repo, plan_path, args, store)
        return 0 if result is None or result.status == "done" else 1

    parser.print_help()
    return 1


def _run_autopilot_task(
    task: AutopilotTask,
    repo: Path,
    plan_path: Path,
    args: argparse.Namespace,
    store: StateStore,
    on_start: Callable[[], None] | None = None,
) -> SupervisorResult | None:
    """Run a single autopilot task through the supervisor.

    Returns ``None`` for a dry run, or a :class:`SupervisorResult` after
    execution. Guard failures are reported as a blocked result.
    """
    config = load_project_config(repo)
    policy_engine = _policy_engine(config)
    agent = _select_agent(config, policy_engine)
    agent_config = config.agents.get(agent.name)
    agent_available = agent.check_available()
    execution_repo = _autopilot_execution_repo(repo, getattr(args, "worktree", None))
    print("Autopilot selected:")
    _print_autopilot_task(task)
    _print_autopilot_agent_profile(agent, agent_config, agent_available)
    print(f"Execution repo: {execution_repo}")

    if not args.execute:
        print("Dry run: add --execute to start this plan item.")
        return None

    if agent.name == "mock" and not args.allow_mock_agent:
        print("Execution blocked: mock agent selected. Enable a real agent or pass --allow-mock-agent.")
        return SupervisorResult(status="blocked", summary="mock agent selected")

    if agent.name != "mock" and not agent_available:
        print(f"Execution blocked: selected agent is unavailable: {agent.name}")
        return SupervisorResult(status="blocked", summary=f"agent unavailable: {agent.name}")

    if args.worktree:
        worktree_error = _validate_autopilot_worktree(repo, execution_repo)
        if worktree_error is not None:
            print(f"Execution blocked: {worktree_error}")
            return SupervisorResult(status="blocked", summary=worktree_error)

    if _repo_has_uncommitted_changes(execution_repo) and not args.allow_dirty:
        print("Execution blocked: repository has uncommitted changes. Commit/stash them or pass --allow-dirty.")
        return SupervisorResult(status="blocked", summary="repository has uncommitted changes")

    if on_start is not None:
        on_start()

    supervisor = Supervisor(
        agent=agent,
        verifier=VerificationRunner(policy_engine=policy_engine),
        verification_commands=config.verification_commands,
        state_store=store,
        max_iterations=config.max_iterations,
        max_no_change_iterations=config.max_no_change_iterations,
        max_runtime_sec=config.max_runtime_sec,
        require_repo_change=True,
        progress_callback=_print_progress,
    )
    result = supervisor.run_once(task=task.to_prompt(), repo=execution_repo)
    task_prefix = f"{result.task_id}: " if result.task_id else ""
    print(f"{task_prefix}{result.summary}")
    return result


def _autopilot_execution_repo(repo: Path, worktree: str | None) -> Path:
    if not worktree:
        return repo
    worktree_path = Path(worktree)
    if not worktree_path.is_absolute():
        worktree_path = repo / worktree_path
    return worktree_path.resolve()


def _validate_autopilot_worktree(repo: Path, worktree: Path) -> str | None:
    if not worktree.exists():
        return f"worktree path does not exist: {worktree}"
    if not worktree.is_dir():
        return f"worktree path is not a directory: {worktree}"

    repo_root = _git_rev_parse_path(repo, "--show-toplevel")
    if repo_root is None:
        return f"repo is not a git repository: {repo}"
    worktree_root = _git_rev_parse_path(worktree, "--show-toplevel")
    if worktree_root is None:
        return f"worktree path is not a git repository: {worktree}"
    if worktree_root != worktree.resolve():
        return f"worktree path must be the git worktree root: {worktree_root}"
    if worktree_root == repo_root:
        return "worktree path must be a separate git worktree, not the main repo"

    repo_common = _git_rev_parse_path(repo, "--git-common-dir")
    worktree_common = _git_rev_parse_path(worktree, "--git-common-dir")
    if repo_common is None or worktree_common is None:
        return "unable to inspect git worktree metadata"
    if repo_common != worktree_common:
        return f"worktree path is not linked to repo: {worktree}"
    return None


def _git_rev_parse_path(repo: Path, flag: str) -> Path | None:
    result = ProcessRunner().run(
        ["git", "rev-parse", "--path-format=absolute", flag],
        cwd=repo,
        options=RunOptions(timeout_sec=30),
    )
    if result.status != "success":
        return None
    value = result.stdout.strip().splitlines()
    if not value:
        return None
    return Path(value[0]).resolve()


def _resolve_plan_path(repo: Path, plan_path: Path) -> Path:
    if plan_path.is_absolute():
        return plan_path
    return repo / plan_path


def _run_autopilot_queue_command(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    if args.autopilot_queue_command is None:
        parser.print_help()
        return 1

    repo = Path(args.repo)
    plan_path = _resolve_plan_path(repo, Path(args.plan))
    if not plan_path.exists():
        print(f"Plan not found: {plan_path}")
        return 1

    store = _state_store_for_repo(repo)

    if args.autopilot_queue_command == "sync":
        new_items, existing_items = sync_plan_items(plan_path, store)
        print(f"Synced {plan_path}")
        print(f"  new: {len(new_items)}")
        print(f"  existing: {len(existing_items)}")
        for item in new_items:
            print(f"  + {item.line_number}: {item.text}")
        return 0

    if args.autopilot_queue_command == "list":
        items = store.list_plan_items(plan_path=plan_path)
        print(f"Queue status for {plan_path}")
        print(f"  total: {len(items)}")
        status_counts: dict[str, int] = {}
        for item in items:
            status_counts[item.status] = status_counts.get(item.status, 0) + 1
        if status_counts:
            summary = ", ".join(
                f"{status}={count}" for status, count in sorted(status_counts.items())
            )
            print("  by status:", summary)
        for item in items:
            task_ref = f" task={item.task_id}" if item.task_id else ""
            print(f"  [{item.status}] {item.line_number}: {item.text}{task_ref}")
        return 0

    if args.autopilot_queue_command == "run-next":
        next_item = next_plan_item(store, plan_path)
        if next_item is None:
            print(f"No queued plan items ready in {plan_path}")
            return 0
        task = plan_item_to_task(next_item)

        def _mark_in_progress() -> None:
            store.update_plan_item_status(next_item.plan_item_id, "in_progress")

        result = _run_autopilot_task(
            task,
            repo,
            plan_path,
            args,
            store,
            on_start=_mark_in_progress,
        )
        if result is None:
            return 0
        item_status = plan_item_status_from_supervisor(result.status)
        store.update_plan_item_status(next_item.plan_item_id, item_status, task_id=result.task_id)
        print(f"Queue item {next_item.plan_item_id}: status={item_status}")
        if result.task_id is not None:
            report_path = _write_task_report(store, repo, result.task_id)
            if report_path is not None:
                print(f"Report: {report_path}")
        return 0 if item_status == "done" else 1

    parser.print_help()
    return 1


def _print_autopilot_task(task: AutopilotTask) -> None:
    print(f"Source: {task.source_label}")
    print(f"Section: {task.section or 'Unsectioned'}")
    print(f"Task: {task.text}")


def _print_autopilot_agent_profile(
    agent: AgentAdapter,
    agent_config: AgentConfig | None,
    available: bool,
) -> None:
    print("Agent profile:")
    print(f"  name: {agent.name}")
    print(f"  type: {_agent_config_value(agent_config, 'type')}")
    print(f"  profile: {_agent_config_value(agent_config, 'profile')}")
    print(f"  mode: {'mock' if agent.name == 'mock' else 'real'}")
    print(f"  command: {_agent_config_value(agent_config, 'command')}")
    print(f"  available: {'yes' if available else 'no'}")


def _print_progress(message: str) -> None:
    print(f"progress: {message}", flush=True)


def _agent_config_value(agent_config: AgentConfig | None, field: str) -> str:
    if agent_config is None:
        return "(unknown)"
    value = getattr(agent_config, field)
    if value == "":
        return "(default)"
    return str(value)


def _repo_has_uncommitted_changes(repo: Path) -> bool:
    result = ProcessRunner().run(
        ["git", "status", "--porcelain=v1"],
        cwd=repo,
        options=RunOptions(timeout_sec=30),
    )
    if result.status != "success":
        return True
    return bool(result.stdout.strip())


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
    if result.status == "needs_approval":
        approval = _persist_memory_approval_request(
            repo=repo,
            tool=tool,
            tool_args=tool_args,
            client=client,
            result=result,
        )
        print(f"approval_request: {approval.approval_id}")
    _print_memory_result(tool, result)
    return 0 if result.status == "passed" else 1


def _persist_memory_approval_request(
    repo: Path,
    tool: str,
    tool_args: dict[str, object],
    client: CodebaseMemoryClient,
    result: CodebaseMemoryResult,
) -> StoredApprovalRequest:
    store = _state_store_for_repo(repo)
    task = store.create_task(
        task=f"Memory approval request: {tool}",
        repo_path=repo,
    )
    store.update_task_status(task.task_id, "blocked")
    return store.add_approval_request(
        task_id=task.task_id,
        iteration_id=None,
        source="memory",
        command_string=client.build_command_string(tool=tool, args=tool_args),
        reason=result.error or f"Codebase Memory tool requires approval: {tool}",
    )


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
