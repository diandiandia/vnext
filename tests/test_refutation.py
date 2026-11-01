import json
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

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
    CategoryRun,
    CategoryRunStatus,
    Applicability,
    AxisRun,
    HypothesisReview,
    HypothesisReviewDisposition,
    ReviewAltitude,
)
from reachable_audit.batch_workflow import BatchWorkflow
from reachable_audit.campaign import CampaignManager
from reachable_audit.execution import (
    DiscoveryCoordinator, ManualExecutionBackend, TaskResult, TaskStatus, TaskView,
)
from reachable_audit.inventory import build_inventory
from reachable_audit.models import ModelError
from conftest import axis_runs_from_evidence
from reachable_audit.planning import create_audit_plan
from reachable_audit.stage_revisions import stage_recovery_plan


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
    source_name: str = "app.py",
    source_text: str = "def run(value): return value\n",
):  # type: ignore[no-untyped-def]
    (tmp_path / source_name).write_text(source_text, encoding="utf-8")
    anchor = f"LOC-{source_name}:1"
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
        source_name, "run", "remote", (anchor,),
    )])
    axis_evidence = {
        "surface": (anchor,),
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
        "remote", (), (anchor,) if verdict_kind is VerdictKind.REACHABLE else (),
        (edge_ref,) if verdict_kind is VerdictKind.REACHABLE else (),
        (edge_ref,) if verdict_kind is VerdictKind.UNREACHABLE else (), (),
        "state edge is reachable" if verdict_kind is VerdictKind.REACHABLE else "blocking guard applies",
    )])
    return manager, workflow


def _review_output(manager: CampaignManager, view: TaskView) -> dict[str, Any]:
    task_input = json.loads(manager.artifacts.get_bytes(view.task.input_refs[0]))
    anchor = f"LOC-{manager.load_inventory(view.task.campaign_id).source_files[0].path}:1"
    if view.task.operation == "refute_reachability":
        record = {
            "refutation_id": f"REF-{view.task.task_id}",
            "hypothesis_id": task_input["hypothesis"]["hypothesis_id"],
            "refuter_id": task_input["refuter_id"],
            "verdict": "REACHABLE",
            "attack_angle": (
                "call_chain" if task_input["assigned_perspective"] == "call_chain"
                else "principal"
            ),
            "evidence_refs": [anchor],
            "rationale": "source-backed independent review",
        }
        field = "refutation"
    elif view.task.operation == "adjudicate_refutations":
        record = {
            "adjudication_id": f"ADJ-{view.task.task_id}",
            "hypothesis_id": task_input["hypothesis_id"],
            "refutation_ids": [item["refutation_id"] for item in task_input["refutations"]],
            "final_verdict": "REACHABLE",
            "actor": "auto",
            "source_verifications": [],
            "rationale": "the independent reviews agree",
        }
        field = "adjudication"
    else:
        record = {
            "revival_id": f"REV-{view.task.task_id}",
            "hypothesis_id": task_input["hypothesis"]["hypothesis_id"],
            "reviewer_id": task_input["reviewer_id"],
            "outcome": "UPHOLD",
            "evidence_refs": [anchor],
            "rationale": "the blocking evidence still applies",
        }
        field = "revival_review"
    return {"schema_version": "1.0", field: record}


def _collect_review(
    manager: CampaignManager, backend: ManualExecutionBackend, view: TaskView,
    output: dict[str, Any] | None = None,
) -> str:
    lease = backend.claim(
        f"worker:{view.task.task_id}", task_id_filter=view.task.task_id,
    )
    assert lease is not None
    output_ref = manager.artifacts.put_text(json.dumps(
        output if output is not None else _review_output(manager, view)
    )).artifact_id
    backend.collect(lease, TaskResult(
        True, output_ref, "review completed", {"agent_runs": 1, "wall_seconds": 1},
    ))
    return output_ref


