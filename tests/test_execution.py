import datetime as dt
from dataclasses import replace
import json
from pathlib import Path

import pytest

from reachable_audit.analysis_models import (
    DiscoveryAxis,
    EvidenceGrade,
    Hypothesis,
    HypothesisStatus,
    Mechanism,
    RevivalOutcome,
    Surface,
    VerdictKind,
    VerdictSubmission,
)
from reachable_audit.campaign import CampaignManager
from reachable_audit.execution import (
    _MAX_TASK_OUTPUT_BYTES,
    DiscoveryCoordinator,
    ManualExecutionBackend,
    TaskResult,
    TaskSpec,
    TaskStatus,
)
from reachable_audit.models import ModelError
from reachable_audit.store import ConflictError
from reachable_audit.runtime_policy import execution_policy_digest
from conftest import axis_runs_from_evidence
from conftest import execution_configuration_fixture
from test_batch_workflow import _workflow


def _setup(tmp_path: Path) -> tuple[CampaignManager, TaskSpec]:
    target = tmp_path / "target"
    target.mkdir()
    manager = CampaignManager(target)
    manager.create_campaign(campaign_id="CMP-exec", snapshot_id="fixture:exec")
    manager.add_batch(
        campaign_id="CMP-exec",
        batch_id="B-1",
        manifest={"work_unit_ids": ["WU-1"]},
    )
    input_ref = manager.artifacts.put_text('{"scope":"WU-1"}').artifact_id
    return manager, TaskSpec(
        task_id="TASK-r1-WU-1",
        campaign_id="CMP-exec",
        batch_id="B-1",
        work_unit_id="WU-1",
        operation="discover_surfaces",
        input_refs=(input_ref,),
        required_output="surface-set/v1",
        budget={"minutes": 10},
    )


def test_manual_backend_leases_once_and_collects_idempotently(tmp_path: Path) -> None:
    manager, task = _setup(tmp_path)
    now = dt.datetime(2026, 9, 29, tzinfo=dt.UTC)
    try:
        backend = ManualExecutionBackend(manager, "CMP-exec", clock=lambda: now)
        assert backend.submit(task).status is TaskStatus.PENDING
        lease = backend.claim("worker-a", lease_seconds=60)
        assert lease is not None
        assert backend.claim("worker-b", lease_seconds=60) is None
        output_ref = manager.artifacts.put_text(json.dumps({
            "schema_version": "1.0",
            "reviewed_paths": [],
            "surfaces": [],
            "boundary_reviews": [],
        })).artifact_id
        result = TaskResult(
            True,
            output_ref,
            "scope inspected",
            {"files": 1, "agent_runs": 1, "wall_seconds": 2},
            {**execution_configuration_fixture(), "model_id": "fixture-model"},
        )
        assert backend.collect(lease, result).status is TaskStatus.SUCCEEDED
        assert backend.collect(lease, result).status is TaskStatus.SUCCEEDED
        completed = next(
            event for event in manager.store.list_events("CMP-exec")
            if event.event_type == "TASK_COMPLETED"
        )
        assert completed.payload["configuration"]["model_id"] == "fixture-model"
    finally:
        manager.close()


def test_collected_r1_output_can_be_amended_before_stage_commit(
    tmp_path: Path,
) -> None:
    manager, workflow, plan = _workflow(tmp_path, "CMP-r1-amend")
    try:
        workflow.run_r0()
        backend = ManualExecutionBackend(manager, workflow.campaign_id)
        coordinator = DiscoveryCoordinator(workflow, backend)
        task = coordinator.schedule_r1()[0].task
        lease = backend.claim("surface-worker", task_id_filter=task.task_id)
        assert lease is not None
        original_ref = manager.artifacts.put_text(json.dumps({
            "schema_version": "1.0",
            "reviewed_paths": list(plan.work_units[0].source_files),
            "surfaces": [{
                "surface_id": "SURF-stray",
                "work_unit_id": plan.work_units[0].work_unit_id,
                "component_id": plan.work_units[0].component_id,
                "kind": "function_entry",
                "entry_path": "elsewhere.py",
                "entry_symbol": "handle",
                "principal": "remote",
                "evidence_refs": ["LOC-elsewhere.py:1"],
            }],
            "boundary_reviews": [],
        })).artifact_id
        backend.collect(lease, TaskResult(
            True, original_ref, "stray surface path",
            {"agent_runs": 1, "wall_seconds": 1},
        ))
        with pytest.raises(ModelError, match="outside Work Unit"):
            coordinator.commit_r1()

        corrected_ref = manager.artifacts.put_text(json.dumps({
            "schema_version": "1.0",
            "reviewed_paths": list(plan.work_units[0].source_files),
            "surfaces": [],
            "boundary_reviews": [],
        })).artifact_id
        amended = backend.amend_completed_output(
            task.task_id,
            corrected_ref,
            reason="restored omitted in-scope reviewed path",
            evidence_refs=(original_ref, corrected_ref),
        )
        assert amended.status is TaskStatus.SUCCEEDED
        assert amended.output_ref == corrected_ref

        coordinator.commit_r1()
        assert workflow._stage_event("R1_COMPLETED") is not None
        with pytest.raises(ModelError, match="after its stage has committed"):
            backend.amend_completed_output(
                task.task_id,
                original_ref,
                reason="attempted post-commit correction",
                evidence_refs=(corrected_ref,),
            )
        amendments = manager.store.list_events(
            workflow.campaign_id,
            entity_type="execution_task_amendment",
            entity_id=task.task_id,
            event_type="TASK_OUTPUT_AMENDED",
        )
        assert len(amendments) == 1
        assert amendments[0].payload["prior_output_ref"] == original_ref
    finally:
        manager.close()


