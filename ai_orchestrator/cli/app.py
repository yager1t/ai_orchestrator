from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from ai_orchestrator import __version__
from ai_orchestrator.agents.base import AgentAdapter
from ai_orchestrator.agents.factory import build_agent, build_agent_candidates
from ai_orchestrator.autopilot import (
    AutopilotTask,
    load_backlog_tasks,
    load_plan_tasks,
    next_plan_item,
    next_plan_items,
    next_task,
    plan_item_status_from_supervisor,
    plan_item_to_task,
    refresh_created_backlog_item_refs,
    sync_backlog_items,
    sync_plan_items,
)
from ai_orchestrator.autopilot.worktree_overview import (
    CLEANUP_STATUSES,
    format_worktree_overview,
    format_worktree_summary,
    gather_worktree_overviews,
    worktree_overview_data,
)
from ai_orchestrator.config.loader import AgentConfig, ProjectConfig, load_project_config
from ai_orchestrator.core.supervisor import Supervisor, SupervisorResult
from ai_orchestrator.evaluation import (
    run_all_suites,
    run_chaos_suite,
    run_golden_suite,
    run_redteam_suite,
)
from ai_orchestrator.memory import CodebaseMemoryClient, CodebaseMemoryResult
from ai_orchestrator.policy.engine import PolicyEngine
from ai_orchestrator.process.runner import ProcessRunner, RunOptions
from ai_orchestrator.reporting.markdown import render_task_report
from ai_orchestrator.storage.db import (
    StateStore,
    StoredActionRecord,
    StoredApprovalRequest,
    StoredAutopilotLoopRun,
    StoredMetricsSummary,
    StoredPlanGraph,
    StoredPlanGraphDependency,
    StoredPlanGraphNode,
    StoredPlanItem,
    StoredTask,
    StoredTimelineEntry,
)
from ai_orchestrator.storage.redaction import redact_secrets
from ai_orchestrator.tools import (
    TOOL_RISK_TIERS,
    ToolBroker,
    ToolCall,
    ToolExecutorRegistry,
    ToolResult,
    ToolResultStatus,
    ToolRiskTier,
    approved_memory_commands_for_call,
    file_tool_executor,
    make_tool_call,
    make_process_tool_call,
    memory_tool_executor,
    process_tool_executor,
)
from ai_orchestrator.tui.app import (
    render_approvals_view,
    render_current_view,
    render_logs_view,
    render_memory_influence_view,
    render_memory_lessons_view,
    render_status_view,
    render_tasks_view,
)
from ai_orchestrator.verification.release import run_release_checks
from ai_orchestrator.verification.runner import (
    VerificationCommand,
    VerificationResult,
    VerificationRunner,
)


_QUEUE_STATUSES = ("created", "in_progress", "done", "blocked", "skipped")
_PLAN_GRAPH_STATUSES = ("active", "done", "blocked", "archived")
_PLAN_GRAPH_NODE_STATUSES = ("pending", "in_progress", "done", "blocked", "skipped")
_TERMINAL_QUEUE_STATUSES = {"done", "skipped"}
_STATE_STORE_CACHE: dict[Path, StateStore] = {}
_KNOWN_AGENT_CONNECTORS = ("codex", "claude", "gemini", "kimi", "generic", "mock")
_AGENT_DEFAULT_COMMANDS = {
    "codex": "codex",
    "claude": "claude",
    "gemini": "gemini",
    "kimi": "kimi",
    "generic": "(configured)",
    "mock": "(internal)",
}
_AGENT_DEFAULT_TYPES = {
    "codex": "codex_exec",
    "claude": "claude_headless",
    "gemini": "gemini_cli",
    "kimi": "kimi_cli",
    "generic": "generic_cli",
    "mock": "mock",
}
_CLI_AUTH_CONNECTORS = {"codex", "claude", "gemini", "kimi"}
_SETUP_PROFILES = (
    "codex-safe",
    "python-project",
    "node-project",
    "docs-project",
    "readonly-review",
)
_DEMO_TASK = "Confirm the README has a top-level heading."
_PRODUCT_COMMANDS = ("fix", "task", "analyze", "review", "docs")
_BEGINNER_ROLES = {
    "developer": "Developer",
    "bug-fixer": "Bug fixer",
    "code-reviewer": "Code reviewer",
    "documentation-writer": "Documentation writer",
    "security-auditor": "Security auditor",
    "qa-engineer": "QA engineer",
}
_PRODUCT_COMMAND_DEFAULT_ROLES = {
    "fix": "bug-fixer",
    "task": "developer",
    "analyze": "code-reviewer",
    "review": "code-reviewer",
    "docs": "documentation-writer",
}
_PRODUCT_COMMAND_DEFAULT_TASKS = {
    "fix": "Find and fix the most important failing behavior in this repository.",
    "task": "Implement the requested coding task safely.",
    "analyze": "Analyze this repository and report the highest-priority risks.",
    "review": "Review this repository for correctness, tests, and safety issues.",
    "docs": "Improve or create documentation for the current project.",
}

# Schema version for the JSON trace produced by ``ai-orch export``.
TRACE_SCHEMA_VERSION = "1.2"


