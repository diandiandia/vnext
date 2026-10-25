from dataclasses import replace
import json
from pathlib import Path

import pytest

from conftest import axis_runs_from_evidence
from reachable_audit.analysis_models import (
    Adjudication,
    AdjudicationActor,
    Applicability,
    AxisRun,
    BatchClosure,
    CampaignClosure,
    CategoryRun,
    CategoryRunStatus,
    DiscoveryAxis,
    EvidenceGrade,
    Hypothesis,
    HypothesisReview,
    HypothesisReviewDisposition,
    HypothesisStatus,
    Mechanism,
    MechanismCard,
    R5Assessment,
    R5Disposition,
    Refutation,
    AttackAngle,
    ReviewAltitude,
    Surface,
    VerdictKind,
    VerdictSubmission,
)
from reachable_audit.batch_workflow import BatchWorkflow
from reachable_audit.campaign import CampaignManager
from reachable_audit.campaign_closure import CampaignCloser, _derive_hypothesis_outcomes
from reachable_audit.cli import main
from reachable_audit.deferred_review import derive_review_queue, review_aware_r3_verdicts
from reachable_audit.execution import DiscoveryCoordinator, ManualExecutionBackend
from reachable_audit.graph import build_component_graph
from reachable_audit.inventory import build_inventory
from reachable_audit.knowledge import create_category_audit_plans
from reachable_audit.models import ModelError
from reachable_audit.planning import create_audit_plan
from reachable_audit.stage_revisions import STAGE_INVALIDATION_DEPENDENTS, active_stage_events


def _workflow(path: Path, *, deferred: bool | None = None):
    (path / "app.py").write_text("def run(value): return value\n", encoding="utf-8")
    inventory = build_inventory(path, "fixture:deferred")
    plan = create_audit_plan(
        campaign_id="CMP-deferred", inventory=inventory, category_families=["STATE"],
    )
    manager = CampaignManager(path)
    manager.create_campaign(
        campaign_id="CMP-deferred", snapshot_id="fixture:deferred",
        constraints=(
            None if deferred is None else ("defer_r35_splits",) if deferred else ()
        ),
    )
    manager.record_inventory(campaign_id="CMP-deferred", inventory=inventory)
    manager.record_plan(campaign_id="CMP-deferred", plan=plan, inventory=inventory)
    manager.record_component_graph(
        campaign_id="CMP-deferred", graph=build_component_graph(path, inventory),
    )
    workflow = BatchWorkflow(manager, "CMP-deferred", plan.batches[0].batch_id)
    unit = plan.work_units[0]
    workflow.run_r0()
    workflow.record_r1([Surface(
        "SURF-run", unit.work_unit_id, unit.component_id, "entry",
        "app.py", "run", "remote", ("LOC-app.py:1",),
    )])
    evidence = {
        axis.value: (f"EVID-{axis.value}",) for axis in DiscoveryAxis
    }
    workflow.record_r2([Hypothesis(
        "HYP-split", unit.work_unit_id, "surface", ("SURF-run",),
        ("SURF-run",), Mechanism("STATE", "stale-owner"),
        "owner can become stale across the entry boundary", HypothesisStatus.NEW,
    )], axis_evidence=evidence, axis_runs=axis_runs_from_evidence(evidence))
    edge_ref = manager.artifacts.put_text("observed state edge").artifact_id
    workflow.record_r3([VerdictSubmission(
        "HYP-split", VerdictKind.REACHABLE, EvidenceGrade.EDGE_PROVEN,
        "remote", ("owner can transition",), ("LOC-app.py:1",),
        (edge_ref,), (), (), "source and edge evidence support the candidate",
    )])
    return manager, workflow, plan


def _refute(workflow: BatchWorkflow, suffix: str = "") -> None:
    for identifier, verdict, angle, rationale in [
        ("call", VerdictKind.REACHABLE, AttackAngle.CALL_CHAIN,
         "the source call chain remains reachable"),
        ("premise", VerdictKind.UNREACHABLE, AttackAngle.PRINCIPAL,
         "the principal appears blocked by the owner premise"),
    ]:
        workflow.record_refutation(Refutation(
            f"REF-{identifier}{suffix}", "HYP-split", f"agent-{identifier}",
            verdict, angle, (f"EVID-{identifier}{suffix}",), rationale,
        ))