def test_manual_backend_claim_filters_by_operation(tmp_path: Path) -> None:
    manager, task = _setup(tmp_path)
    try:
        backend = ManualExecutionBackend(manager, "CMP-exec")
        unrelated = replace(task, task_id="TASK-refute", operation="refute_reachability")
        backend.submit(unrelated)
        backend.submit(task)

        lease = backend.claim("surface-worker", operation="discover_surfaces")

        assert lease is not None
        assert lease.task.task_id == task.task_id
        assert backend.poll(unrelated.task_id).status is TaskStatus.PENDING
    finally:
        manager.close()


def test_manual_backend_claim_targets_specific_task_and_batch(tmp_path: Path) -> None:
    manager, task = _setup(tmp_path)
    try:
        backend = ManualExecutionBackend(manager, "CMP-exec")
        earlier = replace(task, task_id="TASK-earlier", operation="refute_reachability")
        backend.submit(earlier)
        backend.submit(task)

        lease = backend.claim(
            "surface-worker",
            operation="discover_surfaces",
            batch_id=task.batch_id,
            task_id_filter=task.task_id,
        )

        assert lease is not None
        assert lease.task.task_id == task.task_id
        assert backend.poll(earlier.task_id).status is TaskStatus.PENDING
    finally:
        manager.close()


def test_empty_expected_task_stage_does_not_poll_campaign_queue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, workflow, _ = _workflow(tmp_path, "CMP-empty-stage")
    try:
        backend = ManualExecutionBackend(manager, "CMP-empty-stage")
        coordinator = DiscoveryCoordinator(workflow, backend)

        def unexpected_poll(*args: object, **kwargs: object):
            raise AssertionError("empty stage must not poll unrelated tasks")

        monkeypatch.setattr(backend, "list_tasks", unexpected_poll)
        assert coordinator._successful_tasks("refute_reachability", {}) == ()
    finally:
        manager.close()


def test_zero_hypothesis_r35_stages_short_circuit_without_task_listing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, workflow, _ = _workflow(tmp_path, "CMP-zero-r35")
    try:
        workflow.run_r0()
        workflow.record_r1([])
        evidence = {
            axis.value: (f"EVID-{axis.value}",) for axis in DiscoveryAxis
        }
        workflow.record_r2(
            [], axis_evidence=evidence,
            axis_runs=axis_runs_from_evidence(evidence),
        )
        workflow.record_r3([])
        backend = ManualExecutionBackend(manager, workflow.campaign_id)
        coordinator = DiscoveryCoordinator(workflow, backend)

        def unexpected_list_tasks(*_args: object, **_kwargs: object):
            raise AssertionError("zero-target stage must not enumerate tasks")

        monkeypatch.setattr(backend, "list_tasks", unexpected_list_tasks)
        assert coordinator.schedule_r35_refutations() == ()
        assert coordinator.commit_r35_refutations() == ()
        assert coordinator.schedule_r35_adjudications() == ()
        assert coordinator.commit_r35_adjudications() == ()
        assert coordinator.schedule_r35_revivals() == ()
        coordinator.commit_r35_revivals()
        assert workflow._require_stage("R3_5_COMPLETED") is not None
    finally:
        manager.close()


def test_collect_rejects_bad_output_before_terminalizing_task(tmp_path: Path) -> None:
    manager, task = _setup(tmp_path)
    try:
        backend = ManualExecutionBackend(manager, "CMP-exec")
        backend.submit(task)
        lease = backend.claim("worker-a")
        assert lease is not None
        malformed_ref = manager.artifacts.put_text('{"surfaces":[]}').artifact_id
        malformed = TaskResult(
            True, malformed_ref, "malformed output", {"agent_runs": 1, "wall_seconds": 1},
        )

        with pytest.raises(ModelError, match="schema_version mismatch"):
            backend.collect(lease, malformed)
        assert backend.poll(task.task_id).status is TaskStatus.LEASED

        valid_ref = manager.artifacts.put_text(json.dumps({
            "schema_version": "1.0",
            "reviewed_paths": [],
            "surfaces": [],
            "boundary_reviews": [],
        })).artifact_id
        corrected = TaskResult(
            True, valid_ref, "corrected output", {"agent_runs": 1, "wall_seconds": 1},
        )
        assert backend.collect(lease, corrected).status is TaskStatus.SUCCEEDED
    finally:
        manager.close()


