import datetime as dt
from dataclasses import replace
import json
from pathlib import Path

import pytest

from reachable_audit.cli import main
from reachable_audit.execution import ManualExecutionBackend, TaskResult, TaskStatus
from reachable_audit.models import CampaignStatus, ModelError
from reachable_audit.store import ConflictError
from test_execution import _setup


def _recovery_case(tmp_path: Path, *, revision_bound=False):
    manager, task = _setup(tmp_path)
    if revision_bound:
        task = replace(task, stage_revision_ids={"R0_COMPLETED": "REV-original"})
    clock = [dt.datetime.now(dt.UTC)]
    backend = ManualExecutionBackend(manager, task.campaign_id, clock=lambda: clock[0])
    backend.submit(task)
    lease = backend.claim("original-worker", lease_seconds=1)
    assert lease is not None
    output = {
        "schema_version": "1.0",
        "review_altitude": "INSPECTED",
        "reviewed_paths": [],
        "surfaces": [],
        "boundary_reviews": [],
    }
    output_ref = manager.artifacts.put_text(json.dumps(output)).artifact_id
    evidence_ref = manager.artifacts.put_text("Existing worker output independently reviewed").artifact_id
    result = TaskResult(
        True, output_ref, "original measured result", {"agent_runs": 1, "wall_seconds": 1},
    )
    clock[0] += dt.timedelta(seconds=2)
    return manager, backend, lease, result, evidence_ref, clock, output


def test_expired_output_requires_explicit_audited_recovery_and_preserves_measurements(
    tmp_path: Path,
) -> None:
    manager, backend, lease, result, evidence, _, _ = _recovery_case(tmp_path)
    try:
        with pytest.raises(ConflictError, match="expired"):
            backend.collect(lease, result)
        recovered = backend.collect(
            lease, result,
            recovery_reason="Recover existing output without dispatch",
            recovery_evidence_refs=(evidence,),
            recovery_actor="operator-a",
        )
        assert recovered.status is TaskStatus.SUCCEEDED
        events = manager.store.list_events(lease.task.campaign_id)
        authorization = next(e for e in events if e.event_type == "TASK_EXPIRED_RECOVERY_AUTHORIZED")
        consumption = next(e for e in events if e.event_type == "TASK_EXPIRED_RECOVERY_CONSUMED")
        completed = next(e for e in events if e.event_type == "TASK_COMPLETED")
        assert authorization.actor == "operator-a"
        assert authorization.payload["worker_id"] == lease.worker_id
        assert authorization.payload["attempt"] == lease.attempt
        assert authorization.payload["output_ref"] == result.output_ref
        assert authorization.payload["evidence_refs"] == [evidence]
        assert consumption.payload["authorization_event_id"] == authorization.event_id
        assert completed.payload["measurements"] == result.measurements
        assert authorization.sequence < consumption.sequence < completed.sequence
        assert len([e for e in events if e.event_type == "TASK_CLAIMED"]) == 1
        with pytest.raises(ModelError, match="hold the task lease"):
            backend.collect(
                lease, result, recovery_authorization_id=authorization.event_id,
            )
    finally:
        manager.close()


def test_recovery_rejects_invalidated_original_inputs(tmp_path: Path) -> None:
    manager, backend, lease, result, evidence, _, _ = _recovery_case(
        tmp_path, revision_bound=True,
    )
    try:
        manager.store.append_event(
            campaign_id=lease.task.campaign_id, batch_id=lease.task.batch_id,
            entity_type="stage_projection", entity_id=lease.task.batch_id,
            event_type="STAGE_PROJECTION_INVALIDATED",
            idempotency_key="invalidate-original-revision", actor="operator",
            payload={"target_stage": "R0_COMPLETED", "target_revision_id": "REV-original"},
        )
        with pytest.raises(ModelError, match="invalidated"):
            backend.collect(
                lease, result, recovery_reason="operator reviewed",
                recovery_evidence_refs=(evidence,),
            )
        assert not manager.store.list_events(
            lease.task.campaign_id, event_type="TASK_EXPIRED_RECOVERY_AUTHORIZED",
        )
    finally:
        manager.close()


def test_recovery_after_wall_deadline_does_not_dispatch_new_work(tmp_path: Path) -> None:
    manager, backend, lease, result, evidence, clock, _ = _recovery_case(tmp_path)
    try:
        campaign = manager.store.get_campaign(lease.task.campaign_id)
        # The clock remains measured from original Campaign creation, never lease renewal.
        frozen_budget = replace(campaign, budget={"max_wall_seconds": 1})
        original_get_campaign = manager.store.get_campaign
        manager.store.get_campaign = lambda campaign_id: (
            frozen_budget if campaign_id == campaign.campaign_id else original_get_campaign(campaign_id)
        )
        clock[0] += dt.timedelta(seconds=5)
        with pytest.raises(ModelError, match="deadline reached"):
            backend.claim("new-worker")
        assert backend.collect(
            lease, result, recovery_reason="Recover completed output only",
            recovery_evidence_refs=(evidence,),
        ).status is TaskStatus.SUCCEEDED
        assert len(manager.store.list_events(
            campaign.campaign_id, event_type="TASK_CLAIMED",
        )) == 1
    finally:
        manager.close()


