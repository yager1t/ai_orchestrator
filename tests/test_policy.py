from ai_orchestrator.policy.engine import PolicyEngine


def test_policy_denies_codex_auth_read() -> None:
    decision = PolicyEngine().evaluate_command("cat ~/.codex/auth.json")

    assert decision.action == "deny"


def test_policy_asks_on_git_push() -> None:
    decision = PolicyEngine().evaluate_command("git push origin main")

    assert decision.action == "ask"


def test_policy_allows_read_only_command() -> None:
    decision = PolicyEngine().evaluate_command("git status --short")

    assert decision.action == "allow"


def test_policy_uses_custom_deny_patterns() -> None:
    decision = PolicyEngine(deny_patterns=["custom-secret"]).evaluate_command("custom-secret read")

    assert decision.action == "deny"


def test_policy_preserves_default_deny_patterns_with_custom_rules() -> None:
    decision = PolicyEngine(deny_patterns=["custom-secret"]).evaluate_command(
        "cat ~/.codex/auth.json"
    )

    assert decision.action == "deny"


def test_policy_uses_custom_approval_patterns() -> None:
    decision = PolicyEngine(ask_patterns=["deploy"]).evaluate_command("deploy production")

    assert decision.action == "ask"
