from pathlib import Path
import json

import pytest

from reachable_audit.analysis_models import (
    Applicability,
    AxisRun,
    DiscoveryAxis,
    EvidenceGrade,
    Hypothesis,
    HypothesisStatus,
    Mechanism,
    Surface,
    VerdictKind,
    VerdictSubmission,
)
from reachable_audit.batch_workflow import BatchWorkflow
from reachable_audit.campaign import CampaignManager
from reachable_audit.inventory import build_inventory
from reachable_audit.models import BatchStatus, ModelError
from reachable_audit.planning import create_audit_plan
from conftest import axis_runs_from_evidence


def _workflow(
    tmp_path: Path,
    campaign_id: str = "CMP-slice",
    source: str = "def handle(value):\n    return value\n",
):
    (tmp_path / "app.py").write_text(source, encoding="utf-8")
    inventory = build_inventory(tmp_path, "fixture:slice")
    plan = create_audit_plan(
        campaign_id=campaign_id,
        inventory=inventory,
        category_families=["INJECTION"],
    )
    manager = CampaignManager(tmp_path)
    manager.create_campaign(campaign_id=campaign_id, snapshot_id="fixture:slice")
    manager.record_inventory(campaign_id=campaign_id, inventory=inventory)
    manager.record_plan(campaign_id=campaign_id, plan=plan, inventory=inventory)
    return manager, BatchWorkflow(manager, campaign_id, plan.batches[0].batch_id), plan


def test_r0_r3_slice_records_canonical_verdict_and_partial_report(tmp_path: Path) -> None:
    manager, workflow, plan = _workflow(tmp_path)
    work_unit = plan.work_units[0]
    try:
        workflow.run_r0()
        workflow.record_r1([Surface(
            surface_id="SURF-handler",
            work_unit_id=work_unit.work_unit_id,
            component_id=work_unit.component_id,
            kind="function_entry",
            entry_path="app.py",
            entry_symbol="handle",
            principal="remote_unauthenticated",
            evidence_refs=("LOC-app.py:1",),
        )])
        workflow.record_r2(
            [Hypothesis(
                hypothesis_id="HYP-injection",
                work_unit_id=work_unit.work_unit_id,
                origin_axis="surface",
                seed_refs=("SURF-handler",),
                surface_ids=("SURF-handler",),
                mechanism=Mechanism("INJECTION", "unsafe-evaluation"),
                claim="untrusted input reaches an evaluation sink",
                status=HypothesisStatus.NEW,
            )],
            axis_evidence={
                "surface": ("LOC-app.py:1",),
                "mechanism": ("LOC-app.py:2",),
                "state": ("EVID-state",),
                "fix_variant": ("EVID-fix",),
                "boundary": ("EVID-boundary",),
                "differential": ("EVID-differential",),
            },
            axis_runs=axis_runs_from_evidence({
                "surface": ("LOC-app.py:1",),
                "mechanism": ("LOC-app.py:2",),
                "state": ("EVID-state",),
                "fix_variant": ("EVID-fix",),
                "boundary": ("EVID-boundary",),
                "differential": ("EVID-differential",),
            }),
        )
        edge_ref = manager.artifacts.put_text("validated source-to-sink edge").artifact_id
        workflow.record_r3([VerdictSubmission(
            hypothesis_id="HYP-injection",
            verdict=VerdictKind.REACHABLE,
            evidence_grade=EvidenceGrade.EDGE_PROVEN,
            principal="remote_unauthenticated",
            preconditions=(),
            call_chain=("LOC-app.py:1", "LOC-app.py:2"),
            edge_evidence_ids=(edge_ref,),
            blocking_evidence_ids=(),
            experiment_ids=(),
            rationale="the direct data-flow edge has no intervening guard",
        )])
        report = workflow.build_r0_r3_report()

        assert report["status"] == "PASS"
        assert report["verdict_counts"] == {"REACHABLE": 1}
        assert report["batch_complete"] is False
        assert manager.store.get_batch(
            "CMP-slice", plan.batches[0].batch_id
        ).status is BatchStatus.RUNNING
        verdict_event = next(
            event
            for event in manager.store.list_events("CMP-slice")
            if event.event_type == "VERDICT_ADJUDICATED"
        )
        assert verdict_event.entity_id == "HYP-injection"
    finally:
        manager.close()


