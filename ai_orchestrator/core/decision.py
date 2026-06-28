from __future__ import annotations

from dataclasses import dataclass

from ai_orchestrator.agents.base import AgentResult
from ai_orchestrator.verification.runner import VerificationResult


@dataclass(frozen=True)
class Decision:
    status: str  # done | continue | blocked
    reason: str
    follow_up_prompt: str | None = None


class DecisionEngine:
    MAX_FAILED_CHECKS_IN_PROMPT = 3
    MAX_CHECK_OUTPUT_CHARS = 1200
    MAX_FOLLOW_UP_PROMPT_CHARS = 4000

    def decide(
        self,
        agent_result: AgentResult,
        verification_results: list[VerificationResult],
        iteration: int,
        max_iterations: int,
        original_task: str | None = None,
    ) -> Decision:
        if agent_result.status != "success":
            return Decision(
                status="blocked",
                reason=agent_result.error or f"Agent returned status: {agent_result.status}",
            )

        if not verification_results:
            return Decision(status="blocked", reason="No verification commands configured")

        failed_results = [item for item in verification_results if item.status != "passed"]
        if not failed_results:
            passed_summary = ", ".join(item.name for item in verification_results)
            return Decision(status="done", reason=f"Verification passed: {passed_summary}")

        policy_results = [
            item for item in failed_results if item.status in {"policy_denied", "needs_approval"}
        ]
        if policy_results:
            policy_summary = ", ".join(
                f"{item.name}: {item.status} ({item.error or 'policy check failed'})"
                for item in policy_results
            )
            return Decision(status="blocked", reason=f"Verification blocked by policy: {policy_summary}")

        failed_summary = ", ".join(
            f"{item.name}: {item.status} exit={item.exit_code}" for item in failed_results
        )
        if iteration >= max_iterations:
            return Decision(
                status="blocked",
                reason=f"Verification failed after {iteration} iteration(s): {failed_summary}",
            )

        return Decision(
            status="continue",
            reason=f"Verification failed: {failed_summary}",
            follow_up_prompt=self._build_follow_up_prompt(
                failed_results,
                original_task=original_task,
            ),
        )

    def _build_follow_up_prompt(
        self,
        failed_results: list[VerificationResult],
        original_task: str | None = None,
    ) -> str:
        sections = [
            "Previous verification failed. Fix the issues below, then stop for verification."
        ]
        if original_task:
            sections.insert(0, f"Original task:\n{self._excerpt_tail(original_task, 1000)}")
        shown_results = failed_results[: self.MAX_FAILED_CHECKS_IN_PROMPT]
        for item in shown_results:
            details = item.stderr or item.stdout or item.error or "No output captured."
            sections.append(
                "\n".join(
                    [
                        f"Check: {item.name}",
                        f"Status: {item.status}",
                        f"Exit code: {item.exit_code}",
                        f"Output:\n{self._excerpt_tail(details, self.MAX_CHECK_OUTPUT_CHARS)}",
                    ]
                )
            )
        hidden_count = len(failed_results) - len(shown_results)
        if hidden_count > 0:
            sections.append(f"... {hidden_count} more failed check(s) omitted ...")
        return self._excerpt("\n\n".join(sections), self.MAX_FOLLOW_UP_PROMPT_CHARS)

    def _excerpt(self, text: str, limit: int) -> str:
        if len(text) <= limit:
            return text
        suffix = "\n... truncated ..."
        if limit <= len(suffix):
            return suffix[:limit]
        return f"{text[: limit - len(suffix)]}{suffix}"

    def _excerpt_tail(self, text: str, limit: int) -> str:
        if len(text) <= limit:
            return text
        prefix = "... truncated ...\n"
        if limit <= len(prefix):
            return prefix[:limit]
        return f"{prefix}{text[-(limit - len(prefix)):]}"
