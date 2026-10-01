import json
from pathlib import Path

import pytest

from reachable_audit.analysis_models import BatchClosure
from reachable_audit.execution import (
    DiscoveryCoordinator,
    ManualExecutionBackend,
    TaskResult,
)
from reachable_audit.models import BatchStatus, ModelError
from test_experiments_metrics import _ready_for_r5
from conftest import execution_configuration_fixture


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
        lease = backend.claim("closure-reviewer")
        assert lease is not None
        output_ref = manager.artifacts.put_text(json.dumps({
            "schema_version": "1.0",
            "closure": {
                "constraints_observed": ["no network"],
                "unreviewed_scope": [],
                "residual_risks": ["deployment not exercised"],
                "lessons": ["record zero-result category coverage"],
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