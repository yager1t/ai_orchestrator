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
    def decide(
        self,
        agent_result: AgentResult,
        verification_results: list[VerificationResult],
        iteration: int,
        max_iterations: int,
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
            follow_up_prompt=self._build_follow_up_prompt(failed_results),
        )

    def _build_follow_up_prompt(self, failed_results: list[VerificationResult]) -> str:
        sections = [
            "Previous verification failed. Fix the issues below, then stop for verification."
        ]
        for item in failed_results:
            details = item.stderr or item.stdout or item.error or "No output captured."
            sections.append(
                "\n".join(
                    [
                        f"Check: {item.name}",
                        f"Status: {item.status}",
                        f"Exit code: {item.exit_code}",
                        f"Output:\n{details[:2000]}",
                    ]
                )
            )
        return "\n\n".join(sections)