def test_recovery_preserves_required_host_attestation(tmp_path: Path, monkeypatch) -> None:
    manager, backend, lease, result, evidence, _, _ = _recovery_case(tmp_path)
    try:
        campaign = manager.store.get_campaign(lease.task.campaign_id)
        original_get_campaign = manager.store.get_campaign
        monkeypatch.setattr(
            manager.store, "get_campaign",
            lambda campaign_id: (
                replace(campaign, budget={"require_host_worker_attestation": True})
                if campaign_id == campaign.campaign_id else original_get_campaign(campaign_id)
            ),
        )
        monkeypatch.setenv("VNA_HOST_WORKER_HMAC_KEY", "fixture-secret-" * 4)
        with pytest.raises(ModelError, match="signed host_worker_attestation"):
            backend.collect(
                lease, result, recovery_reason="operator reviewed",
                recovery_evidence_refs=(evidence,),
            )
        assert not manager.store.list_events(
            campaign.campaign_id, event_type="TASK_EXPIRED_RECOVERY_AUTHORIZED",
        )
    finally:
        manager.close()


@pytest.mark.parametrize("kind", ["reason", "evidence", "missing-artifact", "output", "budget"])
def test_recovery_cannot_bypass_normal_validation(tmp_path: Path, kind: str) -> None:
    manager, backend, lease, result, evidence, _, _ = _recovery_case(tmp_path)
    try:
        kwargs = {
            "recovery_reason": "Recover original result",
            "recovery_evidence_refs": (evidence,),
        }
        if kind == "reason":
            kwargs["recovery_reason"] = " "
        elif kind == "evidence":
            kwargs["recovery_evidence_refs"] = ()
        elif kind == "missing-artifact":
            kwargs["recovery_evidence_refs"] = ("sha256:" + "0" * 64,)
        elif kind == "output":
            invalid = manager.artifacts.put_text('{"schema_version":"1.0"}').artifact_id
            result = replace(result, output_ref=invalid)
        elif kind == "budget":
            result = replace(result, measurements={"agent_runs": 1, "wall_seconds": 1, "minutes": 11})
        with pytest.raises((ModelError, ValueError, FileNotFoundError)):
            backend.collect(lease, result, **kwargs)
        assert backend.poll(lease.task.task_id).status is TaskStatus.LEASED
        assert not manager.store.list_events(
            lease.task.campaign_id, event_type="TASK_EXPIRED_RECOVERY_CONSUMED",
        )
    finally:
        manager.close()


def test_recovery_rejects_superseded_attempt_wrong_worker_and_forged_task(tmp_path: Path) -> None:
    manager, backend, lease, result, evidence, _, _ = _recovery_case(tmp_path)
    try:
        for invalid in (
            replace(lease, worker_id="other-worker"),
            replace(lease, task=replace(lease.task, budget={})),
            replace(lease, lease_expires_at="2020-01-01T00:00:00+00:00"),
        ):
            with pytest.raises(ModelError):
                backend.collect(
                    invalid, result, recovery_reason="operator reviewed",
                    recovery_evidence_refs=(evidence,),
                )
        next_lease = backend.claim("replacement-worker", lease_seconds=60)
        assert next_lease is not None and next_lease.attempt == 2
        with pytest.raises(ModelError):
            backend.collect(
                lease, result, recovery_reason="operator reviewed",
                recovery_evidence_refs=(evidence,),
            )
    finally:
        manager.close()


def test_recovery_rejects_closed_campaign(tmp_path: Path) -> None:
    manager, backend, lease, result, evidence, _, _ = _recovery_case(tmp_path)
    try:
        for state in (CampaignStatus.RUNNING, CampaignStatus.INTEGRATING, CampaignStatus.COMPLETE):
            manager.store.transition_campaign(lease.task.campaign_id, state)
        with pytest.raises(ConflictError, match="completed Campaign"):
            backend.collect(
                lease, result, recovery_reason="operator reviewed",
                recovery_evidence_refs=(evidence,),
            )
    finally:
        manager.close()