@pytest.mark.parametrize("operation", ["refutation", "adjudication", "revival_review"])
@pytest.mark.parametrize("defect", [
    "missing-id", "null-id", "blank-rationale", "string-references",
    "duplicate-references", "wrong-hypothesis", "wrong-reviewer",
])
def test_r35_collection_rejects_malformed_or_foreign_review_before_success(
    tmp_path: Path, operation: str, defect: str,
) -> None:
    manager, workflow = _reachable_workflow(
        tmp_path,
        verdict_kind=(
            VerdictKind.UNREACHABLE if operation == "revival_review"
            else VerdictKind.REACHABLE
        ),
    )
    try:
        backend = ManualExecutionBackend(manager, workflow.campaign_id)
        coordinator = DiscoveryCoordinator(workflow, backend)
        if operation == "refutation":
            view = coordinator.schedule_r35_refutations()[0]
        elif operation == "adjudication":
            for refuter, angle in (("a", AttackAngle.CALL_CHAIN), ("b", AttackAngle.PRINCIPAL)):
                workflow.record_refutation(Refutation(
                    f"REF-{refuter}", "HYP-state", refuter, VerdictKind.REACHABLE,
                    angle, ("LOC-app.py:1",), "source-backed review",
                ))
            view, = coordinator.schedule_r35_adjudications()
        else:
            view, = coordinator.schedule_r35_revivals()
        output = _review_output(manager, view)
        record = output[operation]
        identity = {
            "refutation": "refutation_id",
            "adjudication": "adjudication_id",
            "revival_review": "revival_id",
        }[operation]
        references = "refutation_ids" if operation == "adjudication" else "evidence_refs"
        if defect == "missing-id":
            del record[identity]
        elif defect == "null-id":
            record[identity] = None
        elif defect == "blank-rationale":
            record["rationale"] = " "
        elif defect == "string-references":
            record[references] = "not-an-array"
        elif defect == "duplicate-references":
            record[references] = [record[references][0]] * 2
        elif defect == "wrong-hypothesis":
            record["hypothesis_id"] = "HYP-other"
        elif operation == "adjudication":
            record["refutation_ids"] = ["REF-other-a", "REF-other-b"]
        else:
            record["refuter_id" if operation == "refutation" else "reviewer_id"] = "other-reviewer"
        lease = backend.claim("reviewer", task_id_filter=view.task.task_id)
        assert lease is not None
        output_ref = manager.artifacts.put_text(json.dumps(output)).artifact_id
        with pytest.raises(ModelError):
            backend.collect(lease, TaskResult(
                True, output_ref, "invalid result", {"agent_runs": 1, "wall_seconds": 1},
            ))
        assert backend.poll(view.task.task_id).status is TaskStatus.LEASED
        assert not manager.store.list_events(
            workflow.campaign_id, entity_id=view.task.task_id, event_type="TASK_COMPLETED",
        )
    finally:
        manager.close()


@pytest.mark.parametrize("language", [
    "c", "cpp", "csharp", "go", "java", "javascript", "kotlin", "php",
    "python", "ruby", "rust", "scala", "shell", "swift", "typescript",
])
def test_r35_refutation_recovery_preserves_language_independent_task_history(
    tmp_path: Path, language: str,
) -> None:
    from reachable_audit.adapters.languages import LANGUAGE_ADAPTERS
    from test_language_adapters import _DECLARATIONS

    source_name = "entry" + sorted(LANGUAGE_ADAPTERS[language].extensions)[0]
    manager, workflow = _reachable_workflow(
        tmp_path, source_name=source_name, source_text=_DECLARATIONS[language] + "\n",
    )
    try:
        backend = ManualExecutionBackend(manager, workflow.campaign_id)
        coordinator = DiscoveryCoordinator(workflow, backend)
        views = coordinator.schedule_r35_refutations()
        outputs = [_collect_review(manager, backend, view) for view in views]
        coordinator.commit_r35_refutations()
        adjudication, = coordinator.schedule_r35_adjudications()
        _collect_review(manager, backend, adjudication)
        coordinator.commit_r35_adjudications()
        assert coordinator.schedule_r35_revivals() == ()
        original_summary = coordinator.commit_r35_revivals()
        original_events = workflow._active_events(event_type="REFUTATION_SUBMITTED")

        replacement = _review_output(manager, views[0])
        replacement["refutation"]["rationale"] = "corrected review of the same source evidence"
        replacement_ref = manager.artifacts.put_text(json.dumps(replacement)).artifact_id
        amended = backend.amend_completed_output(
            views[0].task.task_id, replacement_ref,
            reason="corrected the committed review",
            evidence_refs=(outputs[0], replacement_ref),
        )
        assert amended.status is TaskStatus.SUCCEEDED
        assert workflow._stage_event("R3_COMPLETED") is not None
        assert workflow._stage_event("R3_5_COMPLETED") is None
        assert backend._task_revision_is_stale(adjudication.task)
        assert backend.amend_completed_output(
            views[0].task.task_id, replacement_ref,
            reason="corrected the committed review",
            evidence_refs=(outputs[0], replacement_ref),
        ) == amended
        coordinator.commit_r35_refutations()
        restored_events = workflow._active_events(event_type="REFUTATION_SUBMITTED")
        assert len(restored_events) == 2
        assert {event.event_id for event in restored_events}.isdisjoint(
            event.event_id for event in original_events
        )
        current_adjudication, = coordinator.schedule_r35_adjudications()
        assert current_adjudication.task.task_id != adjudication.task.task_id
        _collect_review(manager, backend, current_adjudication)
        coordinator.commit_r35_adjudications()
        assert coordinator.schedule_r35_revivals() == ()
        summary = coordinator.commit_r35_revivals()
        assert summary != original_summary
        assert coordinator.commit_r35_revivals() == summary
        assert json.loads(manager.artifacts.get_bytes(summary))["review_artifact_refs"]
        recovery = stage_recovery_plan(manager.store.list_events(workflow.campaign_id))
        assert recovery["batches"] == []
        assert manager.artifacts.get_bytes(outputs[0])
        assert len(manager.store.list_events(
            workflow.campaign_id, entity_id=views[0].task.task_id, event_type="TASK_CLAIMED",
        )) == 1
    finally:
        manager.close()


