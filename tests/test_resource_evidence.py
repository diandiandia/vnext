from pathlib import Path
import json

import pytest

from reachable_audit.batch_workflow import BatchWorkflow
from reachable_audit.campaign import CampaignManager
from reachable_audit.cli import main
from reachable_audit.inventory import build_inventory
from reachable_audit.models import ModelError
from reachable_audit.planning import create_audit_plan


def test_resource_registration_is_frozen_and_not_a_call_chain(tmp_path: Path) -> None:
    (tmp_path / "main.py").write_text("VALUE = 1\n")
    (tmp_path / "logging.xml").write_text("<configuration/>\n\n")
    inventory = build_inventory(tmp_path, "fixture:resources")
    plan = create_audit_plan(
        campaign_id="CMP-resources", inventory=inventory, category_families=["STATE"],
    )
    with CampaignManager(tmp_path) as manager:
        manager.create_campaign(campaign_id="CMP-resources", snapshot_id=inventory.snapshot_id)
        manager.record_inventory(campaign_id="CMP-resources", inventory=inventory)
        manager.record_plan(campaign_id="CMP-resources", plan=plan, inventory=inventory)
        workflow = BatchWorkflow(manager, "CMP-resources", plan.batches[0].batch_id)
        with pytest.raises(ModelError, match="registered"):
            workflow._validate_evidence_reference("LOC-logging.xml:1", None)
        ref = manager.register_evidence_files(
            "CMP-resources", ["logging.xml"], reason="review logging configuration",
        )
        assert manager.register_evidence_files(
            "CMP-resources", ["logging.xml"], reason="review logging configuration",
        ) == ref
        workflow.run_r0()
        workflow._validate_evidence_reference("LOC-logging.xml:1", None)
        with pytest.raises(ModelError, match="inventory"):
            workflow._validate_source_location("LOC-logging.xml:1", None)
        with pytest.raises(ModelError, match="blank"):
            workflow._validate_evidence_reference("LOC-logging.xml:2", None)
        (tmp_path / "logging.xml").write_text("<changed/>\n")
        with pytest.raises(ModelError, match="changed"):
            workflow._validate_evidence_reference("LOC-logging.xml:1", None)
        with pytest.raises(ValueError, match="R0"):
            manager.register_evidence_files(
                "CMP-resources", ["logging.xml"], reason="cannot rebaseline",
            )


@pytest.mark.parametrize("path", ["../outside.xml", "/etc/hosts", ".git/config"])
def test_resource_registration_rejects_unsafe_paths(tmp_path: Path, path: str) -> None:
    with CampaignManager(tmp_path) as manager:
        manager.create_campaign(campaign_id="CMP-resource-path", snapshot_id="fixture:paths")
        manager.record_inventory(
            campaign_id="CMP-resource-path", inventory=build_inventory(tmp_path, "fixture:paths"),
        )
        with pytest.raises(ValueError):
            manager.register_evidence_files(
                "CMP-resource-path", [path], reason="unsafe synthetic path",
            )


def test_resource_registration_cli_and_symlink_rejection(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    target = tmp_path / "target"
    target.mkdir()
    state = tmp_path / "state"
    (target / "schema.xml").write_text("<schema/>\n")
    assert main([
        "init", str(target), "--state-dir", str(state),
        "--campaign-id", "CMP-cli-resource", "--snapshot-id", "fixture:resource-cli",
    ]) == 0
    assert main(["inventory", str(target), "CMP-cli-resource", "--state-dir", str(state)]) == 0
    capsys.readouterr()
    request = tmp_path / "evidence.json"
    request.write_text(json.dumps({"paths": ["schema.xml"], "reason": "approved schema"}))
    assert main([
        "evidence-register", str(target), "CMP-cli-resource", "--state-dir", str(state),
        "--input", str(request),
    ]) == 0
    ref = json.loads(capsys.readouterr().out)["artifact_id"]
    with CampaignManager(target, state) as manager:
        (target / "linked.xml").symlink_to(target / "schema.xml")
        with pytest.raises(ValueError, match="unsafe"):
            manager.register_evidence_files(
                "CMP-cli-resource", ["linked.xml"], reason="reject symbolic link",
            )
        event = manager.store.list_events(
            "CMP-cli-resource", event_type="EVIDENCE_FILES_REGISTERED",
        )[0]
        assert event.payload_ref == ref
        (target / "schema.xml").write_text("<changed/>\n")
        with pytest.raises(ValueError, match="changed"):
            manager.register_evidence_files(
                "CMP-cli-resource", ["schema.xml"], reason="no silent replacement",
            )
