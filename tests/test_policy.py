from ai_orchestrator.policy.engine import PolicyEngine


def test_policy_denies_codex_auth_read() -> None:
    decision = PolicyEngine().evaluate_command("cat ~/.codex/auth.json")

    assert decision.action == "deny"


def test_policy_asks_on_git_push() -> None:
    decision = PolicyEngine().evaluate_command("git push origin main")

    assert decision.action == "ask"


def test_policy_asks_on_pip_install() -> None:
    decision = PolicyEngine().evaluate_command("pip install example-package")

    assert decision.action == "ask"


def test_policy_asks_on_python_module_pip_install() -> None:
    decision = PolicyEngine().evaluate_command("python -m pip install example-package")

    assert decision.action == "ask"


def test_policy_asks_on_rm_recursive_force() -> None:
    decision = PolicyEngine().evaluate_command("rm -rf build")

    assert decision.action == "ask"


def test_policy_denies_rm_recursive_force_root() -> None:
    decision = PolicyEngine().evaluate_command("rm -rf /")

    assert decision.action == "deny"


def test_policy_denies_rm_recursive_force_root_after_env_assignment() -> None:
    decision = PolicyEngine().evaluate_command("FOO=bar rm -rf /")

    assert decision.action == "deny"


def test_policy_denies_rm_recursive_force_root_after_env_wrapper() -> None:
    decision = PolicyEngine().evaluate_command("env FOO=bar rm -rf /")

    assert decision.action == "deny"


def test_policy_denies_rm_recursive_force_root_after_sudo_wrapper() -> None:
    decision = PolicyEngine().evaluate_command("sudo -u root rm -rf /")

    assert decision.action == "deny"


def test_policy_denies_rm_recursive_force_root_after_nice_wrapper() -> None:
    decision = PolicyEngine().evaluate_command("nice -n 10 rm -rf /")

    assert decision.action == "deny"


def test_policy_denies_rm_recursive_force_root_after_xargs_wrapper() -> None:
    decision = PolicyEngine().evaluate_command("xargs rm -rf /")

    assert decision.action == "deny"


def test_policy_uses_newline_as_command_separator() -> None:
    decision = PolicyEngine().evaluate_command("git status\nrm -rf /")

    assert decision.action == "deny"


def test_policy_does_not_match_git_push_url() -> None:
    decision = PolicyEngine().evaluate_command("git push-url origin")

    assert decision.action == "allow"


def test_policy_does_not_match_pip_install_single_token() -> None:
    decision = PolicyEngine().evaluate_command("pip-install example-package")

    assert decision.action == "allow"


def test_policy_does_not_match_git_rm_recursive_force() -> None:
    decision = PolicyEngine().evaluate_command("git rm -rf obsolete-file")

    assert decision.action == "allow"


def test_policy_matches_dangerous_command_inside_argv_argument() -> None:
    decision = PolicyEngine().evaluate_argv(["codex", "exec", "git push origin main"])

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


def test_policy_keeps_custom_patterns_as_substrings() -> None:
    decision = PolicyEngine(ask_patterns=["pip-install"]).evaluate_command(
        "run pip-install helper"
    )

    assert decision.action == "ask"
