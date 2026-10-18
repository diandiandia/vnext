from dataclasses import replace
from pathlib import Path
import json
from types import SimpleNamespace

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
from reachable_audit.stage_revisions import (
    STAGE_INVALIDATION_DEPENDENTS,
    active_stage_events,
    stage_revision_ancestry_errors,
    unresolved_stage_invalidations,
)
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


def test_stage_event_filter_keeps_replacement_revision_active() -> None:
    prior = SimpleNamespace(
        event_id="EVT-r1-prior", event_type="R1_COMPLETED", payload={},
    )
    replacement = SimpleNamespace(
        event_id="EVT-r1-replacement", event_type="R1_COMPLETED", payload={},
    )
    invalidation = SimpleNamespace(
        event_id="EVT-invalidate", event_type="STAGE_PROJECTION_INVALIDATED",
        payload={"target_event_id": "EVT-r1-prior"},
    )

    assert active_stage_events(
        [prior, invalidation, replacement], "R1_COMPLETED"
    ) == [replacement]
    assert STAGE_INVALIDATION_DEPENDENTS["R1_COMPLETED"] == (
        "R1_COMPLETED", "R2_COMPLETED", "R3_COMPLETED", "VERDICT_ADJUDICATED",
        "REFUTATION_SUBMITTED", "ADJUDICATION_DECIDED", "REVIVAL_SAMPLE_SELECTED",
        "REVIVAL_REVIEWED", "R3_5_COMPLETED",
        "R4_SCREENING_COVERAGE_RECORDED", "R4_COMPLETED", "R5_COMPLETED", "R6_COMPLETED",
        "TRANSMISSION_METRICS_RECORDED",
    )
    assert "CATEGORY_AUDIT_PLAN_RECORDED" not in STAGE_INVALIDATION_DEPENDENTS[
        "R2_COMPLETED"
    ]


def test_stage_invalidation_clears_only_after_later_same_batch_revision() -> None:
    target = SimpleNamespace(
        event_id="EVT-r1-prior", event_type="R1_COMPLETED", batch_id="B-1",
        sequence=10, payload={},
    )
    marker = SimpleNamespace(
        event_id="EVT-invalidate", event_type="STAGE_PROJECTION_INVALIDATED",
        batch_id="B-1", sequence=11,
        payload={"target_event_id": "EVT-r1-prior", "target_stage": "R1_COMPLETED"},
    )
    other_batch_replacement = SimpleNamespace(
        event_id="EVT-r1-other", event_type="R1_COMPLETED", batch_id="B-2",
        sequence=12, payload={},
    )
    replacement = SimpleNamespace(
        event_id="EVT-r1-new", event_type="R1_COMPLETED", batch_id="B-1",
        sequence=13, payload={},
    )

    assert unresolved_stage_invalidations([target, marker, other_batch_replacement]) == [
        marker,
    ]
    assert unresolved_stage_invalidations([
        target, marker, other_batch_replacement, replacement,
    ]) == []


def test_active_projection_rejects_mismatched_upstream_revision_pin() -> None:
    old_r1 = SimpleNamespace(
        event_id="EVT-r1-old", event_type="R1_COMPLETED", batch_id="B-1",
        sequence=10, payload={"revision_id": "REV-r1-old"},
    )
    r2 = SimpleNamespace(
        event_id="EVT-r2", event_type="R2_COMPLETED", batch_id="B-1",
        sequence=11,
        payload={
            "revision_id": "REV-r2",
            "upstream_revision_ids": {"R1_COMPLETED": "REV-r1-old"},
        },
    )
    invalidation = SimpleNamespace(
        event_id="EVT-invalidate-r1", event_type="STAGE_PROJECTION_INVALIDATED",
        batch_id="B-1", sequence=12,
        payload={"target_event_id": "EVT-r1-old", "target_stage": "R1_COMPLETED"},
    )
    replacement_r1 = SimpleNamespace(
        event_id="EVT-r1-new", event_type="R1_COMPLETED", batch_id="B-1",
        sequence=13, payload={"revision_id": "REV-r1-new"},
    )

    assert stage_revision_ancestry_errors([old_r1, r2]) == []
    other_batch_r1 = SimpleNamespace(
        event_id="EVT-r1-other", event_type="R1_COMPLETED", batch_id="B-2",
        sequence=20, payload={"revision_id": "REV-r1-other"},
    )
    other_batch_r2 = SimpleNamespace(
        event_id="EVT-r2-other", event_type="R2_COMPLETED", batch_id="B-2",
        sequence=21,
        payload={
            "revision_id": "REV-r2-other",
            "upstream_revision_ids": {"R1_COMPLETED": "REV-r1-other"},
        },
    )
    assert stage_revision_ancestry_errors([
        old_r1, r2, other_batch_r1, other_batch_r2,
    ]) == []
    errors = stage_revision_ancestry_errors([
        old_r1, r2, invalidation, replacement_r1,
    ])
    assert len(errors) == 1
    assert "R2_COMPLETED" in errors[0]
    assert "active revision is REV-r1-new" in errors[0]