def test_collect_rejects_output_above_size_ceiling(tmp_path: Path) -> None:
    manager, task = _setup(tmp_path)
    try:
        backend = ManualExecutionBackend(manager, "CMP-exec")
        backend.submit(task)
        lease = backend.claim("worker-a")
        assert lease is not None
        oversized_ref = manager.artifacts.put_text(json.dumps({
            "schema_version": "1.0",
            "reviewed_paths": [],
            "surfaces": [],
            "boundary_reviews": [],
            "padding": "x" * (_MAX_TASK_OUTPUT_BYTES + 1),
        })).artifact_id
        with pytest.raises(ModelError, match="exceeds"):
            backend.collect(lease, TaskResult(
                True, oversized_ref, "too large", {"agent_runs": 1, "wall_seconds": 1},
            ))
        assert backend.poll(task.task_id).status is TaskStatus.LEASED
    finally:
        manager.close()


def test_task_inputs_carry_write_once_output_discipline(tmp_path: Path) -> None:
    manager, workflow, _ = _workflow(tmp_path, "CMP-discipline")
    try:
        workflow.run_r0()
        backend = ManualExecutionBackend(manager, workflow.campaign_id)
        task = DiscoveryCoordinator(workflow, backend).schedule_r1()[0].task
        task_input = json.loads(manager.artifacts.get_bytes(task.input_refs[0]))
        assert "single call" in task_input["output_discipline"]
    finally:
        manager.close()


def test_task_result_requires_usage_and_execution_configuration() -> None:
    with pytest.raises(ModelError, match="requires measurements"):
        TaskResult(True, "sha256:" + "a" * 64, "done", {}, execution_configuration_fixture())
    result = TaskResult(True, "sha256:" + "a" * 64, "done", {
            "agent_runs": 1, "wall_seconds": 1,
        })
    assert result.configuration == {}


def test_runtime_policy_digest_is_available_without_host_attestation(tmp_path: Path) -> None:
    manager, task = _setup(tmp_path)
    try:
        backend = ManualExecutionBackend(manager, "CMP-exec")
        backend.submit(task)
        lease = backend.claim("worker")
        assert lease is not None
        output_ref = manager.artifacts.put_text(json.dumps({
            "schema_version": "1.0",
            "reviewed_paths": [],
            "surfaces": [],
            "boundary_reviews": [],
        })).artifact_id
        backend.collect(lease, TaskResult(
            True, output_ref, "collected without host policy API",
            {"agent_runs": 1, "wall_seconds": 1},
        ))
        completed = next(
            event for event in manager.store.list_events("CMP-exec")
            if event.event_type == "TASK_COMPLETED"
        )
        assert completed.payload["configuration"]["vnext_policy_digest"] == execution_policy_digest()
        assert "host_tool_policy_digest" not in completed.payload["configuration"]
    finally:
        manager.close()


def test_expired_lease_is_reclaimed_and_survives_reopen(tmp_path: Path) -> None:
    manager, task = _setup(tmp_path)
    current = dt.datetime(2026, 9, 29, tzinfo=dt.UTC)
    backend = ManualExecutionBackend(manager, "CMP-exec", clock=lambda: current)
    backend.submit(task)
    first = backend.claim("worker-a", lease_seconds=10)
    assert first is not None
    manager.close()

    current += dt.timedelta(seconds=11)
    target = tmp_path / "target"
    with CampaignManager(target) as reopened:
        recovered = ManualExecutionBackend(reopened, "CMP-exec", clock=lambda: current)
        second = recovered.claim("worker-b", lease_seconds=10)
        assert second is not None
        assert second.attempt == 2
        assert recovered.poll(task.task_id).worker_id == "worker-b"


def test_failed_task_can_be_retried_within_attempt_limit(tmp_path: Path) -> None:
    manager, original = _setup(tmp_path)
    task = replace(original, max_attempts=2)
    try:
        backend = ManualExecutionBackend(manager, "CMP-exec")
        backend.submit(task)
        first = backend.claim("worker-a")
        assert first is not None
        failed = TaskResult(False, None, "worker setup failed", {"agent_runs": 1, "wall_seconds": 1})
        assert backend.collect(first, failed).status is TaskStatus.FAILED

        second = backend.claim("worker-b")
        assert second is not None
        assert second.attempt == 2
        valid_ref = manager.artifacts.put_text(json.dumps({
            "schema_version": "1.0", "reviewed_paths": [],
            "surfaces": [], "boundary_reviews": [],
        })).artifact_id
        result = TaskResult(True, valid_ref, "retry succeeded", {"agent_runs": 1, "wall_seconds": 1})
        assert backend.collect(second, result).status is TaskStatus.SUCCEEDED
        assert backend.claim("worker-c") is None
    finally:
        manager.close()


def test_exhausted_task_requires_operator_retry_authorization(tmp_path: Path) -> None:
    manager, original = _setup(tmp_path)
    task = replace(original, max_attempts=1)
    try:
        backend = ManualExecutionBackend(manager, "CMP-exec")
        backend.submit(task)
        first = backend.claim("worker-a")
        assert first is not None
        assert backend.collect(first, TaskResult(
            False, None, "transient worker error", {"agent_runs": 1, "wall_seconds": 1},
        )).status is TaskStatus.FAILED
        assert backend.claim("worker-b") is None

        assert backend.retry(
            task.task_id, reason="operator verified transient environment failure",
        ).status is TaskStatus.PENDING
        second = backend.claim("worker-b")
        assert second is not None
        assert second.attempt == 2
        valid_ref = manager.artifacts.put_text(json.dumps({
            "schema_version": "1.0", "reviewed_paths": [],
            "surfaces": [], "boundary_reviews": [],
        })).artifact_id
        assert backend.collect(second, TaskResult(
            True, valid_ref, "retry succeeded", {"agent_runs": 1, "wall_seconds": 1},
        )).status is TaskStatus.SUCCEEDED
    finally:
        manager.close()


