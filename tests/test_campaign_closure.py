import json
import os
from pathlib import Path
import signal
import subprocess
import sys

import pytest

from reachable_audit.analysis_models import (
    BatchClosure,
    CampaignClosure,
    HandoffResolution,
    SkillIssue,
    SkillIssueKind,
    SkillIssueStatus,
)
from reachable_audit.campaign_closure import CampaignCloser
from reachable_audit.execution import ManualExecutionBackend, TaskResult, TaskSpec, TaskStatus
from conftest import execution_configuration_fixture
from reachable_audit.graph import build_component_graph
from reachable_audit.models import CampaignStatus, ModelError
from reachable_audit.resource_cleanup import (
    create_campaign_temp_directory,
    register_process_group,
)
from test_experiments_metrics import _ready_for_r5


def _closable_campaign(tmp_path: Path):  # type: ignore[no-untyped-def]
    manager, workflow = _ready_for_r5(tmp_path)
    inventory = manager.load_inventory("CMP-r4")
    manager.record_component_graph(
        campaign_id="CMP-r4", graph=build_component_graph(tmp_path, inventory)
    )
    workflow.record_r5([], [])
    workflow.build_transmission_metrics()
    workflow.close_r6(BatchClosure(
        budget_used={"agent_runs": 2, "minutes": 5},
        constraints_observed=("offline",),
        unreviewed_scope=(),
        residual_risks=("deployment configuration not exercised",),
        lessons=("six-axis clean run completed",),
    ))
    plan_id = str(workflow.batch.manifest["plan_id"])
    return manager, manager.load_audit_plan("CMP-r4", plan_id)


def test_campaign_closure_passes_ten_gates_and_writes_reports(tmp_path: Path) -> None:
    manager, plan = _closable_campaign(tmp_path)
    try:
        report = CampaignCloser(manager, "CMP-r4", plan).close(CampaignClosure(
            architecture_overview="A single Python state component with no external boundary.",
            unreviewed_scope=(),
            residual_risks=("deployment-specific behavior remains untested",),
            limitations=("synthetic fixture",),
            lessons=("clean CategoryRun remains a valid result",),
            knowledge_nominations=("stale-owner mechanism",),
            skill_issues=(),
        ))
        assert report["status"] == "PASS"
        assert set(report["gates"]) == {f"CG{index}" for index in range(1, 11)}
        assert all(gate["pass"] for gate in report["gates"].values())
        assert report["knowledge_published"] is False
        assert manager.store.get_campaign("CMP-r4").status is CampaignStatus.COMPLETE
        report_dir = tmp_path / ".audit_vnext" / "campaigns" / "CMP-r4" / "report"
        assert (report_dir / "report.json").exists()
        assert (report_dir / "report.md").exists()
        lessons = (
            tmp_path / ".audit_vnext" / "campaigns" / "CMP-r4" / "lessons.md"
        ).read_text(encoding="utf-8")
        assert "no skill issues were reported" in lessons
    finally:
        manager.close()


def test_campaign_closure_rejects_incomplete_planned_batch(tmp_path: Path) -> None:
    manager, workflow = _ready_for_r5(tmp_path)
    try:
        inventory = manager.load_inventory("CMP-r4")
        manager.record_component_graph(
            campaign_id="CMP-r4", graph=build_component_graph(tmp_path, inventory)
        )
        plan = manager.load_audit_plan(
            "CMP-r4", str(workflow.batch.manifest["plan_id"])
        )
        with pytest.raises(ModelError, match="CG1"):
            CampaignCloser(manager, "CMP-r4", plan).close(CampaignClosure(
                architecture_overview="Incomplete fixture.",
                unreviewed_scope=("all planned work",),
                residual_risks=("audit incomplete",),
                limitations=(), lessons=(), knowledge_nominations=(),
                skill_issues=(),
            ))
    finally:
        manager.close()


def test_campaign_closure_rejects_blank_closure_statements(tmp_path: Path) -> None:
    manager, plan = _closable_campaign(tmp_path)
    try:
        with pytest.raises(ModelError, match="CG10"):
            CampaignCloser(manager, "CMP-r4", plan).close(CampaignClosure(
                architecture_overview="One component.",
                unreviewed_scope=(),
                residual_risks=("   ",),
                limitations=(),
                lessons=(),
                knowledge_nominations=(),
                skill_issues=(),
            ))
    finally:
        manager.close()


def test_cancelled_handoff_requires_adjudication() -> None:
    with pytest.raises(ModelError, match="adjudication"):
        HandoffResolution.from_dict({
            "handoff_id": "H-1",
            "owner_batch_id": "B-1",
            "outcome": "CANCELLED",
            "evidence_refs": ["ART-1"],
            "rationale": "The boundary is outside the declared product scope.",
        })


def test_campaign_final_report_is_idempotent_but_immutable(tmp_path: Path) -> None:
    manager, plan = _closable_campaign(tmp_path)
    try:
        closure = CampaignClosure(
            architecture_overview="One component.",
            unreviewed_scope=(), residual_risks=(), limitations=(), lessons=(),
            knowledge_nominations=(),
            skill_issues=(),
        )
        first = CampaignCloser(manager, "CMP-r4", plan).close(closure)
        second = CampaignCloser(manager, "CMP-r4", plan).close(closure)
        assert second["artifact_id"] == first["artifact_id"]

        changed = CampaignClosure(
            architecture_overview="A different final account.",
            unreviewed_scope=(), residual_risks=(), limitations=(), lessons=(),
            knowledge_nominations=(),
            skill_issues=(),
        )
        with pytest.raises(ModelError, match="different final report"):
            CampaignCloser(manager, "CMP-r4", plan).close(changed)
    finally:
        manager.close()