def test_r1_direct_claim_requires_inspected_altitude_for_low_tier(
    tmp_path: Path,
) -> None:
    manager, workflow, plan = _workflow(tmp_path, "CMP-low-tier-altitude")
    work_unit = plan.work_units[0]
    try:
        workflow.run_r0()
        claim = {
            "work_unit_id": work_unit.work_unit_id,
            "path": work_unit.source_files[0],
            "claim": "AGENT_DECLARED_REVIEWED",
            "altitude": "SCREENED",
            "risk_tier": "LOW",
        }
        with pytest.raises(
            ModelError, match="LOW path risk tier requires INSPECTED review altitude",
        ):
            workflow.record_r1([], path_review_claims=[claim])
        assert workflow._stage_event("R1_COMPLETED") is None

        claim["altitude"] = "INSPECTED"
        workflow.record_r1([], path_review_claims=[claim])
        assert workflow._stage_event("R1_COMPLETED") is not None
    finally:
        manager.close()


def test_r1_exact_retry_recovers_batch_transition_after_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, workflow, _ = _workflow(tmp_path, "CMP-r1-recovery")
    try:
        workflow.run_r0()
        original_append = manager.store._append_event_tx

        def fail_r1_append(**kwargs: object) -> object:
            if kwargs.get("event_type") == "R1_COMPLETED":
                raise RuntimeError("injected R1 event append failure")
            return original_append(**kwargs)

        with monkeypatch.context() as patch:
            patch.setattr(manager.store, "_append_event_tx", fail_r1_append)
            with pytest.raises(RuntimeError, match="injected R1 event append failure"):
                workflow.record_r1([])
        assert workflow._stage_event("R1_COMPLETED") is None

        original_transition = manager.store.transition_batch

        def fail_running_transition(*args: object, **kwargs: object) -> object:
            target = kwargs.get("target", args[2] if len(args) > 2 else None)
            if target is BatchStatus.RUNNING:
                raise RuntimeError("injected Batch transition failure")
            return original_transition(*args, **kwargs)

        monkeypatch.setattr(manager.store, "transition_batch", fail_running_transition)
        with pytest.raises(RuntimeError, match="injected Batch transition failure"):
            workflow.record_r1([])
        stage_events = workflow._events(event_type="R1_COMPLETED")
        assert len(stage_events) == 1
        artifact_id = stage_events[0].payload_ref
        assert manager.store.get_batch(
            workflow.campaign_id, workflow.batch_id
        ).status is BatchStatus.READY

        monkeypatch.setattr(manager.store, "transition_batch", original_transition)
        assert workflow.record_r1([]) == artifact_id
        assert manager.store.get_batch(
            workflow.campaign_id, workflow.batch_id
        ).status is BatchStatus.RUNNING
        assert len(workflow._events(event_type="R1_COMPLETED")) == 1
    finally:
        manager.close()


def test_r1_conflicting_retry_is_rejected_before_artifact_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, workflow, plan = _workflow(tmp_path, "CMP-r1-conflict")
    try:
        workflow.run_r0()
        artifact_id = workflow.record_r1([])
        original_put_text = manager.artifacts.put_text
        writes = []

        def track_artifact_write(value: str) -> object:
            writes.append(value)
            return original_put_text(value)

        monkeypatch.setattr(manager.artifacts, "put_text", track_artifact_write)
        work_unit = plan.work_units[0]
        changed_surface = Surface(
            surface_id="SURF-changed",
            work_unit_id=work_unit.work_unit_id,
            component_id=work_unit.component_id,
            kind="function_entry",
            entry_path="app.py",
            entry_symbol="handle",
            principal="remote_unauthenticated",
            evidence_refs=("LOC-app.py:1",),
        )
        with pytest.raises(ModelError, match="R1_COMPLETED already committed"):
            workflow.record_r1([changed_surface])

        assert writes == []
        stage_events = workflow._events(event_type="R1_COMPLETED")
        assert len(stage_events) == 1
        assert stage_events[0].payload_ref == artifact_id
    finally:
        manager.close()


