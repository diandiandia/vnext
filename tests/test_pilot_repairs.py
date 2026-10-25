from dataclasses import replace
import json
from pathlib import Path

import pytest

from conftest import axis_runs_from_evidence
from reachable_audit.analysis_models import (
    DiscoveryAxis, Hypothesis, HypothesisStatus, Mechanism, MechanismCard,
)
from reachable_audit.batch_workflow import BatchWorkflow
from reachable_audit.campaign import CampaignManager
from reachable_audit.cli import main
from reachable_audit.execution import (
    DiscoveryCoordinator, ManualExecutionBackend, TaskResult, TaskStatus,
)
from reachable_audit.inventory import build_inventory
from reachable_audit.knowledge import create_category_audit_plans
from reachable_audit.models import ModelError
from reachable_audit.planning import create_audit_plan
from reachable_audit.stage_revisions import stage_recovery_plan
from test_batch_workflow import _workflow


@pytest.mark.parametrize("compact", [False, True])
@pytest.mark.parametrize("reference", [
    "LOC-app.py:1", "LOC-app.py:3", "LOC/app.py:2", "LOC-app.py:99", "LOC-../app.py:2",
    "sha256:" + "0" * 64,
])
def test_r2_rejects_bad_evidence_at_collection(
    tmp_path: Path, compact: bool, reference: str,
) -> None:
    manager, workflow, plan = _workflow(
        tmp_path, "CMP-r2-anchors", source="\ndef handle(): pass\n\n",
    )
    try:
        workflow.run_r0()
        workflow.record_r1([])
        backend = ManualExecutionBackend(manager, workflow.campaign_id)
        coordinator = DiscoveryCoordinator(workflow, backend)
        tasks = (
            coordinator.schedule_r2_compact(entrypoint_checklist=[])
            if compact else coordinator.schedule_r2(entrypoint_checklist=[])
        )
        task = tasks[0].task
        lease = backend.claim("anchor-reviewer", task_id_filter=task.task_id)
        assert lease is not None
        runs = [{
            "axis": axis, "applicability": "APPLICABLE",
            "review_altitude": "SCREENED", "evidence_refs": [reference],
            "rationale": "reviewed the source", "entrypoint_reviews": [],
        } for axis in (
            [item.value for item in DiscoveryAxis]
            if compact else [task.operation.split(":")[1]]
        )]
        output = {
            "schema_version": "1.0", "reviewed_paths": list(plan.work_units[0].source_files),
            "hypotheses": [], **({"axis_runs": runs} if compact else {"axis_run": runs[0]}),
        }
        output_ref = manager.artifacts.put_text(json.dumps(output)).artifact_id
        with pytest.raises((ModelError, FileNotFoundError)):
            backend.collect(lease, TaskResult(
                True, output_ref, "bad anchor", {"agent_runs": 1, "wall_seconds": 1},
            ))
        assert backend.poll(task.task_id).status is TaskStatus.LEASED
        for run in runs:
            run["evidence_refs"] = ["LOC-app.py:2"]
        good_ref = manager.artifacts.put_text(json.dumps(output)).artifact_id
        assert backend.collect(lease, TaskResult(
            True, good_ref, "valid anchor", {"agent_runs": 1, "wall_seconds": 1},
        )).status is TaskStatus.SUCCEEDED
    finally:
        manager.close()


@pytest.mark.parametrize("location", ["aggregate", "axis", "seed"])
def test_direct_r2_rejects_invalid_axis_and_seed_anchors(
    tmp_path: Path, location: str,
) -> None:
    manager, workflow, plan = _workflow(tmp_path, "CMP-direct-anchors")
    try:
        workflow.run_r0()
        workflow.record_r1([])
        evidence = {
            axis.value: ("LOC-app.py:999" if location == "aggregate" else "LOC-app.py:1",)
            for axis in DiscoveryAxis
        }
        runs = axis_runs_from_evidence(evidence)
        if location == "axis":
            runs = (replace(runs[0], evidence_refs=("LOC-app.py:999",)), *runs[1:])
        hypotheses = [Hypothesis(
            "HYP-bad-seed", plan.work_units[0].work_unit_id, "surface",
            ("LOC/app.py:1",), (), Mechanism("INJECTION", "command"),
            "review candidate", HypothesisStatus.NEW,
        )] if location == "seed" else []
        with pytest.raises(ModelError):
            workflow.record_r2(
                hypotheses, axis_evidence=evidence, axis_runs=runs,
            )
        assert workflow._stage_event("R2_COMPLETED") is None
    finally:
        manager.close()