def test_campaign_report_exports_scope_and_execution_measurements(tmp_path: Path) -> None:
    manager, plan = _closable_campaign(tmp_path)
    try:
        batch = plan.batches[0]
        backend = ManualExecutionBackend(manager, "CMP-r4")
        input_ref = manager.artifacts.put_text('{"operation":"measurement-fixture"}').artifact_id
        backend.submit(TaskSpec(
            task_id="TASK-measured",
            campaign_id="CMP-r4",
            batch_id=batch.batch_id,
            work_unit_id=plan.work_units[0].work_unit_id,
            operation="measurement-fixture",
            input_refs=(input_ref,),
            required_output="fixture/v1",
            budget={"agent_runs": 1},
        ))
        lease = backend.claim("measurement-worker")
        assert lease is not None
        output_ref = manager.artifacts.put_text("completed fixture output").artifact_id
        backend.collect(lease, TaskResult(
            True,
            output_ref,
            "measured execution",
            {"agent_runs": 1, "wall_seconds": 7, "tokens": 1234},
            {**execution_configuration_fixture(), "host_tool_policy_digest": "sha256:" + "c" * 64},
        ))

        report = CampaignCloser(manager, "CMP-r4", plan).close(CampaignClosure(
            architecture_overview="One component.",
            unreviewed_scope=(), residual_risks=(), limitations=(), lessons=(),
            knowledge_nominations=(), skill_issues=(),
        ))

        measurements = report["execution_measurements"]
        assert measurements["completed_task_count"] == 1
        assert measurements["totals"] == {
            "agent_runs": 1, "wall_seconds": 7, "tokens": 1234,
        }
        assert measurements["configuration_complete"] is True
        assert measurements["configuration_digest"].startswith("sha256:")
        assert measurements["host_configuration_profiles"] == [{
            "model_id": "test-model",
            "runtime_version": "test-runtime/1",
            "host_tool_policy_digest": "sha256:" + "c" * 64,
        }]
        assert measurements["vnext_policy_digest"].startswith("sha256:")
        assert report["repository_size_bytes"] > 0
        assert report["scope_digest"] == plan.inventory_digest
    finally:
        manager.close()


def test_campaign_closure_releases_owned_resources(tmp_path: Path) -> None:
    manager, plan = _closable_campaign(tmp_path)
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        start_new_session=True,
    )
    try:
        register_process_group(
            manager, "CMP-r4", process.pid, label="test service"
        )
        runtime_directory = create_campaign_temp_directory(
            manager, "CMP-r4", label="harness workspace"
        )
        (runtime_directory / "result.txt").write_text("temporary", encoding="utf-8")
        backend = ManualExecutionBackend(manager, "CMP-r4")
        input_ref = manager.artifacts.put_text("{}").artifact_id
        backend.submit(TaskSpec(
            "TASK-abandoned", "CMP-r4", plan.batches[0].batch_id,
            plan.batches[0].batch_id, "abandoned", (input_ref,), "none/v1", {},
        ))

        report = CampaignCloser(manager, "CMP-r4", plan).close(CampaignClosure(
            architecture_overview="One component.",
            unreviewed_scope=(), residual_risks=(), limitations=(), lessons=(),
            knowledge_nominations=(),
            skill_issues=(),
        ))

        process.wait(timeout=2)
        assert not runtime_directory.exists()
        assert backend.poll("TASK-abandoned").status is TaskStatus.CANCELLED
        assert report["resource_cleanup"]["cancelled_task_ids"] == ["TASK-abandoned"]
        assert report["resource_cleanup"]["failures"] == []
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=2)
        manager.close()


def test_campaign_skill_issue_is_loaded_by_next_campaign(tmp_path: Path) -> None:
    manager, plan = _closable_campaign(tmp_path)
    try:
        issue = SkillIssue(
            issue_id="SKILL-001",
            kind=SkillIssueKind.DEFECT,
            stage="R2",
            summary="language alias was not enumerated",
            evidence_refs=("ART-missed-alias",),
            regression_expectation="the alias fixture produces a hypothesis",
            status=SkillIssueStatus.REGRESSION_PENDING,
        )
        CampaignCloser(manager, "CMP-r4", plan).close(CampaignClosure(
            architecture_overview="One component.",
            unreviewed_scope=(), residual_risks=(), limitations=(), lessons=(),
            knowledge_nominations=(), skill_issues=(issue,),
        ))

        ledger = json.loads(
            (tmp_path / ".audit_vnext" / "skill-regression.json").read_text(
                encoding="utf-8"
            )
        )
        assert ledger["pending_issues"][0]["issue_id"] == "SKILL-001"
        campaign_lessons = (
            tmp_path / ".audit_vnext" / "campaigns" / "CMP-r4" / "lessons.md"
        ).read_text(encoding="utf-8")
        assert "language alias was not enumerated" in campaign_lessons
        lessons = (tmp_path / ".audit_vnext" / "lessons.md").read_text(
            encoding="utf-8"
        )
        assert "language alias was not enumerated" in lessons

        manager.create_campaign(
            campaign_id="CMP-next", snapshot_id="fixture:next"
        )
        baseline = next(
            event for event in manager.store.list_events("CMP-next")
            if event.event_type == "SKILL_REGRESSION_BASELINE_RECORDED"
        )
        assert baseline.payload["pending_issue_ids"] == ["SKILL-001"]
    finally:
        manager.close()