def test_r2_exact_retry_reuses_artifact_and_rejects_conflicts_before_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, workflow, _ = _workflow(tmp_path, "CMP-r2-recovery")
    evidence = {
        axis: (f"EVID-{axis}",)
        for axis in (
            "surface", "mechanism", "state", "fix_variant", "boundary",
            "differential",
        )
    }
    try:
        workflow.run_r0()
        workflow.record_r1([])
        artifact_id = workflow.record_r2(
            [], axis_evidence=evidence, axis_runs=axis_runs_from_evidence(evidence)
        )
        original_put_text = manager.artifacts.put_text
        writes = []

        def track_artifact_write(value: str) -> object:
            writes.append(value)
            return original_put_text(value)

        monkeypatch.setattr(manager.artifacts, "put_text", track_artifact_write)
        assert workflow.record_r2(
            [], axis_evidence=evidence, axis_runs=axis_runs_from_evidence(evidence)
        ) == artifact_id
        assert writes == []

        changed_evidence = {**evidence, "surface": ("EVID-changed",)}
        with pytest.raises(ModelError, match="R2_COMPLETED already committed"):
            workflow.record_r2(
                [],
                axis_evidence=changed_evidence,
                axis_runs=axis_runs_from_evidence(evidence),
            )
        assert writes == []
        stage_events = workflow._events(event_type="R2_COMPLETED")
        assert len(stage_events) == 1
        assert stage_events[0].payload_ref == artifact_id
    finally:
        manager.close()


def test_r2_retry_recovers_after_stage_event_append_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, workflow, _ = _workflow(tmp_path, "CMP-r2-append-recovery")
    evidence = {
        axis: (f"EVID-{axis}",)
        for axis in (
            "surface", "mechanism", "state", "fix_variant", "boundary",
            "differential",
        )
    }
    try:
        workflow.run_r0()
        workflow.record_r1([])
        original_append = manager.store._append_event_tx

        def fail_r2_append(**kwargs: object) -> object:
            if kwargs.get("event_type") == "R2_COMPLETED":
                raise RuntimeError("injected R2 event append failure")
            return original_append(**kwargs)

        monkeypatch.setattr(manager.store, "_append_event_tx", fail_r2_append)
        with pytest.raises(RuntimeError, match="injected R2 event append failure"):
            workflow.record_r2(
                [], axis_evidence=evidence,
                axis_runs=axis_runs_from_evidence(evidence),
            )
        assert workflow._stage_event("R2_COMPLETED") is None

        monkeypatch.setattr(manager.store, "_append_event_tx", original_append)
        artifact_id = workflow.record_r2(
            [], axis_evidence=evidence,
            axis_runs=axis_runs_from_evidence(evidence),
        )
        assert workflow.record_r2(
            [], axis_evidence=evidence,
            axis_runs=axis_runs_from_evidence(evidence),
        ) == artifact_id
        events = workflow._events(event_type="R2_COMPLETED")
        assert len(events) == 1
        assert events[0].payload_ref == artifact_id
    finally:
        manager.close()


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