def test_worker_can_release_lease_for_another_compatible_worker(tmp_path: Path) -> None:
    manager, task = _setup(tmp_path)
    try:
        backend = ManualExecutionBackend(manager, "CMP-exec")
        backend.submit(task)
        first = backend.claim("surface-worker")
        assert first is not None
        assert backend.release(first, reason="worker voluntarily released the task").status is TaskStatus.PENDING

        second = backend.claim("surface-worker", operation="discover_surfaces")
        assert second is not None
        assert second.attempt == 2
        with pytest.raises(ConflictError, match="attempt is stale"):
            backend.collect(first, TaskResult(
                False, None, "stale lease", {"agent_runs": 1, "wall_seconds": 1},
            ))
    finally:
        manager.close()


def test_cancelled_task_cannot_be_claimed(tmp_path: Path) -> None:
    manager, task = _setup(tmp_path)
    try:
        backend = ManualExecutionBackend(manager, "CMP-exec")
        backend.submit(task)
        assert backend.cancel(task.task_id, reason="scope superseded").status is TaskStatus.CANCELLED
        assert backend.claim("worker-a") is None
    finally:
        manager.close()


def test_collection_rejects_measurements_over_budget(tmp_path: Path) -> None:
    manager, task = _setup(tmp_path)
    try:
        backend = ManualExecutionBackend(manager, "CMP-exec")
        backend.submit(task)
        lease = backend.claim("worker-a")
        assert lease is not None
        output_ref = manager.artifacts.put_text(json.dumps({
            "schema_version": "1.0",
            "reviewed_paths": [],
            "surfaces": [],
            "boundary_reviews": [],
        })).artifact_id
        with pytest.raises(ModelError, match="exceeded budget"):
            backend.collect(
                lease,
                TaskResult(
                    True, output_ref, "too slow", {"minutes": 11, "agent_runs": 1, "wall_seconds": 11},
                    execution_configuration_fixture(),
                ),
            )
    finally:
        manager.close()


def test_task_id_cannot_be_reused_with_a_different_spec(tmp_path: Path) -> None:
    manager, task = _setup(tmp_path)
    try:
        backend = ManualExecutionBackend(manager, "CMP-exec")
        backend.submit(task)
        with pytest.raises(ModelError, match="different spec"):
            backend.submit(replace(task, required_output="different/v1"))
    finally:
        manager.close()


def test_discovery_coordinator_commits_r1_and_six_axis_r2(tmp_path: Path) -> None:
    manager, workflow, plan = _workflow(tmp_path, "CMP-coordinator")
    try:
        workflow.run_r0()
        backend = ManualExecutionBackend(manager, "CMP-coordinator")
        coordinator = DiscoveryCoordinator(workflow, backend)
        assert len(coordinator.schedule_r1()) == 1
        lease = backend.claim("surface-worker")
        assert lease is not None
        work_unit = plan.work_units[0]
        surface_output = manager.artifacts.put_text(json.dumps({
            "schema_version": "1.0",
            "reviewed_paths": ["app.py"],
            "surfaces": [{
                "surface_id": "SURF-coordinated",
                "work_unit_id": work_unit.work_unit_id,
                "component_id": work_unit.component_id,
                "kind": "function_entry",
                "entry_path": "app.py",
                "entry_symbol": "handle",
                "principal": "remote_unauthenticated",
                "evidence_refs": ["LOC-app.py:1"],
            }],
            "boundary_reviews": [],
        })).artifact_id
        backend.collect(lease, TaskResult(
              True, surface_output, "surface mapped", {"agent_runs": 1, "wall_seconds": 1}, execution_configuration_fixture()
        ))
        coordinator.commit_r1()

        scheduled_tasks = coordinator.schedule_r2()
        assert len(scheduled_tasks) == 6
        r2_inputs = [
            json.loads(manager.artifacts.get_bytes(view.task.input_refs[0]))
            for view in scheduled_tasks
        ]
        assert len(r2_inputs) == 6
        assert all(item["knowledge_context"]["knowledge_version"] == "portfolio-2026-09-v1" for item in r2_inputs)
        assert all(item["knowledge_context"]["issue_entries"] for item in r2_inputs)
        assert all(item["knowledge_context"]["mechanism_cards"] for item in r2_inputs)
        while (axis_lease := backend.claim("hypothesis-worker")) is not None:
            axis = axis_lease.task.operation.split(":", 1)[1]
            hypotheses = []
            if axis == "surface":
                hypotheses.append({
                    "hypothesis_id": "HYP-coordinated",
                    "work_unit_id": work_unit.work_unit_id,
                    "origin_axis": "surface",
                    "seed_refs": ["SURF-coordinated"],
                    "surface_ids": ["SURF-coordinated"],
                    "mechanism": {
                        "family": "INJECTION",
                        "variant": "unsafe-evaluation",
                    },
                    "claim": "untrusted input may reach evaluation",
                    "status": "NEW",
                })
            output_ref = manager.artifacts.put_text(json.dumps({
                "schema_version": "1.0",
                "reviewed_paths": ["app.py"],
                    "axis_run": {
                        "axis": axis,
                        "applicability": (
                            "NOT_APPLICABLE" if axis == "differential" else "APPLICABLE"
                        ),
                        "evidence_refs": [f"EVID-{axis}"],
                        "rationale": (
                            "this static-only fixture has no alternate runtime mode"
                            if axis == "differential"
                            else f"reviewed the {axis} discovery axis"
                        ),
                    },
                "hypotheses": hypotheses,
            })).artifact_id
            backend.collect(
                axis_lease,
                TaskResult(
                    True, output_ref, f"{axis} axis complete", {"agent_runs": 1, "wall_seconds": 1},
                    execution_configuration_fixture(),
                ),
            )
        coordinator.commit_r2()
        report_events = manager.store.list_events("CMP-coordinator")
        assert any(event.event_type == "R1_COMPLETED" for event in report_events)
        r2_event = next(event for event in report_events if event.event_type == "R2_COMPLETED")
        r2_artifact = json.loads(manager.artifacts.get_bytes(r2_event.payload_ref))
        assert len(r2_artifact["axis_runs"]) == 6
        assert next(
            item for item in r2_artifact["axis_runs"]
            if item["axis"] == "differential"
        )["applicability"] == "NOT_APPLICABLE"
        assert set(reference for refs in r2_artifact["axis_evidence"].values() for reference in refs) == {
            f"EVID-{axis.value}" for axis in DiscoveryAxis
        }
    finally:
        manager.close()


