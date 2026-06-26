from ai_orchestrator.agents.base import AgentResult
from ai_orchestrator.core.decision import DecisionEngine
from ai_orchestrator.verification.runner import VerificationResult


def agent_success() -> AgentResult:
    return AgentResult(status="success", raw_output="ok", session_id="s1")


def verification(status: str) -> VerificationResult:
    return VerificationResult(
        name="unit",
        status=status,
        exit_code=0 if status == "passed" else 1,
        stdout="",
        stderr="" if status == "passed" else "failed",
    )


def failed_verification(name: str, stderr: str = "failed") -> VerificationResult:
    return VerificationResult(
        name=name,
        status="failed",
        exit_code=1,
        stdout="",
        stderr=stderr,
    )


def test_decision_done_when_verification_passes() -> None:
    decision = DecisionEngine().decide(
        agent_success(),
        [verification("passed")],
        iteration=1,
        max_iterations=2,
    )

    assert decision.status == "done"


def test_decision_continue_when_verification_fails_and_retry_allowed() -> None:
    decision = DecisionEngine().decide(
        agent_success(),
        [verification("failed")],
        iteration=1,
        max_iterations=2,
    )

    assert decision.status == "continue"
    assert decision.follow_up_prompt is not None
    assert "Previous verification failed" in decision.follow_up_prompt


def test_decision_blocked_when_max_iterations_reached() -> None:
    decision = DecisionEngine().decide(
        agent_success(),
        [verification("failed")],
        iteration=2,
        max_iterations=2,
    )

    assert decision.status == "blocked"
    assert "Verification failed after" in decision.reason


def test_decision_blocked_without_verification_results() -> None:
    decision = DecisionEngine().decide(
        agent_success(),
        [],
        iteration=1,
        max_iterations=2,
    )

    assert decision.status == "blocked"
    assert decision.reason == "No verification commands configured"


def test_decision_blocks_policy_verification_result_without_retry() -> None:
    decision = DecisionEngine().decide(
        agent_success(),
        [
            VerificationResult(
                name="push",
                status="needs_approval",
                exit_code=None,
                stdout="",
                stderr="",
                error="Requires approval: git push",
            )
        ],
        iteration=1,
        max_iterations=3,
    )

    assert decision.status == "blocked"
    assert decision.follow_up_prompt is None
    assert "Verification blocked by policy" in decision.reason


def test_decision_follow_up_prompt_truncates_large_output() -> None:
    decision = DecisionEngine().decide(
        agent_success(),
        [failed_verification("unit", stderr="x" * 5000)],
        iteration=1,
        max_iterations=2,
    )

    assert decision.follow_up_prompt is not None
    assert len(decision.follow_up_prompt) <= DecisionEngine.MAX_FOLLOW_UP_PROMPT_CHARS
    assert "... truncated ..." in decision.follow_up_prompt


def test_decision_follow_up_prompt_limits_failed_check_count() -> None:
    decision = DecisionEngine().decide(
        agent_success(),
        [
            failed_verification("one"),
            failed_verification("two"),
            failed_verification("three"),
            failed_verification("four"),
        ],
        iteration=1,
        max_iterations=2,
    )

    assert decision.follow_up_prompt is not None
    assert "Check: one" in decision.follow_up_prompt
    assert "Check: three" in decision.follow_up_prompt
    assert "Check: four" not in decision.follow_up_prompt
    assert "1 more failed check(s) omitted" in decision.follow_up_prompt