def test_r3_partial_commit_rejects_conflict_and_recovers_exact_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, workflow, plan = _workflow(tmp_path, "CMP-r3-partial-commit")
    work_unit = plan.work_units[0]
    try:
        workflow.run_r0()
        workflow.record_r1([])
        evidence = {
            axis.value: (f"EVID-{axis.value}",) for axis in DiscoveryAxis
        }
        hypotheses = [Hypothesis(
            hypothesis_id=f"HYP-{work_unit.work_unit_id}-surface-{ordinal}",
            work_unit_id=work_unit.work_unit_id,
            origin_axis="surface",
            seed_refs=(f"EVID-seed-{ordinal}",),
            surface_ids=(),
            mechanism=Mechanism("INJECTION", f"candidate-{ordinal}"),
            claim=f"candidate path {ordinal} may be reachable",
            status=HypothesisStatus.NEW,
        ) for ordinal in (1, 2)]
        workflow.record_r2(
            hypotheses,
            axis_evidence=evidence,
            axis_runs=axis_runs_from_evidence(evidence),
        )
        submissions = [VerdictSubmission(
            hypothesis_id=hypothesis.hypothesis_id,
            verdict=VerdictKind.NEEDS_REVIEW,
            evidence_grade=EvidenceGrade.STATIC_ONLY,
            principal="remote",
            preconditions=(),
            call_chain=(),
            edge_evidence_ids=(),
            blocking_evidence_ids=(),
            experiment_ids=(),
            rationale="retain this candidate for verification",
        ) for hypothesis in hypotheses]
        original_append_event = manager.store.append_event
        adjudication_writes = 0

        def fail_second_adjudication(**kwargs: object):
            nonlocal adjudication_writes
            if kwargs.get("event_type") == "VERDICT_ADJUDICATED":
                adjudication_writes += 1
                if adjudication_writes == 2:
                    raise RuntimeError("injected second verdict write failure")
            return original_append_event(**kwargs)  # type: ignore[arg-type]

        with monkeypatch.context() as patch:
            patch.setattr(manager.store, "append_event", fail_second_adjudication)
            with pytest.raises(RuntimeError, match="injected second verdict"):
                workflow.record_r3(submissions)

        adjudication_events = manager.store.list_batch_events(
            workflow.campaign_id,
            workflow.batch_id,
            event_type="VERDICT_ADJUDICATED",
        )
        assert len(adjudication_events) == 1
        conflicting = [replace(
            submission, rationale="a conflicting retry must not add a verdict",
        ) if submission.hypothesis_id == adjudication_events[0].entity_id else submission
            for submission in submissions]
        with pytest.raises(ModelError, match="conflicts with a prior adjudication"):
            workflow.record_r3(conflicting)
        assert len(manager.store.list_batch_events(
            workflow.campaign_id,
            workflow.batch_id,
            event_type="VERDICT_ADJUDICATED",
        )) == 1
        assert workflow._stage_event("R3_COMPLETED") is None

        workflow.record_r3(submissions)
        assert len(manager.store.list_batch_events(
            workflow.campaign_id,
            workflow.batch_id,
            event_type="VERDICT_ADJUDICATED",
        )) == 2
        assert workflow._stage_event("R3_COMPLETED") is not None
    finally:
        manager.close()


def test_r1_and_r3_cache_source_line_counts_per_stage_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, workflow, plan = _workflow(tmp_path, "CMP-line-cache")
    work_unit = plan.work_units[0]
    original_read_text = Path.read_text
    reads: dict[str, int] = {}

    def counted_read_text(path: Path, *args: object, **kwargs: object) -> str:
        resolved = path.resolve()
        if resolved == (tmp_path / "app.py").resolve():
            reads[str(resolved)] = reads.get(str(resolved), 0) + 1
        return original_read_text(path, *args, **kwargs)

    try:
        workflow.run_r0()
        monkeypatch.setattr(Path, "read_text", counted_read_text)
        workflow.record_r1([
            Surface(
                f"SURF-cache-{line}", work_unit.work_unit_id, work_unit.component_id,
                "function_entry", "app.py", "handle", "remote",
                (f"LOC-app.py:{line}",),
            )
            for line in (1, 2)
        ])
        source_path = str((tmp_path / "app.py").resolve())
        assert reads[source_path] == 1

        axis_evidence = {
            "surface": ("LOC-app.py:1",), "mechanism": ("LOC-app.py:2",),
            "state": ("EVID-state",), "fix_variant": ("EVID-fix",),
            "boundary": ("EVID-boundary",), "differential": ("EVID-diff",),
        }
        workflow.record_r2([Hypothesis(
            "HYP-line-cache", work_unit.work_unit_id, "surface",
            ("SURF-cache-1",), ("SURF-cache-1",),
            Mechanism("INJECTION", "line-cache"),
            "a source path reaches a sink", HypothesisStatus.NEW,
        )], axis_evidence=axis_evidence,
            axis_runs=axis_runs_from_evidence(axis_evidence))
        reads.clear()
        edge_ref = manager.artifacts.put_text("edge proof").artifact_id
        workflow.record_r3([VerdictSubmission(
            "HYP-line-cache", VerdictKind.REACHABLE, EvidenceGrade.EDGE_PROVEN,
            "remote", (), ("LOC-app.py:1", "LOC-app.py:2"),
            (edge_ref,), (), (), "the call chain is source anchored",
        )])
        assert reads[source_path] == 1
    finally:
        manager.close()