@pytest.mark.parametrize("operation", ["adjudication", "revival_review"])
def test_r35_adjudication_and_revival_can_be_amended_and_recommitted(
    tmp_path: Path, operation: str,
) -> None:
    manager, workflow = _reachable_workflow(
        tmp_path,
        verdict_kind=(
            VerdictKind.UNREACHABLE if operation == "revival_review"
            else VerdictKind.REACHABLE
        ),
    )
    try:
        backend = ManualExecutionBackend(manager, workflow.campaign_id)
        coordinator = DiscoveryCoordinator(workflow, backend)
        if operation == "adjudication":
            for refutation in coordinator.schedule_r35_refutations():
                _collect_review(manager, backend, refutation)
            coordinator.commit_r35_refutations()
            view, = coordinator.schedule_r35_adjudications()
        else:
            view, = coordinator.schedule_r35_revivals()
        prior_ref = _collect_review(manager, backend, view)
        if operation == "adjudication":
            coordinator.commit_r35_adjudications()
            assert coordinator.schedule_r35_revivals() == ()
        prior_summary = coordinator.commit_r35_revivals()
        replacement = _review_output(manager, view)
        replacement[operation]["rationale"] += " with a corrected premise explanation"
        replacement_ref = manager.artifacts.put_text(json.dumps(replacement)).artifact_id
        backend.amend_completed_output(
            view.task.task_id, replacement_ref, reason="repair a review explanation",
            evidence_refs=(prior_ref, replacement_ref),
        )
        if operation == "adjudication":
            coordinator.commit_r35_adjudications()
        summary = coordinator.commit_r35_revivals()
        assert summary != prior_summary
        assert coordinator.commit_r35_revivals() == summary
        assert stage_recovery_plan(manager.store.list_events(workflow.campaign_id))["batches"] == []
    finally:
        manager.close()


def test_legacy_bad_refutations_cannot_partially_commit_and_have_a_task_repair_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, workflow = _reachable_workflow(tmp_path)
    try:
        backend = ManualExecutionBackend(manager, workflow.campaign_id)
        coordinator = DiscoveryCoordinator(workflow, backend)
        views = coordinator.schedule_r35_refutations()
        _collect_review(manager, backend, views[0])
        bad_output = _review_output(manager, views[1])
        del bad_output["refutation"]["refutation_id"]
        with monkeypatch.context() as legacy:
            legacy.setattr(backend, "_validate_task_output", lambda *_args: {})
            prior_ref = _collect_review(manager, backend, views[1], bad_output)
        with pytest.raises(ModelError):
            coordinator.commit_r35_refutations()
        assert workflow._active_events(event_type="REFUTATION_SUBMITTED") == []
        replacement_ref = manager.artifacts.put_text(json.dumps(
            _review_output(manager, views[1])
        )).artifact_id
        backend.amend_completed_output(
            views[1].task.task_id, replacement_ref, reason="restore required identity",
            evidence_refs=(prior_ref, replacement_ref),
        )
        coordinator.commit_r35_refutations()
        assert len(workflow._active_events(event_type="REFUTATION_SUBMITTED")) == 2
    finally:
        manager.close()