def test_clean_slice_is_valid_when_all_discovery_axes_have_dispositions(
    tmp_path: Path,
) -> None:
    manager, workflow, _ = _workflow(tmp_path, "CMP-clean")
    try:
        workflow.run_r0()
        workflow.record_r1([])
        workflow.record_r2(
            [],
            axis_evidence={
                "surface": ("EVID-surface-review",),
                "mechanism": ("EVID-mechanism-review",),
                "state": ("EVID-state-review",),
                "fix_variant": ("EVID-fix-review",),
                "boundary": ("EVID-boundary-review",),
                "differential": ("EVID-differential-review",),
            },
            axis_runs=axis_runs_from_evidence({
                "surface": ("EVID-surface-review",),
                "mechanism": ("EVID-mechanism-review",),
                "state": ("EVID-state-review",),
                "fix_variant": ("EVID-fix-review",),
                "boundary": ("EVID-boundary-review",),
                "differential": ("EVID-differential-review",),
            }),
        )
        workflow.record_r3([])
        report = workflow.build_r0_r3_report()
        assert report["status"] == "PASS"
        assert report["hypothesis_count"] == 0
        assert report["verdict_counts"] == {}
    finally:
        manager.close()


def test_r2_axis_dispositions_are_scoped_per_work_unit(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def a(): pass\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("def b(): pass\n", encoding="utf-8")
    inventory = build_inventory(tmp_path, "fixture:multi-work-unit-r2")
    plan = create_audit_plan(
        campaign_id="CMP-multi-r2",
        inventory=inventory,
        category_families=["STATE"],
        max_source_files_per_work_unit=1,
        max_source_files_per_batch=2,
        max_work_units_per_batch=2,
    )
    manager = CampaignManager(tmp_path)
    try:
        manager.create_campaign(
            campaign_id="CMP-multi-r2", snapshot_id="fixture:multi-work-unit-r2"
        )
        manager.record_inventory(campaign_id="CMP-multi-r2", inventory=inventory)
        manager.record_plan(campaign_id="CMP-multi-r2", plan=plan, inventory=inventory)
        workflow = BatchWorkflow(manager, "CMP-multi-r2", plan.batches[0].batch_id)
        workflow.run_r0()
        workflow.record_r1([])
        evidence = {
            axis.value: (f"ART-{axis.value}",) for axis in DiscoveryAxis
        }
        axis_runs = tuple(
            AxisRun(
                axis=axis,
                applicability=Applicability.APPLICABLE,
                evidence_refs=(f"ART-{unit.work_unit_id}-{axis.value}",),
                rationale="reviewed this axis in this Work Unit",
                work_unit_id=unit.work_unit_id,
            )
            for unit in plan.work_units
            for axis in DiscoveryAxis
        )
        workflow.record_r2([], axis_evidence=evidence, axis_runs=axis_runs)
        event = next(
            item for item in manager.store.list_events("CMP-multi-r2")
            if item.event_type == "R2_COMPLETED"
        )
        artifact = json.loads(manager.artifacts.get_bytes(event.payload_ref))
        assert len(artifact["axis_runs"]) == 12
        assert len({(item["work_unit_id"], item["axis"]) for item in artifact["axis_runs"]}) == 12
    finally:
        manager.close()


def test_r1_rejects_surface_outside_work_unit_scope(tmp_path: Path) -> None:
    manager, workflow, plan = _workflow(tmp_path, "CMP-scope")
    try:
        workflow.run_r0()
        with pytest.raises(ModelError, match="outside Work Unit"):
            workflow.record_r1([Surface(
                surface_id="SURF-outside",
                work_unit_id=plan.work_units[0].work_unit_id,
                component_id=plan.work_units[0].component_id,
                kind="entry",
                entry_path="outside.py",
                entry_symbol=None,
                principal="local_user",
                evidence_refs=("LOC-outside.py:1",),
            )])
    finally:
        manager.close()


def test_r1_rejects_a_non_source_or_out_of_range_anchor(tmp_path: Path) -> None:
    manager, workflow, plan = _workflow(tmp_path, "CMP-anchor")
    try:
        workflow.run_r0()
        with pytest.raises(ModelError, match="source anchor is outside"):
            workflow.record_r1([Surface(
                surface_id="SURF-bad-anchor",
                work_unit_id=plan.work_units[0].work_unit_id,
                component_id=plan.work_units[0].component_id,
                kind="entry",
                entry_path="app.py",
                entry_symbol="handle",
                principal="remote",
                evidence_refs=("LOC-app.py:99",),
            )])
    finally:
        manager.close()


def test_phase3_rejects_empirical_evidence_grade(tmp_path: Path) -> None:
    with pytest.raises(ModelError, match="Phase 4 R5"):
        VerdictSubmission.from_dict({
            "hypothesis_id": "HYP-1",
            "verdict": "REACHABLE",
            "evidence_grade": "empirically_confirmed",
            "principal": "remote",
            "call_chain": ["LOC-1"],
            "edge_evidence_ids": ["EV-1"],
            "rationale": "runtime confirmation claimed too early",
        })