def test_revival_task_accepts_worker_not_prebound_to_reviewer_id(tmp_path: Path) -> None:
    manager, workflow, plan = _workflow(tmp_path, "CMP-revival-worker")
    work_unit = plan.work_units[0]
    try:
        workflow.run_r0()
        workflow.record_r1([Surface(
            "SURF-revival", work_unit.work_unit_id, work_unit.component_id,
            "function_entry", "app.py", "handle", "remote", ("LOC-app.py:1",),
        )])
        evidence = {
            "surface": ("LOC-app.py:1",), "mechanism": ("LOC-app.py:1",),
            "state": ("EVID-state",), "fix_variant": ("EVID-fix",),
            "boundary": ("EVID-boundary",), "differential": ("EVID-diff",),
        }
        workflow.record_r2([Hypothesis(
            "HYP-revival", work_unit.work_unit_id, "surface", ("SURF-revival",),
            ("SURF-revival",), Mechanism("INJECTION", "candidate"),
            "candidate is probably blocked", HypothesisStatus.NEW,
        )], axis_evidence=evidence, axis_runs=axis_runs_from_evidence(evidence))
        workflow.record_r3([VerdictSubmission(
            "HYP-revival", VerdictKind.UNREACHABLE, EvidenceGrade.STATIC_ONLY,
            "remote", (), (), (), ("LOC-app.py:1",), (),
            "the input is blocked at the entry guard",
        )])
        workflow.record_revival_selection(
            ["HYP-revival"], rationale="recheck one rejected hypothesis",
            evidence_refs=("LOC-app.py:1",),
        )

        backend = ManualExecutionBackend(manager, workflow.campaign_id)
        coordinator = DiscoveryCoordinator(workflow, backend)
        tasks = coordinator.schedule_r35_revivals()
        assert len(tasks) == 1
        task_input = json.loads(manager.artifacts.get_bytes(tasks[0].task.input_refs[0]))
        lease = backend.claim("available-reviewer")
        assert lease is not None
        assert lease.task.task_id == tasks[0].task.task_id
        output = manager.artifacts.put_text(json.dumps({
            "schema_version": "1.0",
            "revival_review": {
                "revival_id": "REV-HYP-revival",
                "hypothesis_id": "HYP-revival",
                "reviewer_id": task_input["reviewer_id"],
                "outcome": RevivalOutcome.UPHOLD.value,
                "evidence_refs": ["LOC-app.py:1"],
                "rationale": "the guard dominates the candidate path",
            },
        })).artifact_id
        backend.collect(lease, TaskResult(
            True, output, "review completed", {"agent_runs": 1, "wall_seconds": 1},
            execution_configuration_fixture(),
        ))

        coordinator.commit_r35_revivals()
        assert any(
            event.event_type == "R3_5_COMPLETED"
            for event in manager.store.list_events(workflow.campaign_id)
        )
    finally:
        manager.close()