def _add_max_runtime_sec_argument(parser: Any) -> None:
    parser.add_argument(
        "--max-runtime-sec",
        type=int,
        metavar="SECONDS",
        help=(
            "Optional per-run supervisor runtime budget in seconds. "
            "Overrides orchestrator.max_runtime_sec for this queue item."
        ),
    )


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

    setup = sub.add_parser("setup", help="Create a beginner-friendly local config")
    setup.add_argument("--repo", default=".")
    setup.add_argument(
        "--agent",
        choices=["auto", "mock", "codex", "claude", "kimi", "gemini"],
        default="auto",
        help="Default agent to configure; auto chooses the first detected CLI",
    )
    setup.add_argument(
        "--profile",
        choices=_SETUP_PROFILES,
        default="python-project",
        help="Verification and onboarding preset to write into config.yaml",
    )
    setup.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing .ai-orch/config.yaml",
    )
    setup.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the config that would be written without changing files",
    )
    setup.add_argument("--json", action="store_true", help="Print machine-readable output")

    doctor = sub.add_parser("doctor", help="Diagnose local setup readiness")
    doctor.add_argument(
        "doctor_command",
        nargs="?",
        choices=["agents"],
        help="Optional focused doctor view",
    )
    doctor.add_argument("--repo", default=".")
    doctor.add_argument("--json", action="store_true", help="Print machine-readable output")

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

    demo = sub.add_parser(
        "demo",
        help="Run a safe first-value demo using the bundled docs-only example",
    )
    demo.add_argument(
        "--repo",
        default="examples/docs_only_quickstart",
        help="Demo repository to run (default: examples/docs_only_quickstart)",
    )
    demo.add_argument(
        "--task",
        default=_DEMO_TASK,
        help="Demo task text to run through the supervisor",
    )

    onboard = sub.add_parser(
        "onboard",
        help="Run a beginner-friendly first-run readiness wizard",
    )
    onboard.add_argument("--repo", default=".")
    onboard.add_argument("--json", action="store_true", help="Print machine-readable output")

    for command_name in _PRODUCT_COMMANDS:
        product = sub.add_parser(
            command_name,
            help=f"Run a {command_name} scenario through the supervisor",
        )
        product.add_argument(
            "prompt",
            nargs="*",
            help="Scenario prompt; can be used instead of --task",
        )
        product.add_argument("--task", help="Scenario prompt to run")
        product.add_argument("--repo", default=".")
        product.add_argument(
            "--role",
            choices=tuple(_BEGINNER_ROLES),
            default=_PRODUCT_COMMAND_DEFAULT_ROLES[command_name],
            help="Beginner role template to apply",
        )
        product.add_argument(
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

    recover = sub.add_parser(
        "recover",
        help="Recover interrupted runs and expired action leases",
    )
    recover.add_argument("--repo", default=".")
    recover.add_argument(
        "--apply",
        action="store_true",
        help="Apply recovery changes; without this flag the command is a dry run",
    )
    recover.add_argument(
        "--reason",
        help="Required with --apply; persisted in recovery events and action results",
    )
    recover.add_argument("--json", action="store_true", help="Print machine-readable JSON")

    report = sub.add_parser("report", help="Write a markdown task report")
    report.add_argument("task_id")
    report.add_argument("--repo", default=".")

    timeline = sub.add_parser("timeline", help="Show a replayable task timeline")
    timeline.add_argument("task_id")
    timeline.add_argument("--repo", default=".")
    timeline.add_argument("--json", action="store_true", help="Print machine-readable JSON")

    export = sub.add_parser("export", help="Export a task trace as local JSON")
    export.add_argument("task_id")
    export.add_argument("--repo", default=".")
    export.add_argument(
        "--output",
        help="Output JSON file path (default: .ai-orch/traces/<task_id>.json)",
    )
    export.add_argument(
        "--redact",
        action="store_true",
        help=(
            "Omit bulky raw agent output and verification streams "
            "(stdout/stderr) from the exported JSON without changing stored state"
        ),
    )

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

    ci = sub.add_parser(
        "ci",
        help="Run verification and release checks for CI environments",
    )
    ci.add_argument("--repo", default=".")
    ci.add_argument(
        "--approve-command",
        action="append",
        default=[],
        help="Approve one exact verification command string that policy marked as requiring approval",
    )

    agents = sub.add_parser("agents", help="List configured starter agents")
    agents.add_argument("--repo", default=".")
    agents.add_argument("--check", action="store_true", help="Check enabled agent availability")

    metrics = sub.add_parser("metrics", help="Show local execution metrics")
    metrics.add_argument("--repo", default=".")

    eval_parser = sub.add_parser("eval", help="Run local evaluation suites")
    eval_sub = eval_parser.add_subparsers(dest="eval_command")
    eval_golden = eval_sub.add_parser("golden", help="Run the local golden task suite")
    eval_golden.add_argument("--repo", default=".")
    eval_golden.add_argument("--json", action="store_true")
    eval_chaos = eval_sub.add_parser("chaos", help="Run local chaos evaluation scenarios")
    eval_chaos.add_argument("--repo", default=".")
    eval_chaos.add_argument("--json", action="store_true")
    eval_redteam = eval_sub.add_parser(
        "redteam",
        help="Run local security red-team evaluation scenarios",
    )
    eval_redteam.add_argument("--repo", default=".")
    eval_redteam.add_argument("--json", action="store_true")
    eval_all = eval_sub.add_parser("all", help="Run all local evaluation suites")
    eval_all.add_argument("--repo", default=".")
    eval_all.add_argument("--json", action="store_true")

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
    autopilot_loop = autopilot_sub.add_parser(
        "loop",
        help="Run a guarded unattended autopilot queue loop",
    )
    autopilot_loop.add_argument("--repo", default=".")
    autopilot_loop.add_argument("--plan", default="docs/POST_MVP_ROADMAP.md")
    autopilot_loop.add_argument(
        "--max-items",
        type=int,
        default=1,
        help="Maximum number of queue items to process (default: 1)",
    )
    autopilot_loop.add_argument(
        "--execute",
        action="store_true",
        help="Actually process queued items; without this flag the loop is a dry run",
    )
    autopilot_loop.add_argument(
        "--stop-on-risk",
        action="store_true",
        help="Stop before processing when preflight reports queue risk",
    )
    autopilot_loop.add_argument(
        "--allow-dirty",
        action="store_true",
        help="Allow execution when the repository has uncommitted changes",
    )
    autopilot_loop.add_argument(
        "--allow-mock-agent",
        action="store_true",
        help="Allow execution with the mock agent for smoke tests",
    )
    _add_max_runtime_sec_argument(autopilot_loop)
    autopilot_loop.add_argument(
        "--max-attempts",
        type=int,
        default=1,
        help="Maximum attempts before a blocked item is recorded as dead-letter",
    )
    autopilot_loop.add_argument(
        "--max-actions",
        type=int,
        default=100,
        help="Maximum queue item actions allowed in this loop run (default: 100)",
    )
    autopilot_loop.add_argument(
        "--summary-json",
        dest="summary_json",
        metavar="PATH",
        help="Write the underlying batch summary as a machine-readable JSON artifact",
    )
    autopilot_loop.add_argument(
        "--batch-report",
        dest="batch_report",
        metavar="PATH",
        help="Write the underlying batch summary as an operator-facing Markdown artifact",
    )

    autopilot_loop_history = autopilot_sub.add_parser(
        "loop-history",
        help="Show persisted autopilot loop budget ledger runs",
    )
    autopilot_loop_history.add_argument("--repo", default=".")
    autopilot_loop_history.add_argument("--plan", default="docs/POST_MVP_ROADMAP.md")
    autopilot_loop_history.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum number of loop runs to show (default: 10)",
    )
    autopilot_loop_history.add_argument("--json", action="store_true")

    autopilot_worktree_overview = autopilot_sub.add_parser(
        "worktree-overview",
        help="Inspect git worktrees under a base directory without making changes",
    )
    autopilot_worktree_overview.add_argument("--repo", default=".")
    autopilot_worktree_overview.add_argument(
        "--base-dir",
        required=True,
        help="Directory containing candidate git worktrees to inspect",
    )
    autopilot_worktree_overview.add_argument(
        "--dirty-only",
        action="store_true",
        help="Show only worktrees with uncommitted or untracked changes",
    )
    autopilot_worktree_overview.add_argument(
        "--branch-filter",
        metavar="TEXT",
        help="Show only worktrees whose branch name contains TEXT",
    )
    autopilot_worktree_overview.add_argument(
        "--unlinked-only",
        action="store_true",
        help="Show only worktrees not linked to the review repo",
    )
    autopilot_worktree_overview.add_argument(
        "--merged-only",
        action="store_true",
        help="Show only worktrees whose branch is merged into the review repo HEAD",
    )
    autopilot_worktree_overview.add_argument(
        "--cleanup-status",
        dest="cleanup_status",
        metavar="STATUS",
        choices=CLEANUP_STATUSES,
        help="Show only worktrees with the given cleanup status",
    )
    autopilot_worktree_overview.add_argument(
        "--older-than-days",
        type=int,
        default=None,
        metavar="N",
        help="Show only worktrees last modified at least N days ago",
    )
    autopilot_worktree_overview.add_argument(
        "--limit",
        type=int,
        default=0,
        metavar="N",
        help="Show at most the first N filtered rows; 0 means all rows (default: 0)",
    )
    autopilot_worktree_overview.add_argument(
        "--json",
        action="store_true",
        help="Emit the read-only worktree overview as machine-readable JSON",
    )

    autopilot_plan = autopilot_sub.add_parser(
        "plan",
        help="Manage durable PlanGraph state",
    )
    autopilot_plan_sub = autopilot_plan.add_subparsers(dest="autopilot_plan_command")
    autopilot_plan_list = autopilot_plan_sub.add_parser(
        "list",
        help="List persisted plan graphs",
    )
    autopilot_plan_list.add_argument("--repo", default=".")
    autopilot_plan_list.add_argument("--task-id")
    autopilot_plan_list.add_argument("--status", choices=_PLAN_GRAPH_STATUSES)
    autopilot_plan_list.add_argument(
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON object instead of text",
    )
    autopilot_plan_create = autopilot_plan_sub.add_parser(
        "create",
        help="Create a persisted plan graph",
    )
    autopilot_plan_create.add_argument("--repo", default=".")
    autopilot_plan_create.add_argument("--title", required=True)
    autopilot_plan_create.add_argument("--task-id")
    autopilot_plan_create.add_argument(
        "--status",
        choices=_PLAN_GRAPH_STATUSES,
        default="active",
    )
    autopilot_plan_create.add_argument(
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON object instead of text",
    )
    autopilot_plan_show = autopilot_plan_sub.add_parser(
        "show",
        help="Show a plan graph with nodes and dependencies",
    )
    autopilot_plan_show.add_argument("graph_id", type=int)
    autopilot_plan_show.add_argument("--repo", default=".")
    autopilot_plan_show.add_argument(
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON object instead of text",
    )
    autopilot_plan_ready = autopilot_plan_sub.add_parser(
        "ready",
        help="Show pending PlanGraph nodes whose dependencies are done",
    )
    autopilot_plan_ready.add_argument("graph_id", type=int)
    autopilot_plan_ready.add_argument("--repo", default=".")
    autopilot_plan_ready.add_argument(
        "--limit",
        type=int,
        default=0,
        metavar="N",
        help="Show at most N ready nodes; 0 means all ready nodes (default: 0)",
    )
    autopilot_plan_ready.add_argument(
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON object instead of text",
    )
    autopilot_plan_run_next = autopilot_plan_sub.add_parser(
        "run-next",
        help="Claim and run the next ready PlanGraph node",
    )
    autopilot_plan_run_next.add_argument("graph_id", type=int)
    autopilot_plan_run_next.add_argument("--repo", default=".")
    autopilot_plan_run_next.add_argument(
        "--execute",
        action="store_true",
        help="Actually run the selected ready node; without this flag the command is a dry run",
    )
    autopilot_plan_run_next.add_argument(
        "--allow-dirty",
        action="store_true",
        help="Allow execution when the repository has uncommitted changes",
    )
    autopilot_plan_run_next.add_argument(
        "--allow-mock-agent",
        action="store_true",
        help="Allow execution with the mock agent for smoke tests",
    )
    autopilot_plan_run_next.add_argument(
        "--worktree",
        help=(
            "Run the PlanGraph node in an existing separate git worktree. "
            "Relative paths are resolved from --repo."
        ),
    )
    _add_max_runtime_sec_argument(autopilot_plan_run_next)
    autopilot_plan_run_batch = autopilot_plan_sub.add_parser(
        "run-batch",
        help="Run multiple ready PlanGraph nodes serially",
    )
    autopilot_plan_run_batch.add_argument("graph_id", type=int)
    autopilot_plan_run_batch.add_argument("--repo", default=".")
    autopilot_plan_run_batch.add_argument(
        "--max-items",
        type=int,
        default=1,
        help="Maximum number of ready PlanGraph nodes to process (default: 1)",
    )
    autopilot_plan_run_batch.add_argument(
        "--execute",
        action="store_true",
        help="Actually run ready nodes; without this flag the command is a dry run",
    )
    autopilot_plan_run_batch.add_argument(
        "--allow-dirty",
        action="store_true",
        help="Allow execution when the repository has uncommitted changes",
    )
    autopilot_plan_run_batch.add_argument(
        "--allow-mock-agent",
        action="store_true",
        help="Allow execution with the mock agent for smoke tests",
    )
    autopilot_plan_run_batch.add_argument(
        "--worktree",
        help=(
            "Run the PlanGraph nodes in an existing separate git worktree. "
            "Relative paths are resolved from --repo."
        ),
    )
    _add_max_runtime_sec_argument(autopilot_plan_run_batch)
    autopilot_plan_update = autopilot_plan_sub.add_parser(
        "update",
        help="Update a plan graph status",
    )
    autopilot_plan_update.add_argument("graph_id", type=int)
    autopilot_plan_update.add_argument("--repo", default=".")
    autopilot_plan_update.add_argument("--status", choices=_PLAN_GRAPH_STATUSES, required=True)
    autopilot_plan_update.add_argument(
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON object instead of text",
    )
    autopilot_plan_add_node = autopilot_plan_sub.add_parser(
        "add-node",
        help="Add a node to a plan graph",
    )
    autopilot_plan_add_node.add_argument("graph_id", type=int)
    autopilot_plan_add_node.add_argument("--repo", default=".")
    autopilot_plan_add_node.add_argument("--key", required=True)
    autopilot_plan_add_node.add_argument("--title", required=True)
    autopilot_plan_add_node.add_argument(
        "--status",
        choices=_PLAN_GRAPH_NODE_STATUSES,
        default="pending",
    )
    autopilot_plan_add_node.add_argument("--attempts", type=int, default=0)
    autopilot_plan_add_node.add_argument(
        "--depends-on",
        dest="depends_on_node_ids",
        action="append",
        type=int,
        help="Node id this node depends on; repeat for multiple dependencies",
    )
    autopilot_plan_add_node.add_argument(
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON object instead of text",
    )
    autopilot_plan_update_node = autopilot_plan_sub.add_parser(
        "update-node",
        help="Update a plan graph node status and attempt count",
    )
    autopilot_plan_update_node.add_argument("node_id", type=int)
    autopilot_plan_update_node.add_argument("--repo", default=".")
    autopilot_plan_update_node.add_argument(
        "--status",
        choices=_PLAN_GRAPH_NODE_STATUSES,
        required=True,
    )
    attempts_group = autopilot_plan_update_node.add_mutually_exclusive_group()
    attempts_group.add_argument("--attempts", type=int)
    attempts_group.add_argument("--increment-attempts", action="store_true")
    autopilot_plan_update_node.add_argument(
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON object instead of text",
    )
    autopilot_plan_add_dependency = autopilot_plan_sub.add_parser(
        "add-dependency",
        help="Add a dependency edge between two plan graph nodes",
    )
    autopilot_plan_add_dependency.add_argument("graph_id", type=int)
    autopilot_plan_add_dependency.add_argument("--repo", default=".")
    autopilot_plan_add_dependency.add_argument("--node-id", type=int, required=True)
    autopilot_plan_add_dependency.add_argument(
        "--depends-on-node-id",
        type=int,
        required=True,
    )
    autopilot_plan_add_dependency.add_argument(
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON object instead of text",
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
    autopilot_queue_sync_backlog = autopilot_queue_sub.add_parser(
        "sync-backlog",
        help="Load open backlog priority items into the persisted queue",
    )
    autopilot_queue_sync_backlog.add_argument("--repo", default=".")
    autopilot_queue_sync_backlog.add_argument("--backlog", default="docs/BACKLOG.md")
    autopilot_queue_sync_backlog.add_argument(
        "--priority",
        action="append",
        choices=["P0", "P1", "P2", "P3 / Deferred"],
        help="Backlog priority section to include; repeat to include multiple sections",
    )
    autopilot_queue_refresh_refs = autopilot_queue_sub.add_parser(
        "refresh-created-refs",
        help=(
            "Refresh shifted source refs for unchanged created backlog queue items; "
            "dry-run by default"
        ),
    )
    autopilot_queue_refresh_refs.add_argument("--repo", default=".")
    autopilot_queue_refresh_refs.add_argument("--backlog", default="docs/BACKLOG.md")
    autopilot_queue_refresh_refs.add_argument(
        "--priority",
        action="append",
        choices=["P0", "P1", "P2", "P3 / Deferred"],
        help="Backlog priority section to include; repeat to include multiple sections",
    )
    autopilot_queue_refresh_refs.add_argument(
        "--apply",
        action="store_true",
        help="Update matching created queue item refs; dry-run by default",
    )
    autopilot_queue_refresh_refs.add_argument(
        "--json",
        action="store_true",
        help="Emit the read-only refresh summary as machine-readable JSON",
    )
    autopilot_queue_list = autopilot_queue_sub.add_parser(
        "list",
        help="Display persisted queue status without running batch execution",
    )
    autopilot_queue_list.add_argument("--repo", default=".")
    autopilot_queue_list.add_argument("--plan", default="docs/POST_MVP_ROADMAP.md")
    autopilot_queue_list.add_argument(
        "--all-plans",
        action="store_true",
        help="Display queue items from every persisted plan path",
    )
    autopilot_queue_list.add_argument(
        "--status",
        action="append",
        choices=_QUEUE_STATUSES,
        help="Only show queue items with this status; repeat to include multiple statuses",
    )
    autopilot_queue_list.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Limit displayed items after filtering; 0 means all items (default: 0)",
    )
    autopilot_queue_list.add_argument(
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON object instead of the default text summary",
    )
    autopilot_queue_status = autopilot_queue_sub.add_parser(
        "status",
        help="Summarize persisted queue counts and recent items",
    )
    autopilot_queue_status.add_argument("--repo", default=".")
    autopilot_queue_status.add_argument("--plan", default="docs/POST_MVP_ROADMAP.md")
    autopilot_queue_status.add_argument(
        "--all-plans",
        action="store_true",
        help="Summarize queue items from every persisted plan path",
    )
    autopilot_queue_status.add_argument(
        "--status",
        action="append",
        choices=_QUEUE_STATUSES,
        help="Only show recent items for this status; repeat to include multiple statuses",
    )
    autopilot_queue_status.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Number of recent items to show per status (default: 5)",
    )
    autopilot_queue_readiness = autopilot_queue_sub.add_parser(
        "readiness",
        help="Read-only preflight summary of queue counts, risk, and stale items",
    )
    autopilot_queue_readiness.add_argument("--repo", default=".")
    autopilot_queue_readiness.add_argument(
        "--plan", default="docs/POST_MVP_ROADMAP.md"
    )
    autopilot_queue_readiness.add_argument(
        "--all-plans",
        action="store_true",
        help="Summarize readiness for every persisted plan path",
    )
    autopilot_queue_readiness.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Maximum stale and at-risk items to list (default: 5)",
    )
    autopilot_queue_readiness.add_argument(
        "--fail-on-risk",
        action="store_true",
        help=(
            "Return a non-zero exit code when stale created items, "
            "blocked items, or in-progress items are present"
        ),
    )
    autopilot_queue_readiness.add_argument(
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON object instead of the default text summary",
    )
    autopilot_queue_preflight = autopilot_queue_sub.add_parser(
        "preflight",
        help=(
            "Read-only preflight for a selected plan combining queue readiness "
            "with the selected agent profile summary"
        ),
    )
    autopilot_queue_preflight.add_argument("--repo", default=".")
    autopilot_queue_preflight.add_argument(
        "--plan", default="docs/POST_MVP_ROADMAP.md"
    )
    autopilot_queue_preflight.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Maximum stale and at-risk items to list (default: 5)",
    )
    autopilot_queue_preflight.add_argument(
        "--fail-on-risk",
        action="store_true",
        help=(
            "Return a non-zero exit code when stale created items, blocked items, "
            "in-progress items, or the selected agent is unavailable"
        ),
    )
    autopilot_queue_preflight.add_argument(
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON object instead of the default text summary",
    )
    autopilot_queue_reconcile = autopilot_queue_sub.add_parser(
        "reconcile",
        help="Find stale created queue items whose source plan task is no longer open",
    )
    autopilot_queue_reconcile.add_argument("--repo", default=".")
    autopilot_queue_reconcile.add_argument("--plan", default="docs/POST_MVP_ROADMAP.md")
    autopilot_queue_reconcile.add_argument(
        "--all-plans",
        action="store_true",
        help="Reconcile created items from every persisted plan path",
    )
    autopilot_queue_reconcile.add_argument(
        "--apply",
        action="store_true",
        help="Mark stale created queue items as skipped; dry-run by default",
    )
    autopilot_queue_reconcile.add_argument(
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON object instead of the default text summary",
    )
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
    _add_max_runtime_sec_argument(autopilot_queue_run_next)
    autopilot_queue_run_batch = autopilot_queue_sub.add_parser(
        "run-batch",
        help="Run up to a configurable number of persisted queue items serially",
    )
    autopilot_queue_run_batch.add_argument("--repo", default=".")
    autopilot_queue_run_batch.add_argument("--plan", default="docs/POST_MVP_ROADMAP.md")
    autopilot_queue_run_batch.add_argument(
        "--item-id",
        dest="item_id",
        type=int,
        metavar="PLAN_ITEM_ID",
        help=(
            "Process one selected created queue item id from queue show instead "
            "of the default oldest ready item selection"
        ),
    )
    autopilot_queue_run_batch.add_argument(
        "--execute",
        action="store_true",
        help=(
            "Actually run queued items; without this flag the command is a dry run"
        ),
    )
    autopilot_queue_run_batch.add_argument(
        "--allow-dirty",
        action="store_true",
        help="Allow execution when the repository has uncommitted changes",
    )
    autopilot_queue_run_batch.add_argument(
        "--allow-mock-agent",
        action="store_true",
        help="Allow execution with the mock agent for smoke tests",
    )
    worktree_group = autopilot_queue_run_batch.add_mutually_exclusive_group()
    worktree_group.add_argument(
        "--worktree",
        help=(
            "Run the queued items in an existing separate git worktree. "
            "Relative paths are resolved from --repo."
        ),
    )
    worktree_group.add_argument(
        "--rotate-worktrees",
        dest="rotate_worktrees",
        metavar="BASE_DIR",
        help=(
            "Run each queued item in a separate pre-created git worktree under "
            "BASE_DIR. Mutually exclusive with --worktree. Dry-run by default."
        ),
    )
    _add_max_runtime_sec_argument(autopilot_queue_run_batch)
    autopilot_queue_run_batch.add_argument(
        "--max-items",
        type=int,
        default=1,
        help="Maximum number of queue items to process (default: 1)",
    )
    autopilot_queue_run_batch.add_argument(
        "--summary-json",
        dest="summary_json",
        metavar="PATH",
        help=(
            "Write the final batch summary as a machine-readable JSON artifact "
            "to PATH without changing stdout or exit-code semantics"
        ),
    )
    autopilot_queue_run_batch.add_argument(
        "--batch-report",
        dest="batch_report",
        metavar="PATH",
        help=(
            "Write the final batch summary as an operator-facing Markdown "
            "artifact to PATH without changing stdout or exit-code semantics"
        ),
    )
    autopilot_queue_recover = autopilot_queue_sub.add_parser(
        "recover-in-progress",
        help="Find stale in_progress queue items and optionally mark them blocked",
    )
    autopilot_queue_recover.add_argument("--repo", default=".")
    autopilot_queue_recover.add_argument("--plan", default="docs/POST_MVP_ROADMAP.md")
    autopilot_queue_recover.add_argument(
        "--all-plans",
        action="store_true",
        help="Recover in_progress items from every persisted plan path",
    )
    autopilot_queue_recover.add_argument(
        "--apply",
        action="store_true",
        help="Mark stale in_progress queue items as blocked; dry-run by default",
    )
    autopilot_queue_recover.add_argument(
        "--reason",
        help="Reason for blocking stale in_progress items (required with --apply)",
    )
    autopilot_queue_recover.add_argument(
        "--older-than-hours",
        type=int,
        metavar="N",
        help=(
            "Only recover in_progress items whose last status update is older "
            "than N hours"
        ),
    )
    autopilot_queue_recover.add_argument(
        "--json",
        action="store_true",
        help=(
            "Print a machine-readable recovery summary without changing "
            "dry-run/apply or exit-code semantics"
        ),
    )

    autopilot_queue_show = autopilot_queue_sub.add_parser(
        "show",
        help="Show a selected queue item's details without changing state",
    )
    autopilot_queue_show.add_argument(
        "plan_item_id",
        type=int,
        help="Persisted queue item id to show",
    )
    autopilot_queue_show.add_argument("--repo", default=".")
    autopilot_queue_show.add_argument(
        "--plan",
        help=(
            "Optional plan path for compatibility with queue history commands. "
            "When given, the item is shown only if it belongs to this plan."
        ),
    )
    autopilot_queue_show.add_argument(
        "--json",
        action="store_true",
        help="Print selected queue item details as machine-readable JSON",
    )

    autopilot_queue_link_plan_graph = autopilot_queue_sub.add_parser(
        "link-plan-graph",
        help="Link a queue item to a durable PlanGraph root",
    )
    autopilot_queue_link_plan_graph.add_argument(
        "plan_item_id",
        type=int,
        help="Persisted queue item id to link",
    )
    autopilot_queue_link_plan_graph.add_argument("--repo", default=".")
    autopilot_queue_link_plan_graph.add_argument(
        "--plan",
        help=(
            "Optional plan path for compatibility with queue history commands. "
            "When given, the item is linked only if it belongs to this plan."
        ),
    )
    autopilot_queue_link_plan_graph.add_argument(
        "--graph-id",
        type=int,
        required=True,
        help="PlanGraph id to attach to the queue item",
    )
    autopilot_queue_link_plan_graph.add_argument(
        "--root-node-id",
        type=int,
        help="Optional PlanGraph node id representing the queue item's root step",
    )
    autopilot_queue_link_plan_graph.add_argument(
        "--apply",
        action="store_true",
        help="Persist the link; without this flag the command is a dry run",
    )
    autopilot_queue_link_plan_graph.add_argument(
        "--json",
        action="store_true",
        help="Print the link dry-run or apply result as machine-readable JSON",
    )

    autopilot_queue_requeue = autopilot_queue_sub.add_parser(
        "requeue",
        help="Move a blocked queue item back to created after operator review",
    )
    autopilot_queue_requeue.add_argument(
        "plan_item_id",
        type=int,
        help="Persisted queue item id to requeue",
    )
    autopilot_queue_requeue.add_argument("--repo", default=".")
    autopilot_queue_requeue.add_argument(
        "--plan",
        help=(
            "Optional plan path for compatibility with queue history commands. "
            "When given, the item is requeued only if it belongs to this plan."
        ),
    )
    autopilot_queue_requeue.add_argument(
        "--apply",
        action="store_true",
        help="Actually move the item back to created; without this flag the command is a dry run",
    )
    autopilot_queue_requeue.add_argument(
        "--json",
        action="store_true",
        help="Print the requeue dry-run or apply result as machine-readable JSON",
    )

    autopilot_queue_skip = autopilot_queue_sub.add_parser(
        "skip",
        help="Mark a created or blocked queue item as skipped after operator review",
    )
    autopilot_queue_skip.add_argument(
        "plan_item_id",
        type=int,
        help="Persisted queue item id to skip",
    )
    autopilot_queue_skip.add_argument("--repo", default=".")
    autopilot_queue_skip.add_argument(
        "--plan",
        help=(
            "Optional plan path for compatibility with queue history commands. "
            "When given, the item is skipped only if it belongs to this plan."
        ),
    )
    autopilot_queue_skip.add_argument(
        "--reason",
        required=True,
        help="Reason the item is being skipped (required)",
    )
    autopilot_queue_skip.add_argument(
        "--apply",
        action="store_true",
        help="Actually mark the item skipped; without this flag the command is a dry run",
    )
    autopilot_queue_skip.add_argument(
        "--json",
        action="store_true",
        help="Print the skip dry-run or apply result as machine-readable JSON",
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
    memory_lessons = memory_sub.add_parser("lessons", help="List stored memory lessons")
    memory_lessons.add_argument("--repo", default=".")
    memory_lessons.add_argument("--include-stale", action="store_true")
    memory_lessons.add_argument("--limit", type=int, default=20)
    memory_influence = memory_sub.add_parser("influence", help="List memory influence logs")
    memory_influence.add_argument("--repo", default=".")
    memory_influence.add_argument("--task-id")

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
    tui_memory_lessons = tui_sub.add_parser("memory-lessons", help="Render stored memory lessons")
    tui_memory_lessons.add_argument("--repo", default=".")
    tui_memory_lessons.add_argument("--include-stale", action="store_true")
    tui_memory_influence = tui_sub.add_parser("memory-influence", help="Render memory influence logs")
    tui_memory_influence.add_argument("--repo", default=".")
    tui_memory_influence.add_argument("--task-id")
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
    if not _validate_max_runtime_sec(args):
        return 1

    if args.command == "init":
        Path(".ai-orch/state").mkdir(parents=True, exist_ok=True)
        Path(".ai-orch/reports").mkdir(parents=True, exist_ok=True)
        print("Initialized .ai-orch directories")
        return 0

    if args.command == "setup":
        return _run_setup_command(args)

    if args.command == "doctor":
        return _run_doctor_command(args)

    if args.command == "demo":
        return _run_demo_command(args)

    if args.command == "onboard":
        return _run_onboard_command(args)

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

    if args.command == "eval":
        eval_runners = {
            "golden": run_golden_suite,
            "chaos": run_chaos_suite,
            "redteam": run_redteam_suite,
            "all": run_all_suites,
        }
        eval_runner = eval_runners.get(args.eval_command)
        if eval_runner is not None:
            summary = eval_runner(Path(args.repo))
            if args.json:
                print(json.dumps(asdict(summary), indent=2, sort_keys=True))
            else:
                print(_format_evaluation_summary(summary), end="")
            return 0 if summary.unsafe_action_count == 0 and summary.passed == summary.total else 1
        parser.print_help()
        return 1

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
        verification_ok = all(
            _verify_status_allows_success(item.status)
            for item in verification_results
        )
        return 0 if verification_ok else 1

    if args.command == "release-check":
        results = run_release_checks(Path(args.repo))
        for release_item in results:
            print(f"{release_item.name}: {release_item.status} - {release_item.detail}")
        return 0 if all(release_item.status == "passed" for release_item in results) else 1

    if args.command == "ci":
        return _run_ci_command(args)

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
        if args.tui_command == "memory-lessons":
            store = _state_store_for_repo(Path(args.repo))
            print(
                render_memory_lessons_view(
                    store,
                    include_stale=args.include_stale,
                ),
                end="",
            )
            return 0
        if args.tui_command == "memory-influence":
            store = _state_store_for_repo(Path(args.repo))
            print(render_memory_influence_view(store, task_id=args.task_id), end="")
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
            supervisor = _build_supervisor(
                state_store=store,
                config=config,
                progress_callback=_print_progress,
            )
        except ValueError as exc:
            print(str(exc))
            return 1
        _print_run_preamble(
            action="resume",
            repo=Path(task.repo_path),
            config=config,
            supervisor=supervisor,
            task_id=task.task_id,
        )
        supervisor_result = supervisor.run_existing(
            task_id=task.task_id,
            task=task.task,
            repo=Path(task.repo_path),
        )
        _print_supervisor_result(supervisor_result, repo=Path(task.repo_path))
        return 0 if supervisor_result.status == "done" else 1

    if args.command == "recover":
        repo = Path(args.repo)
        store = _state_store_for_repo(repo)
        return _run_recover(args, store)

    if args.command == "report":
        repo = Path(args.repo)
        store = _state_store_for_repo(repo)
        report_path = _write_task_report(store, repo, args.task_id)
        if report_path is None:
            print(f"Task not found: {args.task_id}")
            return 1
        print(f"Report: {report_path}")
        return 0

    if args.command == "timeline":
        store = _state_store_for_repo(Path(args.repo))
        return _run_timeline(args, store)

    if args.command == "export":
        repo = Path(args.repo)
        store = _state_store_for_repo(repo)
        output_path = Path(args.output) if args.output else None
        trace_path = _export_task_trace(
            store, repo, args.task_id, output_path, redact=args.redact
        )
        if trace_path is None:
            print(f"Task not found: {args.task_id}")
            return 1
        print(f"Trace: {trace_path}")
        return 0

    if args.command == "start":
        start_result = _run_supervisor_start(
            repo=Path(args.repo),
            task=args.task,
            worktree=args.worktree,
            use_memory=args.use_memory,
            memory_area=args.memory_area,
        )
        if start_result is None:
            return 1
        return 0 if start_result.status == "done" else 1

    if args.command in _PRODUCT_COMMANDS:
        return _run_product_command(args)

    parser.print_help()
    return 0


def _state_store_for_repo(repo: Path) -> StateStore:
    db_path = (repo / ".ai-orch" / "state" / "ai-orch.db").resolve()
    store = _STATE_STORE_CACHE.get(db_path)
    if store is None:
        store = StateStore(db_path)
        _STATE_STORE_CACHE[db_path] = store
    return store


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


def _export_task_trace(
    store: StateStore,
    repo: Path,
    task_id: str,
    output_path: Path | None = None,
    redact: bool = False,
) -> Path | None:
    """Export the stored task trace for *task_id* to local JSON.

    Includes the task summary, replay timeline, task events, action records,
    replan decisions, iteration details, verification results, approval requests,
    and top-level metadata (schema version, exported timestamp, task id,
    redaction mode) without changing supervisor execution semantics or stored
    task state.

    When *redact* is ``True``, bulky fields such as raw agent output and
    verification stdout/stderr are omitted from the exported JSON. The stored
    task state is left unchanged.

    Returns the destination path on success, or ``None`` if the task is not found.
    """
    task = store.get_task(task_id)
    if task is None:
        return None

    run_id = store.run_id_for_task(task.task_id)
    iterations = [asdict(iteration) for iteration in store.list_iteration_details(task_id)]
    verification_runs = [
        asdict(run) for run in store.list_verification_details(task_id)
    ]
    action_records = [
        _trace_record_with_run_id(asdict(action), run_id)
        for action in store.list_action_records(task_id=task_id)
    ]

    if redact:
        for iteration in iterations:
            iteration.pop("raw_output", None)
        for run in verification_runs:
            run.pop("stdout", None)
            run.pop("stderr", None)

    trace = {
        "metadata": {
            "schema_version": TRACE_SCHEMA_VERSION,
            "exported_at": datetime.now(UTC).isoformat(),
            "task_id": task.task_id,
            "run_id": run_id,
            "redaction_mode": "redacted" if redact else "none",
            "unsafe_action_count": _unsafe_action_count(action_records),
        },
        "task": _trace_record_with_run_id(asdict(task), run_id),
        "timeline": [
            _trace_record_with_run_id(asdict(entry), run_id)
            for entry in store.list_task_timeline(task_id=task_id)
        ],
        "task_events": [
            _trace_record_with_run_id(asdict(event), run_id)
            for event in store.list_task_events(task_id=task_id)
        ],
        "action_records": action_records,
        "action_journal": [
            _trace_action_journal_entry(action, run_id) for action in action_records
        ],
        "replan_decisions": [
            _trace_record_with_run_id(asdict(decision), run_id)
            for decision in store.list_replan_decisions(task_id=task_id)
        ],
        "memory_lessons": [
            _trace_record_with_run_id(asdict(lesson), run_id)
            for lesson in store.list_memory_lessons(include_stale=True)
            if lesson.source_task_id == task_id
        ],
        "reflection_records": [
            _trace_record_with_run_id(asdict(reflection), run_id)
            for reflection in store.list_reflection_records(task_id=task_id)
        ],
        "memory_influence": [
            _trace_record_with_run_id(asdict(influence), run_id)
            for influence in store.list_memory_influence(task_id=task_id)
        ],
        "iterations": [_trace_record_with_run_id(iteration, run_id) for iteration in iterations],
        "verification_runs": [
            _trace_record_with_run_id(run, run_id) for run in verification_runs
        ],
        "approvals": [
            _trace_record_with_run_id(asdict(approval), run_id)
            for approval in store.list_approval_requests(task_id=task_id)
        ],
    }

    destination = output_path or repo / ".ai-orch" / "traces" / f"{task_id}.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(trace, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    return destination


def _trace_record_with_run_id(record: dict[str, object], run_id: str) -> dict[str, object]:
    return {**record, "run_id": run_id}


def _trace_action_journal_entry(
    action: dict[str, object],
    run_id: str,
) -> dict[str, object]:
    payload = _dict_value(action, "payload")
    result = _dict_value(action, "result")
    request = _dict_value(payload, "action_request")
    risk = _dict_value(request, "risk")
    provenance = _dict_value(request, "provenance")
    decision = _dict_value(result, "action_decision")
    action_result = _dict_value(result, "action_result")
    output = _dict_value(result, "output")

    approval_id = decision.get("approval_id")
    if approval_id is None:
        approval_id = output.get("approval_id")

    command_string = action.get("command_string")
    redacted_command = (
        redact_secrets(command_string) if isinstance(command_string, str) else None
    )
    policy_reason = action.get("policy_reason")
    redacted_policy_reason = (
        redact_secrets(policy_reason) if isinstance(policy_reason, str) else None
    )

    return _trace_record_with_run_id(
        {
            "action_id": action.get("action_id"),
            "task_id": action.get("task_id"),
            "iteration_id": action.get("iteration_id"),
            "idempotency_key": action.get("idempotency_key"),
            "action_type": action.get("action_type"),
            "requested_action": request.get("name") or payload.get("tool_name"),
            "category": risk.get("action_type"),
            "risk_tier": risk.get("risk_tier") or payload.get("risk_tier"),
            "requires_approval": risk.get("requires_approval"),
            "status": action.get("status"),
            "command_string": redacted_command,
            "policy_action": action.get("policy_action"),
            "policy_reason": redacted_policy_reason,
            "decision": decision,
            "approval_id": approval_id,
            "outcome": action_result,
            "output_preview": action_result.get("output_preview"),
            "provenance": provenance,
            "lease": {
                "owner": action.get("lease_owner"),
                "expires_at": action.get("lease_expires_at"),
                "heartbeat_at": action.get("heartbeat_at"),
            },
            "created_at": action.get("created_at"),
            "updated_at": action.get("updated_at"),
        },
        run_id,
    )


def _dict_value(payload: dict[str, object], key: str) -> dict[str, object]:
    value = payload.get(key)
    if isinstance(value, dict) and all(isinstance(item_key, str) for item_key in value):
        return cast(dict[str, object], value)
    return {}


def _unsafe_action_count(action_records: list[dict[str, object]]) -> int:
    count = 0
    for action in action_records:
        payload = action.get("payload")
        if not isinstance(payload, dict):
            continue
        request = payload.get("action_request")
        risk = request.get("risk") if isinstance(request, dict) else None
        action_type = risk.get("action_type") if isinstance(risk, dict) else None
        risk_tier = (
            risk.get("risk_tier")
            if isinstance(risk, dict)
            else payload.get("risk_tier")
        )
        policy_action = action.get("policy_action")
        status = action.get("status")
        risky = risk_tier in {"network", "destructive"} or action_type in {
            "dangerous",
            "secret_sensitive",
        }
        if risky and policy_action != "deny":
            if status not in {"policy_denied", "needs_approval"}:
                count += 1
    return count


def _run_recover(args: argparse.Namespace, store: StateStore) -> int:
    running_tasks = [task for task in store.list_tasks() if task.status == "running"]
    expired_actions = store.list_expired_action_leases()
    stale_started_actions = [
        action
        for action in store.list_stale_action_records()
        if action.action_id not in {expired.action_id for expired in expired_actions}
    ]
    recover_actions = [*expired_actions, *stale_started_actions]

    if args.apply and not args.reason:
        print("--reason is required when --apply is set")
        return 1

    blocked_tasks = 0
    failed_actions = 0
    if args.apply:
        for task in running_tasks:
            store.update_task_status(task.task_id, "blocked")
            store.append_task_event(
                task.task_id,
                "task_recovered",
                {
                    "previous_status": "running",
                    "status": "blocked",
                    "reason": args.reason,
                },
                actor="supervisor",
                summary="Task recovered and marked blocked",
                idempotency_key="task_recovered:blocked",
            )
            store.append_task_event(
                task.task_id,
                "task.recovered",
                {
                    "previous_status": "running",
                    "status": "blocked",
                    "reason": args.reason,
                },
                actor="supervisor",
                summary="Task recovered and marked blocked",
            )
            blocked_tasks += 1
        for action in recover_actions:
            completed = store.complete_action_record(
                action.action_id,
                "failed",
                result={
                    "recovered": True,
                    "reason": args.reason,
                    "previous_status": action.status,
                    "lease_owner": action.lease_owner,
                    "lease_expires_at": action.lease_expires_at,
                },
            )
            if completed is not None:
                failed_actions += 1

    if args.json:
        _print_recover_json(
            running_tasks=running_tasks,
            expired_actions=expired_actions,
            stale_started_actions=stale_started_actions,
            apply=bool(args.apply),
            reason=args.reason if args.apply else None,
            blocked_tasks=blocked_tasks,
            failed_actions=failed_actions,
        )
        return 0

    print("Recovery")
    print(f"  running_tasks: {len(running_tasks)}")
    print(f"  expired_action_leases: {len(expired_actions)}")
    print(f"  stale_started_actions: {len(stale_started_actions)}")
    if args.apply:
        print(f"  blocked_tasks: {blocked_tasks}")
        print(f"  failed_actions: {failed_actions}")
        print(f"  reason: {args.reason}")
    else:
        print("  dry_run: use --apply --reason '...' to recover")
    if not running_tasks and not recover_actions:
        print("  No interrupted runs or stale action records found.")
        return 0

    for task in running_tasks:
        print(f"  [running_task] {task.task_id}: {task.task}")
    for action in expired_actions:
        owner = action.lease_owner or "none"
        expires = action.lease_expires_at or "none"
        print(
            (
                f"  [expired_action] {action.action_id}: "
                f"{action.action_type} task={action.task_id} "
                f"owner={owner} expires={expires}"
            )
        )
    for action in stale_started_actions:
        print(
            (
                f"  [stale_action] {action.action_id}: "
                f"{action.action_type} task={action.task_id} "
                f"updated={action.updated_at}"
            )
        )
    return 0


def _print_recover_json(
    *,
    running_tasks: list[StoredTask],
    expired_actions: list[StoredActionRecord],
    stale_started_actions: list[StoredActionRecord],
    apply: bool,
    reason: str | None,
    blocked_tasks: int,
    failed_actions: int,
) -> None:
    payload = {
        "apply": apply,
        "dry_run": not apply,
        "reason": reason,
        "running_tasks": {
            "count": len(running_tasks),
            "items": [asdict(task) for task in running_tasks],
        },
        "expired_action_leases": {
            "count": len(expired_actions),
            "items": [asdict(action) for action in expired_actions],
        },
        "stale_started_actions": {
            "count": len(stale_started_actions),
            "items": [asdict(action) for action in stale_started_actions],
        },
        "recovered": {
            "blocked_tasks": blocked_tasks,
            "failed_actions": failed_actions,
        },
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))


