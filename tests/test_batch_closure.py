import json
import hashlib
import hmac
from dataclasses import asdict, replace
from pathlib import Path
import sys

import pytest

from reachable_audit.analysis_models import (
    BatchClosure,
    Experiment,
    ExperimentFidelity,
    ExperimentResult,
    EvidenceGrade,
    ExternalObservation,
    Finding,
    FindingSeverity,
    FindingStatus,
    Mechanism,
    R5Assessment,
    R5Disposition,
    SurfaceReviewDisposition,
    SurfaceReviewState,
)
from reachable_audit.execution import (
    DiscoveryCoordinator,
    ManualExecutionBackend,
    TaskResult,
)
from reachable_audit.models import BatchStatus, CampaignStatus, ModelError
from test_experiments_metrics import _ready_for_r5
from reachable_audit.experiments.runner import run_harness
from conftest import execution_configuration_fixture


def test_r5_confirmation_can_confirm_static_only_hypothesis(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, workflow = _ready_for_r5(tmp_path, static_hypothesis=True)
    try:
        observed = run_harness(
            manager,
            workflow.campaign_id,
            command=[sys.executable, "-c", "print('confirmed')"],
            hypothesis_id="HYP-static",
        )
        experiment = Experiment(
            "EXP-static", "HYP-static", ExperimentFidelity.REAL_TARGET,
            ExperimentResult.CONFIRMED, "test target",
            (str(observed["execution_artifact_id"]),),
            (str(observed["stdout_artifact_id"]), str(observed["stderr_artifact_id"])),
            (), (), "managed real-target experiment confirmed the mechanism",
        )
        original_list_events = manager.store.list_events
        harness_event_queries = 0

        def counted_list_events(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
            nonlocal harness_event_queries
            if kwargs.get("event_type") == "HARNESS_EXECUTION_COMPLETED":
                harness_event_queries += 1
            return original_list_events(*args, **kwargs)

        monkeypatch.setattr(manager.store, "list_events", counted_list_events)
        workflow.record_r5([experiment], [R5Assessment(
            hypothesis_id="HYP-static",
            experiment_required=True,
            experiment_id="EXP-static",
            disposition=R5Disposition.EMPIRICALLY_CONFIRMED,
            evidence_refs=experiment.command_refs,
            rationale="the registered experiment reproduced the mechanism",
        )])
        finding = Finding(
            finding_id="FND-static-confirmed",
            root_cause_key="static-mechanism-confirmed-by-r5",
            mechanism=Mechanism("STATE", "static-state-transition"),
            hypothesis_ids=("HYP-static",),
            affected_component_ids=(workflow.batch.manifest["work_units"][0]["component_id"],),
            severity=FindingSeverity.MEDIUM,
            evidence_grade=EvidenceGrade.EMPIRICALLY_CONFIRMED,
            status=FindingStatus.CONFIRMED,
            evidence_refs=(str(observed["execution_artifact_id"]),),
            title="R5-confirmed static-only hypothesis",
        )

        artifact_id = workflow.record_finding(finding)

        assert artifact_id.startswith("sha256:")
        assert harness_event_queries == 1
    finally:
        manager.close()


def test_r6_closes_clean_batch_with_all_eight_gates(tmp_path: Path) -> None:
    manager, workflow = _ready_for_r5(tmp_path)
    try:
        workflow.record_r5([], [])
        report = workflow.close_r6(BatchClosure(
            budget_used={"agent_runs": 2, "minutes": 4},
            constraints_observed=("no network",),
            unreviewed_scope=(),
            residual_risks=("runtime deployment not exercised",),
            lessons=("state axis produced no hypothesis",),
        ))

        assert report["status"] == "PASS"
        assert set(report["gates"]) == {
            "BG1", "BG2", "BG3", "BG4", "BG5", "BG6", "BG7", "BG8"
        }
        assert all(gate["pass"] for gate in report["gates"].values())
        assert manager.store.get_batch(
            "CMP-r4", workflow.batch_id
        ).status is BatchStatus.COMPLETE
    finally:
        manager.close()


def test_r6_defaults_missing_surface_dispositions_to_unreviewed(tmp_path: Path) -> None:
    manager, workflow = _ready_for_r5(tmp_path, surface_without_hypothesis=True)
    try:
        r1_event = workflow._stage_event("R1_COMPLETED")
        surfaces = workflow._read_artifact(r1_event.payload_ref)["surfaces"]
        assert surfaces
        workflow.record_r5([], [])
        report = workflow.close_r6(BatchClosure(
            budget_used={"agent_runs": 1},
            constraints_observed=(),
            unreviewed_scope=(),
            residual_risks=(),
            lessons=(),
        ))
        assert {
            item["state"] for item in report["surface_review_dispositions"]
        } == {SurfaceReviewState.UNREVIEWED.value}
        assert {
            item["surface_id"] for item in report["surface_review_dispositions"]
        } == {item["surface_id"] for item in surfaces}
    finally:
        manager.close()


def test_r6_preserves_explicit_surface_review_disposition(tmp_path: Path) -> None:
    manager, workflow = _ready_for_r5(tmp_path, surface_without_hypothesis=True)
    try:
        r1_event = workflow._stage_event("R1_COMPLETED")
        surface = workflow._read_artifact(r1_event.payload_ref)["surfaces"][0]
        workflow.record_r5([], [])
        report = workflow.close_r6(BatchClosure(
            budget_used={"agent_runs": 1},
            constraints_observed=(),
            unreviewed_scope=(),
            residual_risks=(),
            lessons=(),
            surface_dispositions=(SurfaceReviewDisposition(
                surface_id=surface["surface_id"],
                state=SurfaceReviewState.REVIEWED,
                evidence_refs=tuple(surface["evidence_refs"]),
                rationale="review status asserted from the stage evidence",
            ),),
        ))
        dispositions = {
            item["surface_id"]: item["state"]
            for item in report["surface_review_dispositions"]
        }
        assert dispositions[surface["surface_id"]] == SurfaceReviewState.REVIEWED.value
        assert sum(
            state == SurfaceReviewState.UNREVIEWED.value
            for state in dispositions.values()
        ) == len(report["surface_review_dispositions"]) - 1
    finally:
        manager.close()


def test_r6_allows_static_only_verdict_with_explicit_review_disposition(
    tmp_path: Path,
) -> None:
    manager, workflow = _ready_for_r5(tmp_path, static_hypothesis=True)
    try:
        workflow.record_r5([], [R5Assessment(
            hypothesis_id="HYP-static",
            experiment_required=False,
            experiment_id=None,
            disposition=R5Disposition.STATIC_VERDICT_RETAINED,
            evidence_refs=("LOC-state.py:1",),
            rationale="mechanism is plausible, but the chain remains static-only",
        )])
        report = workflow.close_r6(BatchClosure(
            budget_used={"agent_runs": 1},
            constraints_observed=(),
            unreviewed_scope=(),
            residual_risks=("static-only chain remains unproven",),
            lessons=(),
        ))

        assert report["gates"]["BG2"]["pass"] is True
        assert report["needs_review_hypothesis_ids"] == ["HYP-static"]
        assert report["static_only_retained_as_review"] == ["HYP-static"]
    finally:
        manager.close()


def test_signed_external_observation_is_registered_without_r5_upgrade(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    manager, workflow = _ready_for_r5(tmp_path, static_hypothesis=True)
    secret = "external-observation-authority-key-2026".encode()
    monkeypatch.setenv("VNA_R5_EXTERNAL_OBSERVATION_HMAC_KEY", secret.decode())
    try:
        r2_event = workflow._require_stage("R2_COMPLETED")
        evidence_ref = r2_event.payload_ref
        assert evidence_ref is not None
        unsigned = {
            "schema_version": "1.0",
            "observation_id": "OBS-host-001",
            "campaign_id": workflow.campaign_id,
            "batch_id": workflow.batch_id,
            "snapshot_id": manager.store.get_campaign(workflow.campaign_id).snapshot_id,
            "hypothesis_id": "HYP-static",
            "target_ref": manager.store.get_campaign(workflow.campaign_id).target_root,
            "observer_id": "independent-observer-001",
            "method": "manual runtime observation",
            "observed_at": "2026-10-18T12:00:00Z",
            "evidence_refs": [evidence_ref],
        }

        def signed(
            signature: str | None = None, *, target_ref: str | None = None,
        ) -> ExternalObservation:
            observation_value = {
                **unsigned,
                "target_ref": target_ref or unsigned["target_ref"],
            }
            canonical = json.dumps(
                observation_value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            value = {
                **observation_value,
                "signature": signature or hmac.new(
                    secret, canonical, hashlib.sha256,
                ).hexdigest(),
            }
            return ExternalObservation.from_dict(value)

        with pytest.raises(ValueError, match="signature is invalid"):
            manager.record_external_observation(signed("0" * 64))
        assert not manager.store.list_events(
            workflow.campaign_id,
            entity_type="external_observation",
            event_type="OUT_OF_BAND_OBSERVATION_RECORDED",
        )
        with pytest.raises(ValueError, match="target does not match Campaign"):
            manager.record_external_observation(signed(target_ref="other-target"))
        assert not manager.store.list_events(
            workflow.campaign_id,
            entity_type="external_observation",
            event_type="OUT_OF_BAND_OBSERVATION_RECORDED",
        )

        from reachable_audit.cli import main

        observation_path = tmp_path / "external-observation.json"
        observation_path.write_text(json.dumps(asdict(signed())), encoding="utf-8")
        assert main([
            "r5-observation-register",
            str(tmp_path),
            workflow.campaign_id,
            "--input",
            str(observation_path),
        ]) == 0
        registration = json.loads(capsys.readouterr().out)
        assert registration["effect"] == "EVIDENCE_ONLY_NOT_CONFIRMING"
        observation_ref = registration["artifact_id"]
        observation_event = manager.store.list_events(
            workflow.campaign_id,
            entity_type="external_observation",
            event_type="OUT_OF_BAND_OBSERVATION_RECORDED",
        )[0]
        assert observation_event.payload["r5_effect"] == "EVIDENCE_ONLY_NOT_CONFIRMING"
        assert observation_event.payload_ref == observation_ref

        backend = ManualExecutionBackend(manager, workflow.campaign_id)
        r5_tasks = DiscoveryCoordinator(
            workflow, backend,
        ).schedule_r5()
        assert len(r5_tasks) == 1
        r5_input = json.loads(
            manager.artifacts.get_bytes(r5_tasks[0].task.input_refs[0])
        )
        assert r5_input["registered_external_observations"][0]["artifact_id"] == observation_ref

        workflow.record_r5([], [R5Assessment(
            hypothesis_id="HYP-static",
            experiment_required=False,
            experiment_id=None,
            disposition=R5Disposition.NEEDS_REVIEW,
            evidence_refs=(observation_ref,),
            rationale="external observation is registered but not independently promoted",
            external_observation_refs=(observation_ref,),
        )])
        r5_event = workflow._require_stage("R5_COMPLETED")
        r5 = json.loads(manager.artifacts.get_bytes(r5_event.payload_ref))
        assert r5["assessments"][0]["disposition"] == R5Disposition.NEEDS_REVIEW.value
    finally:
        manager.close()


def test_not_feasible_r5_is_required_unresolved_and_never_confirms(
    tmp_path: Path,
) -> None:
    manager, workflow = _ready_for_r5(tmp_path, static_hypothesis=True)
    try:
        assessment = R5Assessment(
            hypothesis_id="HYP-static",
            experiment_required=True,
            experiment_id=None,
            disposition=R5Disposition.NOT_FEASIBLE,
            evidence_refs=("EVID-missing-toolchain",),
            rationale="the required target runtime is unavailable in this environment",
        )
        workflow.record_r5([], [assessment])

        with pytest.raises(ModelError, match="empirical R5 assessment"):
            workflow.record_finding(Finding(
                finding_id="FND-not-feasible",
                root_cause_key="not-feasible-is-not-confirmation",
                mechanism=Mechanism("STATE", "static-state-transition"),
                hypothesis_ids=("HYP-static",),
                affected_component_ids=(
                    workflow.batch.manifest["work_units"][0]["component_id"],
                ),
                severity=FindingSeverity.MEDIUM,
                evidence_grade=EvidenceGrade.EMPIRICALLY_CONFIRMED,
                status=FindingStatus.CONFIRMED,
                evidence_refs=("EVID-missing-toolchain",),
                title="infeasible experiment is not empirical confirmation",
            ))

        report = workflow.close_r6(BatchClosure(
            budget_used={"agent_runs": 1},
            constraints_observed=("target runtime unavailable",),
            unreviewed_scope=(),
            residual_risks=("required experiment was not feasible",),
            lessons=(),
        ))
        assert report["gates"]["BG2"]["pass"] is True
        assert report["gates"]["BG3"]["pass"] is True
        assert report["needs_review_hypothesis_ids"] == ["HYP-static"]
        assert report["not_feasible_experiment_hypothesis_ids"] == ["HYP-static"]
        assert report["static_only_r5_dispositions"]["HYP-static"] == "NOT_FEASIBLE"
    finally:
        manager.close()


@pytest.mark.parametrize(
    "changes",
    (
        {"experiment_required": False},
        {"experiment_id": "EXP-attempted"},
    ),
)
def test_not_feasible_r5_requires_required_null_experiment(
    changes: dict[str, object],
) -> None:
    value: dict[str, object] = {
        "hypothesis_id": "HYP-not-feasible",
        "experiment_required": True,
        "experiment_id": None,
        "disposition": "NOT_FEASIBLE",
        "evidence_refs": ["EVID-blocker"],
        "rationale": "documented host constraint prevented execution",
    }
    value.update(changes)
    with pytest.raises(ModelError, match="NOT_FEASIBLE requires"):
        R5Assessment.from_dict(value)

def test_not_feasible_r5_cannot_hide_an_attempted_experiment(
    tmp_path: Path,
) -> None:
    manager, workflow = _ready_for_r5(tmp_path, static_hypothesis=True)
    try:
        attempted = Experiment(
            "EXP-inconclusive", "HYP-static", ExperimentFidelity.REAL_TARGET,
            ExperimentResult.INCONCLUSIVE, "target", ("CMD-attempted",),
            ("OBS-attempted",), (), (), "the attempt produced no conclusion",
        )
        assessment = R5Assessment(
            hypothesis_id="HYP-static",
            experiment_required=True,
            experiment_id=None,
            disposition=R5Disposition.NOT_FEASIBLE,
            evidence_refs=("EVID-host-limit",),
            rationale="claimed unavailable after the experiment had already run",
        )
        with pytest.raises(ModelError, match="cannot accompany an attempted experiment"):
            workflow.record_r5([attempted], [assessment])
    finally:
        manager.close()


@pytest.mark.parametrize(
    "disposition",
    (R5Disposition.EMPIRICALLY_CONFIRMED, R5Disposition.REFUTED),
)
def test_bg2_accepts_every_explicit_r5_disposition_for_static_only_verdict(
    tmp_path: Path, disposition: R5Disposition,
) -> None:
    manager, workflow = _ready_for_r5(tmp_path, static_hypothesis=True)
    try:
        if disposition is R5Disposition.EMPIRICALLY_CONFIRMED:
            observed = run_harness(
                manager, workflow.campaign_id,
                command=[sys.executable, "-c", "print('observed')"],
                hypothesis_id="HYP-static",
            )
            experiment = Experiment(
                "EXP-static", "HYP-static", ExperimentFidelity.REAL_TARGET,
                ExperimentResult.CONFIRMED, "test target",
                (str(observed["execution_artifact_id"]),),
                (str(observed["stdout_artifact_id"]), str(observed["stderr_artifact_id"])),
                (), (), "managed experiment confirmed the mechanism",
            )
        else:
            experiment = Experiment(
                "EXP-static", "HYP-static", ExperimentFidelity.REAL_TARGET,
                ExperimentResult.REFUTED, "test target", ("CMD-refute",),
                ("OBS-refute",), (), (), "experiment refuted the mechanism",
            )
        workflow.record_r5([experiment], [R5Assessment(
            hypothesis_id="HYP-static",
            experiment_required=True,
            experiment_id="EXP-static",
            disposition=disposition,
            evidence_refs=experiment.command_refs,
            rationale="R5 records an explicit disposition for the static-only R3 chain",
        )])
        report = workflow.close_r6(BatchClosure(
            budget_used={"agent_runs": 1},
            constraints_observed=(),
            unreviewed_scope=(),
            residual_risks=("R3 call chain is static-only",),
            lessons=(),
        ))

        assert report["gates"]["BG2"]["pass"] is True
        assert report["gates"]["BG2"]["detail"]["static_only_r5_dispositions"] == {
            "HYP-static": disposition.value,
        }
        assert "HYP-static" in report["static_only_reachable_hypothesis_ids"]
    finally:
        manager.close()


def test_r6_rejects_missing_r5(tmp_path: Path) -> None:
    manager, workflow = _ready_for_r5(tmp_path)
    try:
        with pytest.raises(ModelError, match="BG1"):
            workflow.close_r6(BatchClosure(
                budget_used={"minutes": 1},
                constraints_observed=(),
                unreviewed_scope=(),
                residual_risks=(),
                lessons=(),
            ))
    finally:
        manager.close()


def test_r5_exact_retry_reuses_artifact_and_rejects_conflicts_before_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, workflow = _ready_for_r5(tmp_path, static_hypothesis=True)
    assessment = R5Assessment(
        hypothesis_id="HYP-static",
        experiment_required=False,
        experiment_id=None,
        disposition=R5Disposition.NEEDS_REVIEW,
        evidence_refs=("EVID-review",),
        rationale="the static-only claim needs manual review",
    )
    try:
        original_append = manager.store._append_event_tx

        def fail_r5_append(**kwargs: object) -> object:
            if kwargs.get("event_type") == "R5_COMPLETED":
                raise RuntimeError("injected R5 event append failure")
            return original_append(**kwargs)

        monkeypatch.setattr(manager.store, "_append_event_tx", fail_r5_append)
        with pytest.raises(RuntimeError, match="injected R5 event append failure"):
            workflow.record_r5([], [assessment])
        assert workflow._stage_event("R5_COMPLETED") is None

        monkeypatch.setattr(manager.store, "_append_event_tx", original_append)
        artifact_id = workflow.record_r5([], [assessment])
        original_put_text = manager.artifacts.put_text
        writes = []

        def track_artifact_write(value: str) -> object:
            writes.append(value)
            return original_put_text(value)

        monkeypatch.setattr(manager.artifacts, "put_text", track_artifact_write)
        assert workflow.record_r5([], [assessment]) == artifact_id
        with pytest.raises(ModelError, match="R5_COMPLETED already committed"):
            workflow.record_r5([], [replace(
                assessment, rationale="conflicting R5 assessment",
            )])
        assert writes == []
        stage_events = workflow._events(event_type="R5_COMPLETED")
        assert len(stage_events) == 1
        assert stage_events[0].payload_ref == artifact_id
    finally:
        manager.close()


def test_r6_can_append_a_report_revision(tmp_path: Path) -> None:
    manager, workflow = _ready_for_r5(tmp_path)
    try:
        workflow.record_r5([], [])
        first = workflow.close_r6(BatchClosure(
            budget_used={"agent_runs": 1},
            constraints_observed=(),
            unreviewed_scope=(),
            residual_risks=("initial risk",),
            lessons=("initial close",),
        ))
        second = workflow.close_r6(BatchClosure(
            budget_used={"agent_runs": 2},
            constraints_observed=(),
            unreviewed_scope=(),
            residual_risks=("updated risk after late finding",),
            lessons=("reconciled after late finding",),
        ))

        events = [
            event for event in manager.store.list_events("CMP-r4")
            if event.batch_id == workflow.batch_id and event.event_type == "R6_COMPLETED"
        ]
        assert len(events) == 2
        assert events[0].payload_ref == first["artifact_id"]
        assert events[1].payload_ref == second["artifact_id"]
        latest = json.loads(manager.artifacts.get_bytes(events[-1].payload_ref))
        assert latest["closure"]["lessons"] == ["reconciled after late finding"]
    finally:
        manager.close()


def test_r6_rejects_handoff_manifest_mismatch(tmp_path: Path) -> None:
    manager, workflow = _ready_for_r5(tmp_path)
    try:
        workflow.record_r5([], [])
        workflow.batch.manifest["handoff_ids"] = ["HO-forged"]

        with pytest.raises(ModelError, match="BG5"):
            workflow.close_r6(BatchClosure(
                budget_used={"agent_runs": 1},
                constraints_observed=(),
                unreviewed_scope=(),
                residual_risks=(),
                lessons=(),
            ))
    finally:
        manager.close()


def test_r6_closure_evidence_runs_as_durable_task(tmp_path: Path) -> None:
    manager, workflow = _ready_for_r5(tmp_path)
    try:
        workflow.record_r5([], [])
        backend = ManualExecutionBackend(manager, "CMP-r4")
        coordinator = DiscoveryCoordinator(workflow, backend)
        coordinator.schedule_r6()
        r1_event = workflow._stage_event("R1_COMPLETED")
        r1_artifact = workflow._read_artifact(r1_event.payload_ref)
        lease = backend.claim("closure-reviewer")
        assert lease is not None
        output_ref = manager.artifacts.put_text(json.dumps({
            "schema_version": "1.0",
            "closure": {
                "constraints_observed": ["no network"],
                "unreviewed_scope": [],
                "residual_risks": ["deployment not exercised"],
                "lessons": ["record zero-result category coverage"],
                "surface_dispositions": [
                    {
                        "surface_id": surface["surface_id"],
                        "state": "UNREVIEWED",
                        "evidence_refs": [],
                        "rationale": "fixture does not claim observed Surface review",
                    }
                    for surface in r1_artifact["surfaces"]
                ],
            },
        })).artifact_id
        backend.collect(lease, TaskResult(
            True, output_ref, "closure evidence collected", {"minutes": 3, "agent_runs": 1, "wall_seconds": 3},
            execution_configuration_fixture(),
        ))
        report = coordinator.commit_r6()
        assert report["status"] == "PASS"
        assert report["closure"]["budget_used"] == {
            "minutes": 3,
            "agent_runs": 1,
            "wall_seconds": 3,
            "task_count": 1,
        }
    finally:
        manager.close()


def test_committed_r6_amendment_appends_projection_while_campaign_open(
    tmp_path: Path,
) -> None:
    manager, workflow = _ready_for_r5(tmp_path)
    try:
        workflow.record_r5([], [])
        backend = ManualExecutionBackend(manager, workflow.campaign_id)
        coordinator = DiscoveryCoordinator(workflow, backend)
        task = coordinator.schedule_r6().task
        r1_artifact = json.loads(manager.artifacts.get_bytes(task.input_refs[1]))
        dispositions = [
            {
                "surface_id": surface["surface_id"],
                "state": SurfaceReviewState.UNREVIEWED.value,
                "evidence_refs": [],
                "rationale": "no review state was established",
            }
            for surface in r1_artifact["surfaces"]
        ]
        output = {
            "schema_version": "1.0",
            "closure": {
                "constraints_observed": [],
                "unreviewed_scope": [],
                "residual_risks": [],
                "lessons": ["initial closure"],
                "surface_dispositions": dispositions,
            },
        }
        lease = backend.claim("closure-reviewer")
        assert lease is not None
        original_ref = manager.artifacts.put_text(json.dumps(output)).artifact_id
        backend.collect(lease, TaskResult(
            True, original_ref, "initial closure", {"agent_runs": 1, "wall_seconds": 1},
            execution_configuration_fixture(),
        ))
        first_report = coordinator.commit_r6()

        replacement = {
            **output,
            "closure": {**output["closure"], "lessons": ["amended closure"]},
        }
        replacement_ref = manager.artifacts.put_text(json.dumps(replacement)).artifact_id
        backend.amend_completed_output(
            task.task_id, replacement_ref, reason="corrected closure lesson",
            evidence_refs=(original_ref, replacement_ref),
        )
        second_report = coordinator.commit_r6()

        assert first_report["closure"]["lessons"] == ("initial closure",)
        assert second_report["closure"]["lessons"] == ("amended closure",)
        r6_events = manager.store.list_batch_events(
            workflow.campaign_id, workflow.batch_id, event_type="R6_COMPLETED",
        )
        assert len(r6_events) == 2
        assert r6_events[-1].payload_ref == second_report["artifact_id"]

        campaign = manager.store.get_campaign(workflow.campaign_id)
        if campaign.status is CampaignStatus.RUNNING:
            manager.store.transition_campaign(
                workflow.campaign_id, CampaignStatus.INTEGRATING,
            )
        manager.store.transition_campaign(
            workflow.campaign_id, CampaignStatus.COMPLETE,
        )
        with pytest.raises(ModelError, match="after Campaign closure"):
            backend.amend_completed_output(
                task.task_id, original_ref, reason="late correction",
                evidence_refs=(replacement_ref,),
            )
    finally:
        manager.close()