def test_compact_r2_runs_all_axes_in_one_task_per_work_unit(tmp_path: Path) -> None:
    manager, workflow, plan = _workflow(
        tmp_path,
        "CMP-r2-compact",
        "import subprocess\n\ndef handle(command):\n    subprocess.run(command, shell=True)\n",
    )
    try:
        workflow.run_r0()
        backend = ManualExecutionBackend(manager, "CMP-r2-compact")
        coordinator = DiscoveryCoordinator(workflow, backend)
        coordinator.schedule_r1()
        lease = backend.claim("surface-worker")
        assert lease is not None
        r1_output = manager.artifacts.put_text(json.dumps({
            "schema_version": "1.0",
            "reviewed_paths": ["app.py"],
            "surfaces": [],
            "boundary_reviews": [],
        })).artifact_id
        backend.collect(lease, TaskResult(
            True, r1_output, "reviewed scoped sources",
            {"agent_runs": 1, "wall_seconds": 1}, execution_configuration_fixture(),
        ))
        coordinator.commit_r1()

        tasks = coordinator.schedule_r2_compact()
        assert len(tasks) == len(plan.work_units) == 1
        task_input = json.loads(manager.artifacts.get_bytes(tasks[0].task.input_refs[0]))
        assert set(task_input["analysis_contract"]) == {axis.value for axis in DiscoveryAxis}
        assert task_input["hotspot_report"]["provider_id"] == "python-ast-hotspots-v1"
        assert task_input["hotspot_report"]["candidates"][0]["rule_id"] == "PY-CMD-001"
        assert task_input["hotspot_report"]["candidates"][0]["evidence_ref"] == "LOC-app.py:4"
        compact_lease = backend.claim("compact-r2-worker")
        assert compact_lease is not None
        axis_runs = [{
            "axis": axis.value,
            "applicability": "APPLICABLE",
            "evidence_refs": ["LOC-app.py:1"],
            "rationale": f"reviewed {axis.value} axis",
        } for axis in DiscoveryAxis]
        output_ref = manager.artifacts.put_text(json.dumps({
            "schema_version": "1.0",
            "reviewed_paths": ["app.py"],
            "axis_runs": axis_runs,
            "hypotheses": [],
        })).artifact_id
        backend.collect(compact_lease, TaskResult(
            True, output_ref, "completed all six axes",
            {"agent_runs": 1, "wall_seconds": 3}, execution_configuration_fixture(),
        ))
        coordinator.commit_r2_compact()
        r2_event = next(
            event for event in manager.store.list_events("CMP-r2-compact")
            if event.event_type == "R2_COMPLETED"
        )
        r2 = json.loads(manager.artifacts.get_bytes(r2_event.payload_ref))
        assert len(r2["axis_runs"]) == 6
        assert r2["hypotheses"] == []
    finally:
        manager.close()


def test_collect_rejects_incomplete_reviewed_paths_with_gap_list(tmp_path: Path) -> None:
    manager, workflow, _ = _workflow(tmp_path, "CMP-coverage")
    try:
        workflow.run_r0()
        backend = ManualExecutionBackend(manager, "CMP-coverage")
        coordinator = DiscoveryCoordinator(workflow, backend)
        task = coordinator.schedule_r1()[0].task
        lease = backend.claim("worker")
        assert lease is not None
        output_ref = manager.artifacts.put_text(json.dumps({
            "schema_version": "1.0", "reviewed_paths": [], "surfaces": [],
            "boundary_reviews": [],
        })).artifact_id
        with pytest.raises(ModelError, match=r"reviewed path coverage mismatch.*app\.py"):
            backend.collect(lease, TaskResult(
                True, output_ref, "partial", {"agent_runs": 1, "wall_seconds": 1},
                execution_configuration_fixture(),
            ))
        assert backend.poll(task.task_id).status is TaskStatus.LEASED
    finally:
        manager.close()


def test_r1_accepts_reviewed_scope_all_and_input_groups_files_by_directory(
    tmp_path: Path,
) -> None:
    manager, workflow, plan = _workflow(tmp_path, "CMP-scope-all")
    try:
        workflow.run_r0()
        backend = ManualExecutionBackend(manager, "CMP-scope-all")
        coordinator = DiscoveryCoordinator(workflow, backend)
        task = coordinator.schedule_r1()[0].task
        task_input = json.loads(manager.artifacts.get_bytes(task.input_refs[0]))
        assert "source_files" not in task_input["work_unit"]
        assert task_input["work_unit"]["source_files_by_directory"] == {".": ["app.py"]}
        assert task_input["work_unit"]["source_file_count"] == 1
        assert "unsupported_paths" not in task_input["hotspot_report"]

        lease = backend.claim("worker")
        assert lease is not None
        conflicting_ref = manager.artifacts.put_text(json.dumps({
            "schema_version": "1.0", "reviewed_scope": "ALL_SOURCE_FILES",
            "excluded_paths": ["app.py"], "surfaces": [], "boundary_reviews": [],
        })).artifact_id
        with pytest.raises(ModelError, match="conflicts with 1 excluded paths"):
            backend.collect(lease, TaskResult(
                True, conflicting_ref, "conflict", {"agent_runs": 1, "wall_seconds": 1},
            ))
        missing_ref = manager.artifacts.put_text(json.dumps({
            "schema_version": "1.0", "surfaces": [], "boundary_reviews": [],
        })).artifact_id
        with pytest.raises(ModelError, match="reviewed_scope"):
            backend.collect(lease, TaskResult(
                True, missing_ref, "no scope", {"agent_runs": 1, "wall_seconds": 1},
            ))
        complete_ref = manager.artifacts.put_text(json.dumps({
            "schema_version": "1.0", "reviewed_scope": "ALL_SOURCE_FILES",
            "surfaces": [], "boundary_reviews": [],
        })).artifact_id
        backend.collect(lease, TaskResult(
            True, complete_ref, "complete", {"agent_runs": 1, "wall_seconds": 1},
        ))
        coordinator.commit_r1()
        assert workflow._stage_event("R1_COMPLETED") is not None
    finally:
        manager.close()


