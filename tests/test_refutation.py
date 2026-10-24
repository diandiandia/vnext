import json
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
    RevivalOutcome,
    RevivalReview,
    SourceVerification,
    Surface,
    VerdictKind,
    VerdictSubmission,
)
from reachable_audit.batch_workflow import BatchWorkflow
from reachable_audit.campaign import CampaignManager
from reachable_audit.execution import DiscoveryCoordinator, ManualExecutionBackend
from reachable_audit.inventory import build_inventory
from reachable_audit.models import ModelError
from conftest import axis_runs_from_evidence
from reachable_audit.planning import create_audit_plan


@pytest.mark.parametrize("outcome", list(RevivalOutcome))
def test_revival_summary_separates_review_from_overturn(
    tmp_path: Path, outcome: RevivalOutcome,
) -> None:
    manager, workflow = _reachable_workflow(
        tmp_path, verdict_kind=VerdictKind.UNREACHABLE,
    )
    try:
        workflow.record_revival_selection(
            ["HYP-state"], rationale="sample a rejected hypothesis",
            evidence_refs=("EVID-selection",),
        )
        workflow.record_revival_review(RevivalReview(
            "REV-state", "HYP-state", "reviewer", outcome,
            ("LOC-app.py:1",), "source-backed review disposition",
        ))
        ref = workflow.complete_r35()
        summary = json.loads(manager.artifacts.get_bytes(ref))
        assert summary["adjudicated_hypothesis_ids"] == []
        assert summary["revival_reviewed_hypothesis_ids"] == ["HYP-state"]
        assert summary["revived_hypothesis_ids"] == ["HYP-state"]
        assert summary["upheld_hypothesis_ids"] == (
            ["HYP-state"] if outcome is RevivalOutcome.UPHOLD else []
        )
        assert summary["actual_revived_hypothesis_ids"] == (
            [] if outcome is RevivalOutcome.UPHOLD else ["HYP-state"]
        )
        assert workflow.complete_r35() == ref
    finally:
        manager.close()


def _reachable_workflow(
    tmp_path: Path, *, verdict_kind: VerdictKind = VerdictKind.REACHABLE,
    static_challenges: bool = False, static_only: bool = False,
):  # type: ignore[no-untyped-def]
    (tmp_path / "app.py").write_text("def run(value): return value\n", encoding="utf-8")
    inventory = build_inventory(tmp_path, "fixture:refute")
    plan = create_audit_plan(
        campaign_id="CMP-refute",
        inventory=inventory,
        category_families=["STATE"],
    )
    manager = CampaignManager(tmp_path)
    manager.create_campaign(
        campaign_id="CMP-refute", snapshot_id="fixture:refute",
        constraints=("static_challenges",) if static_challenges else (),
    )
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
        "HYP-state", verdict_kind,
        EvidenceGrade.EDGE_PROVEN if verdict_kind is VerdictKind.REACHABLE and not static_only else EvidenceGrade.STATIC_ONLY,
        "remote", (), ("LOC-app.py:1",) if verdict_kind is VerdictKind.REACHABLE else (),
        (edge_ref,) if verdict_kind is VerdictKind.REACHABLE else (),
        (edge_ref,) if verdict_kind is VerdictKind.UNREACHABLE else (), (),
        "state edge is reachable" if verdict_kind is VerdictKind.REACHABLE else "blocking guard applies",
    )])
    return manager, workflow


@pytest.mark.parametrize("enabled", [False, True])
def test_static_challenges_are_frozen_opt_in(tmp_path: Path, enabled: bool) -> None:
    manager, workflow = _reachable_workflow(
        tmp_path, static_only=True, static_challenges=enabled,
    )
    try:
        backend = ManualExecutionBackend(manager, "CMP-refute")
        coordinator = DiscoveryCoordinator(workflow, backend)
        tasks = coordinator.schedule_r35_refutations()
        assert len(tasks) == (2 if enabled else 0)
        if not enabled:
            with pytest.raises(ModelError, match="edge-proven"):
                workflow.build_refutation_brief("HYP-state", refuter_id="a")
            return
        for refuter, angle in [("a", AttackAngle.CALL_CHAIN), ("b", AttackAngle.PRINCIPAL)]:
            workflow.record_refutation(Refutation(
                f"REF-{refuter}", "HYP-state", refuter, VerdictKind.REACHABLE,
                angle, ("LOC-app.py:1",), "static source challenge retains the hypothesis",
            ))
        workflow.record_adjudication(Adjudication(
            "ADJ-static", "HYP-state", ("REF-a", "REF-b"), VerdictKind.REACHABLE,
            AdjudicationActor.AUTO, (), "no observed blocker; no empirical proof",
        ))
        workflow.record_revival_selection(
            [], rationale="no unreachable hypotheses", evidence_refs=("LOC-app.py:1",),
        )
        workflow.complete_r35()
        assert workflow._r3_verdicts()[0]["evidence_grade"] == "static_only"
    finally:
        manager.close()


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


def test_revival_scheduler_reuses_existing_selection(tmp_path: Path) -> None:
    manager, workflow = _reachable_workflow(
        tmp_path, verdict_kind=VerdictKind.UNREACHABLE,
    )
    try:
        workflow.record_revival_selection(
            ["HYP-state"], rationale="review selected rejection",
            evidence_refs=("EVID-selection",),
        )
        backend = ManualExecutionBackend(manager, workflow.campaign_id)
        tasks = DiscoveryCoordinator(workflow, backend).schedule_r35_revivals()

        assert len(tasks) == 1
        task_input = json.loads(manager.artifacts.get_bytes(tasks[0].task.input_refs[0]))
        assert task_input["hypothesis"]["hypothesis_id"] == "HYP-state"
        selection_events = [
            event for event in manager.store.list_events(workflow.campaign_id)
            if event.event_type == "REVIVAL_SAMPLE_SELECTED"
        ]
        assert len(selection_events) == 1
    finally:
        manager.close()


def test_legacy_r35_summary_retry_does_not_rewrite_recorded_stage(tmp_path: Path) -> None:
    manager, workflow = _reachable_workflow(
        tmp_path, verdict_kind=VerdictKind.UNREACHABLE,
    )
    try:
        workflow.record_revival_selection(
            ["HYP-state"], rationale="review rejection",
            evidence_refs=("EVID-selection",),
        )
        workflow.record_revival_review(RevivalReview(
            "REV-state", "HYP-state", "reviewer", RevivalOutcome.UPHOLD,
            ("LOC-app.py:1",), "blocking evidence remains valid",
        ))
        legacy_value = {
            "schema_version": "1.0",
            "adjudicated_hypothesis_ids": [],
            "revived_hypothesis_ids": ["HYP-state"],
        }
        metadata = workflow._stage_revision_metadata(
            "R3_5", legacy_value, {}, ("R3_COMPLETED",)
        )
        ref = workflow._put_json(legacy_value)
        manager.store.append_event(
            campaign_id=workflow.campaign_id, batch_id=workflow.batch_id,
            entity_type="batch_stage", entity_id=workflow.batch_id,
            event_type="R3_5_COMPLETED", idempotency_key="legacy-r35-fixture",
            actor="tool", payload={**legacy_value, **metadata}, payload_ref=ref,
        )
        assert workflow.complete_r35() == ref
        assert len(manager.store.list_events(
            workflow.campaign_id, event_type="R3_5_COMPLETED",
        )) == 1
    finally:
        manager.close()