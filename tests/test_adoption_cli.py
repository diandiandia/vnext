import json
from pathlib import Path

from reachable_audit.cli import main
from reachable_audit.planning import _stable_id
from reachable_audit.campaign import CampaignManager
from reachable_audit.task_budget import budget_status


def test_init_freezes_adoption_flags_and_preserves_repeat(tmp_path: Path, capsys):
    target = tmp_path / "target"
    target.mkdir()
    args = ["init", str(target), "--snapshot-id", "fixture:adoption",
            "--campaign-id", "CMP-adoption", "--state-dir", str(tmp_path / "state")]
    assert main(args + ["--coverage-critic", "--domain-guidance"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert {"coverage_critic_v1", "domain_guidance_v1"} <= set(result["constraints"])
    assert main(args) == 0
    assert json.loads(capsys.readouterr().out)["constraints"] == result["constraints"]
    assert main(args + ["--no-coverage-critic"]) == 2
    assert "reused with different data" in capsys.readouterr().err.lower()


def test_identity_does_not_fold_unicode_paths_or_reorder_tuple():
    composed = "src/caf\u00e9.py"
    decomposed = "src/cafe\u0301.py"
    assert _stable_id("WU", "snapshot", composed) != _stable_id("WU", "snapshot", decomposed)
    assert _stable_id("WU", "component-a", "entry-b") != _stable_id("WU", "entry-b", "component-a")
    assert _stable_id("WU", "snapshot", composed) == _stable_id("WU", "snapshot", composed)


def test_budget_cli_uses_same_durable_policy_and_status(tmp_path: Path, capsys):
    target = tmp_path / "target"
    target.mkdir()
    state = tmp_path / "state"
    policy_path = tmp_path / "policy.json"
    policy = {
        "totals": {"agent_runs": 20}, "default_attempt_budget": {"agent_runs": 1},
        "protected_reserve": {"agent_runs": 8},
    }
    policy_path.write_text(json.dumps(policy), encoding="utf-8")
    assert main([
        "init", str(target), "--campaign-id", "CMP-budget-cli",
        "--snapshot-id", "fixture:budget-cli", "--state-dir", str(state),
        "--task-budget-policy", str(policy_path),
    ]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["budget"]["task_budget_policy"] == policy
    assert main(["task-budget-status", str(target), "CMP-budget-cli",
                 "--state-dir", str(state)]) == 0
    output = json.loads(capsys.readouterr().out)
    with CampaignManager(target, state) as manager:
        assert output == budget_status(manager, "CMP-budget-cli")