def test_agent_work_unit_round_trips_grouped_paths() -> None:
    from reachable_audit.execution import _agent_work_unit, _expand_agent_work_unit_files

    unit = {
        "work_unit_id": "WU-1",
        "source_files": ["a.py", "pkg/b.py", "pkg/sub/c.py"],
        "boundary_edge_ids": ["E1", "E2"],
    }
    view = _agent_work_unit(unit, drop_edge_ids=True)
    assert sorted(_expand_agent_work_unit_files(view)) == sorted(unit["source_files"])
    assert view["boundary_edge_count"] == 2 and "boundary_edge_ids" not in view
    assert _agent_work_unit(unit)["boundary_edge_ids"] == ["E1", "E2"]


def test_collect_rejects_missing_boundary_reviews_with_gap_list(tmp_path: Path) -> None:
    manager, task = _setup(tmp_path)
    try:
        backend = ManualExecutionBackend(manager, "CMP-exec")
        input_ref = manager.artifacts.put_text(json.dumps({
            "work_unit": {"work_unit_id": "WU-1", "source_files": []},
            "boundary_edges": [{"edge_id": "EDGE-a"}, {"edge_id": "EDGE-b"}],
        })).artifact_id
        backend.submit(replace(task, input_refs=(input_ref,)))
        lease = backend.claim("worker")
        assert lease is not None
        partial_ref = manager.artifacts.put_text(json.dumps({
            "schema_version": "1.0", "reviewed_paths": [], "surfaces": [],
            "boundary_reviews": [{"edge_id": "EDGE-a"}],
        })).artifact_id
        with pytest.raises(ModelError, match=r"missing=1 \(first \['EDGE-b'\]\)"):
            backend.collect(lease, TaskResult(
                True, partial_ref, "partial", {"agent_runs": 1, "wall_seconds": 1},
            ))
        complete_ref = manager.artifacts.put_text(json.dumps({
            "schema_version": "1.0", "reviewed_paths": [], "surfaces": [],
            "boundary_reviews": [{"edge_id": "EDGE-a"}, {"edge_id": "EDGE-b"}],
        })).artifact_id
        assert backend.collect(lease, TaskResult(
            True, complete_ref, "complete", {"agent_runs": 1, "wall_seconds": 1},
        )).status is TaskStatus.SUCCEEDED
    finally:
        manager.close()


def test_discovery_coordinator_schedules_and_commits_r3(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "schema.yaml").write_text("entry: generated\n", encoding="utf-8")
    manager, workflow, plan = _workflow(tmp_path, "CMP-r3-tasks")
    try:
        work_unit = plan.work_units[0]
        workflow.run_r0()
        workflow.record_r1([Surface(
            "SURF-r3", work_unit.work_unit_id, work_unit.component_id,
            "function_entry", "app.py", "handle", "remote",
            ("LOC-app.py:1",),
        )])
        axis_evidence = {
            "surface": ("LOC-app.py:1",),
            "mechanism": ("LOC-app.py:2",),
            "state": ("EVID-state",),
            "fix_variant": ("EVID-fix",),
            "boundary": ("EVID-boundary",),
            "differential": ("EVID-differential",),
        }
        workflow.record_r2([Hypothesis(
            "HYP-r3", work_unit.work_unit_id, "surface", ("SURF-r3",),
            ("SURF-r3",), Mechanism("INJECTION", "unsafe-evaluation"),
            "input may reach evaluation", HypothesisStatus.NEW,
        )], axis_evidence=axis_evidence,
            axis_runs=axis_runs_from_evidence(axis_evidence))
        backend = ManualExecutionBackend(manager, "CMP-r3-tasks")
        coordinator = DiscoveryCoordinator(workflow, backend)
        assert len(coordinator.schedule_r3()) == 1
        lease = backend.claim("verifier")
        assert lease is not None
        schema_evidence_ref = "LOC-schema.yaml:1"
        bad_output_ref = manager.artifacts.put_text(json.dumps({
            "schema_version": "1.0",
            "verdict": {
                "hypothesis_id": "HYP-r3",
                "verdict": "REACHABLE",
                "evidence_grade": "edge_proven",
                "principal": "remote",
                "preconditions": [],
                "call_chain": ["LOC-src/missing.py:3554"],
                "edge_evidence_ids": [schema_evidence_ref],
                "blocking_evidence_ids": [],
                "experiment_ids": [],
                "rationale": "transcription error in a source anchor",
            },
        })).artifact_id
        with monkeypatch.context() as patch:
            patch.setattr(
                manager,
                "load_inventory",
                lambda *_args, **_kwargs: (_ for _ in ()).throw(
                    AssertionError("indexed collect must not reload Campaign inventory")
                ),
            )
            with pytest.raises(ModelError, match="not in the Campaign inventory"):
                backend.collect(lease, TaskResult(
                    True, bad_output_ref, "bad anchor",
                    {"agent_runs": 1, "wall_seconds": 1},
                    execution_configuration_fixture(),
                ))
        assert backend.poll(lease.task.task_id).status is TaskStatus.LEASED
        output_ref = manager.artifacts.put_text(json.dumps({
            "schema_version": "1.0",
            "verdict": {
                "hypothesis_id": "HYP-r3",
                "verdict": "REACHABLE",
                "evidence_grade": "edge_proven",
                "principal": "remote",
                "preconditions": [],
                "call_chain": ["LOC-app.py:1", "LOC-app.py:2"],
                "edge_evidence_ids": [schema_evidence_ref],
                "blocking_evidence_ids": [],
                "experiment_ids": [],
                "rationale": "direct call and data-flow edge",
            },
        })).artifact_id
        with monkeypatch.context() as patch:
            patch.setattr(
                manager,
                "load_inventory",
                lambda *_args, **_kwargs: (_ for _ in ()).throw(
                    AssertionError("indexed collect must not reload Campaign inventory")
                ),
            )
            backend.collect(lease, TaskResult(
                True, output_ref, "verified",
                {"agent_runs": 1, "wall_seconds": 1},
                execution_configuration_fixture(),
            ))
        coordinator.commit_r3()
        assert workflow.build_r0_r3_report()["verdict_counts"] == {"REACHABLE": 1}
    finally:
        manager.close()


