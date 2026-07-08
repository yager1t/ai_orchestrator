import json

from ai_orchestrator.cli.app import main
from ai_orchestrator.evaluation import run_all_suites, run_golden_suite


def test_golden_suite_executes_tasks_and_tracks_zero_unsafe_actions() -> None:
    summary = run_golden_suite()

    assert summary.suite == "golden"
    assert summary.total == 3
    assert summary.executed_count == summary.total
    assert summary.passed == summary.total
    assert summary.pass_rate == 1.0
    assert summary.recovery_total > 0
    assert summary.recovery_rate == 1.0
    assert summary.chaos_count == 0
    assert summary.security_red_team_count == 0
    assert summary.unsafe_action_count == 0
    assert {result.actual_status for result in summary.results} == {"done", "blocked"}
    assert all(result.executed for result in summary.results)


def test_all_evaluation_suite_includes_chaos_and_redteam() -> None:
    summary = run_all_suites()

    assert summary.suite == "all"
    assert summary.total == 12
    assert summary.executed_count == summary.total
    assert summary.passed == summary.total
    assert summary.chaos_count == 5
    assert summary.security_red_team_count == 4
    assert summary.unsafe_action_count == 0


def test_eval_golden_prints_summary(capsys, tmp_path) -> None:
    exit_code = main(["eval", "golden", "--repo", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Golden evaluation" in output
    assert "executed: 3" in output
    assert "unsafe_action_count: 0" in output
    assert "security_red_team_scenarios: 0" in output
    assert "golden-docs-safe: pass expected=done actual=done" in output


def test_eval_golden_json_output(capsys, tmp_path) -> None:
    exit_code = main(["eval", "golden", "--repo", str(tmp_path), "--json"])
    output = capsys.readouterr().out

    payload = json.loads(output)
    assert exit_code == 0
    assert payload["suite"] == "golden"
    assert payload["executed_count"] == 3
    assert payload["unsafe_action_count"] == 0
    assert payload["chaos_count"] == 0
    assert payload["results"][0]["executed"] is True


def test_eval_split_commands_print_suite_summaries(capsys, tmp_path) -> None:
    chaos_exit = main(["eval", "chaos", "--repo", str(tmp_path)])
    chaos_output = capsys.readouterr().out
    redteam_exit = main(["eval", "redteam", "--repo", str(tmp_path)])
    redteam_output = capsys.readouterr().out
    all_exit = main(["eval", "all", "--repo", str(tmp_path)])
    all_output = capsys.readouterr().out

    assert chaos_exit == 0
    assert "Chaos evaluation" in chaos_output
    assert "chaos_scenarios: 5" in chaos_output
    assert redteam_exit == 0
    assert "Redteam evaluation" in redteam_output
    assert "security_red_team_scenarios: 4" in redteam_output
    assert all_exit == 0
    assert "All evaluation" in all_output
    assert "total: 12" in all_output