def test_r35_amendment_invalidates_pending_r4_inputs_and_rolls_back_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from reachable_audit.knowledge import create_category_audit_plans
    from test_category_runs import _card

    manager, workflow = _reachable_workflow(tmp_path)
    try:
        backend = ManualExecutionBackend(manager, workflow.campaign_id)
        coordinator = DiscoveryCoordinator(workflow, backend)
        refutations = coordinator.schedule_r35_refutations()
        old_refs = [_collect_review(manager, backend, view) for view in refutations]
        coordinator.commit_r35_refutations()
        adjudication, = coordinator.schedule_r35_adjudications()
        _collect_review(manager, backend, adjudication)
        coordinator.commit_r35_adjudications()
        coordinator.schedule_r35_revivals()
        coordinator.commit_r35_revivals()
        plan = manager.load_audit_plan(workflow.campaign_id, workflow.batch.manifest["plan_id"])
        category_plan, = create_category_audit_plans(plan.work_units, [_card()], budget={})
        category_plan = replace(category_plan, seed_card_ids=())
        workflow.record_category_audit_plan([category_plan])
        old_r4, = coordinator.schedule_r4()
        old_lease = backend.claim("old-r4-worker", task_id_filter=old_r4.task.task_id)
        assert old_lease is not None
        replacement = _review_output(manager, refutations[0])
        replacement["refutation"]["rationale"] = "corrected a committed premise"
        replacement_ref = manager.artifacts.put_text(json.dumps(replacement)).artifact_id
        original_append = manager.store._append_event_tx

        def fail_invalidation(**kwargs: object) -> object:
            if kwargs.get("event_type") == "STAGE_PROJECTION_INVALIDATED":
                raise RuntimeError("injected R3.5 recovery failure")
            return original_append(**kwargs)

        with monkeypatch.context() as patch:
            patch.setattr(manager.store, "_append_event_tx", fail_invalidation)
            with pytest.raises(RuntimeError, match="injected R3.5 recovery failure"):
                backend.amend_completed_output(
                    refutations[0].task.task_id, replacement_ref,
                    reason="repair the premise", evidence_refs=(old_refs[0], replacement_ref),
                )
        assert backend.poll(refutations[0].task.task_id).output_ref == old_refs[0]
        assert workflow._stage_event("R3_5_COMPLETED") is not None
        assert not backend._task_revision_is_stale(old_r4.task)
        backend.amend_completed_output(
            refutations[0].task.task_id, replacement_ref,
            reason="repair the premise", evidence_refs=(old_refs[0], replacement_ref),
        )
        assert backend._task_revision_is_stale(old_r4.task)
        with pytest.raises(ModelError, match="invalidated"):
            backend.collect(old_lease, TaskResult(
                True, old_refs[0], "stale review", {"agent_runs": 1, "wall_seconds": 1},
            ))
        with pytest.raises(ModelError, match="required Batch stage is missing"):
            coordinator.schedule_r4()
        coordinator.commit_r35_refutations()
        current_adjudication, = coordinator.schedule_r35_adjudications()
        _collect_review(manager, backend, current_adjudication)
        coordinator.commit_r35_adjudications()
        coordinator.commit_r35_revivals()
        current_r4, = coordinator.schedule_r4()
        assert current_r4.task.task_id != old_r4.task.task_id
        current_input = json.loads(manager.artifacts.get_bytes(current_r4.task.input_refs[0]))
        assert current_input["operation"] == "run_category_audit"
        r2 = workflow._read_artifact(workflow._require_stage("R2_COMPLETED").payload_ref)
        run = CategoryRun(
            "CR-current", category_plan.category_plan_id, category_plan.work_unit_id,
            "STATE", category_plan.mechanism_variants,
            tuple(replace(
                AxisRun.from_dict(item), review_altitude=ReviewAltitude.INSPECTED,
            ) for item in r2["axis_runs"]),
            Applicability.APPLICABLE, CategoryRunStatus.COMPLETE,
            ("LOC-app.py:1",), "fresh review against current upstream state",
            ("HYP-state",), (),
            (HypothesisReview(
                "HYP-state", HypothesisReviewDisposition.SUPPORTED,
                ("LOC-app.py:1",), "the current evidence supports the path",
            ),),
        )
        output_ref = manager.artifacts.put_text(json.dumps({
            "schema_version": "1.0", "category_run": asdict(run),
        })).artifact_id
        lease = backend.claim("fresh-r4-worker", task_id_filter=current_r4.task.task_id)
        assert lease is not None
        backend.collect(lease, TaskResult(
            True, output_ref, "fresh category review", {"agent_runs": 1, "wall_seconds": 1},
        ))
        coordinator.commit_r4()
        r4 = workflow._require_stage("R4_COMPLETED")
        assert r4.payload["upstream_revision_ids"]["R3_5_COMPLETED"] == (
            workflow._require_stage("R3_5_COMPLETED").payload["revision_id"]
        )
    finally:
        manager.close()

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