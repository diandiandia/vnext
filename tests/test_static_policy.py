import json
from pathlib import Path
import sys

import pytest

from reachable_audit.analysis_models import CampaignClosure
from reachable_audit.campaign import CampaignManager
from reachable_audit.campaign_closure import CampaignCloser
from reachable_audit.cli import main
from reachable_audit.execution import DiscoveryCoordinator, ManualExecutionBackend
from reachable_audit.experiments.runner import run_harness
from reachable_audit.models import dynamic_execution_policy, ModelError
from test_batch_workflow import _workflow
from test_campaign_closure import _closable_campaign


def _freeze_static_creation(monkeypatch: pytest.MonkeyPatch) -> None:
    create = CampaignManager.create_campaign

    def create_static(self, **kwargs):
        kwargs["constraints"] = (*kwargs.get("constraints", ()), "static_only")
        return create(self, **kwargs)

    monkeypatch.setattr(CampaignManager, "create_campaign", create_static)


@pytest.mark.parametrize("static_only", [False, True])
def test_init_status_and_export_policy(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], static_only: bool,
) -> None:
    target = tmp_path / "target"
    target.mkdir()
    state = tmp_path / "state"
    args = [
        "init", str(target), "--state-dir", str(state),
        "--snapshot-id", "fixture:policy", "--campaign-id", "CMP-policy",
    ]
    if static_only:
        args += ["--static-only", "--static-challenges"]
    assert main(args) == 0
    created = json.loads(capsys.readouterr().out)
    expected = "STATIC_ONLY" if static_only else "UNDECLARED"
    assert ("static_only" in created["constraints"]) is static_only
    assert ("static_challenges" in created["constraints"]) is static_only
    with CampaignManager(target, state) as manager:
        campaign = manager.store.get_campaign("CMP-policy")
        assert dynamic_execution_policy(campaign) == expected
        assert campaign.constraints == (
            ("static_challenges", "static_only") if static_only else ()
        )
    exported = json.loads((state / "campaign.json").read_text())
    assert exported["dynamic_execution_policy"] == expected
    assert main(["status", str(target), "--state-dir", str(state)]) == 0
    status = json.loads(capsys.readouterr().out)["campaigns"][0]
    assert status["dynamic_execution_policy"] == expected


@pytest.mark.parametrize("constraints", [
    (), ("offline",), ("static_challenges",), ("STATIC_ONLY",),
    ("experimental_go_hotspots",),
])
def test_policy_does_not_infer_declarations(
    tmp_path: Path, constraints: tuple[str, ...],
) -> None:
    with CampaignManager(tmp_path) as manager:
        campaign = manager.create_campaign(
            snapshot_id="fixture:policy", constraints=constraints,
        )
        assert dynamic_execution_policy(campaign) == "UNDECLARED"


@pytest.mark.parametrize("static_only", [False, True])
def test_task_input_includes_frozen_campaign_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, static_only: bool,
) -> None:
    if static_only:
        _freeze_static_creation(monkeypatch)
    manager, workflow, _ = _workflow(tmp_path)
    try:
        workflow.run_r0()
        backend = ManualExecutionBackend(manager, workflow.campaign_id)
        coordinator = DiscoveryCoordinator(workflow, backend)
        task = coordinator.schedule_r1()[0].task
        value = json.loads(manager.artifacts.get_bytes(task.input_refs[0]))
        assert value["dynamic_execution_policy"] == (
            "STATIC_ONLY" if static_only else "UNDECLARED"
        )
        assert "host authorization" in value["execution_policy"]
        assert "single call" in value["output_discipline"]
        if static_only:
            assert "Campaign forbids dynamic execution" in value["execution_policy"]
        plain_ref = coordinator._put_json({"schema_version": "1.0"})
        assert "dynamic_execution_policy" not in json.loads(
            manager.artifacts.get_bytes(plain_ref)
        )
    finally:
        manager.close()


@pytest.mark.parametrize("static_only", [False, True])
def test_report_includes_policy_without_changing_experiment_requirement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, static_only: bool,
) -> None:
    if static_only:
        _freeze_static_creation(monkeypatch)
    manager, plan = _closable_campaign(tmp_path, not_feasible=True)
    try:
        report = CampaignCloser(manager, "CMP-r4", plan).close(CampaignClosure(
            architecture_overview="A static policy fixture.",
            unreviewed_scope=(), residual_risks=(), limitations=(), lessons=(),
            knowledge_nominations=(), skill_issues=(),
        ))
        expected = "STATIC_ONLY" if static_only else "UNDECLARED"
        assert report["dynamic_execution_policy"] == expected
        assert f"Dynamic execution policy: `{expected}`" in CampaignCloser._markdown(report)
        assessment = report["hypothesis_outcomes"][0]["r5_assessment"]
        assert assessment["experiment_required"] is True
        assert assessment["disposition"] == "NOT_FEASIBLE"
    finally:
        manager.close()


@pytest.mark.parametrize("via_cli", [False, True])
def test_static_campaign_rejects_harness_before_side_effects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str], via_cli: bool,
) -> None:
    target = tmp_path / "target"
    target.mkdir()
    state = tmp_path / "state"
    with CampaignManager(target, state) as manager:
        manager.create_campaign(
            campaign_id="CMP-static", snapshot_id="fixture:policy",
            constraints=("static_only",),
        )
        before_events = manager.store.list_events("CMP-static")
        before_files = sorted(str(p.relative_to(state)) for p in state.rglob("*"))

        def forbidden(*args, **kwargs):
            pytest.fail("static-only rejection must precede harness side effects")

        monkeypatch.setattr(
            "reachable_audit.experiments.runner.create_campaign_temp_directory", forbidden,
        )
        monkeypatch.setattr("reachable_audit.experiments.runner.subprocess.Popen", forbidden)
        monkeypatch.setattr(manager.artifacts, "put_text", forbidden)
        command = [sys.executable, "-c", "print('must not run')"]
        if via_cli:
            input_path = tmp_path / "harness.json"
            input_path.write_text(json.dumps({"command": command}))
            assert main([
                "harness-run", str(target), "CMP-static",
                "--state-dir", str(state), "--input", str(input_path),
            ]) == 2
            assert "static-only" in capsys.readouterr().err
        else:
            with pytest.raises(ModelError, match="static-only"):
                run_harness(manager, "CMP-static", command=command, profile="go-offline")
        assert manager.store.list_events("CMP-static") == before_events
        assert sorted(str(p.relative_to(state)) for p in state.rglob("*")) == before_files