def test_discovery_coordinator_runs_independent_r35_refutations(tmp_path: Path) -> None:
    manager, workflow, plan = _workflow(tmp_path, "CMP-r35-tasks")
    try:
        work_unit = plan.work_units[0]
        workflow.run_r0()
        workflow.record_r1([Surface(
            "SURF-r35", work_unit.work_unit_id, work_unit.component_id,
            "function_entry", "app.py", "handle", "remote",
            ("LOC-app.py:1",),
        )])
        axis_evidence = {
            "surface": ("LOC-app.py:1",),
            "mechanism": ("LOC-app.py:2",),
            "state": ("EVID-state",),
            "fix_variant": ("EVID-fix",),
            "boundary": ("EVID-boundary",),
            "differential": ("EVID-differential",),
        }
        workflow.record_r2([Hypothesis(
            "HYP-r35", work_unit.work_unit_id, "surface", ("SURF-r35",),
            ("SURF-r35",), Mechanism("INJECTION", "unsafe-evaluation"),
            "input may reach evaluation", HypothesisStatus.NEW,
        )], axis_evidence=axis_evidence,
            axis_runs=axis_runs_from_evidence(axis_evidence))
        edge_evidence_ref = manager.artifacts.put_text("R3.5 edge evidence").artifact_id
        workflow.record_r3([VerdictSubmission(
            "HYP-r35", VerdictKind.REACHABLE, EvidenceGrade.EDGE_PROVEN,
            "remote", (), ("LOC-app.py:1",), (edge_evidence_ref,), (), (),
            "direct call and data-flow edge",
        )])
        backend = ManualExecutionBackend(manager, "CMP-r35-tasks")
        coordinator = DiscoveryCoordinator(workflow, backend)
        assert len(coordinator.schedule_r35_refutations()) == 2
        for slot, angle in (("call-chain", "call_chain"), ("premise", "principal")):
            refuter_id = f"refuter:{workflow.batch_id}:HYP-r35:{slot}"
            lease = backend.claim(refuter_id)
            assert lease is not None
            output_ref = manager.artifacts.put_text(json.dumps({
                "schema_version": "1.0",
                "refutation": {
                    "refutation_id": f"REF-{slot}",
                    "hypothesis_id": "HYP-r35",
                    "refuter_id": refuter_id,
                    "verdict": "REACHABLE",
                    "attack_angle": angle,
                    "evidence_refs": [f"EVID-{slot}"],
                    "rationale": f"{slot} perspective supports the path",
                },
            })).artifact_id
            backend.collect(lease, TaskResult(
                        True, output_ref, "refuted", {"agent_runs": 1, "wall_seconds": 1}, execution_configuration_fixture()
            ))
        coordinator.commit_r35_refutations()
        assert len(coordinator.schedule_r35_adjudications()) == 1
        lease = backend.claim("adjudicator")
        assert lease is not None
        output_ref = manager.artifacts.put_text(json.dumps({
            "schema_version": "1.0",
            "adjudication": {
                "adjudication_id": "ADJ-r35",
                "hypothesis_id": "HYP-r35",
                "refutation_ids": ["REF-call-chain", "REF-premise"],
                "final_verdict": "REACHABLE",
                "actor": "auto",
                "source_verifications": [],
                "rationale": "both independent reviews confirm reachability",
            },
        })).artifact_id
        backend.collect(lease, TaskResult(
            True, output_ref, "adjudicated", {"agent_runs": 1, "wall_seconds": 1}, execution_configuration_fixture()
        ))
        coordinator.commit_r35_adjudications()
        assert coordinator.schedule_r35_revivals() == ()
        coordinator.commit_r35_revivals()
        events = manager.store.list_events("CMP-r35-tasks")
        assert sum(event.event_type == "REFUTATION_SUBMITTED" for event in events) == 2
        assert sum(event.event_type == "R3_5_COMPLETED" for event in events) == 1
    finally:
        manager.close()