def test_recovery_authorization_binds_output_and_consumes_only_on_success(tmp_path: Path) -> None:
    manager, backend, lease, result, evidence, clock, _ = _recovery_case(tmp_path)
    try:
        authorization = manager.authorize_expired_task_recovery(
            lease.task.campaign_id,
            task_id=lease.task.task_id, worker_id=lease.worker_id,
            attempt=lease.attempt, output_ref=result.output_ref,
            lease_expires_at=lease.lease_expires_at,
            reason="operator reviewed", evidence_refs=(evidence,),
            now=clock[0].isoformat(),
        )
        alternate = manager.artifacts.put_text(json.dumps({
            "schema_version": "1.0", "review_altitude": "INSPECTED",
            "reviewed_paths": [], "surfaces": [], "boundary_reviews": [],
            "note": "different output",
        })).artifact_id
        with pytest.raises(ConflictError, match="original lease/output"):
            backend.collect(
                lease, replace(result, output_ref=alternate),
                recovery_authorization_id=authorization.event_id,
            )
        assert not manager.store.list_events(
            lease.task.campaign_id, event_type="TASK_EXPIRED_RECOVERY_CONSUMED",
        )
        assert backend.collect(
            lease, result, recovery_authorization_id=authorization.event_id,
        ).status is TaskStatus.SUCCEEDED
    finally:
        manager.close()


@pytest.mark.parametrize("terminal", ["SUCCEEDED", "FAILED", "CANCELLED"])
def test_recovery_rejects_terminal_tasks(tmp_path: Path, terminal: str) -> None:
    manager, backend, lease, result, evidence, clock, _ = _recovery_case(tmp_path)
    try:
        clock[0] = dt.datetime.fromisoformat(lease.lease_expires_at) - dt.timedelta(seconds=0.5)
        if terminal == "CANCELLED":
            backend.release(lease, reason="stop work")
            backend.cancel(lease.task.task_id, reason="operator cancelled task")
        else:
            backend.collect(lease, replace(result, succeeded=terminal == "SUCCEEDED"))
        clock[0] += dt.timedelta(seconds=2)
        with pytest.raises(ModelError, match="hold the task lease"):
            backend.collect(
                lease, result, recovery_reason="operator reviewed",
                recovery_evidence_refs=(evidence,),
            )
    finally:
        manager.close()


def test_recovery_consumption_rolls_back_if_completion_write_fails(
    tmp_path: Path, monkeypatch,
) -> None:
    manager, backend, lease, result, evidence, _, _ = _recovery_case(tmp_path)
    try:
        append = manager.store._append_event_tx

        def fail_completion(**kwargs):
            if kwargs["event_type"] == "TASK_COMPLETED":
                raise RuntimeError("simulated completion storage failure")
            return append(**kwargs)

        monkeypatch.setattr(manager.store, "_append_event_tx", fail_completion)
        with pytest.raises(RuntimeError, match="storage failure"):
            backend.collect(
                lease, result, recovery_reason="operator reviewed",
                recovery_evidence_refs=(evidence,),
            )
        assert backend.poll(lease.task.task_id).status is TaskStatus.LEASED
        assert not manager.store.list_events(
            lease.task.campaign_id, event_type="TASK_EXPIRED_RECOVERY_CONSUMED",
        )
        authorization = manager.store.list_events(
            lease.task.campaign_id, event_type="TASK_EXPIRED_RECOVERY_AUTHORIZED",
        )[0]
        monkeypatch.setattr(manager.store, "_append_event_tx", append)
        assert backend.collect(
            lease, result, recovery_authorization_id=authorization.event_id,
        ).status is TaskStatus.SUCCEEDED
    finally:
        manager.close()


def test_recovery_cli_requires_original_attempt_reason_evidence_and_valid_measurements(
    tmp_path: Path, capsys,
) -> None:
    manager, backend, lease, result, evidence, _, output = _recovery_case(tmp_path)
    try:
        # Use the real wall clock too: the CLI intentionally has no clock override.
        import time
        time.sleep(1.1)
        result_path = tmp_path / "result.json"
        result_value = {
            "succeeded": True, "output": output, "summary": result.summary,
            "measurements": dict(result.measurements),
        }
        result_path.write_text(json.dumps(result_value), encoding="utf-8")
        base = [
            "task-collect", str(manager.target_root), lease.task.campaign_id,
            lease.task.task_id, lease.worker_id, "--state-dir", str(manager.state_dir),
            "--input", str(result_path),
        ]
        assert main(base + ["--recovery"]) == 2
        assert "original --attempt" in capsys.readouterr().err
        assert main(base + ["--reason", "unapproved"]) == 2
        capsys.readouterr()
        recovery = [
            "--recovery", "--reason", "operator reviewed",
            "--attempt", "1", "--evidence-ref", evidence,
        ]
        result_value["measurements"]["wall_seconds"] = 1.5
        result_path.write_text(json.dumps(result_value), encoding="utf-8")
        assert main(base + recovery) == 2
        assert "integers" in capsys.readouterr().err
        result_value["measurements"]["wall_seconds"] = 1
        result_path.write_text(json.dumps(result_value), encoding="utf-8")
        assert main(base + recovery) == 0
        assert json.loads(capsys.readouterr().out)["status"] == "SUCCEEDED"
    finally:
        manager.close()