@pytest.mark.parametrize("bundled", [False, True])
@pytest.mark.parametrize("fail_on", [
    "TASK_SUBMITTED", "R4_SCREENING_COVERAGE_RECORDED", "SCREENING_VALIDATION",
])
def test_r4_mixed_schedule_rolls_back_every_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bundled: bool, fail_on: str,
) -> None:
    (tmp_path / "a.py").write_text("STATE = {}\n")
    (tmp_path / "b.py").write_text("STATE = {}\n")
    inventory = build_inventory(tmp_path, "fixture:mixed")
    plan = create_audit_plan(
        campaign_id="CMP-mixed", inventory=inventory, category_families=["STATE"],
        max_source_files_per_work_unit=1, max_source_files_per_batch=2,
        max_work_units_per_batch=2,
    )
    assert len(plan.work_units) == 2
    with CampaignManager(tmp_path) as manager:
        manager.create_campaign(campaign_id=plan.campaign_id, snapshot_id=inventory.snapshot_id)
        manager.record_inventory(campaign_id=plan.campaign_id, inventory=inventory)
        manager.record_plan(campaign_id=plan.campaign_id, plan=plan, inventory=inventory)
        workflow = BatchWorkflow(manager, plan.campaign_id, plan.batches[0].batch_id)
        workflow.run_r0()
        workflow.record_r1([])
        evidence = {axis.value: ("LOC-a.py:1",) for axis in DiscoveryAxis}
        runs = tuple(
            replace(
                run, work_unit_id=unit.work_unit_id,
            )
            for index, unit in enumerate(plan.work_units)
            for run in axis_runs_from_evidence(
                evidence, not_applicable=tuple(evidence) if index == 0 else (),
            )
        )
        workflow.record_r2([], axis_evidence=evidence, axis_runs=runs)
        workflow.record_r3([])
        workflow.record_revival_selection([], rationale="no unreachable hypotheses", evidence_refs=("LOC-a.py:1",))
        workflow.complete_r35()
        backend = ManualExecutionBackend(manager, plan.campaign_id)
        coordinator = DiscoveryCoordinator(workflow, backend)
        card = next(
            card for card in coordinator.knowledge_catalog.cards.values()
            if card["family"] == "STATE" and "python" in card["language_applicability"]
        )
        workflow.record_category_audit_plan(
            create_category_audit_plans(plan.work_units, [MechanismCard.from_dict(card)], budget={}),
        )
        schedule = coordinator.schedule_r4_bundled if bundled else coordinator.schedule_r4
        before = manager.store.list_events(plan.campaign_id)
        original = manager.store._append_event_tx

        def failing_append(**kwargs):
            result = original(**kwargs)
            if kwargs.get("event_type") == fail_on:
                raise RuntimeError("injected scheduling failure after write")
            return result

        with monkeypatch.context() as patch:
            patch.setattr(manager.store, "_append_event_tx", failing_append)
            if fail_on == "SCREENING_VALIDATION":
                def invalid_screening(_run):
                    raise ModelError("screening evidence resolves to a blank line")

                patch.setattr(workflow, "validate_category_evidence", invalid_screening)
                with pytest.raises(ModelError, match="blank line"):
                    schedule()
            else:
                with pytest.raises(RuntimeError, match="injected scheduling failure"):
                    schedule()
        assert manager.store.list_events(plan.campaign_id) == before
        assert backend.list_tasks() == ()
        tasks = schedule()
        assert len(tasks) == 1
        after = manager.store.list_events(plan.campaign_id)
        assert schedule() == tasks
        assert manager.store.list_events(plan.campaign_id) == after


def test_recovery_cli_is_read_only_and_uses_active_replacements(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    with CampaignManager(tmp_path, tmp_path / "state") as manager:
        campaign = manager.create_campaign(snapshot_id="fixture:recovery", campaign_id="CMP-recovery")
        store = manager.store
        marker = {
            "campaign_id": campaign.campaign_id, "batch_id": "B-1",
            "entity_type": "batch_stage", "entity_id": "B-1", "actor": "test",
        }
        store.append_event(
            **marker, event_type="STAGE_PROJECTION_INVALIDATED", idempotency_key="invalidate",
            payload={"target_event_id": "old-r2", "target_stage": "R2_COMPLETED"},
        )
        before = store.list_events(campaign.campaign_id)
        plan = stage_recovery_plan(before)
        assert plan["batches"][0]["steps"] == [{
            "stage": "R2_COMPLETED", "commands": ["task-schedule-r2", "task-commit-r2"],
        }]
        assert main([
            "recovery-plan", str(tmp_path), campaign.campaign_id,
            "--state-dir", str(tmp_path / "state"),
        ]) == 0
        result = json.loads(capsys.readouterr().out)
        assert result["automatic_result_reuse"] is False
        assert result["read_only"] is True
        assert store.list_events(campaign.campaign_id) == before
        store.append_event(
            **marker, event_type="R2_COMPLETED", idempotency_key="replacement",
            payload={"revision_id": "new-r2"},
        )
        assert stage_recovery_plan(store.list_events(campaign.campaign_id))["batches"] == []