def _coordinator(manager: CampaignManager, workflow: BatchWorkflow):
    return DiscoveryCoordinator(
        workflow, ManualExecutionBackend(manager, workflow.campaign_id),
    )


@pytest.mark.parametrize("enabled", [False, True])
def test_init_freezes_split_deferral(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], enabled: bool,
) -> None:
    args = [
        "init", str(tmp_path), "--snapshot-id", "fixture:init-deferred",
        "--campaign-id", "CMP-init", "--state-dir", ".audit_vnext",
    ]
    opted_in = ["--defer-r35-splits"] if enabled else ["--no-defer-r35-splits"]
    assert main(args + opted_in) == 0
    campaign = json.loads(capsys.readouterr().out)
    assert ("defer_r35_splits" in campaign["constraints"]) is enabled
    assert main(args + opted_in) == 0
    capsys.readouterr()
    assert main(args + (["--no-defer-r35-splits"] if enabled else ["--defer-r35-splits"])) == 2
    capsys.readouterr()
    with CampaignManager(tmp_path) as manager:
        assert manager.store.get_campaign("CMP-init").constraints == (
            ("defer_r35_splits",) if enabled else ()
        )


def test_new_cli_campaign_defaults_to_deferral_and_preserves_old_policy(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    args = [
        "init", str(tmp_path), "--snapshot-id", "fixture:default",
        "--state-dir", ".audit_vnext",
    ]
    assert main(args + ["--campaign-id", "CMP-default"]) == 0
    assert "defer_r35_splits" in json.loads(capsys.readouterr().out)["constraints"]
    with CampaignManager(tmp_path) as manager:
        manager.create_campaign(
            snapshot_id="fixture:default", campaign_id="CMP-old", constraints=(),
        )
        before = manager.store.list_events("CMP-old")
    assert main(args + ["--campaign-id", "CMP-old"]) == 0
    assert json.loads(capsys.readouterr().out)["constraints"] == []
    with CampaignManager(tmp_path) as manager:
        assert manager.store.list_events("CMP-old") == before


def test_library_default_and_explicit_constraints_are_frozen(tmp_path: Path) -> None:
    with CampaignManager(tmp_path) as manager:
        new = manager.create_campaign(snapshot_id="fixture:default", campaign_id="CMP-new")
        assert new.constraints == ("defer_r35_splits",)
        old = manager.create_campaign(
            snapshot_id="fixture:default", campaign_id="CMP-explicit", constraints=(),
        )
        assert old.constraints == ()
        assert manager.create_campaign(
            snapshot_id="fixture:default", campaign_id="CMP-explicit",
        ) == old
        assert manager.create_campaign(
            snapshot_id="fixture:default", campaign_id="CMP-new",
        ) == new


def test_legacy_split_still_requires_human(tmp_path: Path) -> None:
    manager, workflow, _ = _workflow(tmp_path, deferred=False)
    try:
        _refute(workflow)
        with pytest.raises(ModelError, match="human adjudication"):
            workflow.record_adjudication(Adjudication(
                "ADJ-legacy", "HYP-split", ("REF-call", "REF-premise"),
                VerdictKind.NEEDS_REVIEW, AdjudicationActor.AUTO, (), "unresolved split",
            ))
        coordinator = _coordinator(manager, workflow)
        task, = coordinator.schedule_r35_adjudications()
        assert task.task.operation == "adjudicate_refutations"
        assert workflow._active_events(event_type="ADJUDICATION_DECIDED") == []
    finally:
        manager.close()


@pytest.mark.parametrize("final_verdict", [VerdictKind.REACHABLE, VerdictKind.UNREACHABLE])
def test_opt_in_forbids_definitive_auto_split(
    tmp_path: Path, final_verdict: VerdictKind,
) -> None:
    manager, workflow, _ = _workflow(tmp_path)
    try:
        _refute(workflow)
        with pytest.raises(ModelError, match="human adjudication"):
            workflow.record_adjudication(Adjudication(
                "ADJ-definitive", "HYP-split", ("REF-call", "REF-premise"),
                final_verdict, AdjudicationActor.AUTO, (), "choose a side",
            ))
    finally:
        manager.close()


def test_deferred_split_preserves_perspective_and_refutation_coverage(tmp_path: Path) -> None:
    manager, workflow, _ = _workflow(tmp_path)
    try:
        workflow.record_refutation(Refutation(
            "REF-call", "HYP-split", "a", VerdictKind.REACHABLE,
            AttackAngle.CALL_CHAIN, ("EVID-call",), "call remains reachable",
        ))
        adjudication = Adjudication(
            "ADJ-coverage", "HYP-split", ("REF-call", "REF-premise"),
            VerdictKind.NEEDS_REVIEW, AdjudicationActor.AUTO, (), "defer",
        )
        with pytest.raises(ModelError, match="two independent"):
            workflow.record_adjudication(adjudication)
        workflow.record_refutation(Refutation(
            "REF-premise", "HYP-split", "b", VerdictKind.UNREACHABLE,
            AttackAngle.CALL_CHAIN, ("EVID-premise",), "another call-chain objection",
        ))
        with pytest.raises(ModelError, match="premise perspectives"):
            workflow.record_adjudication(adjudication)
    finally:
        manager.close()


def test_deferred_split_requires_every_refutation_id(tmp_path: Path) -> None:
    manager, workflow, _ = _workflow(tmp_path)
    try:
        _refute(workflow)
        with pytest.raises(ModelError, match="every submitted refutation"):
            workflow.record_adjudication(Adjudication(
                "ADJ-incomplete", "HYP-split", ("REF-call",),
                VerdictKind.NEEDS_REVIEW, AdjudicationActor.AUTO, (), "defer",
            ))
    finally:
        manager.close()


def test_split_scheduling_commit_and_reopen_are_durable_and_idempotent(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    manager, workflow, _ = _workflow(tmp_path)
    _refute(workflow)
    original_r3 = workflow._r3_verdicts()
    coordinator = _coordinator(manager, workflow)
    assert coordinator.schedule_r35_adjudications() == ()
    event, = workflow._active_events(event_type="ADJUDICATION_DECIDED")
    queue = derive_review_queue(manager, workflow.campaign_id)
    packet, = queue
    assert packet["hypothesis"]["claim"] == "owner can become stale across the entry boundary"
    assert packet["hypothesis"]["seed_refs"] == ["SURF-run"]
    assert packet["hypothesis"]["mechanism"]["family"] == "STATE"
    assert packet["r3_verdict"] == original_r3[0]
    assert packet["r3_verdict"]["preconditions"] == ["owner can transition"]
    assert packet["r3_verdict"]["principal"] == "remote"
    assert packet["r3_verdict"]["evidence_grade"] == EvidenceGrade.EDGE_PROVEN.value
    assert len(packet["refutations"]) == 2
    for refutation in packet["refutations"]:
        assert refutation["refutation_id"] in packet["unresolved_rationale"]
        assert refutation["rationale"] in packet["unresolved_rationale"]
        assert refutation["evidence_refs"][0] in packet["unresolved_rationale"]
    assert packet["adjudication_artifact_ref"] == event.payload_ref
    assert packet["adjudication"]["actor"] == "auto"
    assert packet["adjudication"]["source_verifications"] == []
    assert packet["effective_verdict"] == "NEEDS_REVIEW"
    assert coordinator.commit_r35_adjudications() == (event.payload_ref,)
    assert coordinator.schedule_r35_adjudications() == ()
    refutations = coordinator._r35_refutations("HYP-split")
    assert coordinator._deferred_split_adjudication(
        "HYP-split", refutations,
    ) == coordinator._deferred_split_adjudication(
        "HYP-split", list(reversed(refutations)),
    )
    assert coordinator.commit_r35_adjudications() == (event.payload_ref,)
    assert workflow._active_events(event_type="ADJUDICATION_DECIDED") == [event]
    assert workflow._r3_verdicts() == original_r3
    effective, = review_aware_r3_verdicts(workflow)
    assert effective["verdict"] == "NEEDS_REVIEW"
    assert effective["verifier_verdict"] == "REACHABLE"
    assert coordinator.backend.list_tasks(operation="adjudicate_refutations") == ()
    assert manager.store.list_events(
        workflow.campaign_id, event_type="HUMAN_ADJUDICATION_APPROVED",
    ) == []
    manager.close()
    with CampaignManager(tmp_path) as reopened:
        workflow = BatchWorkflow(reopened, "CMP-deferred", workflow.batch_id)
        coordinator = _coordinator(reopened, workflow)
        assert coordinator.schedule_r35_adjudications() == ()
        assert coordinator.commit_r35_adjudications() == (event.payload_ref,)
        assert derive_review_queue(reopened, "CMP-deferred") == queue
    assert main([
        "review-queue", str(tmp_path), "CMP-deferred", "--state-dir", ".audit_vnext",
    ]) == 0
    assert json.loads(capsys.readouterr().out) == queue


@pytest.mark.parametrize("operation", ["schedule_r35_adjudications", "commit_r35_adjudications"])
def test_retry_recovers_after_durable_append(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str,
) -> None:
    manager, workflow, _ = _workflow(tmp_path)
    try:
        _refute(workflow)
        coordinator = _coordinator(manager, workflow)
        record = workflow.record_adjudication

        def fail_after_record(adjudication: Adjudication) -> str:
            record(adjudication)
            raise RuntimeError("interrupted after durable append")

        with monkeypatch.context() as patch:
            patch.setattr(workflow, "record_adjudication", fail_after_record)
            with pytest.raises(RuntimeError, match="durable append"):
                getattr(coordinator, operation)()
        event, = workflow._active_events(event_type="ADJUDICATION_DECIDED")
        assert coordinator.schedule_r35_adjudications() == ()
        assert coordinator.commit_r35_adjudications() == (event.payload_ref,)
        assert workflow._active_events(event_type="ADJUDICATION_DECIDED") == [event]
    finally:
        manager.close()


def test_opt_in_preserves_agreement_tasks_and_source_demotion_checks(tmp_path: Path) -> None:
    manager, workflow, _ = _workflow(tmp_path)
    try:
        for refuter, angle in [("call", AttackAngle.CALL_CHAIN), ("premise", AttackAngle.PRINCIPAL)]:
            workflow.record_refutation(Refutation(
                f"REF-{refuter}", "HYP-split", f"agent-{refuter}",
                VerdictKind.UNREACHABLE, angle, (f"EVID-{refuter}",),
                "a source-backed blocker is proposed",
            ))
        task, = _coordinator(manager, workflow).schedule_r35_adjudications()
        assert task.task.operation == "adjudicate_refutations"
        assert workflow._active_events(event_type="ADJUDICATION_DECIDED") == []
        with pytest.raises(ModelError, match="source verification"):
            workflow.record_adjudication(Adjudication(
                "ADJ-agreement", "HYP-split", ("REF-call", "REF-premise"),
                VerdictKind.UNREACHABLE, AdjudicationActor.AUTO, (), "both report a blocker",
            ))
    finally:
        manager.close()


def test_queue_drops_split_after_explicit_human_resolution(tmp_path: Path) -> None:
    manager, workflow, _ = _workflow(tmp_path)
    try:
        _refute(workflow)
        _coordinator(manager, workflow).schedule_r35_adjudications()
        assert len(derive_review_queue(manager, workflow.campaign_id)) == 1
        workflow.record_adjudication(Adjudication(
            "ADJ-human", "HYP-split", ("REF-call", "REF-premise"),
            VerdictKind.REACHABLE, AdjudicationActor.HUMAN, (),
            "operator records source review resolving the principal objection",
        ))
        assert derive_review_queue(manager, workflow.campaign_id) == []
    finally:
        manager.close()


@pytest.mark.parametrize("deferred_first", [False, True])
def test_split_scheduler_preserves_later_human_resolution(
    tmp_path: Path, deferred_first: bool,
) -> None:
    manager, workflow, _ = _workflow(tmp_path)
    try:
        _refute(workflow)
        coordinator = _coordinator(manager, workflow)
        if deferred_first:
            coordinator.schedule_r35_adjudications()
        human = Adjudication(
            "ADJ-human-resolved", "HYP-split", ("REF-call", "REF-premise"),
            VerdictKind.REACHABLE, AdjudicationActor.HUMAN, (),
            "operator resolves the recorded principal objection with source review",
        )
        human_ref = workflow.record_adjudication(human)
        before = manager.store.list_events(workflow.campaign_id)
        assert coordinator.schedule_r35_adjudications() == ()
        assert coordinator.commit_r35_adjudications() == (human_ref,)
        assert manager.store.list_events(workflow.campaign_id) == before
        assert derive_review_queue(manager, workflow.campaign_id) == []
    finally:
        manager.close()


def _invalidate(workflow: BatchWorkflow, stage: str) -> None:
    types = set(STAGE_INVALIDATION_DEPENDENTS[stage])
    events = workflow._active_events(event_types=types)
    for event in events:
        workflow.manager.store.append_event(
            campaign_id=workflow.campaign_id, batch_id=workflow.batch_id,
            entity_type="batch_stage", entity_id=workflow.batch_id,
            event_type="STAGE_PROJECTION_INVALIDATED",
            idempotency_key=f"invalidate:{event.event_id}", actor="test",
            payload={
                "target_event_id": event.event_id, "target_stage": event.event_type,
                "target_revision_id": event.payload.get("revision_id", event.event_id),
            },
        )
    assert not active_stage_events(workflow._events(), stage)


@pytest.mark.parametrize("stage", ["R2_COMPLETED", "R3_COMPLETED"])
def test_queue_excludes_invalidated_historical_stages(tmp_path: Path, stage: str) -> None:
    manager, workflow, _ = _workflow(tmp_path)
    try:
        _refute(workflow)
        _coordinator(manager, workflow).schedule_r35_adjudications()
        assert len(derive_review_queue(manager, workflow.campaign_id)) == 1
        _invalidate(workflow, stage)
        assert derive_review_queue(manager, workflow.campaign_id) == []
    finally:
        manager.close()


def test_queue_uses_only_replacement_refutations_and_adjudication(tmp_path: Path) -> None:
    manager, workflow, _ = _workflow(tmp_path)
    try:
        _refute(workflow)
        coordinator = _coordinator(manager, workflow)
        coordinator.schedule_r35_adjudications()
        old_packet, = derive_review_queue(manager, workflow.campaign_id)
        original = VerdictSubmission.from_dict(workflow._r3_verdicts()[0])
        _invalidate(workflow, "R3_COMPLETED")
        workflow.record_r3([replace(original, rationale="replacement source review")])
        assert derive_review_queue(manager, workflow.campaign_id) == []
        _refute(workflow, "-replacement")
        coordinator.schedule_r35_adjudications()
        packet, = derive_review_queue(manager, workflow.campaign_id)
        assert packet["adjudication_artifact_ref"] != old_packet["adjudication_artifact_ref"]
        assert {item["refutation_id"] for item in packet["refutations"]} == {
            "REF-call-replacement", "REF-premise-replacement",
        }
        assert packet["adjudication"]["refutation_ids"] == [
            "REF-call-replacement", "REF-premise-replacement",
        ]
        assert packet["r3_verdict"]["rationale"] == "replacement source review"
        assert coordinator.commit_r35_adjudications() == (packet["adjudication_artifact_ref"],)
    finally:
        manager.close()


def test_deferred_split_closes_workflow_without_semantic_resolution(tmp_path: Path) -> None:
    manager, workflow, plan = _workflow(tmp_path)
    try:
        _refute(workflow)
        coordinator = _coordinator(manager, workflow)
        coordinator.schedule_r35_adjudications()
        coordinator.commit_r35_adjudications()
        workflow.record_revival_selection(
            [], rationale="no unreachable verifier hypotheses", evidence_refs=("EVID-selection",),
        )
        workflow.complete_r35()
        card = next(
            card for card in coordinator.knowledge_catalog.cards.values()
            if card["family"] == "STATE" and "python" in card["language_applicability"]
        )
        category_plan, = create_category_audit_plans(
            plan.work_units, [MechanismCard.from_dict(card)], budget={},
        )
        workflow.record_category_audit_plan([category_plan])
        task, = coordinator.schedule_r4()
        task_input = json.loads(manager.artifacts.get_bytes(task.task.input_refs[0]))
        assert task_input["r3_verdicts_to_reconcile"][0]["verdict"] == "NEEDS_REVIEW"
        workflow.record_r4([CategoryRun(
            "CR-deferred", category_plan.category_plan_id, category_plan.work_unit_id,
            "STATE", category_plan.mechanism_variants,
            tuple(AxisRun(
                DiscoveryAxis(axis), Applicability.APPLICABLE, (f"EVID-{axis}",),
                f"inspected {axis}", review_altitude=ReviewAltitude.INSPECTED,
            ) for axis in category_plan.discovery_axes),
            Applicability.APPLICABLE, CategoryRunStatus.COMPLETE,
            ("EVID-r4",), "all planned axes reviewed; split remains unresolved",
            ("HYP-split",), (),
            (HypothesisReview(
                "HYP-split", HypothesisReviewDisposition.NEEDS_REVIEW,
                ("EVID-r4",), "retain both source-backed perspectives for review",
            ),),
        )])
        r5_task, = coordinator.schedule_r5()
        r5_input = json.loads(manager.artifacts.get_bytes(r5_task.task.input_refs[0]))
        assert r5_input["verdict"]["verdict"] == "NEEDS_REVIEW"
        workflow.record_r5([], [R5Assessment(
            "HYP-split", False, None, R5Disposition.NEEDS_REVIEW,
            ("EVID-r5",), "no experiment resolves the split",
        )])
        workflow.build_transmission_metrics()
        workflow.close_r6(BatchClosure(
            {"agent_runs": 0}, (), ("HYP-split remains unresolved",),
            ("owner premise requires post-run review",), ("preserve split evidence",),
        ))
        report = CampaignCloser(manager, workflow.campaign_id, plan).close(CampaignClosure(
            architecture_overview="A bounded state-owner source review.",
            unreviewed_scope=(), residual_risks=(), limitations=(), lessons=(),
            knowledge_nominations=(), skill_issues=(),
        ))
        assert report["status"] == "PASS"
        packet, = report["review_queue"]
        assert report["review_queue"] == derive_review_queue(manager, workflow.campaign_id)
        outcome, = report["hypothesis_outcomes"]
        assert outcome["state"] == "NEEDS_REVIEW"
        assert outcome["r4_reviews"][0]["disposition"] == "NEEDS_REVIEW"
        assert outcome["r5_assessment"]["disposition"] == "NEEDS_REVIEW"
        assert any("HYP-split" in scope for scope in report["unreviewed_scope"])
        markdown = CampaignCloser._markdown(report)
        assert "Provisional / Unresolved Review Queue" in markdown
        assert "PASS means workflow completion, not semantic resolution" in markdown
        assert packet["unresolved_rationale"] in markdown
        assert "no human approval is implied" in markdown
        assert manager.artifacts.get_bytes(report["artifact_id"])
    finally:
        manager.close()


def test_unresolved_adjudication_is_not_derived_as_rejection() -> None:
    outcome, = _derive_hypothesis_outcomes(
        [{"hypothesis_id": "HYP-unresolved"}],
        [{"hypothesis_id": "HYP-unresolved", "verdict": "REACHABLE"}],
        [{"category_run_id": "CR-reject", "hypothesis_reviews": [{
            "hypothesis_id": "HYP-unresolved", "disposition": "REJECTED",
        }]}],
        [{"hypothesis_id": "HYP-unresolved", "disposition": "REFUTED"}],
        [], unresolved_ids=["HYP-unresolved"],
    )
    assert outcome["state"] == "NEEDS_REVIEW"
