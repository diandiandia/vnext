from pathlib import Path

import pytest

from reachable_audit.analysis_models import (
    Adjudication,
    AdjudicationActor,
    AttackAngle,
    EvidenceGrade,
    Hypothesis,
    HypothesisStatus,
    Mechanism,
    Refutation,
    SourceVerification,
    Surface,
    VerdictKind,
    VerdictSubmission,
)
from reachable_audit.batch_workflow import BatchWorkflow
from reachable_audit.campaign import CampaignManager
from reachable_audit.inventory import build_inventory
from reachable_audit.models import ModelError
from conftest import axis_runs_from_evidence
from reachable_audit.planning import create_audit_plan


def _reachable_workflow(tmp_path: Path):  # type: ignore[no-untyped-def]
    (tmp_path / "app.py").write_text("def run(value): return value\n", encoding="utf-8")
    inventory = build_inventory(tmp_path, "fixture:refute")
    plan = create_audit_plan(
        campaign_id="CMP-refute",
        inventory=inventory,
        category_families=["STATE"],
    )
    manager = CampaignManager(tmp_path)
    manager.create_campaign(campaign_id="CMP-refute", snapshot_id="fixture:refute")
    manager.record_inventory(campaign_id="CMP-refute", inventory=inventory)
    manager.record_plan(campaign_id="CMP-refute", plan=plan, inventory=inventory)
    workflow = BatchWorkflow(manager, "CMP-refute", plan.batches[0].batch_id)
    work_unit = plan.work_units[0]
    workflow.run_r0()
    workflow.record_r1([Surface(
        "SURF-run", work_unit.work_unit_id, work_unit.component_id, "entry",
        "app.py", "run", "remote", ("LOC-app.py:1",),
    )])
    axis_evidence = {
        "surface": ("LOC-app.py:1",),
        "mechanism": ("MECH-stale-owner",),
        "state": ("STATE-owner",),
        "fix_variant": ("EVID-fix",),
        "boundary": ("EVID-boundary",),
        "differential": ("EVID-differential",),
    }
    workflow.record_r2([Hypothesis(
        "HYP-state", work_unit.work_unit_id, "state", ("STATE-owner",),
        ("SURF-run",), Mechanism("STATE", "stale-owner"),
        "owner state can become stale", HypothesisStatus.NEW,
    )], axis_evidence=axis_evidence,
        axis_runs=axis_runs_from_evidence(axis_evidence))
    edge_ref = manager.artifacts.put_text("state edge evidence").artifact_id
    workflow.record_r3([VerdictSubmission(
        "HYP-state", VerdictKind.REACHABLE, EvidenceGrade.EDGE_PROVEN,
        "remote", (), ("LOC-app.py:1",), (edge_ref,), (), (),
        "state edge is reachable",
    )])
    return manager, workflow


def test_r35_requires_independent_perspectives_and_source_verified_demotion(
    tmp_path: Path,
) -> None:
    manager, workflow = _reachable_workflow(tmp_path)
    try:
        brief = workflow.build_refutation_brief("HYP-state", refuter_id="agent-a")
        assert "refutations" not in brief
        workflow.record_refutation(Refutation(
            "REF-call", "HYP-state", "agent-a", VerdictKind.UNREACHABLE,
            AttackAngle.CALL_CHAIN, ("EVID-call-block",), "call edge is blocked",
        ))
        workflow.record_refutation(Refutation(
            "REF-principal", "HYP-state", "agent-b", VerdictKind.UNREACHABLE,
            AttackAngle.PRINCIPAL, ("EVID-principal",), "principal cannot trigger it",
        ))
        with pytest.raises(ModelError, match="source verification"):
            workflow.record_adjudication(Adjudication(
                "ADJ-state", "HYP-state", ("REF-call", "REF-principal"),
                VerdictKind.UNREACHABLE, AdjudicationActor.AUTO, (), "both blocks hold",
            ))
        workflow.record_adjudication(Adjudication(
            "ADJ-state", "HYP-state", ("REF-call", "REF-principal"),
            VerdictKind.UNREACHABLE, AdjudicationActor.AUTO,
            (SourceVerification(
                "principal cannot reach run", "EVID-principal", "app.py:1",
            ),),
            "both blocking facts were checked against source",
        ))
        workflow.record_revival_selection(
            [], rationale="no initial UNREACHABLE verdicts", evidence_refs=("EVID-r3-set",)
        )
        workflow.complete_r35()
        events = manager.store.list_events("CMP-refute")
        assert sum(event.event_type == "REFUTATION_SUBMITTED" for event in events) == 2
        assert sum(event.event_type == "R3_5_COMPLETED" for event in events) == 1
    finally:
        manager.close()


def test_split_refutations_require_human_adjudication(tmp_path: Path) -> None:
    manager, workflow = _reachable_workflow(tmp_path)
    try:
        workflow.record_refutation(Refutation(
            "REF-a", "HYP-state", "agent-a", VerdictKind.REACHABLE,
            AttackAngle.CALL_CHAIN, ("EVID-a",), "chain holds",
        ))
        workflow.record_refutation(Refutation(
            "REF-b", "HYP-state", "agent-b", VerdictKind.NEEDS_REVIEW,
            AttackAngle.DEPLOYMENT, ("EVID-b",), "deployment is uncertain",
        ))
        with pytest.raises(ModelError, match="human adjudication"):
            workflow.record_adjudication(Adjudication(
                "ADJ-split", "HYP-state", ("REF-a", "REF-b"),
                VerdictKind.NEEDS_REVIEW, AdjudicationActor.AUTO, (), "split vote",
            ))
    finally:
        manager.close()