def _run_timeline(args: argparse.Namespace, store: StateStore) -> int:
    task = store.get_task(args.task_id)
    if task is None:
        print(f"Task not found: {args.task_id}")
        return 1

    timeline = store.list_task_timeline(task.task_id)
    if args.json:
        _print_timeline_json(task=task, timeline=timeline)
        return 0

    print(f"Timeline: {task.task_id}")
    print(f"  entries: {len(timeline)}")
    if not timeline:
        print("  No timeline entries recorded.")
        return 0
    for entry in timeline:
        status = f" status={entry.status}" if entry.status else ""
        print(
            (
                f"  [{entry.timeline_index}] {entry.occurred_at} "
                f"{entry.source}:{entry.source_id} {entry.event_type}{status}"
            )
        )
        print(f"    {entry.summary}")
    return 0


def _print_timeline_json(
    *,
    task: StoredTask,
    timeline: list[StoredTimelineEntry],
) -> None:
    payload = {
        "task": asdict(task),
        "timeline": [asdict(entry) for entry in timeline],
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))


def _task_report_path(repo: Path, task_id: str | None) -> Path | None:
    """Return the expected Markdown report path if it exists.

    Returns ``None`` when *task_id* is missing or the report file has not
    been generated yet.
    """
    if task_id is None:
        return None
    report_path = repo / ".ai-orch" / "reports" / f"{task_id}.md"
    return report_path if report_path.exists() else None


def _queue_item_refs(repo: Path, item: StoredPlanItem) -> str:
    task_ref = f" task={item.task_id}" if item.task_id else ""
    worktree_ref = (
        f" worktree={item.selected_worktree_path}" if item.selected_worktree_path else ""
    )
    blocked_reason_ref = f" reason={item.blocked_reason}" if item.blocked_reason else ""
    graph_ref = f" graph={item.plan_graph_id}" if item.plan_graph_id is not None else ""
    root_ref = (
        f" root_node={item.plan_graph_root_node_id}"
        if item.plan_graph_root_node_id is not None
        else ""
    )
    report_path = _task_report_path(repo, item.task_id)
    report_ref = f" report={report_path}" if report_path else ""
    return f"{task_ref}{worktree_ref}{blocked_reason_ref}{graph_ref}{root_ref}{report_ref}"


_RUNTIME_BUDGET_EXHAUSTED_SUMMARY = "Runtime budget exhausted"


def _runtime_budget_exhausted_reason(result: SupervisorResult) -> str | None:
    if result.status == "blocked" and result.summary == _RUNTIME_BUDGET_EXHAUSTED_SUMMARY:
        return _RUNTIME_BUDGET_EXHAUSTED_SUMMARY
    return None


def _mark_plan_graph_node_started(store: StateStore, item: StoredPlanItem) -> None:
    if item.plan_graph_root_node_id is None:
        return
    store.update_plan_graph_node_status(
        item.plan_graph_root_node_id,
        "in_progress",
        increment_attempts=True,
    )


def _finish_plan_graph_node_for_queue_result(
    store: StateStore,
    item: StoredPlanItem,
    item_status: str,
    task_id: str | None,
) -> None:
    if item.plan_graph_id is None or item.plan_graph_root_node_id is None:
        return
    node_status = "done" if item_status == "done" else "blocked"
    store.update_plan_graph_node_status(
        item.plan_graph_root_node_id,
        node_status,
    )
    if task_id is not None:
        store.link_replan_decisions_to_plan_graph(
            task_id,
            item.plan_graph_id,
            plan_graph_node_id=item.plan_graph_root_node_id,
        )
        store.create_replan_follow_up_nodes(task_id, item.plan_graph_id)


def _validate_max_runtime_sec(args: argparse.Namespace) -> bool:
    max_runtime_sec = getattr(args, "max_runtime_sec", None)
    if max_runtime_sec is None or max_runtime_sec > 0:
        return True
    print("--max-runtime-sec must be greater than 0")
    return False


def _verify_status_allows_success(status: str) -> bool:
    return status in {"passed", "policy_denied"}


def _filter_queue_items(
    items: list[StoredPlanItem],
    statuses: tuple[str, ...],
) -> list[StoredPlanItem]:
    if not statuses:
        return items
    allowed = set(statuses)
    return [item for item in items if item.status in allowed]


def _format_problem_summary(
    items: list[StoredPlanItem],
    *,
    limit: int | None = None,
) -> str | None:
    """Return a read-only summary of blocked and in-progress items by reason.

    Groups items whose status is ``blocked`` or ``in_progress`` by their
    blocked reason (``(no reason)`` when none is recorded) and shows the
    count plus the latest affected queue item ids, ordered by most recent
    update.  Returns ``None`` when there are no affected items.
    """
    affected = [item for item in items if item.status in {"blocked", "in_progress"}]
    if not affected:
        return None

    groups: dict[tuple[str, str], list[StoredPlanItem]] = {}
    for item in affected:
        reason = item.blocked_reason if item.blocked_reason else "(no reason)"
        groups.setdefault((item.status, reason), []).append(item)

    lines = ["Problem summary:"]
    status_order = {status: index for index, status in enumerate(_QUEUE_STATUSES)}
    for (status, reason), group in sorted(
        groups.items(),
        key=lambda kv: (status_order.get(kv[0][0], 99), kv[0][1].lower()),
    ):
        latest = sorted(
            group,
            key=lambda item: (item.updated_at, item.plan_item_id),
            reverse=True,
        )
        if limit:
            latest = latest[:limit]
        ids = ", ".join(str(item.plan_item_id) for item in latest)
        lines.append(f"  {status} ({reason}): count={len(group)} latest=[{ids}]")
    return "\n".join(lines)


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


def _format_evaluation_summary(summary: Any) -> str:
    lines = [
        f"{summary.suite.title()} evaluation",
        f"  total: {summary.total}",
        f"  executed: {summary.executed_count}",
        f"  passed: {summary.passed}",
        f"  pass_rate: {summary.pass_rate:.1%}",
        (
            "  recovery: "
            f"passed={summary.recovery_passed} "
            f"total={summary.recovery_total} "
            f"rate={summary.recovery_rate:.1%}"
        ),
        f"  blocked_count: {summary.blocked_count}",
        f"  unsafe_action_count: {summary.unsafe_action_count}",
        f"  chaos_scenarios: {summary.chaos_count}",
        f"  security_red_team_scenarios: {summary.security_red_team_count}",
    ]
    for result in summary.results:
        status = "pass" if result.passed else "fail"
        lines.append(
            "  "
            f"- {result.task_id}: {status} "
            f"expected={result.expected_status} actual={result.actual_status} "
            f"run_id={result.run_id or 'none'}"
        )
    return "\n".join(lines) + "\n"


def _build_supervisor(
    state_store: StateStore,
    config: ProjectConfig,
    progress_callback: Callable[[str], None] | None = None,
) -> Supervisor:
    policy_engine = _policy_engine(config)
    return Supervisor(
        agent=_select_agent(config, policy_engine),
        verifier=VerificationRunner(policy_engine=policy_engine),
        verification_commands=config.verification_commands,
        state_store=state_store,
        max_iterations=config.max_iterations,
        max_no_change_iterations=config.max_no_change_iterations,
        max_runtime_sec=config.max_runtime_sec,
        progress_callback=progress_callback,
        memory_lesson_limit=config.memory.max_lessons,
    )


def _print_run_preamble(
    *,
    action: str,
    repo: Path,
    config: ProjectConfig,
    supervisor: Supervisor,
    task_id: str | None = None,
) -> None:
    agent = supervisor.agent
    check_names = ", ".join(command.name for command in config.verification_commands)
    print("=== ai-orch run ===")
    if task_id:
        print(f"task_id: {task_id}")
    print(f"action: {action}")
    print(f"repo: {repo}")
    print(f"agent: {agent.name}")
    print(f"verification: {check_names or 'none'}")
    print("status: running")
    if agent.name == "mock":
        print(
            "note: mock agent is smoke-test mode; it verifies the orchestration loop "
            "but does not perform real AI work."
        )
    print("", flush=True)


def _print_supervisor_result(
    result: SupervisorResult,
    *,
    repo: Path,
    store: StateStore | None = None,
    report_path: Path | None = None,
) -> None:
    task_prefix = f"{result.task_id}: " if result.task_id else ""
    print(f"{task_prefix}{result.summary}")
    print("")
    print("Run summary:")
    print(f"  task_id: {result.task_id or 'none'}")
    print(f"result: {result.status}")
    if result.task_id and store is not None:
        files_changed = _files_changed_for_task(store, result.task_id)
        verification_status = _verification_status_for_task(store, result.task_id)
        if files_changed:
            print(f"  files_changed: {', '.join(files_changed)}")
        else:
            print("  files_changed: none")
        print(f"  verification: {verification_status}")
    if report_path is not None:
        print(f"  report: {report_path}")
    if result.task_id:
        print("next commands:")
        print(f"  ai-orch status {result.task_id} --repo {repo}")
        print(f"  ai-orch report {result.task_id} --repo {repo}")
        print(f"  ai-orch timeline {result.task_id} --repo {repo}")


def _files_changed_for_task(store: StateStore, task_id: str) -> list[str]:
    seen: set[str] = set()
    files: list[str] = []
    for iteration in store.list_iteration_details(task_id):
        for path in iteration.files_changed:
            if path not in seen:
                seen.add(path)
                files.append(path)
    return files


def _verification_status_for_task(store: StateStore, task_id: str) -> str:
    runs = store.list_verification_details(task_id)
    if not runs:
        return "not_run"
    if all(run.status == "passed" for run in runs):
        return "passed"
    if any(run.status == "failed" for run in runs):
        return "failed"
    return ", ".join(sorted({run.status for run in runs}))


def _run_supervisor_start(
    *,
    repo: Path,
    task: str,
    worktree: str | None = None,
    use_memory: bool = False,
    memory_area: str = "supervisor",
    action: str = "start",
    write_report: bool = False,
    require_verification: bool = False,
) -> SupervisorResult | None:
    config_path = repo / ".ai-orch" / "config.yaml"
    if not config_path.exists():
        print(f"Config not found: {config_path}")
        print("Next command: ai-orch setup --repo .")
        print("For a safe first result, run: ai-orch demo")
        return None
    config = load_project_config(repo)
    if require_verification and not config.verification_commands:
        print("No verification commands configured.")
        print("Next command: ai-orch setup --repo . --force")
        return None
    execution_repo = _autopilot_execution_repo(repo, worktree)
    if worktree:
        worktree_error = _validate_autopilot_worktree(repo, execution_repo)
        if worktree_error is not None:
            print(f"Execution blocked: {worktree_error}")
            return None
    planning_context = None
    if use_memory:
        memory_context = _load_memory_planning_context(
            config=config,
            repo=repo,
            area=memory_area,
        )
        if memory_context.status != "passed":
            print(f"memory context: {memory_context.status}")
            if memory_context.error:
                print(f"error: {memory_context.error}")
            return None
        planning_context = memory_context.stdout
    try:
        store = _state_store_for_repo(repo)
        supervisor = _build_supervisor(
            state_store=store,
            config=config,
            progress_callback=_print_progress,
        )
    except ValueError as exc:
        print(str(exc))
        print("Next command: ai-orch doctor agents --repo .")
        return None
    _print_run_preamble(
        action=action,
        repo=execution_repo,
        config=config,
        supervisor=supervisor,
    )
    result = supervisor.run_once(
        task=task,
        repo=execution_repo,
        planning_context=planning_context,
    )
    report_path = None
    if write_report and result.task_id:
        report_path = _write_task_report(store, execution_repo, result.task_id)
    _print_supervisor_result(
        result,
        repo=execution_repo,
        store=store,
        report_path=report_path,
    )
    return result