def test_r3_accepts_anchor_in_inventory_build_manifest(tmp_path: Path) -> None:
    (tmp_path / "BUILD.gn").write_text("group('v8_fuzzers') {}\n", encoding="utf-8")
    manager, workflow, plan = _workflow(tmp_path, "CMP-build-anchor")
    work_unit = plan.work_units[0]
    try:
        workflow.run_r0()
        workflow.record_r1([Surface(
            "SURF-build-anchor", work_unit.work_unit_id, work_unit.component_id,
            "function_entry", "app.py", "handle", "local", ("LOC-app.py:1",),
        )])
        axis_evidence = {
            "surface": ("LOC-app.py:1",), "mechanism": ("LOC-app.py:1",),
            "state": ("EVID-state",), "fix_variant": ("EVID-fix",),
            "boundary": ("LOC-BUILD.gn:1",), "differential": ("EVID-diff",),
        }
        workflow.record_r2([Hypothesis(
            "HYP-build-anchor", work_unit.work_unit_id, "boundary",
            ("SURF-build-anchor",), ("SURF-build-anchor",),
            Mechanism("INJECTION", "build-declared-entry"),
            "a build-declared target reaches this path", HypothesisStatus.NEW,
        )], axis_evidence=axis_evidence,
            axis_runs=axis_runs_from_evidence(axis_evidence))
        edge_ref = manager.artifacts.put_text("build declaration evidence").artifact_id

        artifact_id = workflow.record_r3([VerdictSubmission(
            "HYP-build-anchor", VerdictKind.REACHABLE, EvidenceGrade.EDGE_PROVEN,
            "local_builder", (), ("LOC-app.py:1", "LOC-BUILD.gn:1"),
            (edge_ref,), (), (), "the build manifest declares the target input",
        )])

        assert artifact_id.startswith("sha256:")
    finally:
        manager.close()


def test_r3_allows_noninventory_schema_as_evidence_not_call_chain(
    tmp_path: Path,
) -> None:
    (tmp_path / "schema.yaml").write_text("entry: generated\n", encoding="utf-8")
    manager, workflow, plan = _workflow(tmp_path, "CMP-schema-evidence")
    work_unit = plan.work_units[0]
    try:
        workflow.run_r0()
        workflow.record_r1([Surface(
            "SURF-schema-evidence", work_unit.work_unit_id, work_unit.component_id,
            "function_entry", "app.py", "handle", "remote", ("LOC-app.py:1",),
        )])
        axis_evidence = {
            "surface": ("LOC-app.py:1",), "mechanism": ("LOC-app.py:1",),
            "state": ("EVID-state",), "fix_variant": ("EVID-fix",),
            "boundary": ("EVID-boundary",), "differential": ("EVID-diff",),
        }
        workflow.record_r2([Hypothesis(
            "HYP-schema-evidence", work_unit.work_unit_id, "surface",
            ("SURF-schema-evidence",), ("SURF-schema-evidence",),
            Mechanism("INJECTION", "generated-schema-contract"),
            "the generated schema constrains the source path",
            HypothesisStatus.NEW,
        )], axis_evidence=axis_evidence,
            axis_runs=axis_runs_from_evidence(axis_evidence))

        with pytest.raises(ModelError, match="source anchor is not in the Campaign inventory"):
            workflow.record_r3([VerdictSubmission(
                "HYP-schema-evidence", VerdictKind.REACHABLE, EvidenceGrade.EDGE_PROVEN,
                "remote", (), ("LOC-schema.yaml:1",), ("LOC-app.py:1",), (), (),
                "a schema file is not itself a source-to-sink call-chain step",
            )])

        artifact_id = workflow.record_r3([VerdictSubmission(
            "HYP-schema-evidence", VerdictKind.REACHABLE, EvidenceGrade.EDGE_PROVEN,
            "remote", (), ("LOC-app.py:1",), ("LOC-schema.yaml:1",), (), (),
            "the source path is constrained by the generated schema",
        )])

        assert artifact_id.startswith("sha256:")
    finally:
        manager.close()


