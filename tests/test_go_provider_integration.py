import json
from pathlib import Path
import sys

import pytest

from reachable_audit.analysis_models import Surface
from reachable_audit.batch_workflow import BatchWorkflow
from reachable_audit.campaign import CampaignManager
from reachable_audit.cli import main
from reachable_audit.execution import DiscoveryCoordinator, ManualExecutionBackend
from reachable_audit.inventory import build_inventory
from reachable_audit.planning import create_audit_plan


def test_cli_go_profile_uses_registered_offline_harness(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    target = tmp_path / "target"
    target.mkdir()
    state = tmp_path / "state"
    assert main([
        "init", str(target), "--state-dir", str(state),
        "--campaign-id", "CMP-runtime", "--snapshot-id", "fixture:runtime",
    ]) == 0
    capsys.readouterr()
    harness_input = tmp_path / "harness.json"
    harness_input.write_text(json.dumps({
        "profile": "go-offline",
        "command": [
            sys.executable, "-c",
            "import os; print(os.environ['GOPROXY'], os.environ['GOTOOLCHAIN'])",
        ],
        "timeout_seconds": 5,
        "hypothesis_id": "HYP-runtime",
    }))
    assert main([
        "harness-run", str(target), "CMP-runtime", "--state-dir", str(state),
        "--input", str(harness_input),
    ]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["exit_code"] == 0
    assert result["resource_limits"]["address_space_bytes"] == 8 * 1024**3
    with CampaignManager(target, state) as manager:
        assert manager.artifacts.get_bytes(result["stdout_artifact_id"]).strip() == (
            b"off local"
        )
        events = manager.store.list_events(
            "CMP-runtime", event_type="HARNESS_EXECUTION_COMPLETED",
        )
        assert len(events) == 1
        assert events[0].payload_ref == result["execution_artifact_id"]
    assert main([
        "resource-cleanup", str(target), "CMP-runtime", "--state-dir", str(state),
    ]) == 0
    assert json.loads(capsys.readouterr().out)["failures"] == []


@pytest.mark.parametrize("enabled", [False, True])
def test_cli_freezes_experimental_go_provider_choice(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], enabled: bool,
) -> None:
    target = tmp_path / "target"
    target.mkdir()
    state = tmp_path / "state"
    args = [
        "init", str(target), "--state-dir", str(state),
        "--campaign-id", "CMP-provider", "--snapshot-id", "fixture:provider",
    ]
    if enabled:
        args.append("--experimental-go-hotspots")
    assert main(args) == 0
    record = json.loads(capsys.readouterr().out)
    assert ("experimental_go_hotspots" in record["constraints"]) is enabled
    with CampaignManager(target, state) as manager:
        assert (
            "experimental_go_hotspots"
            in manager.store.get_campaign("CMP-provider").constraints
        ) is enabled


@pytest.mark.parametrize("enabled", [False, True])
def test_r1_and_both_r2_modes_receive_frozen_go_provider_choice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, enabled: bool,
) -> None:
    import reachable_audit.execution as execution

    (tmp_path / "app.py").write_text("def handle(value):\n    return value\n")
    inventory = build_inventory(tmp_path, "fixture:provider")
    plan = create_audit_plan(
        campaign_id="CMP-provider", inventory=inventory,
        category_families=["INJECTION"],
    )
    with CampaignManager(tmp_path) as manager:
        manager.create_campaign(
            campaign_id="CMP-provider", snapshot_id="fixture:provider",
            constraints=("experimental_go_hotspots",) if enabled else (),
        )
        manager.record_inventory(campaign_id="CMP-provider", inventory=inventory)
        manager.record_plan(campaign_id="CMP-provider", plan=plan, inventory=inventory)
        workflow = BatchWorkflow(manager, "CMP-provider", plan.batches[0].batch_id)
        workflow.run_r0()
        calls = []
        original_scan = execution.scan_work_unit_hotspots

        def observed_scan(root, paths, **kwargs):  # type: ignore[no-untyped-def]
            calls.append(kwargs)
            return original_scan(root, paths, **kwargs)

        monkeypatch.setattr(execution, "scan_work_unit_hotspots", observed_scan)
        coordinator = DiscoveryCoordinator(
            workflow, ManualExecutionBackend(manager, "CMP-provider"),
        )
        coordinator.schedule_r1()
        unit = plan.work_units[0]
        workflow.record_r1([Surface(
            "SURF-provider", unit.work_unit_id, unit.component_id,
            "entry", "app.py", "handle", "remote", ("LOC-app.py:1",),
        )])
        coordinator.schedule_r2(entrypoint_checklist=())
        coordinator.schedule_r2_compact(entrypoint_checklist=())
        assert len(calls) == 3
        assert all(call["enable_go"] is enabled for call in calls)
        assert all(set(call["expected_digests"]) == {"app.py"} for call in calls)