def _run_demo_command(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    config_path = repo / ".ai-orch" / "config.yaml"
    if not config_path.exists():
        print(f"Demo config not found: {config_path}")
        print("Use the bundled example or run setup for your own repository first.")
        return 1

    print("=== ai-orch demo ===")
    print(f"repo: {repo}")
    print("mode: mock demo")
    print("This path does not require external AI credentials.")
    result = _run_supervisor_start(
        repo=repo,
        task=args.task,
        action="demo",
        write_report=True,
    )
    if result is None:
        return 1

    print("")
    print("Demo summary:")
    print("- mode: mock demo")
    print(f"- task_id: {result.task_id or 'none'}")
    print(f"- result: {result.status}")
    print(f"- verification: {'passed' if result.status == 'done' else 'not passed'}")
    print("Next real-worker path:")
    print("1. Install and log in to Codex CLI or another supported worker.")
    print("2. Run: ai-orch setup --profile codex-safe --agent codex --force")
    print("3. Run: ai-orch doctor agents --repo .")
    return 0 if result.status == "done" else 1


def _run_product_command(args: argparse.Namespace) -> int:
    repo = Path(args.repo)
    task = _product_task_from_args(args)
    result = _run_supervisor_start(
        repo=repo,
        task=task,
        worktree=args.worktree,
        action=args.command,
        write_report=True,
        require_verification=True,
    )
    if result is None:
        return 1
    return 0 if result.status == "done" else 1


def _product_task_from_args(args: argparse.Namespace) -> str:
    explicit = args.task or " ".join(args.prompt).strip()
    if not explicit:
        explicit = _PRODUCT_COMMAND_DEFAULT_TASKS[args.command]
    role_name = _BEGINNER_ROLES[args.role]
    scenario = args.command
    return (
        f"Role: {role_name}.\n"
        f"Scenario: {scenario}.\n"
        "Work in small steps, keep changes scoped, and rely on verification as "
        "the source of truth.\n"
        f"User request: {explicit}"
    )


def _run_onboard_command(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    payload = _onboard_payload(repo)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    print("=== ai-orch onboard ===")
    print(f"repo: {repo}")
    print("System checks:")
    checks = cast(list[dict[str, object]], payload["checks"])
    for check in checks:
        marker = "ok" if check["ok"] else "needs attention"
        print(f"- {check['name']}: {marker} - {check['detail']}")
    print("")
    print("Worker CLIs:")
    detected_agents = cast(dict[str, str | None], payload["detected_agents"])
    for name, value in detected_agents.items():
        print(f"- {name}: {value or 'not found'}")
    print("")
    print("Recommended path:")
    recommended_steps = cast(list[str], payload["recommended_steps"])
    for index, step in enumerate(recommended_steps, start=1):
        print(f"{index}. {step}")
    print("")
    print("Scenarios:")
    scenarios = cast(list[dict[str, str]], payload["scenarios"])
    for scenario in scenarios:
        print(f"- {scenario['name']}: {scenario['command']}")
    return 0


def _onboard_payload(repo: Path) -> dict[str, object]:
    config_path = repo / ".ai-orch" / "config.yaml"
    state_dir = repo / ".ai-orch" / "state"
    reports_dir = repo / ".ai-orch" / "reports"
    detected = _detect_agent_commands()
    config_exists = config_path.exists()
    config = load_project_config(repo)
    default_available = _agent_availability(config, config.default_agent)
    checks = [
        {
            "name": "config",
            "ok": config_exists,
            "detail": "found" if config_exists else "missing; run ai-orch setup --repo .",
        },
        {
            "name": "state_dir",
            "ok": state_dir.exists(),
            "detail": "found" if state_dir.exists() else "missing; setup creates it",
        },
        {
            "name": "reports_dir",
            "ok": reports_dir.exists(),
            "detail": "found" if reports_dir.exists() else "missing; setup creates it",
        },
        {
            "name": "selected_worker",
            "ok": default_available == "yes",
            "detail": f"{config.default_agent} availability={default_available}",
        },
        {
            "name": "verification",
            "ok": bool(config.verification_commands),
            "detail": (
                f"{len(config.verification_commands)} command(s)"
                if config.verification_commands
                else "missing; run setup or edit config"
            ),
        },
    ]
    recommended_steps = _onboard_recommended_steps(config, config_exists, default_available)
    scenarios = [
        {"name": "Fix a bug", "command": 'ai-orch fix --task "Describe the bug"'},
        {"name": "Build a feature", "command": 'ai-orch task --task "Describe the feature"'},
        {"name": "Analyze project", "command": "ai-orch analyze"},
        {"name": "Review code", "command": "ai-orch review"},
        {"name": "Write docs", "command": 'ai-orch docs --task "Document setup"'},
    ]
    return {
        "repo": str(repo),
        "config_path": str(config_path),
        "config_exists": config_exists,
        "mode": "mock demo" if config.default_agent == "mock" else "real worker",
        "default_agent": config.default_agent,
        "default_agent_available": default_available,
        "detected_agents": detected,
        "checks": checks,
        "recommended_steps": recommended_steps,
        "scenarios": scenarios,
        "ready": all(check["ok"] for check in checks),
    }


def _onboard_recommended_steps(
    config: ProjectConfig,
    config_exists: bool,
    default_available: str,
) -> list[str]:
    if not config_exists:
        return [
            "Run: ai-orch setup --profile codex-safe --agent auto",
            "Run: ai-orch doctor agents --repo .",
            "Run: ai-orch demo",
        ]
    if config.default_agent == "mock":
        return [
            "Run: ai-orch demo",
            "Install and log in to Codex CLI for real-worker mode.",
            "Run: ai-orch setup --profile codex-safe --agent codex --force",
        ]
    if default_available != "yes":
        return [
            f"Install or fix the {config.default_agent} CLI.",
            "Run that worker's native login/status command.",
            "Run: ai-orch doctor agents --repo .",
        ]
    return [
        "Run: ai-orch fix --task \"Describe the bug\"",
        "Run: ai-orch task --task \"Describe the feature\"",
        "Run: ai-orch report TASK_ID --repo .",
    ]


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


def _run_setup_command(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    ai_orch_dir = repo / ".ai-orch"
    config_path = ai_orch_dir / "config.yaml"
    detected = _detect_agent_commands()
    default_agent = _select_setup_default_agent(args.agent, detected, args.profile)
    config_text = _render_setup_config(default_agent, detected, args.profile)
    readiness = _setup_readiness_summary(default_agent, detected, args.profile)
    payload = {
        "repo": str(repo),
        "config_path": str(config_path),
        "profile": args.profile,
        "default_agent": default_agent,
        "detected_agents": detected,
        "readiness": readiness,
        "dry_run": bool(args.dry_run),
        "written": False,
    }

    if config_path.exists() and not args.force and not args.dry_run:
        payload["error"] = "config_exists"
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(f"Config already exists: {config_path}")
            print("Use --force to overwrite it, or --dry-run to preview the generated config.")
        return 1

    if not args.dry_run:
        (ai_orch_dir / "state").mkdir(parents=True, exist_ok=True)
        (ai_orch_dir / "reports").mkdir(parents=True, exist_ok=True)
        config_path.write_text(config_text, encoding="utf-8")
        payload["written"] = True

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    action = "Would write" if args.dry_run else "Wrote"
    print(f"{action}: {config_path}")
    print(f"profile: {args.profile}")
    print(f"default_agent: {default_agent}")
    print("Detected CLI agents:")
    for name in ["codex", "claude", "kimi", "gemini"]:
        print(f"- {name}: {detected.get(name) or 'not found'}")
    print("Readiness:")
    for key, value in readiness.items():
        print(f"- {key}: {value}")
    print("Next steps:")
    print("1. Run: ai-orch doctor --repo .")
    print("2. Run: ai-orch demo")
    print("3. If a real worker is selected, run that CLI's native login command.")
    print('4. Try: ai-orch start --repo . --task "Check setup"')
    return 0


def _run_doctor_command(args: argparse.Namespace) -> int:
    if args.doctor_command == "agents":
        return _run_doctor_agents_command(args)

    repo = Path(args.repo).resolve()
    config_path = repo / ".ai-orch" / "config.yaml"
    state_dir = repo / ".ai-orch" / "state"
    reports_dir = repo / ".ai-orch" / "reports"
    config = load_project_config(repo)
    config_exists = config_path.exists()
    agents = [
        {
            "name": agent.name,
            "type": agent.type,
            "enabled": agent.enabled,
            "command": _agent_config_value(agent, "command"),
            "available": _agent_availability(config, agent.name),
            "default": agent.name == config.default_agent,
        }
        for agent in config.agents.values()
    ]
    default_available = _agent_availability(config, config.default_agent)
    readiness = _doctor_readiness_summary(config, default_available)
    issues: list[str] = []
    warnings: list[str] = []
    if not config_exists:
        issues.append("missing_config")
    if config.default_agent not in config.agents:
        issues.append("default_agent_missing")
    elif not config.agents[config.default_agent].enabled:
        issues.append("default_agent_disabled")
    elif default_available != "yes":
        issues.append("default_agent_unavailable")
    if not config.verification_commands:
        issues.append("no_verification_commands")
    if not state_dir.exists():
        warnings.append("missing_state_dir")
    if not reports_dir.exists():
        warnings.append("missing_reports_dir")

    payload = {
        "repo": str(repo),
        "config_path": str(config_path),
        "config_exists": config_exists,
        "state_dir_exists": state_dir.exists(),
        "reports_dir_exists": reports_dir.exists(),
        "default_agent": config.default_agent,
        "default_agent_available": default_available,
        "readiness": readiness,
        "agents": agents,
        "verification_commands": [
            {"name": command.name, "timeout_sec": command.timeout_sec}
            for command in config.verification_commands
        ],
        "issues": issues,
        "warnings": warnings,
        "ready": not issues,
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if not issues else 1

    print("=== ai-orch doctor ===")
    print(f"repo: {repo}")
    print(f"config: {'found' if config_exists else 'missing'} ({config_path})")
    print(f"state_dir: {'ok' if state_dir.exists() else 'missing'}")
    print(f"reports_dir: {'ok' if reports_dir.exists() else 'missing'}")
    print(f"default_agent: {config.default_agent} available={default_available}")
    print("readiness:")
    for key, value in readiness.items():
        print(f"- {key}: {value}")
    print("agents:")
    for agent in agents:
        marker = " default" if agent["default"] else ""
        print(
            f"- {agent['name']}: enabled={agent['enabled']} "
            f"type={agent['type']} available={agent['available']}{marker}"
        )
    print(f"verification_commands: {len(config.verification_commands)}")
    for command in config.verification_commands:
        print(f"- {command.name}: timeout={command.timeout_sec}")
    if warnings:
        print("warnings:")
        for warning in warnings:
            print(f"- {warning}")
    if issues:
        print("issues:")
        for issue in issues:
            print(f"- {issue}")
        print("Suggested fix: run ai-orch setup --repo .")
        return 1
    print("ready: yes")
    return 0


def _run_doctor_agents_command(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    config_path = repo / ".ai-orch" / "config.yaml"
    config_exists = config_path.exists()
    config = load_project_config(repo)
    rows = _doctor_agent_rows(config)
    default_row = next(
        (row for row in rows if row["name"] == config.default_agent),
        None,
    )
    issues: list[str] = []
    if not config_exists:
        issues.append("missing_config")
    if default_row is None:
        issues.append("default_agent_missing")
    elif default_row["availability"] != "yes":
        issues.append("default_agent_unavailable")

    payload = {
        "repo": str(repo),
        "config_path": str(config_path),
        "config_exists": config_exists,
        "default_agent": config.default_agent,
        "fallback_agents": config.fallback_agents,
        "connectors": rows,
        "readiness": _doctor_agents_readiness(rows, config.default_agent),
        "api_adapters": {
            "status": "not_implemented",
            "guidance": (
                "Use provider CLIs or a generic wrapper with externally managed "
                "environment credentials."
            ),
        },
        "issues": issues,
        "ready": not issues,
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if not issues else 1

    print("=== ai-orch doctor agents ===")
    print(f"repo: {repo}")
    print(f"default_agent: {config.default_agent}")
    if config.fallback_agents:
        print(f"fallbacks: {', '.join(config.fallback_agents)}")
    print("connectors:")
    for row in rows:
        markers = []
        if row["default"]:
            markers.append("default")
        if row["fallback"]:
            markers.append("fallback")
        marker = f" ({', '.join(markers)})" if markers else ""
        print(
            f"- {row['name']}: configured={row['configured']} "
            f"enabled={row['enabled']} type={row['type']} "
            f"command={row['command']} available={row['availability']}{marker}"
        )
        print(f"  auth: {row['auth_model']}")
        print(f"  api: {row['api_status']}")
        print(f"  next: {row['next_step']}")
    print(
        "api_adapters: not_implemented "
        "(use provider CLIs or a generic wrapper with env-managed credentials)"
    )
    if issues:
        print("issues:")
        for issue in issues:
            print(f"- {issue}")
        return 1
    print("ready: yes")
    return 0


def _doctor_agent_rows(config: ProjectConfig) -> list[dict[str, object]]:
    names = list(_KNOWN_AGENT_CONNECTORS)
    for name in config.agents:
        if name not in names:
            names.append(name)

    detected = _detect_agent_commands()
    rows: list[dict[str, object]] = []
    for name in names:
        agent_config = config.agents.get(name)
        connector = _agent_connector_name(name, agent_config)
        configured = agent_config is not None
        enabled = bool(agent_config.enabled) if agent_config else False
        if not configured:
            availability = "not_configured"
        elif not enabled:
            availability = "skipped"
        else:
            availability = _agent_availability(config, name)
        command = _doctor_agent_command(name, connector, agent_config)
        rows.append(
            {
                "name": name,
                "connector": connector,
                "type": (
                    agent_config.type
                    if agent_config
                    else _AGENT_DEFAULT_TYPES.get(connector, "generic_cli")
                ),
                "configured": configured,
                "enabled": enabled,
                "command": command,
                "cli_path": detected.get(connector),
                "availability": availability,
                "auth_model": _agent_auth_model(connector, agent_config),
                "api_status": _agent_api_status(connector),
                "next_step": _agent_next_step(connector, configured, enabled, availability),
                "default": name == config.default_agent,
                "fallback": name in config.fallback_agents,
            }
        )
    return rows


def _agent_next_step(
    connector: str,
    configured: bool,
    enabled: bool,
    availability: str,
) -> str:
    if not configured:
        return "run setup with this worker or keep it as an optional connector"
    if not enabled:
        return "enable in .ai-orch/config.yaml when you want to use it"
    if connector == "mock":
        return "ready for smoke tests and demos; no login required"
    if availability == "yes":
        return "CLI found; run the worker's native login/status command if tasks fail auth"
    return "install the CLI and complete its native login outside ai-orch"


def _agent_connector_name(name: str, agent_config: AgentConfig | None) -> str:
    if agent_config is None:
        return name
    if agent_config.type == "mock":
        return "mock"
    if agent_config.type == "generic_cli":
        return "generic"
    if agent_config.type == "codex_exec":
        return "codex"
    if agent_config.type in {"claude", "claude_headless"}:
        return "claude"
    if agent_config.type in {"gemini", "gemini_cli"}:
        return "gemini"
    if agent_config.type in {"kimi", "kimi_cli"}:
        return "kimi"
    return name


def _doctor_agent_command(
    name: str,
    connector: str,
    agent_config: AgentConfig | None,
) -> str:
    if agent_config is not None and agent_config.command:
        return agent_config.command
    return _AGENT_DEFAULT_COMMANDS.get(connector, _AGENT_DEFAULT_COMMANDS["generic"])


def _agent_auth_model(connector: str, agent_config: AgentConfig | None) -> str:
    if connector == "mock":
        return "none; smoke-test adapter"
    if connector in _CLI_AUTH_CONNECTORS:
        return "native CLI login or CLI-managed provider credentials"
    if agent_config and agent_config.env:
        return "external environment variables supplied by wrapper process"
    return "external wrapper/environment; no secrets stored by ai-orch"


def _agent_api_status(connector: str) -> str:
    if connector == "mock":
        return "not_applicable"
    return "not_implemented; use CLI adapter or generic wrapper"


def _detect_agent_commands() -> dict[str, str | None]:
    return {
        "codex": shutil.which("codex"),
        "claude": shutil.which("claude"),
        "kimi": shutil.which("kimi"),
        "gemini": shutil.which("gemini"),
    }


def _select_setup_default_agent(
    requested: str,
    detected: dict[str, str | None],
    profile: str = "python-project",
) -> str:
    if requested != "auto":
        return requested
    if profile == "codex-safe":
        return "codex" if detected.get("codex") else "mock"
    for name in ["codex", "claude", "kimi", "gemini"]:
        if detected.get(name):
            return name
    return "mock"


def _render_setup_config(
    default_agent: str,
    detected: dict[str, str | None],
    profile: str = "python-project",
) -> str:
    fallback_agents = [
        name
        for name in ["codex", "claude", "kimi", "gemini", "mock"]
        if name != default_agent
    ]
    lines = [
        "project:",
        '  name: "ai-orchestrator-project"',
        '  repo: "."',
        f'  setup_profile: "{profile}"',
        "",
        "orchestrator:",
        f'  default_agent: "{default_agent}"',
        "  fallback_agents:",
        *[f'    - "{name}"' for name in fallback_agents],
        "  max_iterations: 4",
        "  max_no_change_iterations: 2",
        "  max_runtime_sec: 1800",
        "",
        "agents:",
        "  mock:",
        "    enabled: true",
        '    type: "mock"',
        "",
        "  codex:",
        f'    enabled: {_yaml_bool(default_agent == "codex" or bool(detected.get("codex")))}',
        '    type: "codex_exec"',
        '    command: "codex"',
        "    args:",
        '      - "exec"',
        '      - "--json"',
        '      - "--sandbox"',
        '      - "workspace-write"',
        '      - "{prompt}"',
        "    timeout_sec: 1800",
        "",
        "  claude:",
        f'    enabled: {_yaml_bool(default_agent == "claude" or bool(detected.get("claude")))}',
        '    type: "claude_headless"',
        '    command: "claude"',
        "    args:",
        '      - "-p"',
        '      - "{prompt}"',
        '      - "--output-format"',
        '      - "json"',
        "    timeout_sec: 1800",
        "",
        "  kimi:",
        f'    enabled: {_yaml_bool(default_agent == "kimi" or bool(detected.get("kimi")))}',
        '    type: "kimi_cli"',
        '    command: "kimi"',
        "    args:",
        '      - "{prompt}"',
        "    timeout_sec: 1800",
        "",
        "  gemini:",
        f'    enabled: {_yaml_bool(default_agent == "gemini" or bool(detected.get("gemini")))}',
        '    type: "gemini_cli"',
        '    command: "gemini"',
        "    args:",
        '      - "-p"',
        '      - "{prompt}"',
        "    timeout_sec: 1800",
        "",
        "verification:",
        "  strict: true",
        "  commands:",
        *_verification_profile_lines(profile),
        "",
        "policy:",
        "  deny:",
        '    - "rm -rf /"',
        '    - "cat ~/.ssh"',
        '    - "cat ~/.codex/auth.json"',
        "  require_approval:",
        '    - "git push"',
        '    - "rm -rf"',
        '    - "pip install"',
        '    - "npm install"',
        "",
        "memory:",
        '  provider: "codebase-memory-mcp"',
        "  command:",
        '    - "codebase-memory-mcp"',
        '    - "cli"',
        '  project: ""',
        "  timeout_sec: 120",
        "  max_lessons: 5",
        "",
    ]
    return "\n".join(lines)


def _verification_profile_lines(profile: str) -> list[str]:
    profiles = {
        "codex-safe": [
            ('compile', "python -m compileall ai_orchestrator", 120),
            ('tests', "python -m pytest", 300),
        ],
        "python-project": [
            ('compile', "python -m compileall .", 120),
            ('tests', "python -m pytest", 300),
        ],
        "node-project": [
            ('npm-test', "npm test", 300),
        ],
        "docs-project": [
            (
                'readme-has-heading',
                "python -c \"import re, sys; txt=open('README.md', encoding='utf-8').read(); sys.exit(0 if re.search(r'^# ', txt, re.MULTILINE) else 1)\"",
                30,
            ),
        ],
        "readonly-review": [
            ('diff-check', "git diff --check", 60),
        ],
    }
    commands = profiles.get(profile, profiles["python-project"])
    lines: list[str] = []
    for name, command, timeout in commands:
        lines.extend(
            [
                f'    - name: "{name}"',
                f'      run: "{command}"',
                f"      timeout_sec: {timeout}",
            ]
        )
    return lines


def _setup_readiness_summary(
    default_agent: str,
    detected: dict[str, str | None],
    profile: str,
) -> dict[str, str]:
    worker_ready = default_agent == "mock" or bool(detected.get(default_agent))
    mode = "mock demo" if default_agent == "mock" else "real worker"
    auth = (
        "not required"
        if default_agent == "mock"
        else f"run {default_agent} native login/status outside ai-orch"
    )
    return {
        "installed": "config preview" if not detected else "local CLI scan complete",
        "profile": profile,
        "mode": mode,
        "real_worker_ready": "yes" if worker_ready and default_agent != "mock" else "no",
        "mock_demo_mode": "yes" if default_agent == "mock" else "no",
        "worker_auth": auth,
        "verification_configured": "yes",
    }


def _doctor_readiness_summary(
    config: ProjectConfig,
    default_available: str,
) -> dict[str, str]:
    mode = "mock demo" if config.default_agent == "mock" else "real worker"
    return {
        "installed": "yes",
        "selected_worker": config.default_agent,
        "mode": mode,
        "real_worker_ready": (
            "yes" if config.default_agent != "mock" and default_available == "yes" else "no"
        ),
        "mock_demo_mode": "yes" if config.default_agent == "mock" else "no",
        "worker_auth": (
            "not required"
            if config.default_agent == "mock"
            else "managed by the selected worker CLI outside ai-orch"
        ),
        "verification_configured": "yes" if config.verification_commands else "no",
    }


def _doctor_agents_readiness(
    rows: list[dict[str, object]],
    default_agent: str,
) -> dict[str, str]:
    default_row = next((row for row in rows if row["name"] == default_agent), None)
    if default_row is None:
        return {"selected_worker": default_agent, "status": "missing"}
    mode = "mock demo" if default_agent == "mock" else "real worker"
    return {
        "selected_worker": default_agent,
        "mode": mode,
        "availability": str(default_row["availability"]),
        "next_step": str(default_row["next_step"]),
    }


def _yaml_bool(value: bool) -> str:
    return "true" if value else "false"


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


def _run_ci_command(args: argparse.Namespace) -> int:
    """Run verification and release checks for CI environments.

    Returns 0 when every check passes, 1 when any verification or release
    check fails or requires approval. Output is grouped and parseable.
    """
    repo = Path(args.repo)
    config = load_project_config(repo)
    exit_code = 0

    print("verification:")
    if not config.verification_commands:
        print("  (none configured)")
    else:
        runner = _verification_runner(config, approved_commands=set(args.approve_command))
        verification_results = runner.run_many(config.verification_commands, cwd=repo)
        for item in verification_results:
            print(f"  {item.name}: {item.status} exit={item.exit_code}")
            if item.status != "passed":
                exit_code = 1

    print("release:")
    release_results = run_release_checks(repo)
    for release_item in release_results:
        print(f"  {release_item.name}: {release_item.status} - {release_item.detail}")
        if release_item.status != "passed":
            exit_code = 1

    return exit_code


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

    if approval.source == "tool_broker":
        return _retry_tool_broker_approval_request(store, approval, task)

    repo = Path(task.repo_path)
    config = load_project_config(repo)
    broker = ToolBroker(store, _policy_engine(config))
    call = make_process_tool_call(
        "process.approval_retry",
        "write",
        command=approval.command_string,
        task_id=approval.task_id,
        idempotency_key=(
            f"approval:{approval.approval_id}:retry:"
            f"{approval.command_string}"
        ),
    )
    runner = _verification_runner(config, approved_commands={approval.command_string})
    result = broker.run_approved(
        call,
        lambda _call: _approval_retry_tool_result(
            call,
            runner.run(
                VerificationCommand(
                    name=f"approval-{approval.approval_id}",
                    run=approval.command_string,
                ),
                cwd=repo,
            ),
        ),
        approval_id=approval.approval_id,
    )
    retry_status = _tool_retry_status(result)
    exit_code = _tool_retry_exit_code(result)
    updated_approval = store.record_approval_retry(
        approval_id=approval.approval_id,
        status=retry_status,
        exit_code=exit_code,
        error=result.error or _tool_retry_stderr(result),
    )
    print(f"retry: {retry_status} exit={exit_code}")
    if updated_approval is not None:
        print(
            "retry history: "
            f"count={updated_approval.retry_count} "
            f"last_status={updated_approval.last_retry_status} "
            f"last_exit={updated_approval.last_retry_exit_code}"
        )
    if result.error:
        print(f"error: {result.error}")
    stdout = _tool_retry_stdout(result)
    stderr = _tool_retry_stderr(result)
    if stdout:
        print(stdout, end="" if stdout.endswith("\n") else "\n")
    if stderr:
        print(stderr, end="" if stderr.endswith("\n") else "\n")
    return 0 if retry_status == "passed" else 1


def _approval_retry_tool_result(
    call: ToolCall,
    result: VerificationResult,
) -> ToolResult:
    status: ToolResultStatus
    if result.status == "passed":
        status = "succeeded"
    elif result.status in {"policy_denied", "needs_approval"}:
        status = cast(ToolResultStatus, result.status)
    else:
        status = "failed"

    return ToolResult(
        call=call,
        status=status,
        output={
            "verification_status": result.status,
            "exit_code": result.exit_code,
            "stdout": result.stdout,
            "stderr": result.stderr,
        },
        error=result.error or (result.stderr if result.status != "passed" else None),
    )


def _retry_tool_broker_approval_request(
    store: StateStore,
    approval: StoredApprovalRequest,
    task: StoredTask,
) -> int:
    action = _find_tool_broker_action_for_approval(store, approval)
    if action is None:
        print(f"Tool action not found for approval request: {approval.approval_id}")
        return 1

    call = _tool_call_from_action(action)
    if call is None:
        print(f"Tool action payload is invalid for approval request: {approval.approval_id}")
        return 1

    repo = Path(task.repo_path)
    config = load_project_config(repo)
    broker = ToolBroker(store, _policy_engine(config))
    registry = _tool_executor_registry(repo, config=config, approved_call=call)
    executor = registry.get(call.spec.name)
    if executor is None:
        print(f"No executor registered for tool: {call.spec.name}")
        return 1

    result = broker.run_approved(
        call,
        executor,
        approval_id=approval.approval_id,
    )
    retry_status = _tool_retry_status(result)
    exit_code = _tool_retry_exit_code(result)
    updated_approval = store.record_approval_retry(
        approval_id=approval.approval_id,
        status=retry_status,
        exit_code=exit_code,
        error=result.error or _tool_retry_stderr(result),
    )
    print(f"retry: {retry_status} exit={exit_code}")
    if updated_approval is not None:
        print(
            "retry history: "
            f"count={updated_approval.retry_count} "
            f"last_status={updated_approval.last_retry_status} "
            f"last_exit={updated_approval.last_retry_exit_code}"
        )
    if result.error:
        print(f"error: {result.error}")
    stdout = _tool_retry_stdout(result)
    stderr = _tool_retry_stderr(result)
    if stdout:
        print(stdout, end="" if stdout.endswith("\n") else "\n")
    if stderr:
        print(stderr, end="" if stderr.endswith("\n") else "\n")
    return 0 if retry_status == "passed" else 1


def _tool_executor_registry(
    repo: Path,
    *,
    config: ProjectConfig | None = None,
    approved_call: ToolCall | None = None,
) -> ToolExecutorRegistry:
    registry = (
        ToolExecutorRegistry()
        .register_prefix("process.", process_tool_executor(repo))
        .register_prefix("fs.", file_tool_executor(repo))
    )
    if config is None:
        return registry

    approved_commands: set[str] = set()
    command_client = _memory_client(config)
    if approved_call is not None:
        approved_commands.update(
            approved_memory_commands_for_call(command_client, approved_call)
        )
    memory_client = _memory_client(config, approved_commands=approved_commands)
    return (
        registry.register_prefix("memory.", memory_tool_executor(memory_client, cwd=repo))
    )


def _find_tool_broker_action_for_approval(
    store: StateStore,
    approval: StoredApprovalRequest,
) -> StoredActionRecord | None:
    actions = store.list_action_records(
        approval.task_id,
        iteration_id=approval.iteration_id,
    )
    for action in actions:
        if _approval_id_from_action_result(action) == approval.approval_id:
            return action
    return None


def _approval_id_from_action_result(action: StoredActionRecord) -> int | None:
    output = action.result.get("output")
    if not isinstance(output, dict):
        return None
    approval_id = output.get("approval_id")
    if isinstance(approval_id, int):
        return approval_id
    return None


def _tool_call_from_action(action: StoredActionRecord) -> ToolCall | None:
    tool_name = action.payload.get("tool_name")
    risk_tier = action.payload.get("risk_tier")
    arguments = action.payload.get("arguments")
    if not isinstance(tool_name, str):
        return None
    if not isinstance(risk_tier, str) or risk_tier not in TOOL_RISK_TIERS:
        return None
    if not isinstance(arguments, dict):
        return None
    if not all(isinstance(key, str) for key in arguments):
        return None

    return make_tool_call(
        tool_name=tool_name,
        risk_tier=cast(ToolRiskTier, risk_tier),
        action_type=action.action_type,
        idempotency_key=action.idempotency_key,
        arguments=cast(dict[str, object], arguments),
        task_id=action.task_id,
        iteration_id=action.iteration_id,
    )


def _tool_retry_status(result: ToolResult) -> str:
    if result.status == "succeeded":
        return "passed"
    return result.status


def _tool_retry_output(result: ToolResult) -> dict[str, object]:
    output = result.output.get("tool_output")
    if isinstance(output, dict):
        return output
    return {}


def _tool_retry_exit_code(result: ToolResult) -> int | None:
    exit_code = _tool_retry_output(result).get("exit_code")
    if isinstance(exit_code, int) and not isinstance(exit_code, bool):
        return exit_code
    return None


def _tool_retry_stdout(result: ToolResult) -> str:
    stdout = _tool_retry_output(result).get("stdout")
    if isinstance(stdout, str):
        return stdout
    return ""


def _tool_retry_stderr(result: ToolResult) -> str:
    stderr = _tool_retry_output(result).get("stderr")
    if isinstance(stderr, str):
        return stderr
    return ""


def _run_autopilot_command(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    if args.autopilot_command is None:
        parser.print_help()
        return 1

    repo = Path(args.repo)
    if args.autopilot_command == "plan":
        return _run_autopilot_plan_command(args, parser)

    if args.autopilot_command == "queue":
        return _run_autopilot_queue_command(args, parser)

    if args.autopilot_command == "worktree-overview":
        return _run_autopilot_worktree_overview(args)

    plan_path = _resolve_plan_path(repo, Path(args.plan))
    if args.autopilot_command == "loop-history":
        store = _state_store_for_repo(repo)
        return _run_autopilot_loop_history(args, plan_path, store)

    if not plan_path.exists():
        print(f"Plan not found: {plan_path}")
        return 1

    store = _state_store_for_repo(repo)

    if args.autopilot_command == "loop":
        return _run_autopilot_loop(args, repo, plan_path, store)

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


def _run_autopilot_worktree_overview(args: argparse.Namespace) -> int:
    """Render a read-only overview of git worktrees under a base directory."""
    repo = Path(args.repo)
    base_dir = Path(args.base_dir)
    older_than_days = getattr(args, "older_than_days", None)
    if older_than_days is not None and older_than_days < 1:
        print("--older-than-days must be at least 1")
        return 1
    if not base_dir.is_absolute():
        base_dir = repo / base_dir
    base_dir = base_dir.resolve()

    if not base_dir.exists():
        print(f"Base directory does not exist: {base_dir}")
        return 1
    if not base_dir.is_dir():
        print(f"Base path is not a directory: {base_dir}")
        return 1

    repo_for_link = _git_rev_parse_path(repo, "--show-toplevel")
    overviews = gather_worktree_overviews(base_dir, repo=repo_for_link)
    total_count = len(overviews)
    if args.dirty_only:
        overviews = [overview for overview in overviews if overview.dirty]
    branch_filter = getattr(args, "branch_filter", None)
    if branch_filter:
        overviews = [
            overview for overview in overviews if branch_filter in overview.branch
        ]
    if args.unlinked_only:
        overviews = [overview for overview in overviews if overview.linked is False]
    if args.merged_only:
        overviews = [overview for overview in overviews if overview.merged is True]
    cleanup_status = getattr(args, "cleanup_status", None)
    if cleanup_status:
        overviews = [
            overview for overview in overviews if overview.cleanup_status == cleanup_status
        ]
    if older_than_days is not None:
        cutoff = datetime.now(UTC) - timedelta(days=older_than_days)
        overviews = [
            overview
            for overview in overviews
            if overview.last_modified is not None and overview.last_modified <= cutoff
        ]

    filtered_count = len(overviews)
    limit = getattr(args, "limit", 0)
    if limit > 0:
        overviews = overviews[:limit]

    if args.json:
        print(
            json.dumps(
                worktree_overview_data(
                    overviews,
                    base_dir,
                    repo=repo_for_link,
                    total_count=total_count,
                    filtered_count=filtered_count,
                ),
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0

    if not overviews:
        if branch_filter:
            print(format_worktree_summary(overviews, total_count, filtered_count))
            print(
                f"No git worktrees matching branch filter '{branch_filter}' "
                f"found under {base_dir}"
            )
        elif args.dirty_only:
            print(format_worktree_summary(overviews, total_count, filtered_count))
            print(f"No dirty git worktrees found under {base_dir}")
        elif args.unlinked_only:
            print(format_worktree_summary(overviews, total_count, filtered_count))
            print(f"No unlinked git worktrees found under {base_dir}")
        elif args.merged_only:
            print(format_worktree_summary(overviews, total_count, filtered_count))
            print(f"No merged git worktrees found under {base_dir}")
        elif cleanup_status:
            print(format_worktree_summary(overviews, total_count, filtered_count))
            print(
                f"No git worktrees matching cleanup status '{cleanup_status}' "
                f"found under {base_dir}"
            )
        elif older_than_days is not None:
            print(format_worktree_summary(overviews, total_count, filtered_count))
            print(
                f"No git worktrees older than {older_than_days} days "
                f"found under {base_dir}"
            )
        return 0
    print(
        format_worktree_overview(
            overviews,
            base_dir,
            repo=repo_for_link,
            total_count=total_count,
            filtered_count=filtered_count,
        )
    )
    return 0


def _run_autopilot_loop_history(
    args: argparse.Namespace,
    plan_path: Path,
    store: StateStore,
) -> int:
    if args.limit < 0:
        print("--limit cannot be negative")
        return 1
    limit = args.limit if args.limit > 0 else None
    runs = store.list_autopilot_loop_runs(plan_path=plan_path, limit=limit)
    if args.json:
        print(
            json.dumps(
                {
                    "plan": str(plan_path),
                    "count": len(runs),
                    "runs": [asdict(run) for run in runs],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    print(_format_autopilot_loop_history(plan_path, runs), end="")
    return 0


def _format_autopilot_loop_history(
    plan_path: Path,
    runs: list[StoredAutopilotLoopRun],
) -> str:
    lines = [
        "=== Autopilot loop history ===",
        f"plan: {plan_path}",
        f"count: {len(runs)}",
    ]
    if not runs:
        lines.append("No loop runs recorded.")
        return "\n".join(lines) + "\n"
    for run in runs:
        lines.append(
            f"#{run.loop_run_id} mode={run.mode} result={run.result_code} "
            f"selected={run.selected_count} processed={run.processed_count} "
            f"dead_letters={run.dead_letter_count} stop={run.stop_reason}"
        )
    return "\n".join(lines) + "\n"


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

    max_runtime_sec = getattr(args, "max_runtime_sec", None)
    runtime_budget = (
        max_runtime_sec if max_runtime_sec is not None else config.max_runtime_sec
    )
    supervisor = Supervisor(
        agent=agent,
        verifier=VerificationRunner(policy_engine=policy_engine),
        verification_commands=config.verification_commands,
        state_store=store,
        max_iterations=config.max_iterations,
        max_no_change_iterations=config.max_no_change_iterations,
        max_runtime_sec=runtime_budget,
        require_repo_change=True,
        progress_callback=_print_progress,
        memory_lesson_limit=config.memory.max_lessons,
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


def _queue_item_label(item: StoredPlanItem, *, include_plan_path: bool) -> str:
    if include_plan_path:
        return f"{item.plan_path}:{item.line_number}"
    return str(item.line_number)


def _resolve_stored_plan_path(repo: Path, stored_plan_path: Path | str) -> Path:
    plan_path = Path(stored_plan_path)
    if plan_path.is_absolute():
        return plan_path
    return repo / plan_path


def _load_open_queue_tasks(source_path: Path) -> list[AutopilotTask]:
    if source_path.name.lower() == "backlog.md":
        return load_backlog_tasks(source_path)
    return load_plan_tasks(source_path)


def _stale_created_queue_items(
    repo: Path,
    items: list[StoredPlanItem],
) -> list[StoredPlanItem]:
    open_task_keys_by_plan: dict[str, set[tuple[int, str]]] = {}
    stale_items: list[StoredPlanItem] = []
    for item in items:
        if item.status != "created":
            continue
        plan_key = str(item.plan_path)
        if plan_key not in open_task_keys_by_plan:
            source_path = _resolve_stored_plan_path(repo, item.plan_path)
            if source_path.exists():
                open_task_keys_by_plan[plan_key] = {
                    (task.line_number, task.text) for task in _load_open_queue_tasks(source_path)
                }
            else:
                open_task_keys_by_plan[plan_key] = set()
        if (item.line_number, item.text) not in open_task_keys_by_plan[plan_key]:
            stale_items.append(item)
    return stale_items


def _run_autopilot_queue_readiness(
    args: argparse.Namespace,
    repo: Path,
    store: StateStore,
) -> int:
    """Render a read-only preflight readiness summary for the queue.

    Combines overall counts, created readiness, blocked/in-progress risk,
    stale created items (source plan task no longer open), and stale
    in-progress items without mutating stored state.
    """
    include_plan_path = bool(args.all_plans)
    if include_plan_path:
        plan_label = "all persisted plans"
        all_items = store.list_plan_items()
    else:
        plan_path = _resolve_plan_path(repo, Path(args.plan))
        if not plan_path.exists():
            if args.json:
                print(
                    json.dumps(
                        {"error": f"Plan not found: {plan_path}"},
                        indent=2,
                        ensure_ascii=False,
                    )
                )
            else:
                print(f"Plan not found: {plan_path}")
            return 1
        plan_label = str(plan_path)
        all_items = store.list_plan_items(plan_path=plan_path)

    status_counts: dict[str, int] = {}
    for item in all_items:
        status_counts[item.status] = status_counts.get(item.status, 0) + 1

    stale_created = _stale_created_queue_items(repo, all_items)
    stale_in_progress = [item for item in all_items if item.status == "in_progress"]
    created_total = status_counts.get("created", 0)
    created_ready = max(0, created_total - len(stale_created))
    blocked_total = status_counts.get("blocked", 0)
    in_progress_total = status_counts.get("in_progress", 0)

    limit = max(0, args.limit)

    if args.json:
        result = {
            "plan": plan_label,
            "total": len(all_items),
            "by_status": dict(sorted(status_counts.items())),
            "created_readiness": {
                "ready": created_ready,
                "stale": len(stale_created),
            },
            "blocked_in_progress_risk": {
                "blocked": blocked_total,
                "in_progress": in_progress_total,
            },
            "stale_created": {
                "count": len(stale_created),
                "items": [
                    _queue_item_readiness_ref(repo, item)
                    for item in stale_created[:limit]
                ],
            },
            "stale_in_progress": {
                "count": len(stale_in_progress),
                "items": [
                    _queue_item_readiness_ref(repo, item)
                    for item in stale_in_progress[:limit]
                ],
            },
            "problem_summary": _problem_summary_data(
                all_items,
                limit=limit if limit else None,
            ),
        }
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        if args.fail_on_risk and (stale_created or blocked_total or in_progress_total):
            return 2
        return 0

    print(f"Queue readiness for {plan_label}")
    print(f"  total: {len(all_items)}")
    if status_counts:
        summary = ", ".join(
            f"{status}={count}" for status, count in sorted(status_counts.items())
        )
        print("  by status:", summary)
    else:
        print("  No plan items found.")
        return 0

    print("  created readiness:", f"ready={created_ready} stale={len(stale_created)}")
    print(
        "  blocked/in_progress risk:",
        f"blocked={blocked_total} in_progress={in_progress_total}",
    )
    print("  stale created:", len(stale_created))
    print("  stale in_progress:", len(stale_in_progress))

    if stale_created:
        print("  stale created items:")
        for item in stale_created[:limit]:
            refs = _queue_item_refs(repo, item)
            item_label = _queue_item_label(item, include_plan_path=include_plan_path)
            print(f"    id={item.plan_item_id} {item_label}: {item.text}{refs}")
        if len(stale_created) > limit:
            print(f"    ... and {len(stale_created) - limit} more")

    if stale_in_progress:
        print("  stale in_progress items:")
        for item in stale_in_progress[:limit]:
            refs = _queue_item_refs(repo, item)
            item_label = _queue_item_label(item, include_plan_path=include_plan_path)
            print(f"    id={item.plan_item_id} {item_label}: {item.text}{refs}")
        if len(stale_in_progress) > limit:
            print(f"    ... and {len(stale_in_progress) - limit} more")

    problem_summary = _format_problem_summary(
        all_items,
        limit=limit if limit else None,
    )
    if problem_summary:
        print(problem_summary)

    if args.fail_on_risk and (stale_created or blocked_total or in_progress_total):
        return 2

    return 0


def _next_action_for_preflight(
    *,
    agent_available: bool,
    created_ready: int,
    stale_created_count: int,
    in_progress_count: int,
    blocked_count: int,
) -> str:
    """Return a read-only operator hint for the next queue action.

    The hint is ordered by precedence: fix the selected agent first, then
    reconcile stale created items, recover in-progress items, review blocked
    items, run the batch when everything is ready, or report nothing to do.
    """
    if not agent_available:
        return "fix_agent"
    if stale_created_count:
        return "reconcile_stale_created"
    if in_progress_count:
        return "recover_in_progress"
    if blocked_count:
        return "review_blocked"
    if created_ready:
        return "run_batch"
    return "none"


def _queue_preflight_snapshot(
    repo: Path,
    plan_path: Path,
    store: StateStore,
    *,
    limit: int = 5,
) -> dict[str, Any]:
    """Return a read-only preflight snapshot for *plan_path*.

    Combines queue readiness counts with the selected agent profile summary,
    ``preflight_result``, and ``next_action``. The snapshot reflects the
    persisted queue state before any batch selection or execution.
    """
    all_items = store.list_plan_items(plan_path=plan_path)

    status_counts: dict[str, int] = {}
    for item in all_items:
        status_counts[item.status] = status_counts.get(item.status, 0) + 1

    stale_created = _stale_created_queue_items(repo, all_items)
    stale_in_progress = [item for item in all_items if item.status == "in_progress"]
    created_total = status_counts.get("created", 0)
    created_ready = max(0, created_total - len(stale_created))
    blocked_total = status_counts.get("blocked", 0)
    in_progress_total = status_counts.get("in_progress", 0)
    has_readiness_risk = bool(stale_created or blocked_total or in_progress_total)

    config = load_project_config(repo)
    policy_engine = _policy_engine(config)
    agent = _select_agent(config, policy_engine)
    agent_config = config.agents.get(agent.name)
    agent_available = agent.check_available()
    agent_profile = _agent_profile_data(agent, agent_config, agent_available)
    agent_ready = agent_available and bool(agent_profile["configured"])
    mode = "mock" if agent.name == "mock" else "real"

    preflight_ok = not has_readiness_risk and agent_ready
    next_action = _next_action_for_preflight(
        agent_available=agent_ready,
        created_ready=created_ready,
        stale_created_count=len(stale_created),
        in_progress_count=in_progress_total,
        blocked_count=blocked_total,
    )

    bounded_limit = max(0, limit)
    return {
        "plan": str(plan_path),
        "total": len(all_items),
        "by_status": dict(sorted(status_counts.items())),
        "created_readiness": {
            "ready": created_ready,
            "stale": len(stale_created),
        },
        "blocked_in_progress_risk": {
            "blocked": blocked_total,
            "in_progress": in_progress_total,
        },
        "stale_created": {
            "count": len(stale_created),
            "items": [
                _queue_item_readiness_ref(repo, item)
                for item in stale_created[:bounded_limit]
            ],
        },
        "stale_in_progress": {
            "count": len(stale_in_progress),
            "items": [
                _queue_item_readiness_ref(repo, item)
                for item in stale_in_progress[:bounded_limit]
            ],
        },
        "problem_summary": _problem_summary_data(
            all_items,
            limit=bounded_limit if bounded_limit else None,
        ),
        "agent_profile": {
            "name": agent_profile["name"],
            "configured": agent_profile["configured"],
            "type": agent_profile["type"],
            "profile": agent_profile["profile"],
            "mode": mode,
            "command": agent_profile["command"],
            "available": agent_profile["available"],
        },
        "preflight_result": "pass" if preflight_ok else "risk_or_unavailable",
        "next_action": next_action,
    }


def _run_autopilot_queue_preflight(
    args: argparse.Namespace,
    repo: Path,
    store: StateStore,
) -> int:
    """Render a read-only preflight summary for a selected plan.

    Combines queue readiness with the selected agent profile summary
    (``name``, ``type``, ``mode``, configured command, and availability).
    The command never executes queue items or mutates stored state.
    With ``--fail-on-risk`` the command exits ``2`` when readiness risk or
    agent unavailability is present.
    """
    plan_path = _resolve_plan_path(repo, Path(args.plan))
    if not plan_path.exists():
        if args.json:
            print(
                json.dumps(
                    {"error": f"Plan not found: {plan_path}"},
                    indent=2,
                    ensure_ascii=False,
                )
            )
        else:
            print(f"Plan not found: {plan_path}")
        return 1

    limit = max(0, args.limit)
    snapshot = _queue_preflight_snapshot(repo, plan_path, store, limit=limit)

    if args.json:
        print(json.dumps(snapshot, indent=2, ensure_ascii=False, default=str))
        if args.fail_on_risk and snapshot["preflight_result"] != "pass":
            return 2
        return 0

    print(f"Queue preflight for {plan_path}")
    print(f"  total: {snapshot['total']}")
    by_status = snapshot["by_status"]
    if by_status:
        summary = ", ".join(
            f"{status}={count}" for status, count in sorted(by_status.items())
        )
        print("  by status:", summary)
    else:
        print("  No plan items found.")

    created_readiness = snapshot["created_readiness"]
    blocked_in_progress_risk = snapshot["blocked_in_progress_risk"]
    print(
        "  created readiness:",
        f"ready={created_readiness['ready']} stale={created_readiness['stale']}",
    )
    print(
        "  blocked/in_progress risk:",
        f"blocked={blocked_in_progress_risk['blocked']} "
        f"in_progress={blocked_in_progress_risk['in_progress']}",
    )
    print("  stale created:", created_readiness["stale"])
    print("  stale in_progress:", snapshot["stale_in_progress"]["count"])

    stale_created_items = snapshot["stale_created"]["items"]
    if stale_created_items:
        print("  stale created items:")
        for ref in stale_created_items:
            item_id = ref["plan_item_id"]
            item = store.get_plan_item(item_id)
            if item is None:
                continue
            refs = _queue_item_refs(repo, item)
            item_label = _queue_item_label(item, include_plan_path=False)
            print(f"    id={item_id} {item_label}: {item.text}{refs}")
        if snapshot["stale_created"]["count"] > limit:
            print(f"    ... and {snapshot['stale_created']['count'] - limit} more")

    stale_in_progress_items = snapshot["stale_in_progress"]["items"]
    if stale_in_progress_items:
        print("  stale in_progress items:")
        for ref in stale_in_progress_items:
            item_id = ref["plan_item_id"]
            item = store.get_plan_item(item_id)
            if item is None:
                continue
            refs = _queue_item_refs(repo, item)
            item_label = _queue_item_label(item, include_plan_path=False)
            print(f"    id={item_id} {item_label}: {item.text}{refs}")
        if snapshot["stale_in_progress"]["count"] > limit:
            print(
                f"    ... and {snapshot['stale_in_progress']['count'] - limit} more"
            )

    problem_summary = _format_problem_summary(
        store.list_plan_items(plan_path=plan_path),
        limit=limit if limit else None,
    )
    if problem_summary:
        print(problem_summary)

    agent_profile = snapshot["agent_profile"]
    print("Agent profile:")
    print(f"  name: {agent_profile['name']}")
    if not agent_profile["configured"]:
        print("  configured: no")
    print(f"  type: {agent_profile['type']}")
    print(f"  profile: {agent_profile['profile']}")
    print(f"  mode: {agent_profile['mode']}")
    print(f"  command: {agent_profile['command']}")
    print(f"  available: {'yes' if agent_profile['available'] else 'no'}")
    print(f"preflight_result: {snapshot['preflight_result']}")
    print(f"next_action: {snapshot['next_action']}")

    if args.fail_on_risk and snapshot["preflight_result"] != "pass":
        return 2

    return 0


def _queue_item_readiness_ref(repo: Path, item: StoredPlanItem) -> dict[str, object]:
    """Return a machine-readable reference for a queue item."""
    report_path = _task_report_path(repo, item.task_id)
    return {
        "plan_item_id": item.plan_item_id,
        "plan_path": item.plan_path,
        "line_number": item.line_number,
        "text": item.text,
        "status": item.status,
        "task_id": item.task_id,
        "selected_worktree_path": item.selected_worktree_path,
        "blocked_reason": item.blocked_reason,
        "plan_graph_id": item.plan_graph_id,
        "plan_graph_root_node_id": item.plan_graph_root_node_id,
        "report_path": str(report_path) if report_path else None,
    }


def _problem_summary_data(
    items: list[StoredPlanItem],
    *,
    limit: int | None = None,
) -> list[dict[str, object]] | None:
    """Return a structured summary of blocked and in-progress items by reason.

    Mirrors ``_format_problem_summary`` but returns a JSON-serializable list
    instead of a human-readable string. Returns ``None`` when no affected
    items exist.
    """
    affected = [item for item in items if item.status in {"blocked", "in_progress"}]
    if not affected:
        return None

    groups: dict[tuple[str, str], list[StoredPlanItem]] = {}
    for item in affected:
        reason = item.blocked_reason if item.blocked_reason else "(no reason)"
        groups.setdefault((item.status, reason), []).append(item)

    status_order = {status: index for index, status in enumerate(_QUEUE_STATUSES)}
    result: list[dict[str, object]] = []
    for (status, reason), group in sorted(
        groups.items(),
        key=lambda kv: (status_order.get(kv[0][0], 99), kv[0][1].lower()),
    ):
        latest = sorted(
            group,
            key=lambda item: (item.updated_at, item.plan_item_id),
            reverse=True,
        )
        if limit:
            latest = latest[:limit]
        result.append(
            {
                "status": status,
                "reason": reason,
                "count": len(group),
                "latest_ids": [item.plan_item_id for item in latest],
            }
        )
    return result


def _run_autopilot_queue_reconcile(
    args: argparse.Namespace,
    repo: Path,
    store: StateStore,
) -> int:
    include_plan_path = bool(args.all_plans)
    if include_plan_path:
        plan_label = "all persisted plans"
        all_items = store.list_plan_items()
    else:
        plan_path = _resolve_plan_path(repo, Path(args.plan))
        if not plan_path.exists():
            if args.json:
                print(
                    json.dumps(
                        {"error": f"Plan not found: {plan_path}"},
                        indent=2,
                        ensure_ascii=False,
                    )
                )
            else:
                print(f"Plan not found: {plan_path}")
            return 1
        plan_label = str(plan_path)
        all_items = store.list_plan_items(plan_path=plan_path)

    stale_items = _stale_created_queue_items(repo, all_items)
    skipped_count = 0
    if args.apply:
        updated_items: list[StoredPlanItem] = []
        for item in stale_items:
            updated = store.update_plan_item_status(item.plan_item_id, "skipped")
            updated_items.append(updated if updated is not None else item)
        stale_items = updated_items
        skipped_count = len(stale_items)

    if args.json:
        _print_reconcile_json(
            repo,
            plan_label=plan_label,
            include_plan_path=include_plan_path,
            total=len(all_items),
            stale_items=stale_items,
            apply=bool(args.apply),
            skipped_count=skipped_count,
        )
        return 0

    print(f"Queue reconcile for {plan_label}")
    print(f"  total: {len(all_items)}")
    print(f"  stale_created: {len(stale_items)}")
    if not stale_items:
        print("  No stale created queue items found.")
        return 0

    if args.apply:
        print(f"  skipped: {len(stale_items)}")
    else:
        print("  dry_run: use --apply to mark stale items skipped")

    for item in stale_items:
        refs = _queue_item_refs(repo, item)
        item_label = _queue_item_label(item, include_plan_path=include_plan_path)
        print(f"  [stale] {item_label}: {item.text}{refs}")
    return 0


def _print_reconcile_json(
    repo: Path,
    *,
    plan_label: str,
    include_plan_path: bool,
    total: int,
    stale_items: list[StoredPlanItem],
    apply: bool,
    skipped_count: int,
) -> None:
    payload = {
        "plan": plan_label,
        "all_plans": include_plan_path,
        "total": total,
        "apply": apply,
        "dry_run": not apply,
        "stale_created": {
            "count": len(stale_items),
            "items": [_queue_item_readiness_ref(repo, item) for item in stale_items],
        },
        "skipped": {"count": skipped_count},
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))


def _run_autopilot_queue_recover_in_progress(
    args: argparse.Namespace,
    repo: Path,
    store: StateStore,
) -> int:
    """Find stale in_progress queue items and optionally mark them blocked.

    Dry-run by default.  When ``args.apply`` is set, every ``in_progress``
    queue item is moved to ``blocked`` and the supplied ``--reason`` is
    persisted so the operator can later decide whether to continue, mark
    done, or keep blocked.
    """
    include_plan_path = bool(args.all_plans)
    if include_plan_path:
        plan_label = "all persisted plans"
        items = store.list_plan_items(status="in_progress")
    else:
        plan_path = _resolve_plan_path(repo, Path(args.plan))
        if not plan_path.exists():
            print(f"Plan not found: {plan_path}")
            return 1
        plan_label = str(plan_path)
        items = store.list_plan_items(plan_path=plan_path, status="in_progress")

    if args.apply and not args.reason:
        print("--reason is required when --apply is set")
        return 1

    if args.older_than_hours is not None:
        if args.older_than_hours < 1:
            print("--older-than-hours must be at least 1")
            return 1
        cutoff = datetime.now(UTC) - timedelta(hours=args.older_than_hours)
        items = [
            item
            for item in items
            if _plan_item_updated_before(item, cutoff)
        ]

    if not items:
        if args.json:
            _print_recover_in_progress_json(
                repo,
                plan_label=plan_label,
                include_plan_path=include_plan_path,
                items=items,
                args=args,
                blocked_count=0,
            )
        else:
            print(f"Queue recover for {plan_label}")
            print(f"  stale_in_progress: {len(items)}")
            print("  No stale in_progress queue items found.")
        return 0

    blocked_count = 0
    if args.apply:
        updated_items: list[StoredPlanItem] = []
        for item in items:
            updated = store.update_plan_item_status(
                item.plan_item_id,
                "blocked",
                blocked_reason=args.reason,
            )
            updated_items.append(updated if updated is not None else item)
        items = updated_items
        blocked_count = len(items)

    if args.json:
        _print_recover_in_progress_json(
            repo,
            plan_label=plan_label,
            include_plan_path=include_plan_path,
            items=items,
            args=args,
            blocked_count=blocked_count,
        )
        return 0

    print(f"Queue recover for {plan_label}")
    print(f"  stale_in_progress: {len(items)}")
    if args.apply:
        print(f"  blocked: {len(items)}")
        print(f"  reason: {args.reason}")
    else:
        print(
            "  dry_run: use --apply --reason '...' to mark stale items blocked"
        )

    for item in items:
        refs = _queue_item_refs(repo, item)
        item_label = _queue_item_label(item, include_plan_path=include_plan_path)
        print(f"  [stale_in_progress] {item_label}: {item.text}{refs}")
    return 0


def _print_recover_in_progress_json(
    repo: Path,
    *,
    plan_label: str,
    include_plan_path: bool,
    items: list[StoredPlanItem],
    args: argparse.Namespace,
    blocked_count: int,
) -> None:
    payload = {
        "plan": plan_label,
        "all_plans": include_plan_path,
        "apply": bool(args.apply),
        "dry_run": not bool(args.apply),
        "older_than_hours": args.older_than_hours,
        "stale_in_progress": {
            "count": len(items),
            "items": [_queue_item_readiness_ref(repo, item) for item in items],
        },
        "blocked": {
            "count": blocked_count,
            "reason": args.reason if args.apply else None,
        },
        "applied_reason": args.reason if args.apply else None,
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))


def _plan_item_updated_before(item: StoredPlanItem, cutoff: datetime) -> bool:
    updated_at = datetime.fromisoformat(item.updated_at)
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=UTC)
    return updated_at < cutoff


def _validate_queue_item_plan(
    repo: Path,
    plan_item_id: int,
    requested_plan: str | None,
    item_plan_path: str,
) -> int | None:
    """Validate that a queue item belongs to the requested plan.

    Returns an exit code when the plan is missing or the item does not belong
    to it; otherwise returns ``None``.
    """
    if requested_plan is None:
        return None
    plan_path = _resolve_plan_path(repo, Path(requested_plan))
    if not plan_path.exists():
        print(f"Plan not found: {plan_path}")
        return 1
    if Path(item_plan_path) != plan_path:
        print(f"Queue item {plan_item_id} does not belong to plan {plan_path}")
        return 1
    return None


def _run_autopilot_queue_show(
    args: argparse.Namespace,
    repo: Path,
    store: StateStore,
) -> int:
    """Print a selected queue item's details without changing stored state.

    Shows the status, source, task text, task id, report path, selected
    worktree, and blocker/skip reason so an operator can decide whether to
    requeue, skip, or continue without mutating the queue.

    When ``--plan`` is provided, the command validates that the selected item
    belongs to the requested plan before displaying it.
    """
    item = store.get_plan_item(args.plan_item_id)
    if item is None:
        print(f"Queue item not found: {args.plan_item_id}")
        return 1

    validation_error = _validate_queue_item_plan(
        repo, args.plan_item_id, getattr(args, "plan", None), item.plan_path
    )
    if validation_error is not None:
        return validation_error

    report_path = _task_report_path(repo, item.task_id)
    if args.json:
        payload = {
            "plan_item_id": item.plan_item_id,
            "status": item.status,
            "source": f"{item.plan_path}:{item.line_number}",
            "plan_path": item.plan_path,
            "line_number": item.line_number,
            "task": item.text,
            "task_id": item.task_id,
            "report_path": str(report_path) if report_path else None,
            "selected_worktree": item.selected_worktree_path,
            "reason": item.blocked_reason,
            "plan_graph_id": item.plan_graph_id,
            "plan_graph_root_node_id": item.plan_graph_root_node_id,
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
        return 0

    print(f"Queue item: {item.plan_item_id}")
    print(f"  status: {item.status}")
    print(f"  source: {item.plan_path}:{item.line_number}")
    print(f"  task: {item.text}")
    print(f"  task_id: {item.task_id or 'none'}")
    print(f"  report_path: {report_path or 'none'}")
    print(f"  selected_worktree: {item.selected_worktree_path or 'none'}")
    print(f"  reason: {item.blocked_reason or 'none'}")
    print(f"  plan_graph_id: {item.plan_graph_id or 'none'}")
    print(f"  plan_graph_root_node_id: {item.plan_graph_root_node_id or 'none'}")
    return 0


def _run_autopilot_queue_link_plan_graph(
    args: argparse.Namespace,
    repo: Path,
    store: StateStore,
) -> int:
    """Link a queue item to a durable PlanGraph root.

    The command is dry-run by default so an operator can verify the queue item,
    graph, and root node references before mutating persisted state.
    """
    item = store.get_plan_item(args.plan_item_id)
    if item is None:
        print(f"Queue item not found: {args.plan_item_id}")
        return 1

    validation_error = _validate_queue_item_plan(
        repo, args.plan_item_id, getattr(args, "plan", None), item.plan_path
    )
    if validation_error is not None:
        return validation_error

    graph = store.get_plan_graph(args.graph_id)
    if graph is None:
        print(f"PlanGraph not found: {args.graph_id}")
        return 1

    root_node = None
    if args.root_node_id is not None:
        root_node = store.get_plan_graph_node(args.root_node_id)
        if root_node is None or root_node.graph_id != graph.graph_id:
            print(
                "PlanGraph root node not found in graph "
                f"{graph.graph_id}: {args.root_node_id}"
            )
            return 1

    plan_scope = {
        "requested_plan": (
            str(_resolve_plan_path(repo, Path(args.plan))) if args.plan else None
        ),
        "item_plan": item.plan_path,
        "validated": bool(args.plan),
    }
    link = {
        "graph_id": graph.graph_id,
        "graph_title": graph.title,
        "root_node_id": root_node.node_id if root_node else None,
        "root_node_key": root_node.node_key if root_node else None,
        "root_node_title": root_node.title if root_node else None,
    }

    if not args.apply:
        if args.json:
            payload = {
                "plan_item": _queue_item_readiness_ref(repo, item),
                "plan_scope": plan_scope,
                "link": link,
                "mode": "dry_run",
                "applied": False,
            }
            print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
            return 0
        print(f"Link queue item {item.plan_item_id} to PlanGraph {graph.graph_id}")
        print(f"  source: {item.plan_path}:{item.line_number}")
        print(f"  task: {item.text}")
        print(f"  graph_title: {graph.title}")
        print(f"  root_node_id: {link['root_node_id'] or 'none'}")
        print("  dry_run: use --apply to persist this link")
        return 0

    try:
        linked = store.link_plan_item_to_plan_graph(
            item.plan_item_id,
            graph.graph_id,
            plan_graph_root_node_id=root_node.node_id if root_node else None,
        )
    except ValueError as exc:
        print(f"PlanGraph link error: {exc}")
        return 1
    if linked is None:
        print(f"Queue item not found: {item.plan_item_id}")
        return 1

    if args.json:
        payload = {
            "plan_item": _queue_item_readiness_ref(repo, linked),
            "plan_scope": plan_scope,
            "link": link,
            "mode": "apply",
            "applied": True,
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
        return 0

    print(f"Link queue item {item.plan_item_id} to PlanGraph {graph.graph_id}")
    print(f"  source: {item.plan_path}:{item.line_number}")
    print(f"  task: {item.text}")
    print(f"  graph_title: {graph.title}")
    print(f"  root_node_id: {link['root_node_id'] or 'none'}")
    print("  status: linked")
    return 0


def _run_autopilot_queue_requeue(
    args: argparse.Namespace,
    repo: Path,
    store: StateStore,
) -> int:
    """Move a selected blocked queue item back to ``created`` after review.

    Dry-run by default. When ``args.apply`` is set, the persisted item is
    updated, its blocker metadata is cleared, and the item is left ready for
    a future queue run. It is never executed by this command.
    """
    item = store.get_plan_item(args.plan_item_id)
    if item is None:
        print(f"Queue item not found: {args.plan_item_id}")
        return 1

    if item.status != "blocked":
        print(
            f"Queue item {args.plan_item_id} is not blocked (status={item.status})"
        )
        return 1

    validation_error = _validate_queue_item_plan(
        repo, args.plan_item_id, getattr(args, "plan", None), item.plan_path
    )
    if validation_error is not None:
        return validation_error

    cleared_metadata = [
        "blocked_reason",
        "task_id",
        "selected_worktree_path",
    ]
    plan_scope = {
        "requested_plan": (
            str(_resolve_plan_path(repo, Path(args.plan))) if args.plan else None
        ),
        "item_plan": item.plan_path,
        "validated": bool(args.plan),
    }

    if args.json and not args.apply:
        payload = {
            "plan_item": _queue_item_readiness_ref(repo, item),
            "plan_scope": plan_scope,
            "mode": "dry_run",
            "applied": False,
            "resulting_status": item.status,
            "cleared_metadata": [],
            "would_clear_metadata": cleared_metadata,
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
        return 0

    if not args.json:
        print(f"Requeue queue item {item.plan_item_id}")
        print(f"  source: {item.plan_path}:{item.line_number}")
        print(f"  task: {item.text}")
        if item.blocked_reason:
            print(f"  blocked_reason: {item.blocked_reason}")
        if item.task_id:
            print(f"  task_id: {item.task_id}")
        if item.selected_worktree_path:
            print(f"  selected_worktree_path: {item.selected_worktree_path}")

    if not args.apply:
        print("  dry_run: use --apply to move this item back to created")
        return 0

    requeued = store.requeue_plan_item(item.plan_item_id)
    if requeued is None:
        print("  requeue failed: item is no longer blocked")
        return 1

    if args.json:
        payload = {
            "plan_item": _queue_item_readiness_ref(repo, item),
            "plan_scope": plan_scope,
            "mode": "apply",
            "applied": True,
            "resulting_status": requeued.status,
            "cleared_metadata": cleared_metadata,
            "would_clear_metadata": [],
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
        return 0

    print("  status: created")
    print("  cleared: blocked_reason, task_id, selected_worktree_path")
    return 0


def _run_autopilot_queue_skip(
    args: argparse.Namespace,
    repo: Path,
    store: StateStore,
) -> int:
    """Mark a selected ``created`` or ``blocked`` queue item as ``skipped``.

    Dry-run by default. When ``args.apply`` is set, the persisted item is
    updated to ``skipped`` and the operator-supplied reason is recorded. The
    item is never executed or deleted by this command.

    When ``--plan`` is provided, the command validates that the selected item
    belongs to the requested plan before skipping it.
    """
    item = store.get_plan_item(args.plan_item_id)
    if item is None:
        print(f"Queue item not found: {args.plan_item_id}")
        return 1

    if item.status not in {"created", "blocked"}:
        print(
            f"Queue item {args.plan_item_id} cannot be skipped (status={item.status})"
        )
        return 1

    validation_error = _validate_queue_item_plan(
        repo, args.plan_item_id, getattr(args, "plan", None), item.plan_path
    )
    if validation_error is not None:
        return validation_error

    plan_scope = {
        "requested_plan": (
            str(_resolve_plan_path(repo, Path(args.plan))) if args.plan else None
        ),
        "item_plan": item.plan_path,
        "validated": bool(args.plan),
    }

    if args.json and not args.apply:
        payload = {
            "plan_item": _queue_item_readiness_ref(repo, item),
            "plan_scope": plan_scope,
            "skip_reason": args.reason,
            "mode": "dry_run",
            "applied": False,
            "resulting_status": item.status,
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
        return 0

    if not args.json:
        print(f"Skip queue item {item.plan_item_id}")
        print(f"  source: {item.plan_path}:{item.line_number}")
        print(f"  task: {item.text}")
        print(f"  current_status: {item.status}")
        print(f"  reason: {args.reason}")
        if item.blocked_reason and item.status == "blocked":
            print(f"  blocked_reason: {item.blocked_reason}")
        if item.task_id:
            print(f"  task_id: {item.task_id}")
        if item.selected_worktree_path:
            print(f"  selected_worktree_path: {item.selected_worktree_path}")

    if not args.apply:
        print("  dry_run: use --apply to mark this item skipped")
        return 0

    skipped = store.skip_plan_item(item.plan_item_id, reason=args.reason)
    if skipped is None:
        print("  skip failed: item is no longer created or blocked")
        return 1

    if args.json:
        payload = {
            "plan_item": _queue_item_readiness_ref(repo, item),
            "plan_scope": plan_scope,
            "skip_reason": args.reason,
            "mode": "apply",
            "applied": True,
            "resulting_status": skipped.status,
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
        return 0

    print("  status: skipped")
    return 0


def _plan_graph_payload(store: StateStore, graph: StoredPlanGraph) -> dict[str, object]:
    nodes = store.list_plan_graph_nodes(graph.graph_id)
    dependencies = store.list_plan_graph_dependencies(graph.graph_id)
    return {
        "graph": asdict(graph),
        "nodes": [asdict(node) for node in nodes],
        "dependencies": [asdict(dependency) for dependency in dependencies],
    }


def _plan_graph_list_payload(graphs: list[StoredPlanGraph]) -> dict[str, object]:
    return {
        "total": len(graphs),
        "graphs": [asdict(graph) for graph in graphs],
    }


def _ready_plan_graph_nodes_payload(
    graph: StoredPlanGraph,
    nodes: list[StoredPlanGraphNode],
) -> dict[str, object]:
    return {
        "graph": asdict(graph),
        "ready_count": len(nodes),
        "nodes": [asdict(node) for node in nodes],
    }


def _print_plan_graph_text(
    store: StateStore,
    graph: StoredPlanGraph,
    *,
    prefix: str = "PlanGraph",
) -> None:
    nodes = store.list_plan_graph_nodes(graph.graph_id)
    dependencies = store.list_plan_graph_dependencies(graph.graph_id)
    dependencies_by_node: dict[int, list[StoredPlanGraphDependency]] = {}
    for dependency in dependencies:
        dependencies_by_node.setdefault(dependency.node_id, []).append(dependency)

    print(f"{prefix}: {graph.graph_id}")
    print(f"  title: {graph.title}")
    print(f"  status: {graph.status}")
    print(f"  task_id: {graph.task_id or 'none'}")
    print(f"  nodes: {len(nodes)}")
    print(f"  dependencies: {len(dependencies)}")
    for node in nodes:
        print(
            "  "
            f"node={node.node_id} key={node.node_key} "
            f"status={node.status} attempts={node.attempts} title={node.title}"
        )
        node_dependencies = dependencies_by_node.get(node.node_id, [])
        if node_dependencies:
            depends_on = ", ".join(
                str(dependency.depends_on_node_id)
                for dependency in node_dependencies
            )
            print(f"    depends_on: {depends_on}")


def _print_ready_plan_graph_nodes_text(
    graph: StoredPlanGraph,
    nodes: list[StoredPlanGraphNode],
) -> None:
    print(f"Ready PlanGraph nodes: {len(nodes)}")
    print(f"  graph: {graph.graph_id}")
    if not nodes:
        print("  No ready PlanGraph nodes.")
        return
    for node in nodes:
        print(
            "  "
            f"node={node.node_id} key={node.node_key} "
            f"status={node.status} attempts={node.attempts} title={node.title}"
        )


def _plan_graph_node_to_task(
    graph: StoredPlanGraph,
    node: StoredPlanGraphNode,
) -> AutopilotTask:
    return AutopilotTask(
        source_path=Path(f"PlanGraph-{graph.graph_id}"),
        line_number=node.node_id,
        text=node.title,
        section=f"PlanGraph {graph.graph_id}: {graph.title}",
    )


def _print_plan_graph_list_text(graphs: list[StoredPlanGraph]) -> None:
    print(f"PlanGraphs: {len(graphs)}")
    for graph in graphs:
        task_ref = f" task={graph.task_id}" if graph.task_id else ""
        print(
            f"  id={graph.graph_id} [{graph.status}] "
            f"{graph.title}{task_ref}"
        )


def _print_plan_graph_json(payload: dict[str, object]) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))


def _run_autopilot_plan_run_next(
    args: argparse.Namespace,
    store: StateStore,
) -> int:
    if not _validate_max_runtime_sec(args):
        return 1
    repo = Path(args.repo)
    graph = store.get_plan_graph(args.graph_id)
    if graph is None:
        print(f"PlanGraph not found: {args.graph_id}")
        return 1
    ready_nodes = store.list_ready_plan_graph_nodes(graph.graph_id, limit=1)
    if not ready_nodes:
        print(f"No ready PlanGraph nodes in graph {graph.graph_id}")
        return 0

    node = ready_nodes[0]
    node_status = _run_plan_graph_node(args, store, repo, graph, node)
    if node_status is None:
        return 0
    return 0 if node_status == "done" else 1


def _run_autopilot_plan_run_batch(
    args: argparse.Namespace,
    store: StateStore,
) -> int:
    if not _validate_max_runtime_sec(args):
        return 1
    if args.max_items <= 0:
        print("--max-items must be at least 1")
        return 1
    repo = Path(args.repo)
    graph = store.get_plan_graph(args.graph_id)
    if graph is None:
        print(f"PlanGraph not found: {args.graph_id}")
        return 1

    processed = 0
    if not args.execute:
        ready_nodes = store.list_ready_plan_graph_nodes(
            graph.graph_id,
            limit=args.max_items,
        )
        if not ready_nodes:
            print(f"No ready PlanGraph nodes in graph {graph.graph_id}")
            return 0
        for node in ready_nodes:
            _run_plan_graph_node(args, store, repo, graph, node)
        print(
            f"Dry run: would process {len(ready_nodes)} PlanGraph node(s). "
            "Add --execute to run."
        )
        return 0

    for _ in range(args.max_items):
        ready_nodes = store.list_ready_plan_graph_nodes(graph.graph_id, limit=1)
        if not ready_nodes:
            if processed == 0:
                print(f"No ready PlanGraph nodes in graph {graph.graph_id}")
            break
        node_status = _run_plan_graph_node(args, store, repo, graph, ready_nodes[0])
        if node_status is None:
            return 1
        processed += 1
        if node_status != "done":
            print(
                "PlanGraph batch stopped after "
                f"{processed} node(s): status={node_status}"
            )
            return 1

    print(f"PlanGraph batch complete: processed {processed} node(s)")
    return 0


def _run_plan_graph_node(
    args: argparse.Namespace,
    store: StateStore,
    repo: Path,
    graph: StoredPlanGraph,
    node: StoredPlanGraphNode,
) -> str | None:
    task = _plan_graph_node_to_task(graph, node)

    def _mark_in_progress() -> None:
        store.update_plan_graph_node_status(
            node.node_id,
            "in_progress",
            increment_attempts=True,
        )

    print(f"PlanGraph node: {node.node_id}")
    result = _run_autopilot_task(
        task,
        repo,
        Path(f"PlanGraph-{graph.graph_id}"),
        args,
        store,
        on_start=_mark_in_progress,
    )
    if result is None:
        return None

    node_status = "done" if result.status == "done" else "blocked"
    store.update_plan_graph_node_status(node.node_id, node_status)
    if result.task_id is not None:
        store.link_replan_decisions_to_plan_graph(
            result.task_id,
            graph.graph_id,
            plan_graph_node_id=node.node_id,
        )
        store.create_replan_follow_up_nodes(result.task_id, graph.graph_id)

    print(f"PlanGraph node {node.node_id}: status={node_status}")
    if result.task_id is not None:
        report_path = _write_task_report(store, repo, result.task_id)
        if report_path is not None:
            print(f"Report: {report_path}")
    return node_status


def _run_autopilot_plan_command(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
) -> int:
    if args.autopilot_plan_command is None:
        parser.print_help()
        return 1

    store = _state_store_for_repo(Path(args.repo))

    try:
        if args.autopilot_plan_command == "list":
            graphs = store.list_plan_graphs(task_id=args.task_id, status=args.status)
            if args.json:
                _print_plan_graph_json(_plan_graph_list_payload(graphs))
                return 0
            _print_plan_graph_list_text(graphs)
            return 0

        if args.autopilot_plan_command == "create":
            created_graph = store.create_plan_graph(
                title=args.title,
                task_id=args.task_id,
                status=args.status,
            )
            if args.json:
                _print_plan_graph_json(_plan_graph_payload(store, created_graph))
                return 0
            _print_plan_graph_text(store, created_graph, prefix="Created PlanGraph")
            return 0

        if args.autopilot_plan_command == "show":
            shown_graph = store.get_plan_graph(args.graph_id)
            if shown_graph is None:
                print(f"PlanGraph not found: {args.graph_id}")
                return 1
            if args.json:
                _print_plan_graph_json(_plan_graph_payload(store, shown_graph))
                return 0
            _print_plan_graph_text(store, shown_graph)
            return 0

        if args.autopilot_plan_command == "ready":
            ready_graph = store.get_plan_graph(args.graph_id)
            if ready_graph is None:
                print(f"PlanGraph not found: {args.graph_id}")
                return 1
            if args.limit < 0:
                print("--limit must be 0 or greater")
                return 1
            limit = args.limit if args.limit > 0 else None
            ready_nodes = store.list_ready_plan_graph_nodes(
                args.graph_id,
                limit=limit,
            )
            if args.json:
                _print_plan_graph_json(
                    _ready_plan_graph_nodes_payload(ready_graph, ready_nodes)
                )
                return 0
            _print_ready_plan_graph_nodes_text(ready_graph, ready_nodes)
            return 0

        if args.autopilot_plan_command == "run-next":
            return _run_autopilot_plan_run_next(args, store)

        if args.autopilot_plan_command == "run-batch":
            return _run_autopilot_plan_run_batch(args, store)

        if args.autopilot_plan_command == "update":
            updated_graph = store.update_plan_graph_status(args.graph_id, args.status)
            if updated_graph is None:
                print(f"PlanGraph not found: {args.graph_id}")
                return 1
            if args.json:
                _print_plan_graph_json(_plan_graph_payload(store, updated_graph))
                return 0
            _print_plan_graph_text(store, updated_graph, prefix="Updated PlanGraph")
            return 0

        if args.autopilot_plan_command == "add-node":
            target_graph = store.get_plan_graph(args.graph_id)
            if target_graph is None:
                print(f"PlanGraph not found: {args.graph_id}")
                return 1
            created_node = store.add_plan_graph_node(
                graph_id=args.graph_id,
                node_key=args.key,
                title=args.title,
                status=args.status,
                attempts=args.attempts,
                depends_on_node_ids=args.depends_on_node_ids,
            )
            refreshed_graph = store.get_plan_graph(args.graph_id)
            if refreshed_graph is None:
                print(f"PlanGraph not found: {args.graph_id}")
                return 1
            if args.json:
                payload = _plan_graph_payload(store, refreshed_graph)
                payload["node"] = asdict(created_node)
                _print_plan_graph_json(payload)
                return 0
            print(f"Added PlanGraph node: {created_node.node_id}")
            _print_plan_graph_text(store, refreshed_graph)
            return 0

        if args.autopilot_plan_command == "update-node":
            updated_node = store.update_plan_graph_node_status(
                args.node_id,
                args.status,
                attempts=args.attempts,
                increment_attempts=args.increment_attempts,
            )
            if updated_node is None:
                print(f"PlanGraph node not found: {args.node_id}")
                return 1
            node_graph = store.get_plan_graph(updated_node.graph_id)
            if node_graph is None:
                print(f"PlanGraph not found: {updated_node.graph_id}")
                return 1
            if args.json:
                payload = _plan_graph_payload(store, node_graph)
                payload["node"] = asdict(updated_node)
                _print_plan_graph_json(payload)
                return 0
            print(f"Updated PlanGraph node: {updated_node.node_id}")
            _print_plan_graph_text(store, node_graph)
            return 0

        if args.autopilot_plan_command == "add-dependency":
            target_graph = store.get_plan_graph(args.graph_id)
            if target_graph is None:
                print(f"PlanGraph not found: {args.graph_id}")
                return 1
            dependency = store.add_plan_graph_dependency(
                graph_id=args.graph_id,
                node_id=args.node_id,
                depends_on_node_id=args.depends_on_node_id,
            )
            if dependency is None:
                print("PlanGraph dependency was not recorded")
                return 1
            refreshed_graph = store.get_plan_graph(args.graph_id)
            if refreshed_graph is None:
                print(f"PlanGraph not found: {args.graph_id}")
                return 1
            if args.json:
                payload = _plan_graph_payload(store, refreshed_graph)
                payload["dependency"] = asdict(dependency)
                _print_plan_graph_json(payload)
                return 0
            print(
                "Added PlanGraph dependency: "
                f"{dependency.node_id}->{dependency.depends_on_node_id}"
            )
            _print_plan_graph_text(store, refreshed_graph)
            return 0
    except ValueError as exc:
        print(f"PlanGraph error: {exc}")
        return 1

    parser.print_help()
    return 1


def _run_autopilot_queue_command(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    if args.autopilot_queue_command is None:
        parser.print_help()
        return 1

    repo = Path(args.repo)
    store = _state_store_for_repo(repo)

    if args.autopilot_queue_command == "sync-backlog":
        backlog_path = _resolve_plan_path(repo, Path(args.backlog))
        if not backlog_path.exists():
            print(f"Backlog not found: {backlog_path}")
            return 1
        priorities = tuple(args.priority or ["P0", "P1", "P2"])
        new_items, existing_items = sync_backlog_items(
            backlog_path,
            store,
            priorities=priorities,
        )
        print(f"Synced backlog {backlog_path}")
        print(f"  priorities: {', '.join(priorities)}")
        print(f"  new: {len(new_items)}")
        print(f"  existing: {len(existing_items)}")
        for item in new_items:
            print(f"  + {item.section}:{item.line_number}: {item.text}")
        return 0

    if args.autopilot_queue_command == "sync":
        plan_path = _resolve_plan_path(repo, Path(args.plan))
        if not plan_path.exists():
            print(f"Plan not found: {plan_path}")
            return 1
        new_items, existing_items = sync_plan_items(plan_path, store)
        print(f"Synced {plan_path}")
        print(f"  new: {len(new_items)}")
        print(f"  existing: {len(existing_items)}")
        for item in new_items:
            print(f"  + {item.line_number}: {item.text}")
        return 0

    if args.autopilot_queue_command == "refresh-created-refs":
        backlog_path = _resolve_plan_path(repo, Path(args.backlog))
        if not backlog_path.exists():
            print(f"Backlog not found: {backlog_path}")
            return 1
        priorities = tuple(args.priority or ["P0", "P1", "P2"])
        refreshes = refresh_created_backlog_item_refs(
            backlog_path,
            store,
            priorities=priorities,
            apply=args.apply,
        )
        if args.json:
            updated_count = len(refreshes) if args.apply else 0
            print(
                json.dumps(
                    {
                        "backlog_path": str(backlog_path),
                        "priorities": list(priorities),
                        "apply": bool(args.apply),
                        "dry_run": not bool(args.apply),
                        "matched_count": len(refreshes),
                        "updated_count": updated_count,
                        "items": [
                            {
                                "plan_item_id": refresh.item.plan_item_id,
                                "text": refresh.item.text,
                                "old_source_ref": {
                                    "path": refresh.item.plan_path,
                                    "section": refresh.item.section,
                                    "line_number": refresh.item.line_number,
                                },
                                "new_source_ref": {
                                    "path": str(backlog_path),
                                    "section": refresh.section,
                                    "line_number": refresh.line_number,
                                },
                            }
                            for refresh in refreshes
                        ],
                    },
                    indent=2,
                    ensure_ascii=False,
                    default=str,
                )
            )
            return 0
        print(f"Refresh created backlog refs for {backlog_path}")
        print(f"  priorities: {', '.join(priorities)}")
        print(f"  matched: {len(refreshes)}")
        if args.apply:
            print(f"  updated: {len(refreshes)}")
        else:
            print("  dry_run: use --apply to update matching created refs")
        for refresh in refreshes:
            item = refresh.item
            print(
                "  "
                f"id={item.plan_item_id} {item.section}:"
                f"{item.line_number}->{refresh.line_number}: {item.text}"
            )
        return 0

    if args.autopilot_queue_command == "list":
        include_plan_path = bool(args.all_plans)
        if include_plan_path:
            plan_label = "all persisted plans"
            all_items = store.list_plan_items()
        else:
            plan_path = _resolve_plan_path(repo, Path(args.plan))
            if not plan_path.exists():
                if args.json:
                    print(
                        json.dumps(
                            {"error": f"Plan not found: {plan_path}"},
                            indent=2,
                            ensure_ascii=False,
                        )
                    )
                else:
                    print(f"Plan not found: {plan_path}")
                return 1
            plan_label = str(plan_path)
            all_items = store.list_plan_items(plan_path=plan_path)
        statuses = tuple(args.status or [])
        matched_items = _filter_queue_items(all_items, statuses)
        items = matched_items
        limit = max(0, args.limit)
        if limit:
            items = items[:limit]
        status_counts: dict[str, int] = {}
        for item in all_items:
            status_counts[item.status] = status_counts.get(item.status, 0) + 1
        if args.json:
            payload = {
                "plan": plan_label,
                "all_plans": include_plan_path,
                "total": len(all_items),
                "filtered": len(matched_items),
                "status_filter": list(statuses),
                "limit": limit,
                "showing": len(items),
                "by_status": dict(sorted(status_counts.items())),
                "items": [_queue_item_readiness_ref(repo, item) for item in items],
                "problem_summary": _problem_summary_data(
                    matched_items,
                    limit=limit if limit else None,
                ),
            }
            print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
            return 0
        print(f"Queue status for {plan_label}")
        print(f"  total: {len(all_items)}")
        if statuses:
            print(f"  filtered: {len(matched_items)} status={','.join(statuses)}")
        if limit:
            print(f"  limit: {limit}")
            print(f"  showing: {len(items)}")
        if status_counts:
            summary = ", ".join(
                f"{status}={count}" for status, count in sorted(status_counts.items())
            )
            print("  by status:", summary)
        problem_summary = _format_problem_summary(
            matched_items,
            limit=limit if limit else None,
        )
        if problem_summary:
            print(problem_summary)
        for item in items:
            refs = _queue_item_refs(repo, item)
            item_label = _queue_item_label(item, include_plan_path=include_plan_path)
            print(
                f"  id={item.plan_item_id} [{item.status}] {item_label}: {item.text}{refs}"
            )
        return 0

    if args.autopilot_queue_command == "status":
        include_plan_path = bool(args.all_plans)
        if include_plan_path:
            plan_label = "all persisted plans"
            items = store.list_plan_items()
        else:
            plan_path = _resolve_plan_path(repo, Path(args.plan))
            if not plan_path.exists():
                print(f"Plan not found: {plan_path}")
                return 1
            plan_label = str(plan_path)
            items = store.list_plan_items(plan_path=plan_path)
        statuses = tuple(args.status or [])
        filtered_items = _filter_queue_items(items, statuses)
        print(f"Queue status for {plan_label}")
        print(f"  total: {len(items)}")
        if statuses:
            print(f"  filtered: {len(filtered_items)} status={','.join(statuses)}")
        status_counts = {}
        for item in items:
            status_counts[item.status] = status_counts.get(item.status, 0) + 1
        if status_counts:
            summary = ", ".join(
                f"{status}={count}" for status, count in sorted(status_counts.items())
            )
            print("  by status:", summary)
        else:
            print("  No plan items found.")

        problem_summary = _format_problem_summary(
            filtered_items,
            limit=max(0, args.limit) if args.limit else None,
        )
        if problem_summary:
            print(problem_summary)

        limit = max(0, args.limit)
        for status, label in (
            ("created", "created"),
            ("in_progress", "started"),
            ("done", "done"),
            ("blocked", "blocked"),
            ("skipped", "skipped"),
        ):
            if statuses and status not in statuses:
                continue
            recent = sorted(
                [item for item in items if item.status == status],
                key=lambda item: (item.updated_at, item.plan_item_id),
                reverse=True,
            )[:limit]
            if not recent:
                continue
            print(f"  recent {label}:")
            for item in recent:
                refs = _queue_item_refs(repo, item)
                item_label = _queue_item_label(item, include_plan_path=include_plan_path)
                print(
                    f"    id={item.plan_item_id} {item_label}: {item.text}{refs}"
                )
        return 0

    if args.autopilot_queue_command == "readiness":
        return _run_autopilot_queue_readiness(args, repo, store)

    if args.autopilot_queue_command == "preflight":
        return _run_autopilot_queue_preflight(args, repo, store)

    if args.autopilot_queue_command == "reconcile":
        return _run_autopilot_queue_reconcile(args, repo, store)

    if args.autopilot_queue_command == "recover-in-progress":
        return _run_autopilot_queue_recover_in_progress(args, repo, store)

    if args.autopilot_queue_command == "show":
        return _run_autopilot_queue_show(args, repo, store)

    if args.autopilot_queue_command == "link-plan-graph":
        return _run_autopilot_queue_link_plan_graph(args, repo, store)

    if args.autopilot_queue_command == "requeue":
        return _run_autopilot_queue_requeue(args, repo, store)

    if args.autopilot_queue_command == "skip":
        return _run_autopilot_queue_skip(args, repo, store)

    if args.autopilot_queue_command == "run-next":
        if not _validate_max_runtime_sec(args):
            return 1
        plan_path = _resolve_plan_path(repo, Path(args.plan))
        if not plan_path.exists():
            print(f"Plan not found: {plan_path}")
            return 1
        next_item = next_plan_item(store, plan_path)
        if next_item is None:
            print(f"No queued plan items ready in {plan_path}")
            return 0
        task = plan_item_to_task(next_item)

        def _mark_in_progress() -> None:
            store.update_plan_item_status(next_item.plan_item_id, "in_progress")
            _mark_plan_graph_node_started(store, next_item)

        print(f"Queue item: {next_item.plan_item_id}")

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
        blocked_reason = _runtime_budget_exhausted_reason(result)
        store.update_plan_item_status(
            next_item.plan_item_id,
            item_status,
            task_id=result.task_id,
            blocked_reason=blocked_reason,
        )
        _finish_plan_graph_node_for_queue_result(
            store,
            next_item,
            item_status,
            result.task_id,
        )
        print(f"Queue item {next_item.plan_item_id}: status={item_status}")
        if result.task_id is not None:
            report_path = _write_task_report(store, repo, result.task_id)
            if report_path is not None:
                print(f"Report: {report_path}")
        return 0 if item_status == "done" else 1

    if args.autopilot_queue_command == "run-batch":
        if not _validate_max_runtime_sec(args):
            return 1
        plan_path = _resolve_plan_path(repo, Path(args.plan))
        if not plan_path.exists():
            print(f"Plan not found: {plan_path}")
            return 1
        return _run_autopilot_queue_batch(args, repo, plan_path, store)

    parser.print_help()
    return 1


def _build_batch_summary(
    store: StateStore,
    plan_path: Path,
    item_ids: list[int],
    report_paths: list[Path],
    worktree_paths: list[Path],
    mode: str,
    preflight_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a machine-readable summary for a batch dry-run or execution."""
    all_items = store.list_plan_items(plan_path=plan_path)
    item_by_id = {item.plan_item_id: item for item in all_items}
    selected_items = [
        item_by_id[item_id] for item_id in item_ids if item_id in item_by_id
    ]
    report_path_by_task_id = {
        path.stem: str(path)
        for path in report_paths
    }

    status_counts: dict[str, int] = {}
    for item in selected_items:
        status_counts[item.status] = status_counts.get(item.status, 0) + 1

    first_non_done = next(
        (item for item in all_items if item.status not in _TERMINAL_QUEUE_STATUSES),
        None,
    )

    count_key = "selected_count" if mode == "dry-run" else "processed_count"
    summary: dict[str, object] = {
        "mode": mode,
        "plan_path": str(plan_path),
        count_key: len(selected_items),
        "status_counts": dict(sorted(status_counts.items())),
        "first_non_done_item": None,
        "report_paths": [str(path) for path in report_paths],
        "selected_worktree_paths": [str(path) for path in worktree_paths],
        "selected_item_refs": _build_selected_item_refs(
            selected_items,
            worktree_paths,
            report_path_by_task_id,
        ),
    }
    if first_non_done is not None:
        summary["first_non_done_item"] = {
            "plan_item_id": first_non_done.plan_item_id,
            "status": first_non_done.status,
            "text": first_non_done.text,
            "source": f"{first_non_done.plan_path}:{first_non_done.line_number}",
        }
    if preflight_snapshot is not None:
        summary["preflight_snapshot"] = preflight_snapshot
    return summary


def _build_selected_item_refs(
    items: list[StoredPlanItem],
    worktree_paths: list[Path],
    report_path_by_task_id: dict[str, str],
) -> list[dict[str, object]]:
    """Return stable machine-readable refs for selected or processed items."""
    refs: list[dict[str, object]] = []
    for index, item in enumerate(items):
        selected_worktree_path = item.selected_worktree_path
        if selected_worktree_path is None:
            if len(worktree_paths) == len(items):
                selected_worktree_path = str(worktree_paths[index])
            elif len(worktree_paths) == 1:
                selected_worktree_path = str(worktree_paths[0])

        refs.append(
            {
                "plan_item_id": item.plan_item_id,
                "status": item.status,
                "plan_path": item.plan_path,
                "line_number": item.line_number,
                "text": item.text,
                "selected_worktree_path": selected_worktree_path,
                "task_id": item.task_id,
                "report_path": (
                    report_path_by_task_id.get(item.task_id)
                    if item.task_id is not None
                    else None
                ),
            }
        )
    return refs


def _print_batch_summary(summary: dict[str, Any]) -> None:
    """Print an operator-facing summary for a batch dry-run or execution."""
    mode = summary["mode"]
    label = "Selected" if mode == "dry-run" else "Processed"
    count_key = "selected_count" if mode == "dry-run" else "processed_count"
    item_count = summary[count_key]

    print("=== Batch summary ===")
    print(f"{label}: {item_count} item(s)")
    status_counts = summary["status_counts"]
    print(
        "Status counts: "
        + (
            ", ".join(f"{status}={count}" for status, count in status_counts.items())
            or "(none)"
        )
    )
    first_non_done = summary.get("first_non_done_item")
    if first_non_done is not None:
        print(
            f"First non-done queue item: {first_non_done['plan_item_id']} "
            f"(status={first_non_done['status']})"
        )
    worktree_paths = summary["selected_worktree_paths"]
    if worktree_paths:
        print("Selected worktrees:")
        for path in worktree_paths:
            print(f"  {path}")
    report_paths = summary["report_paths"]
    if report_paths:
        print("Reports:")
        for path in report_paths:
            print(f"  {path}")


def _write_batch_summary_json(path: Path, summary: dict[str, Any]) -> None:
    """Persist a batch summary as formatted JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )


def _write_batch_report_markdown(path: Path, summary: dict[str, Any]) -> None:
    """Persist a batch summary as an operator-facing Markdown artifact."""
    mode = summary["mode"]
    label = "Selected" if mode == "dry-run" else "Processed"
    count_key = "selected_count" if mode == "dry-run" else "processed_count"

    lines = [
        "# Autopilot Batch Report",
        "",
        "## Summary",
        "",
        f"- Mode: `{mode}`",
        f"- Plan: `{summary['plan_path']}`",
        f"- {label}: {summary[count_key]} item(s)",
        "- Status counts: "
        + (
            ", ".join(
                f"`{status}`={count}"
                for status, count in summary["status_counts"].items()
            )
            or "(none)"
        ),
        "",
    ]

    first_non_done = summary.get("first_non_done_item")
    lines.extend(["## First Non-Done Item", ""])
    if first_non_done is None:
        lines.extend(["None.", ""])
    else:
        lines.extend(
            [
                f"- Queue item: `{first_non_done['plan_item_id']}`",
                f"- Status: `{first_non_done['status']}`",
                f"- Source: `{first_non_done['source']}`",
                f"- Text: {first_non_done['text']}",
                "",
            ]
        )

    lines.extend(["## Reports", ""])
    report_paths = summary["report_paths"]
    if report_paths:
        lines.extend(f"- `{path}`" for path in report_paths)
    else:
        lines.append("None.")
    lines.append("")

    lines.extend(["## Selected Worktrees", ""])
    worktree_paths = summary["selected_worktree_paths"]
    if worktree_paths:
        lines.extend(f"- `{path}`" for path in worktree_paths)
    else:
        lines.append("None.")
    lines.append("")

    lines.extend(["## Selected Item Refs", "", "```json"])
    lines.append(
        json.dumps(
            summary["selected_item_refs"],
            indent=2,
            ensure_ascii=False,
            default=str,
        )
    )
    lines.extend(["```", ""])

    if "preflight_snapshot" in summary:
        lines.extend(["## Preflight Snapshot", "", "```json"])
        lines.append(
            json.dumps(
                summary["preflight_snapshot"],
                indent=2,
                ensure_ascii=False,
                default=str,
            )
        )
        lines.extend(["```", ""])

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def _emit_batch_summary(
    store: StateStore,
    plan_path: Path,
    item_ids: list[int],
    report_paths: list[Path],
    worktree_paths: list[Path],
    mode: str,
    summary_json: Path | None = None,
    batch_report: Path | None = None,
    preflight_snapshot: dict[str, Any] | None = None,
) -> bool:
    """Print and optionally persist a batch summary.

    Returns ``True`` when the summary is printed (and written, when requested)
    successfully, or ``False`` when a requested artifact cannot be written.
    """
    summary = _build_batch_summary(
        store,
        plan_path,
        item_ids,
        report_paths,
        worktree_paths,
        mode,
        preflight_snapshot=preflight_snapshot,
    )
    _print_batch_summary(summary)
    if summary_json is not None:
        try:
            _write_batch_summary_json(summary_json, summary)
        except OSError as exc:
            print(
                f"Failed to write batch summary JSON to {summary_json}: {exc}",
                file=sys.stderr,
            )
            return False
    if batch_report is not None:
        try:
            _write_batch_report_markdown(batch_report, summary)
        except OSError as exc:
            print(
                f"Failed to write batch report Markdown to {batch_report}: {exc}",
                file=sys.stderr,
            )
            return False
    return True


def _run_autopilot_loop(
    args: argparse.Namespace,
    repo: Path,
    plan_path: Path,
    store: StateStore,
) -> int:
    """Run the persisted queue through a guarded unattended loop."""
    started_at = datetime.now(UTC)
    if args.max_items <= 0:
        print("Loop stopped: budget exhausted (--max-items must be at least 1)")
        return 1
    if args.max_attempts <= 0:
        print("Loop stopped: budget exhausted (--max-attempts must be at least 1)")
        return 1
    if args.max_actions <= 0:
        print("Loop stopped: budget exhausted (--max-actions must be at least 1)")
        return 1

    preflight_snapshot = _queue_preflight_snapshot(repo, plan_path, store)
    stop_reason = _loop_preflight_stop_reason(args, preflight_snapshot)
    if stop_reason is not None:
        print(f"Loop stopped on {stop_reason}: next_action={preflight_snapshot['next_action']}")
        loop_run = _record_autopilot_loop_run(
            store,
            args,
            plan_path,
            selected_item_ids=[],
            selected_count=0,
            processed_count=0,
            dead_letter_count=0,
            stop_reason=stop_reason,
            result_code=1,
            started_at=started_at,
        )
        _print_loop_ledger(
            args,
            selected_count=0,
            processed_count=0,
            dead_letter_count=0,
            stop_reason=stop_reason,
            loop_run=loop_run,
        )
        return 1

    loop_max_items = min(args.max_items, args.max_actions)
    loop_args = argparse.Namespace(**vars(args))
    loop_args.max_items = loop_max_items
    loop_args.worktree = None
    loop_args.rotate_worktrees = None
    loop_args.item_id = None
    selected_items = _select_batch_plan_items(loop_args, store, plan_path, limit=loop_max_items)
    if selected_items is None:
        return 1
    selected_ids = [item.plan_item_id for item in selected_items]

    print("=== Autopilot loop ===")
    print(f"Mode: {'execute' if args.execute else 'dry-run'}")
    print(f"Plan: {plan_path}")
    print(f"Selected: {len(selected_ids)} item(s)")

    result_code = _run_autopilot_queue_batch(loop_args, repo, plan_path, store)
    dead_letter_count = 0
    if args.execute and selected_ids:
        dead_letter_count = _record_loop_dead_letters(
            store,
            selected_ids,
            max_attempts=args.max_attempts,
        )

    processed_count = _loop_processed_count(store, selected_ids) if args.execute else 0
    stop_reason = _loop_stop_reason_after_batch(
        result_code,
        selected_ids=selected_ids,
        processed_count=processed_count,
        dead_letter_count=dead_letter_count,
        action_budget_exhausted=loop_max_items < args.max_items,
    )
    if stop_reason:
        print(f"Loop stopped: {stop_reason}")
    else:
        print("Loop complete")
    loop_run = _record_autopilot_loop_run(
        store,
        args,
        plan_path,
        selected_item_ids=selected_ids,
        selected_count=len(selected_ids),
        processed_count=processed_count,
        dead_letter_count=dead_letter_count,
        stop_reason=stop_reason or "complete",
        result_code=result_code,
        started_at=started_at,
    )
    _print_loop_ledger(
        args,
        selected_count=len(selected_ids),
        processed_count=processed_count,
        dead_letter_count=dead_letter_count,
        stop_reason=stop_reason or "complete",
        loop_run=loop_run,
    )
    return result_code


def _record_autopilot_loop_run(
    store: StateStore,
    args: argparse.Namespace,
    plan_path: Path,
    *,
    selected_item_ids: list[int],
    selected_count: int,
    processed_count: int,
    dead_letter_count: int,
    stop_reason: str,
    result_code: int,
    started_at: datetime,
) -> StoredAutopilotLoopRun:
    completed_at = datetime.now(UTC)
    return store.record_autopilot_loop_run(
        plan_path=plan_path,
        mode="execute" if args.execute else "dry-run",
        max_runtime_sec=getattr(args, "max_runtime_sec", None),
        max_attempts=args.max_attempts,
        max_actions=args.max_actions,
        selected_count=selected_count,
        processed_count=processed_count,
        dead_letter_count=dead_letter_count,
        stop_reason=stop_reason,
        result_code=result_code,
        selected_item_ids=selected_item_ids,
        elapsed_sec=max(0.0, (completed_at - started_at).total_seconds()),
        started_at=started_at.isoformat(),
        completed_at=completed_at.isoformat(),
    )


def _loop_preflight_stop_reason(
    args: argparse.Namespace,
    preflight_snapshot: dict[str, Any],
) -> str | None:
    next_action = str(preflight_snapshot.get("next_action", "none"))
    if next_action == "fix_agent":
        return "unavailable agent"
    if args.stop_on_risk and next_action in {
        "reconcile_stale_created",
        "recover_in_progress",
        "review_blocked",
    }:
        return "risk"
    return None


def _record_loop_dead_letters(
    store: StateStore,
    selected_ids: list[int],
    *,
    max_attempts: int,
) -> int:
    if max_attempts > 1:
        return 0
    recorded = 0
    for plan_item_id in selected_ids:
        item = store.get_plan_item(plan_item_id)
        if item is None or item.status != "blocked":
            continue
        existing = store.list_dead_letter_items(plan_item_id=plan_item_id)
        if existing:
            continue
        reason = item.blocked_reason or "loop item stopped with status=blocked"
        store.add_dead_letter_item(
            item.plan_item_id,
            reason,
            task_id=item.task_id,
            attempts=max_attempts,
        )
        recorded += 1
    return recorded


def _loop_processed_count(store: StateStore, selected_ids: list[int]) -> int:
    processed = 0
    for plan_item_id in selected_ids:
        item = store.get_plan_item(plan_item_id)
        if item is not None and item.status in {"done", "blocked", "skipped"}:
            processed += 1
    return processed


def _loop_stop_reason_after_batch(
    result_code: int,
    *,
    selected_ids: list[int],
    processed_count: int,
    dead_letter_count: int,
    action_budget_exhausted: bool,
) -> str | None:
    if not selected_ids:
        return None
    if dead_letter_count:
        return "dead-letter"
    if result_code != 0:
        return "blocker or failed checks"
    if action_budget_exhausted or processed_count >= len(selected_ids):
        return "budget exhausted" if action_budget_exhausted else None
    return None


def _print_loop_ledger(
    args: argparse.Namespace,
    *,
    selected_count: int,
    processed_count: int,
    dead_letter_count: int,
    stop_reason: str,
    loop_run: StoredAutopilotLoopRun,
) -> None:
    runtime_budget = getattr(args, "max_runtime_sec", None)
    print("=== Loop budget ledger ===")
    print(f"loop_run_id: {loop_run.loop_run_id}")
    print(f"runtime_sec: max={runtime_budget or 'config'}")
    print(f"attempts: max={args.max_attempts}")
    print(
        "actions: "
        f"max={args.max_actions} selected={selected_count} processed={processed_count}"
    )
    print(f"dead_letters: {dead_letter_count}")
    print(f"stop_reason: {stop_reason}")


def _run_autopilot_queue_batch(
    args: argparse.Namespace,
    repo: Path,
    plan_path: Path,
    store: StateStore,
) -> int:
    """Run up to *args.max_items* queued plan items serially.

    Dry-runs by default.  When ``args.execute`` is set, each item is started,
    its status is updated from the supervisor result, a Markdown report is
    written, and the loop stops on the first non-done result.
    """
    max_items = max(0, args.max_items)
    if max_items <= 0:
        print("--max-items must be at least 1")
        return 1

    preflight_snapshot = _queue_preflight_snapshot(repo, plan_path, store)

    if getattr(args, "rotate_worktrees", None):
        if not args.execute:
            return _dry_run_rotated_batch(
                args, repo, plan_path, store, preflight_snapshot=preflight_snapshot
            )
        return _run_rotated_autopilot_queue_batch(
            args, repo, plan_path, store, preflight_snapshot=preflight_snapshot
        )

    fixed_worktree: Path | None = None
    if getattr(args, "worktree", None):
        fixed_worktree = _autopilot_execution_repo(repo, args.worktree)

    if not args.execute:
        items = _select_batch_plan_items(args, store, plan_path, limit=max_items)
        if items is None:
            return 1
        if not items:
            print(f"No queued plan items ready in {plan_path}")
            return 0
        for item in items:
            print(f"Queue item: {item.plan_item_id}")
            task = plan_item_to_task(item)
            _run_autopilot_task(task, repo, plan_path, args, store)
        print(f"Dry run: would process {len(items)} item(s). Add --execute to run.")
        if not _emit_batch_summary(
            store,
            plan_path,
            [item.plan_item_id for item in items],
            [],
            [fixed_worktree] if fixed_worktree else [],
            mode="dry-run",
            summary_json=Path(args.summary_json) if args.summary_json else None,
            batch_report=Path(args.batch_report) if args.batch_report else None,
            preflight_snapshot=preflight_snapshot,
        ):
            return 1
        return 0

    processed_ids: list[int] = []
    report_paths: list[Path] = []
    selected_items = _select_batch_plan_items(args, store, plan_path, limit=max_items)
    if selected_items is None:
        return 1
    if not selected_items:
        print(f"No more queued plan items ready in {plan_path}")
    for selected_item in selected_items:
        next_item = (
            selected_item
            if getattr(args, "item_id", None) is not None
            else next_plan_item(store, plan_path)
        )
        if next_item is None:
            print(f"No more queued plan items ready in {plan_path}")
            break
        task = plan_item_to_task(next_item)
        print(f"Queue item: {next_item.plan_item_id}")

        def _mark_in_progress(
            linked_item: StoredPlanItem = next_item,
            plan_item_id: int = next_item.plan_item_id,
            selected_worktree: Path | None = fixed_worktree,
        ) -> None:
            store.update_plan_item_status(
                plan_item_id,
                "in_progress",
                selected_worktree_path=selected_worktree,
            )
            _mark_plan_graph_node_started(store, linked_item)

        result = _run_autopilot_task(
            task,
            repo,
            plan_path,
            args,
            store,
            on_start=_mark_in_progress,
        )
        if result is None:
            print("Batch stopped: unexpected dry run in execute mode")
            return 1
        item_status = plan_item_status_from_supervisor(result.status)
        blocked_reason = _runtime_budget_exhausted_reason(result)
        store.update_plan_item_status(
            next_item.plan_item_id,
            item_status,
            task_id=result.task_id,
            selected_worktree_path=fixed_worktree,
            blocked_reason=blocked_reason,
        )
        _finish_plan_graph_node_for_queue_result(
            store,
            next_item,
            item_status,
            result.task_id,
        )
        processed_ids.append(next_item.plan_item_id)
        print(f"Queue item {next_item.plan_item_id}: status={item_status}")
        if result.task_id is not None:
            report_path = _write_task_report(store, repo, result.task_id)
            if report_path is not None:
                print(f"Report: {report_path}")
                report_paths.append(report_path)
        if item_status != "done":
            print(f"Batch stopped after {len(processed_ids)} item(s): status={item_status}")
            if not _emit_batch_summary(
                store,
                plan_path,
                processed_ids,
                report_paths,
                [fixed_worktree] if fixed_worktree else [],
                mode="execute",
                summary_json=Path(args.summary_json) if args.summary_json else None,
                batch_report=Path(args.batch_report) if args.batch_report else None,
                preflight_snapshot=preflight_snapshot,
            ):
                return 1
            return 1

    print(f"Batch complete: processed {len(processed_ids)} item(s)")
    if not _emit_batch_summary(
        store,
        plan_path,
        processed_ids,
        report_paths,
        [fixed_worktree] if fixed_worktree else [],
        mode="execute",
        summary_json=Path(args.summary_json) if args.summary_json else None,
        batch_report=Path(args.batch_report) if args.batch_report else None,
        preflight_snapshot=preflight_snapshot,
    ):
        return 1
    return 0


def _run_rotated_autopilot_queue_batch(
    args: argparse.Namespace,
    repo: Path,
    plan_path: Path,
    store: StateStore,
    *,
    preflight_snapshot: dict[str, Any] | None = None,
) -> int:
    """Execute a serial batch with one selected worktree per queue item."""
    base_dir = _resolve_rotated_worktree_base(repo, args.rotate_worktrees)
    if not base_dir.exists():
        print(f"Rotation base directory does not exist: {base_dir}")
        return 1
    if not base_dir.is_dir():
        print(f"Rotation base path is not a directory: {base_dir}")
        return 1

    max_items = max(0, args.max_items)
    items = _select_batch_plan_items(args, store, plan_path, limit=max_items)
    if items is None:
        return 1
    if not items:
        print(f"No queued plan items ready in {plan_path}")
        return 0

    selected = _select_rotated_worktrees(
        repo, base_dir, store, allow_dirty=args.allow_dirty, count=len(items)
    )
    if len(selected) < len(items):
        print(
            "Execution blocked: not enough clean, available worktrees under "
            f"{base_dir} for {len(items)} queued item(s)"
        )
        return 1

    processed_ids: list[int] = []
    report_paths: list[Path] = []
    for item, worktree in zip(items, selected):
        task = plan_item_to_task(item)
        run_args = _args_with_worktree(args, worktree)
        print(f"Queue item: {item.plan_item_id}")
        print(f"Worktree: {worktree}")

        def _mark_in_progress(
            linked_item: StoredPlanItem = item,
            plan_item_id: int = item.plan_item_id,
            selected_worktree: Path = worktree,
        ) -> None:
            store.update_plan_item_status(
                plan_item_id,
                "in_progress",
                selected_worktree_path=selected_worktree,
            )
            _mark_plan_graph_node_started(store, linked_item)

        result = _run_autopilot_task(
            task,
            repo,
            plan_path,
            run_args,
            store,
            on_start=_mark_in_progress,
        )
        if result is None:
            print("Batch stopped: unexpected dry run in execute mode")
            return 1
        item_status = plan_item_status_from_supervisor(result.status)
        blocked_reason = _runtime_budget_exhausted_reason(result)
        store.update_plan_item_status(
            item.plan_item_id,
            item_status,
            task_id=result.task_id,
            selected_worktree_path=worktree,
            blocked_reason=blocked_reason,
        )
        _finish_plan_graph_node_for_queue_result(
            store,
            item,
            item_status,
            result.task_id,
        )
        processed_ids.append(item.plan_item_id)
        print(f"Queue item {item.plan_item_id}: status={item_status}")
        if result.task_id is not None:
            report_path = _write_task_report(store, repo, result.task_id)
            if report_path is not None:
                print(f"Report: {report_path}")
                report_paths.append(report_path)
        if item_status != "done":
            print(f"Batch stopped after {len(processed_ids)} item(s): status={item_status}")
            if not _emit_batch_summary(
                store,
                plan_path,
                processed_ids,
                report_paths,
                selected,
                mode="execute",
                summary_json=Path(args.summary_json) if args.summary_json else None,
                batch_report=Path(args.batch_report) if args.batch_report else None,
                preflight_snapshot=preflight_snapshot,
            ):
                return 1
            return 1

    print(f"Batch complete: processed {len(processed_ids)} item(s)")
    if not _emit_batch_summary(
        store,
        plan_path,
        processed_ids,
        report_paths,
        selected,
        mode="execute",
        summary_json=Path(args.summary_json) if args.summary_json else None,
        batch_report=Path(args.batch_report) if args.batch_report else None,
        preflight_snapshot=preflight_snapshot,
    ):
        return 1
    return 0


def _dry_run_rotated_batch(
    args: argparse.Namespace,
    repo: Path,
    plan_path: Path,
    store: StateStore,
    *,
    preflight_snapshot: dict[str, Any] | None = None,
) -> int:
    """Dry-run a batch with per-task worktree rotation."""
    base_dir = _resolve_rotated_worktree_base(repo, args.rotate_worktrees)
    if not base_dir.exists():
        print(f"Rotation base directory does not exist: {base_dir}")
        return 1
    if not base_dir.is_dir():
        print(f"Rotation base path is not a directory: {base_dir}")
        return 1

    max_items = max(0, args.max_items)
    items = _select_batch_plan_items(args, store, plan_path, limit=max_items)
    if items is None:
        return 1
    if not items:
        print(f"No queued plan items ready in {plan_path}")
        return 0

    selected = _select_rotated_worktrees(
        repo, base_dir, store, allow_dirty=args.allow_dirty, count=len(items)
    )
    if len(selected) < len(items):
        print(
            "Execution blocked: not enough clean, available worktrees under "
            f"{base_dir} for {len(items)} queued item(s)"
        )
        return 1

    for item, worktree in zip(items, selected):
        task = plan_item_to_task(item)
        print(f"Queue item: {item.plan_item_id}")
        print("Autopilot selected:")
        _print_autopilot_task(task)
        print(f"Worktree: {worktree}")

    print(
        f"Dry run: would process {len(items)} item(s) using rotated worktrees. "
        "Add --execute to start."
    )
    if not _emit_batch_summary(
        store,
        plan_path,
        [item.plan_item_id for item in items],
        [],
        selected,
        mode="dry-run",
        summary_json=Path(args.summary_json) if args.summary_json else None,
        batch_report=Path(args.batch_report) if args.batch_report else None,
        preflight_snapshot=preflight_snapshot,
    ):
        return 1
    return 0


def _select_batch_plan_items(
    args: argparse.Namespace,
    store: StateStore,
    plan_path: Path,
    *,
    limit: int,
) -> list[StoredPlanItem] | None:
    """Return the queue items selected for this batch run.

    Without ``--item-id`` this preserves the existing default queue selection.
    With ``--item-id`` the batch is narrowed to exactly one created item from
    the selected plan.
    """
    item_id = getattr(args, "item_id", None)
    if item_id is None:
        return next_plan_items(store, plan_path, limit=limit)

    item = store.get_plan_item(item_id)
    if item is None:
        print(f"Queue item not found: {item_id}")
        return None
    if Path(item.plan_path) != plan_path:
        print(f"Queue item {item_id} does not belong to plan {plan_path}")
        return None
    if item.status != "created":
        print(f"Queue item {item_id} is not ready (status={item.status})")
        return None
    return [item]


def _args_with_worktree(args: argparse.Namespace, worktree: Path) -> argparse.Namespace:
    values = vars(args).copy()
    values["worktree"] = str(worktree)
    return argparse.Namespace(**values)


def _resolve_rotated_worktree_base(repo: Path, base_dir: str) -> Path:
    base_path = Path(base_dir)
    if not base_path.is_absolute():
        base_path = repo / base_path
    return base_path.resolve()


def _select_rotated_worktrees(
    repo: Path,
    base_dir: Path,
    store: StateStore,
    allow_dirty: bool,
    count: int,
) -> list[Path]:
    """Select up to *count* clean, available git worktrees from *base_dir*.

    Worktrees are inspected in sorted path order. A worktree is skipped when it
    fails validation, has uncommitted changes (unless *allow_dirty*), or is
    already associated with an ``in_progress`` queue item.
    """
    busy = _busy_rotated_worktrees(store)
    candidates = sorted(
        [path for path in base_dir.iterdir() if path.is_dir()],
        key=lambda p: str(p),
    )
    selected: list[Path] = []
    for candidate in candidates:
        if candidate.resolve() in busy:
            continue
        error = _validate_autopilot_worktree(repo, candidate)
        if error is not None:
            continue
        if not allow_dirty and _repo_has_uncommitted_changes(candidate):
            continue
        selected.append(candidate.resolve())
        if len(selected) >= count:
            break
    return selected


def _busy_rotated_worktrees(store: StateStore) -> set[Path]:
    """Return worktree paths currently associated with in-progress plan items."""
    busy: set[Path] = set()
    for item in store.list_plan_items(status="in_progress"):
        if item.selected_worktree_path is not None:
            busy.add(Path(item.selected_worktree_path).resolve())
            continue
        if item.task_id is None:
            continue
        task = store.get_task(item.task_id)
        if task is None:
            continue
        busy.add(Path(task.repo_path).resolve())
    return busy


def _print_autopilot_task(task: AutopilotTask) -> None:
    print(f"Source: {task.source_label}")
    print(f"Section: {task.section or 'Unsectioned'}")
    print(f"Task: {task.text}")


def _print_autopilot_agent_profile(
    agent: AgentAdapter,
    agent_config: AgentConfig | None,
    available: bool,
) -> None:
    profile = _agent_profile_data(agent, agent_config, available)
    print("Agent profile:")
    print(f"  name: {profile['name']}")
    if not profile["configured"]:
        print("  configured: no")
    print(f"  type: {profile['type']}")
    print(f"  profile: {profile['profile']}")
    print(f"  mode: {profile['mode']}")
    print(f"  command: {profile['command']}")
    print(f"  available: {'yes' if profile['available'] else 'no'}")


def _print_progress(message: str) -> None:
    print(f"progress: {message}", flush=True)


def _agent_profile_data(
    agent: AgentAdapter,
    agent_config: AgentConfig | None,
    available: bool,
) -> dict[str, Any]:
    if agent_config is None:
        return {
            "name": agent.name,
            "configured": False,
            "type": "(missing)",
            "profile": "(missing)",
            "mode": "mock" if agent.name == "mock" else "real",
            "command": "(missing)",
            "available": available,
        }
    return {
        "name": agent.name,
        "configured": True,
        "type": _agent_config_value(agent_config, "type"),
        "profile": _agent_config_value(agent_config, "profile"),
        "mode": "mock" if agent.name == "mock" else "real",
        "command": _agent_config_value(agent_config, "command"),
        "available": available,
    }


def _agent_config_value(agent_config: AgentConfig, field: str) -> str:
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
    if args.memory_command == "lessons":
        store = _state_store_for_repo(repo)
        if args.limit < 0:
            print("--limit must be 0 or greater")
            return 1
        print(
            _format_memory_lessons(
                store.list_memory_lessons(
                    include_stale=args.include_stale,
                    limit=args.limit if args.limit > 0 else None,
                )
            ),
            end="",
        )
        return 0
    if args.memory_command == "influence":
        store = _state_store_for_repo(repo)
        print(_format_memory_influence(store.list_memory_influence(args.task_id)), end="")
        return 0

    config = load_project_config(repo)
    approved_commands = set(getattr(args, "approve_command", []) or [])
    client = _memory_client(config, approved_commands=approved_commands)
    project = config.memory.project

    if args.memory_command == "status":
        print(f"provider: {config.memory.provider or 'codebase-memory-mcp'}")
        print(f"command: {' '.join(config.memory.command)}")
        print(f"project: {project or '(default)'}")
        print(f"max_lessons: {config.memory.max_lessons}")
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
    step_results: list[tuple[str, CodebaseMemoryResult]] = []
    for label, tool, tool_args in _memory_preflight_steps(args.area, project, args.limit):
        print(f"step: {label}")
        result = client.run_tool(tool, tool_args, cwd=repo)
        _print_memory_result(tool, result)
        statuses.append(result.status)
        step_results.append((label, result))

    total = len(statuses)
    passed_count = sum(1 for status in statuses if status == "passed")
    failure_count = total - passed_count
    print(
        f"preflight summary: area={args.area} total={total} "
        f"passed={passed_count} failed={failure_count}"
    )
    if failure_count:
        print("failures:")
        for label, result in step_results:
            if result.status != "passed":
                print(f"  {label}: {result.status}")
    return 0 if failure_count == 0 else 1


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


def _format_memory_lessons(lessons: list[Any]) -> str:
    lines = ["Memory lessons"]
    if not lessons:
        lines.append("  No memory lessons recorded.")
        return "\n".join(lines) + "\n"
    for lesson in lessons:
        stale = "yes" if lesson.is_stale else "no"
        lines.append(
            (
                f"  lesson={lesson.lesson_id} outcome={lesson.outcome_status} "
                f"stale={stale} source_task={lesson.source_task_id}"
            )
        )
        lines.append(f"     lesson: {lesson.lesson}")
        if lesson.failure_reason:
            lines.append(f"     reason: {lesson.failure_reason}")
    return "\n".join(lines) + "\n"


def _format_memory_influence(influences: list[Any]) -> str:
    lines = ["Memory influence"]
    if not influences:
        lines.append("  No memory influence recorded.")
        return "\n".join(lines) + "\n"
    for influence in influences:
        iteration = "none" if influence.iteration_id is None else str(influence.iteration_id)
        injected = "yes" if influence.injected else "no"
        lines.append(
            (
                f"  influence={influence.influence_id} task={influence.task_id} "
                f"lesson={influence.lesson_id} iteration={iteration} injected={injected}"
            )
        )
        lines.append(f"     reason: {influence.reason}")
    return "\n".join(lines) + "\n"


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