def test_evidence_only_anchor_rejects_audit_and_vcs_state(tmp_path: Path) -> None:
    (tmp_path / "schema.yaml").write_text("field: value\n", encoding="utf-8")
    (tmp_path / ".audit_vnext").mkdir()
    (tmp_path / ".audit_vnext" / "report.md").write_text(
        "prior audit report\n", encoding="utf-8"
    )
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("repository metadata\n", encoding="utf-8")
    manager, workflow, _ = _workflow(tmp_path, "CMP-evidence-state")
    try:
        inventoried = {source.path for source in manager.load_inventory(
            workflow.campaign_id
        ).source_files}
        workflow._validate_source_location(
            "LOC-schema.yaml:1", inventoried, allow_evidence_only=True
        )
        with pytest.raises(ModelError, match="source anchor is not in the Campaign inventory"):
            workflow._validate_source_location(
                "LOC-.audit_vnext/report.md:1",
                inventoried,
                allow_evidence_only=True,
            )
        with pytest.raises(ModelError, match="source anchor is not in the Campaign inventory"):
            workflow._validate_source_location(
                "LOC-.git/config:1", inventoried, allow_evidence_only=True
            )
    finally:
        manager.close()


def test_r1_rejects_surface_anchor_on_blank_line(tmp_path: Path) -> None:
    manager, workflow, plan = _workflow(
        tmp_path, "CMP-blank-surface", source="def handle(value):\n\n    return value\n"
    )
    work_unit = plan.work_units[0]
    try:
        workflow.run_r0()
        with pytest.raises(ModelError, match="blank line"):
            workflow.record_r1([Surface(
                "SURF-blank", work_unit.work_unit_id, work_unit.component_id,
                "function_entry", "app.py", "handle", "remote", ("LOC-app.py:2",),
            )])
    finally:
        manager.close()


def test_r3_rejects_call_chain_anchor_on_blank_line(tmp_path: Path) -> None:
    manager, workflow, plan = _workflow(
        tmp_path, "CMP-blank-chain", source="def handle(value):\n\n    return value\n"
    )
    work_unit = plan.work_units[0]
    try:
        workflow.run_r0()
        workflow.record_r1([Surface(
            "SURF-blank-chain", work_unit.work_unit_id, work_unit.component_id,
            "function_entry", "app.py", "handle", "remote", ("LOC-app.py:1",),
        )])
        axis_evidence = {
            "surface": ("LOC-app.py:1",), "mechanism": ("LOC-app.py:3",),
            "state": ("EVID-state",), "fix_variant": ("EVID-fix",),
            "boundary": ("EVID-boundary",), "differential": ("EVID-diff",),
        }
        workflow.record_r2([Hypothesis(
            "HYP-blank-chain", work_unit.work_unit_id, "surface",
            ("SURF-blank-chain",), ("SURF-blank-chain",),
            Mechanism("INJECTION", "blank-anchor"), "blank anchor is not proof",
            HypothesisStatus.NEW,
        )], axis_evidence=axis_evidence,
            axis_runs=axis_runs_from_evidence(axis_evidence))
        edge_ref = manager.artifacts.put_text("edge proof").artifact_id
        with pytest.raises(ModelError, match="blank line"):
            workflow.record_r3([VerdictSubmission(
                "HYP-blank-chain", VerdictKind.REACHABLE, EvidenceGrade.EDGE_PROVEN,
                "remote", (), ("LOC-app.py:1", "LOC-app.py:2"),
                (edge_ref,), (), (), "blank line cannot anchor a call-chain step",
            )])
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
        invalid_axis_runs = (
            AxisRun(
                axis=axis_runs[0].axis,
                applicability=axis_runs[0].applicability,
                evidence_refs=axis_runs[0].evidence_refs,
                rationale=axis_runs[0].rationale,
                work_unit_id=axis_runs[0].work_unit_id,
                review_altitude="DEEP",
            ),
            *axis_runs[1:],
        )
        with pytest.raises(ModelError, match="invalid review altitude"):
            workflow.record_r2(
                [], axis_evidence=evidence, axis_runs=invalid_axis_runs,
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