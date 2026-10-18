import json
import datetime as dt
import os
from dataclasses import replace
from pathlib import Path
import signal
import subprocess
import sys

import pytest

from reachable_audit.analysis_models import (
    BatchClosure,
    CampaignClosure,
    HandoffResolution,
    R5Assessment,
    R5Disposition,
    ScopeDisposition,
    ScopeDispositionKind,
    SkillIssue,
    SkillIssueKind,
    SkillIssueStatus,
)
from reachable_audit.campaign_closure import CampaignCloser
from reachable_audit.execution import (
    DiscoveryCoordinator,
    ManualExecutionBackend,
    TaskResult,
    TaskSpec,
    TaskStatus,
)
from conftest import execution_configuration_fixture
from reachable_audit.graph import build_component_graph
from reachable_audit.inventory import build_inventory
from reachable_audit.models import CampaignAuditMode, CampaignStatus, ModelError
from reachable_audit.plan_models import PlanPathDisposition, PlanPathState
from reachable_audit.planning import create_audit_plan
from reachable_audit.planning import create_audit_plan
from reachable_audit.resource_cleanup import (
    create_campaign_temp_directory,
    register_process_group,
)
from test_experiments_metrics import _ready_for_r5


def _closable_campaign(
    tmp_path: Path, *, surface_without_hypothesis: bool = False,
    screening_work_unit: bool = False, not_feasible: bool = False,
    path_dispositions: tuple[PlanPathDisposition, ...] = (),
    path_review_claims: tuple[dict[str, str], ...] = (),
    axis_review_altitudes: dict[str, str] | None = None,
):  # type: ignore[no-untyped-def]
    manager, workflow = _ready_for_r5(
        tmp_path,
        static_hypothesis=not_feasible,
        surface_without_hypothesis=surface_without_hypothesis,
        screening_work_unit=screening_work_unit,
        path_dispositions=path_dispositions,
        path_review_claims=path_review_claims,
        axis_review_altitudes=axis_review_altitudes,
    )
    inventory = manager.load_inventory("CMP-r4")
    manager.record_component_graph(
        campaign_id="CMP-r4", graph=build_component_graph(tmp_path, inventory)
    )
    if not_feasible:
        workflow.record_r5([], [R5Assessment(
            hypothesis_id="HYP-static",
            experiment_required=True,
            experiment_id=None,
            disposition=R5Disposition.NOT_FEASIBLE,
            evidence_refs=("EVID-environment-blocker",),
            rationale="the required target runtime is unavailable",
        )])
    else:
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
        lessons_path = tmp_path / ".audit_vnext" / "campaigns" / "CMP-r4" / "lessons.md"
        lessons_path.parent.mkdir(parents=True, exist_ok=True)
        lessons_path.write_text("# Operator notes\n\nKeep this note.\n", encoding="utf-8")
        input_ref = manager.artifacts.put_text(json.dumps({
            "operation": "discover_surfaces",
            "snapshot_id": "fixture:r4",
        })).artifact_id
        task_spec_ref = manager.artifacts.put_text(json.dumps({
            "task_id": "TASK-report-inputs",
            "operation": "discover_surfaces",
            "batch_id": plan.batches[0].batch_id,
            "work_unit_id": plan.work_units[0].work_unit_id,
            "input_refs": [input_ref],
            "budget": {"agent_runs": 1},
        })).artifact_id
        output_ref = manager.artifacts.put_text("{}").artifact_id
        manager.store.append_event(
            campaign_id="CMP-r4", batch_id=plan.batches[0].batch_id,
            entity_type="execution_task", entity_id="TASK-report-inputs",
            event_type="TASK_SUBMITTED", idempotency_key="submit-report-inputs",
            actor="test", payload={}, payload_ref=task_spec_ref,
        )
        manager.store.append_event(
            campaign_id="CMP-r4", batch_id=plan.batches[0].batch_id,
            entity_type="execution_task", entity_id="TASK-report-inputs",
            event_type="TASK_COMPLETED", idempotency_key="complete-report-inputs",
            actor="test",
            payload={
                "measurements": {"agent_runs": 1, "wall_seconds": 1},
                "configuration": {
                    "model_id": "test-model",
                    "runtime_version": "test-runtime",
                    "host_tool_policy_digest": "sha256:" + "a" * 64,
                },
            },
            payload_ref=output_ref,
        )
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
        assert report["audit_mode"] == "fresh"
        assert report["scope_completeness"] == "NO_DECLARED_UNREVIEWED_SCOPE"
        assert set(report["gates"]) == {f"CG{index}" for index in range(1, 11)}
        assert all(gate["pass"] for gate in report["gates"].values())
        assert report["knowledge_published"] is False
        task_measurements = report["execution_measurements"]["tasks"]
        assert task_measurements
        assert all(item["input_artifact_refs"] for item in task_measurements)
        assert manager.store.get_campaign("CMP-r4").status is CampaignStatus.COMPLETE
        report_dir = tmp_path / ".audit_vnext" / "campaigns" / "CMP-r4" / "report"
        assert (report_dir / "report.json").exists()
        markdown_report = (report_dir / "report.md").read_text(encoding="utf-8")
        assert "Audit mode: `fresh`" in markdown_report
        assert "NO_DECLARED_UNREVIEWED_SCOPE" in markdown_report
        follow_up_markdown = CampaignCloser._markdown({
            **report, "history_source_campaign_ids": ["CMP-prior"],
        })
        assert follow_up_markdown.index("## Coverage") < follow_up_markdown.index(
            "## Declared History Sources"
        )
        lessons = lessons_path.read_text(encoding="utf-8")
        assert "Keep this note." in lessons
        assert "clean CategoryRun remains a valid result" in lessons
        issues = (
            tmp_path / ".audit_vnext" / "campaigns" / "CMP-r4" / "skill-issues.md"
        ).read_text(encoding="utf-8")
        assert "no skill issues were reported" in issues
    finally:
        manager.close()


def test_campaign_report_preserves_not_feasible_r5_as_unresolved(tmp_path: Path) -> None:
    manager, plan = _closable_campaign(tmp_path, not_feasible=True)
    try:
        report = CampaignCloser(manager, "CMP-r4", plan).close(CampaignClosure(
            architecture_overview="A static-only result with an unavailable runtime.",
            unreviewed_scope=(),
            residual_risks=("required experiment could not run",),
            limitations=("target runtime unavailable",),
            lessons=(),
            knowledge_nominations=(),
            skill_issues=(),
        ))
        assert report["not_feasible_experiment_hypothesis_ids"] == ["HYP-static"]
        assert report["gates"]["CG7"]["pass"] is True
        markdown = CampaignCloser._markdown(report)
        assert "Required Experiments Not Feasible" in markdown
        assert "not evidence of safety, confirmation, or refutation" in markdown
        assert "`HYP-static`" in markdown
    finally:
        manager.close()


def test_campaign_report_marks_screening_scope_not_release_eligible(
    tmp_path: Path,
) -> None:
    manager, plan = _closable_campaign(tmp_path, screening_work_unit=True)
    try:
        report = CampaignCloser(manager, "CMP-r4", plan).close(CampaignClosure(
            architecture_overview="A screening-only component.",
            unreviewed_scope=(), residual_risks=(), limitations=(), lessons=(),
            knowledge_nominations=(), skill_issues=(),
        ))

        assert report["status"] == "PASS"
        assert report["coverage"]["screened_work_units"] == 1
        assert report["coverage"]["substantive_work_units"] == 0
        assert report["screening_coverage"]["screened_fraction"] == 1.0
        assert report["screening_coverage"]["ceiling_status"] == "NOT_CONFIGURED"
        assert report["screening_coverage"]["release_eligible"] is False
        assert report["scope_completeness"] == "WITH_SCREENING_ONLY_WORK_UNITS"
    finally:
        manager.close()


def test_campaign_closure_accepts_reviewed_surface_without_hypothesis(
    tmp_path: Path,
) -> None:
    manager, plan = _closable_campaign(tmp_path, surface_without_hypothesis=True)
    try:
        report = CampaignCloser(manager, "CMP-r4", plan).close(CampaignClosure(
            architecture_overview="A reviewed state component with no security hypothesis.",
            unreviewed_scope=(),
            residual_risks=(),
            limitations=(),
            lessons=("surface reviewed clean across all applicable axes",),
            knowledge_nominations=(),
            skill_issues=(),
        ))

        assert report["gates"]["CG3"]["pass"] is True
        assert report["gates"]["CG3"]["detail"]["surface_count"] == 1
        assert report["gates"]["CG3"]["detail"]["surfaces_without_hypothesis"]
        assert report["surface_review_state_counts"] == {"UNREVIEWED": 1}
        assert report["surface_review_dispositions"][0]["surface_id"] == (
            report["gates"]["CG3"]["detail"]["surfaces_without_hypothesis"][0]
        )
    finally:
        manager.close()


def test_campaign_closure_requires_current_evidence_for_unreviewed_scope(
    tmp_path: Path,
) -> None:
    manager, plan = _closable_campaign(tmp_path)
    try:
        with pytest.raises(ModelError, match="CG10"):
            CampaignCloser(manager, "CMP-r4", plan).close(CampaignClosure(
                architecture_overview="One reviewed component.",
                unreviewed_scope=("trusted-input deserializer family",),
                residual_risks=(), limitations=(), lessons=(),
                knowledge_nominations=(), skill_issues=(),
            ))

        disposition = ScopeDisposition(
            scope_ref="trusted-input deserializer family",
            disposition=ScopeDispositionKind.EXCLUDED,
            snapshot_id="fixture:r4",
            rationale="Current owner review excludes this threat-model class.",
            approved_by="current-reviewer",
            evidence_refs=("LOC-state.py:1",),
        )
        report = CampaignCloser(manager, "CMP-r4", plan).close(CampaignClosure(
            architecture_overview="One reviewed component.",
            unreviewed_scope=("trusted-input deserializer family",),
            residual_risks=("excluded family remains unreviewed",),
            limitations=(), lessons=(), knowledge_nominations=(), skill_issues=(),
            scope_dispositions=(disposition,),
        ))

        assert report["status"] == "PASS"
        assert report["scope_completeness"] == "WITH_DECLARED_UNREVIEWED_SCOPE"
        assert report["scope_dispositions"][0]["approved_by"] == "current-reviewer"
        markdown_report = (
            tmp_path / ".audit_vnext" / "campaigns" / "CMP-r4" / "report" / "report.md"
        ).read_text(encoding="utf-8")
        assert "trusted-input deserializer family" in markdown_report
        assert "approved by `current-reviewer`" in markdown_report
    finally:
        manager.close()


def test_fresh_campaign_rejects_historical_scope_evidence(tmp_path: Path) -> None:
    manager, plan = _closable_campaign(tmp_path)
    try:
        historical_artifact = manager.artifacts.put_text("prior campaign decision")
        manager.store.append_event(
            campaign_id="CMP-r4", batch_id=None,
            entity_type="test_history", entity_id="prior-decision",
            event_type="HISTORICAL_DECISION_IMPORTED",
            idempotency_key="test-historical-scope-evidence",
            actor="test", payload={}, payload_ref=historical_artifact.artifact_id,
        )
        disposition = ScopeDisposition(
            scope_ref="historical scope exclusion",
            disposition=ScopeDispositionKind.EXCLUDED,
            snapshot_id="fixture:r4",
            rationale="Reused a prior decision.",
            approved_by="reviewer",
            evidence_refs=(historical_artifact.artifact_id,),
            history_source_campaign_id="CMP-old",
        )
        with pytest.raises(ModelError, match="CG10"):
            CampaignCloser(manager, "CMP-r4", plan).close(CampaignClosure(
                architecture_overview="One reviewed component.",
                unreviewed_scope=("historical scope exclusion",),
                residual_risks=(), limitations=(), lessons=(),
                knowledge_nominations=(), skill_issues=(),
                scope_dispositions=(disposition,),
            ))
    finally:
        manager.close()


def test_fresh_campaign_rejects_historical_artifact_reregistered_as_current(
    tmp_path: Path,
) -> None:
    manager, plan = _closable_campaign(tmp_path)
    try:
        manager.create_campaign(
            campaign_id="CMP-old-source", snapshot_id="fixture:old"
        )
        old_artifact = manager.artifacts.put_text("prior campaign evidence")
        manager.store.append_event(
            campaign_id="CMP-old-source", batch_id=None,
            entity_type="test_history", entity_id="old-evidence",
            event_type="OLD_EVIDENCE_RECORDED",
            idempotency_key="old-evidence-record",
            actor="test", payload={}, payload_ref=old_artifact.artifact_id,
        )
        manager.store.append_event(
            campaign_id="CMP-r4", batch_id=None,
            entity_type="test_import", entity_id="copied-evidence",
            event_type="HISTORICAL_EVIDENCE_COPIED",
            idempotency_key="copied-evidence-record",
            actor="test", payload={}, payload_ref=old_artifact.artifact_id,
        )
        disposition = ScopeDisposition(
            scope_ref="copied historical evidence",
            disposition=ScopeDispositionKind.EXCLUDED,
            snapshot_id="fixture:r4",
            rationale="The prior artifact was copied into the fresh run.",
            approved_by="reviewer",
            evidence_refs=(old_artifact.artifact_id,),
        )
        with pytest.raises(ModelError, match="CG10"):
            CampaignCloser(manager, "CMP-r4", plan).close(CampaignClosure(
                architecture_overview="One reviewed component.",
                unreviewed_scope=("copied historical evidence",),
                residual_risks=(), limitations=(), lessons=(),
                knowledge_nominations=(), skill_issues=(),
                scope_dispositions=(disposition,),
            ))
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


def test_campaign_closure_uses_latest_r6_report_revision(tmp_path: Path) -> None:
    manager, workflow = _ready_for_r5(tmp_path)
    try:
        plan = manager.load_audit_plan(
            "CMP-r4", str(workflow.batch.manifest["plan_id"])
        )
        inventory = manager.load_inventory("CMP-r4")
        manager.record_component_graph(
            campaign_id="CMP-r4", graph=build_component_graph(tmp_path, inventory)
        )
        workflow.record_r5([], [])
        first = workflow.close_r6(BatchClosure(
            budget_used={"agent_runs": 1}, constraints_observed=(),
            unreviewed_scope=(), residual_risks=(), lessons=(),
        ))
        stale_report = {
            "schema_version": "1.0",
            "campaign_id": "CMP-r4",
            "batch_id": workflow.batch_id,
            "findings": [{"finding_id": "FND-stale"}],
        }
        stale_ref = manager.artifacts.put_text(json.dumps(stale_report)).artifact_id
        manager.store.append_event(
            campaign_id="CMP-r4", batch_id=workflow.batch_id,
            entity_type="batch_stage", entity_id=workflow.batch_id,
            event_type="R6_COMPLETED", idempotency_key="test-r6-stale-revision",
            actor="test", payload={"finding_ids": ["FND-stale"]},
            payload_ref=stale_ref,
        )
        latest = workflow.close_r6(BatchClosure(
            budget_used={"agent_runs": 2}, constraints_observed=(),
            unreviewed_scope=(), residual_risks=(), lessons=("corrected report",),
        ))
        assert latest["artifact_id"] != first["artifact_id"]

        report = CampaignCloser(manager, "CMP-r4", plan).close(CampaignClosure(
            architecture_overview="One reviewed component.",
            unreviewed_scope=(), residual_risks=(), limitations=(),
            lessons=("use latest R6 revision",), knowledge_nominations=(),
            skill_issues=(),
        ))

        assert report["gates"]["CG9"]["pass"] is True
        assert report["findings"] == []
    finally:
        manager.close()


def test_campaign_closure_waits_for_amended_r6_task_projection(tmp_path: Path) -> None:
    manager, workflow = _ready_for_r5(tmp_path)
    try:
        inventory = manager.load_inventory("CMP-r4")
        manager.record_component_graph(
            campaign_id="CMP-r4", graph=build_component_graph(tmp_path, inventory)
        )
        workflow.record_r5([], [])
        workflow.build_transmission_metrics()
        workflow.close_r6(BatchClosure(
            budget_used={"agent_runs": 1}, constraints_observed=(),
            unreviewed_scope=(), residual_risks=(), lessons=("initial close",),
        ))
        plan = manager.load_audit_plan(
            "CMP-r4", str(workflow.batch.manifest["plan_id"])
        )
        backend = ManualExecutionBackend(manager, "CMP-r4")
        coordinator = DiscoveryCoordinator(workflow, backend)
        task = coordinator.schedule_r6().task
        r1_artifact = json.loads(manager.artifacts.get_bytes(task.input_refs[1]))
        output = {
            "schema_version": "1.0",
            "closure": {
                "constraints_observed": [],
                "unreviewed_scope": [],
                "residual_risks": [],
                "lessons": ["durable close"],
                "surface_dispositions": [{
                    "surface_id": surface["surface_id"],
                    "state": "UNREVIEWED",
                    "evidence_refs": [],
                    "rationale": "no review state was established",
                } for surface in r1_artifact["surfaces"]],
            },
        }
        lease = backend.claim("closure-reviewer")
        assert lease is not None
        original_ref = manager.artifacts.put_text(json.dumps(output)).artifact_id
        backend.collect(lease, TaskResult(
            True, original_ref, "durable close",
            {"agent_runs": 1, "wall_seconds": 1}, execution_configuration_fixture(),
        ))
        coordinator.commit_r6()
        amended_output = {
            **output,
            "closure": {**output["closure"], "lessons": ["corrected close"]},
        }
        amended_ref = manager.artifacts.put_text(
            json.dumps(amended_output)
        ).artifact_id
        backend.amend_completed_output(
            task.task_id, amended_ref, reason="corrected closure evidence",
            evidence_refs=(original_ref, amended_ref),
        )
        closer = CampaignCloser(manager, "CMP-r4", plan)
        closure = CampaignClosure(
            architecture_overview="One reviewed component.",
            unreviewed_scope=(), residual_risks=(), limitations=(),
            lessons=("close latest R6 projection",), knowledge_nominations=(),
            skill_issues=(),
        )
        with pytest.raises(ModelError, match="R6 task amendments to be recommitted"):
            closer.close(closure)

        coordinator.commit_r6()
        report = closer.close(closure)
        assert report["gates"]["CG1"]["pass"] is True
    finally:
        manager.close()


def test_campaign_report_preserves_excluded_path_scope(tmp_path: Path) -> None:
    manager, plan = _closable_campaign(
        tmp_path,
        path_dispositions=(PlanPathDisposition(
            path="state.py",
            state=PlanPathState.EXCLUDED,
            rationale="outside the approved audit boundary",
            approved_by="scope-owner",
            evidence_refs=("LOC-state.py:1",),
        ),),
    )
    try:
        report = CampaignCloser(manager, "CMP-r4", plan).close(CampaignClosure(
            architecture_overview="One component with an explicitly excluded path.",
            unreviewed_scope=(), residual_risks=(), limitations=(),
            lessons=(), knowledge_nominations=(), skill_issues=(),
        ))

        assert report["gates"]["CG2"]["pass"] is True
        assert report["coverage"]["inventory_source_files"] == 1
        assert report["coverage"]["included_source_files"] == 0
        assert report["coverage"]["excluded_source_files"] == 1
        assert report["path_scope_counts"]["EXCLUDED"] == 1
        assert report["path_scope_dispositions"] == [{
            "path": "state.py",
            "state": "EXCLUDED",
            "rationale": "outside the approved audit boundary",
            "approved_by": "scope-owner",
            "evidence_refs": ["LOC-state.py:1"],
        }]
        markdown = (
            manager.state_dir / "campaigns" / "CMP-r4" / "report" / "report.md"
        ).read_text(encoding="utf-8")
        assert "**EXCLUDED** `state.py`" in markdown
    finally:
        manager.close()


def test_campaign_closure_rejects_stale_plan_after_new_plan_is_recorded(
    tmp_path: Path,
) -> None:
    manager, old_plan = _closable_campaign(tmp_path)
    try:
        inventory = manager.load_inventory("CMP-r4")
        newer_plan = create_audit_plan(
            campaign_id="CMP-r4",
            inventory=inventory,
            category_families=("STATE", "AUTHN"),
        )
        manager.record_plan(
            campaign_id="CMP-r4", plan=newer_plan, inventory=inventory,
        )

        with pytest.raises(ModelError, match="not the latest recorded Plan"):
            CampaignCloser(manager, "CMP-r4", old_plan).close(CampaignClosure(
                architecture_overview="Stale plan must not close the Campaign.",
                unreviewed_scope=(), residual_risks=(), limitations=(),
                lessons=(), knowledge_nominations=(), skill_issues=(),
            ))
    finally:
        manager.close()


def test_campaign_closure_rejects_plan_object_different_from_recorded_artifact(
    tmp_path: Path,
) -> None:
    manager, plan = _closable_campaign(tmp_path)
    try:
        changed_plan = replace(plan, category_families=("FORGED",))
        with pytest.raises(ModelError, match="differs from latest Plan artifact"):
            CampaignCloser(manager, "CMP-r4", changed_plan).close(CampaignClosure(
                architecture_overview="Mutated plan object must not close the Campaign.",
                unreviewed_scope=(), residual_risks=(), limitations=(),
                lessons=(), knowledge_nominations=(), skill_issues=(),
            ))
    finally:
        manager.close()


def test_campaign_closure_rejects_plan_file_different_from_recorded_artifact(
    tmp_path: Path,
) -> None:
    manager, plan = _closable_campaign(tmp_path)
    try:
        plan_path = (
            manager.state_dir / "campaigns" / "CMP-r4" / "plans"
            / f"{plan.plan_id}.json"
        )
        plan_value = json.loads(plan_path.read_text(encoding="utf-8"))
        plan_value["category_families"] = ["FORGED"]
        plan_path.write_text(json.dumps(plan_value), encoding="utf-8")

        with pytest.raises(ModelError, match="file differs from latest Plan artifact"):
            CampaignCloser(manager, "CMP-r4", plan).close(CampaignClosure(
                architecture_overview="Mutated durable Plan file must not close the Campaign.",
                unreviewed_scope=(), residual_risks=(), limitations=(),
                lessons=(), knowledge_nominations=(), skill_issues=(),
            ))
    finally:
        manager.close()


def test_campaign_closure_rejects_invalid_path_scope_evidence(tmp_path: Path) -> None:
    manager, plan = _closable_campaign(
        tmp_path,
        path_dispositions=(PlanPathDisposition(
            path="state.py",
            state=PlanPathState.DEFERRED,
            rationale="source could not be reviewed",
            approved_by="scope-owner",
            evidence_refs=("LOC-state.py:100",),
        ),),
    )
    try:
        with pytest.raises(ModelError, match="CG2"):
            CampaignCloser(manager, "CMP-r4", plan).close(CampaignClosure(
                architecture_overview="One component with a deferred path.",
                unreviewed_scope=(), residual_risks=(), limitations=(),
                lessons=(), knowledge_nominations=(), skill_issues=(),
            ))
    finally:
        manager.close()


def test_campaign_report_separates_agent_path_review_claims(tmp_path: Path) -> None:
    (tmp_path / "other.py").write_text("OTHER = True\n", encoding="utf-8")
    (tmp_path / "state.py").write_text("STATE = {}\n", encoding="utf-8")
    inventory = build_inventory(tmp_path, "fixture:r4")
    plan_seed = create_audit_plan(
        campaign_id="CMP-r4", inventory=inventory, category_families=["STATE"],
    )
    work_unit_id = plan_seed.work_units[0].work_unit_id
    scope_claims = (
        {
            "work_unit_id": work_unit_id,
            "path": "state.py",
            "claim": "AGENT_DECLARED_REVIEWED",
            "altitude": "INSPECTED",
            "risk_tier": "HIGH",
        },
        {
            "work_unit_id": work_unit_id,
            "path": "other.py",
            "claim": "AGENT_DECLARED_REVIEWED",
            "altitude": "INSPECTED",
            "risk_tier": "LOW",
        },
    )
    manager, plan = _closable_campaign(
        tmp_path,
        path_review_claims=scope_claims,
        axis_review_altitudes={
            "surface": "SCREENED",
            "mechanism": "INSPECTED",
        },
    )
    try:
        assert plan.work_units[0].work_unit_id == work_unit_id
        report = CampaignCloser(manager, "CMP-r4", plan).close(CampaignClosure(
            architecture_overview="One component with an Agent-declared path review.",
            unreviewed_scope=(), residual_risks=(), limitations=(),
            lessons=(), knowledge_nominations=(), skill_issues=(),
        ))

        assert report["coverage"]["agent_declared_reviewed_paths"] == 2
        assert report["coverage"]["agent_declared_path_review_altitudes"] == {
            "INSPECTED": 2,
        }
        assert report["path_review_altitude_counts"] == {
            "INSPECTED": 2,
        }
        assert report["path_risk_tier_altitudes"] == {
            "HIGH": {"INSPECTED": 1},
            "LOW": {"INSPECTED": 1},
        }
        assert report["coverage"]["path_risk_tiers"] == {"HIGH": 1, "LOW": 1}
        assert report["risk_tier_discovery_axis_altitudes"]["HIGH"]["surface"] == {
            "SCREENED": 1,
        }
        assert report["risk_tier_discovery_axis_altitudes"]["LOW"]["mechanism"] == {
            "INSPECTED": 1,
        }
        assert report["discovery_axis_review_altitudes"]["surface"] == {
            "SCREENED": 1,
        }
        assert report["discovery_axis_review_altitudes"]["mechanism"] == {
            "INSPECTED": 1,
        }
        assert report["category_axis_review_altitudes"]["STATE"]["surface"] == {
            "SCREENED": 1,
        }
        assert report["category_axis_review_altitudes"]["STATE"]["mechanism"] == {
            "INSPECTED": 1,
        }
        assert {
            item["path"]: (item["altitude"], item["risk_tier"])
            for item in report["path_review_claims"]
        } == {
            "state.py": ("INSPECTED", "HIGH"),
            "other.py": ("INSPECTED", "LOW"),
        }
        markdown = (
            manager.state_dir / "campaigns" / "CMP-r4" / "report" / "report.md"
        ).read_text(encoding="utf-8")
        assert "Agent declarations, not host-observed file reads" in markdown
        assert "INSPECTED 1" in markdown
        assert "SCREENED 1" in markdown
        assert "tier `HIGH`" in markdown
        assert "`mechanism`: INSPECTED 1" in markdown
        assert "R2 `HIGH` / `surface`: SCREENED 1" in markdown
        assert "R4 `STATE` / `LOW` / `mechanism`: INSPECTED 1" in markdown
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


def test_campaign_closure_json_requires_explicit_scope_dispositions() -> None:
    with pytest.raises(ModelError, match="scope_dispositions"):
        CampaignClosure.from_dict({
            "architecture_overview": "one component",
            "unreviewed_scope": [],
            "residual_risks": [],
            "limitations": [],
            "lessons": [],
            "knowledge_nominations": [],
            "skill_issues": [],
        })


def test_markdown_report_summarizes_and_details_findings_by_severity() -> None:
    report = {
        "campaign_id": "CMP-report",
        "snapshot_id": "fixture:report",
        "status": "PASS",
        "audit_mode": "fresh",
        "scope_completeness": "NO_DECLARED_UNREVIEWED_SCOPE",
        "architecture_overview": "A representative test component.",
        "coverage": {"work_units": 2, "surfaces": 4},
        "findings": [
            {
                "finding_id": "FND-low",
                "severity": "LOW",
                "status": "CONFIRMED",
                "evidence_grade": "edge_proven",
                "title": "Low severity issue",
                "root_cause_key": "low-root",
                "mechanism": {"family": "STATE", "variant": "low-variant"},
                "evidence_refs": ["LOC-src/low.py:4"],
                "affected_component_ids": ["COMP-low"],
                "hypothesis_ids": ["HYP-low"],
                "source_finding_ids": ["FIND-low"],
            },
            {
                "finding_id": "FND-critical",
                "severity": "CRITICAL",
                "status": "CONFIRMED",
                "evidence_grade": "empirically_confirmed",
                "title": "Critical severity issue",
                "root_cause_key": "critical-root",
                "mechanism": {
                    "family": "MEMORY-SAFETY",
                    "variant": "write-overflow",
                    "freeform": "Controlled input crosses the destination bound.",
                },
                "evidence_refs": ["LOC-src/critical.c:42"],
                "affected_component_ids": ["COMP-critical"],
                "hypothesis_ids": ["HYP-critical"],
                "source_finding_ids": ["FIND-critical"],
            },
            {
                "finding_id": "FND-high",
                "severity": "HIGH",
                "status": "NEEDS_REVIEW",
                "evidence_grade": "edge_proven",
                "title": "High severity issue",
                "root_cause_key": "high-root",
                "mechanism": {"family": "RESOURCE-DOS", "variant": "unbounded"},
                "evidence_refs": ["LOC-src/high.go:8"],
                "affected_component_ids": ["COMP-high"],
                "hypothesis_ids": ["HYP-high"],
                "source_finding_ids": ["FIND-high"],
            },
            {
                "finding_id": "FND-medium",
                "severity": "MEDIUM",
                "status": "CONFIRMED",
                "evidence_grade": "edge_proven",
                "title": "Medium severity issue",
                "root_cause_key": "medium-root",
                "mechanism": {"family": "AUTH", "variant": "missing-check"},
                "evidence_refs": ["LOC-src/medium.rs:12"],
                "affected_component_ids": ["COMP-medium"],
                "hypothesis_ids": ["HYP-medium"],
                "source_finding_ids": ["FIND-medium"],
            },
        ],
        "unreviewed_scope": [],
        "scope_dispositions": [],
        "history_source_campaign_ids": [],
        "limitations": [],
        "residual_risks": [],
        "execution_measurements": {"configuration_complete": True},
        "gates": {"CG1": {"pass": True}},
    }

    markdown = CampaignCloser._markdown(report)
    details = markdown.split("## 3. Detailed Findings by Severity", 1)[1]

    assert "## 1. Audit Summary" in markdown
    assert "## 2. Findings Overview" in markdown
    assert "CRITICAL 1, HIGH 1, MEDIUM 1, LOW 1" in markdown
    assert "NEEDS_REVIEW 1" in markdown
    assert "Controlled input crosses the destination bound." in markdown
    assert "LOC-src/critical.c:42" in markdown
    assert details.index("### Critical") < details.index("### High")
    assert details.index("### High") < details.index("### Medium")
    assert details.index("### Medium") < details.index("### Low")


def test_markdown_report_handles_legacy_json_without_scope_metadata() -> None:
    markdown = CampaignCloser._markdown({
        "campaign_id": "CMP-old-report",
        "snapshot_id": "fixture:old",
        "status": "PASS",
        "architecture_overview": "Legacy report fixture.",
        "coverage": {},
        "findings": [],
        "unreviewed_scope": ["prior scope statement"],
        "residual_risks": [],
        "gates": {},
    })

    assert "NOT_RECORDED (legacy report schema)" in markdown
    assert "LEGACY_REPORT_WITH_UNSTRUCTURED_UNREVIEWED_SCOPE" in markdown
    assert "Structured scope dispositions were not recorded" in markdown


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
            {
                "agent_runs": 1, "wall_seconds": 7, "tokens": 1234,
                "input_tokens": 100, "cache_read_tokens": 300, "output_tokens": 50,
            },
            {**execution_configuration_fixture(), "host_tool_policy_digest": "sha256:" + "c" * 64},
        ))
        for task_id, task_measurements in (
            ("TASK-failed-measured", {
                "agent_runs": 1, "wall_seconds": 2, "input_tokens": 50,
                "cache_read_tokens": 0, "output_tokens": 4,
            }),
            ("TASK-failed-missing-usage", {"agent_runs": 1, "wall_seconds": 1}),
        ):
            backend.submit(TaskSpec(
                task_id=task_id,
                campaign_id="CMP-r4",
                batch_id=batch.batch_id,
                work_unit_id=plan.work_units[0].work_unit_id,
                operation="measurement-fixture",
                input_refs=(input_ref,),
                required_output="fixture/v1",
                budget={"agent_runs": 1},
            ))
            failed_lease = backend.claim("measurement-worker", task_id_filter=task_id)
            assert failed_lease is not None
            backend.collect(failed_lease, TaskResult(
                False, None, "failed attempt", task_measurements,
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
            "input_tokens": 100, "cache_read_tokens": 300, "output_tokens": 50,
        }
        assert measurements["totals_by_operation"]["measurement-fixture"]["tasks"] == 1
        assert measurements["usage"] == {
            "tasks_reporting_usage": 1, "tasks_missing_usage": 0,
            "usage_complete": True, "cache_hit_ratio": 0.75,
        }
        assert measurements["attempt_usage"] == {
            "attempt_count": 3,
            "attempts_reporting_usage": 2,
            "attempts_missing_usage": 1,
            "usage_complete": False,
            "totals": {
                "input_tokens": 150, "cache_read_tokens": 300, "output_tokens": 54,
            },
            "totals_by_operation": {
                "measurement-fixture": {
                    "attempts_reporting_usage": 2,
                    "input_tokens": 150,
                    "cache_read_tokens": 300,
                    "output_tokens": 54,
                },
            },
            "missing_attempts": [{
                "task_id": "TASK-failed-missing-usage",
                "event_id": measurements["attempt_usage"]["missing_attempts"][0]["event_id"],
                "event_type": "TASK_FAILED",
            }],
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


@pytest.mark.parametrize("state", ["released", "expired", "cancelled", "active"])
def test_attempt_accounting_never_counts_unreported_claims_as_free(
    tmp_path: Path, state: str,
) -> None:
    manager, plan = _closable_campaign(tmp_path)
    try:
        now = dt.datetime(2026, 10, 17, tzinfo=dt.UTC)
        backend = ManualExecutionBackend(manager, "CMP-r4", clock=lambda: now)
        input_ref = manager.artifacts.put_text("{}").artifact_id
        task = TaskSpec(
            "TASK-interrupted", "CMP-r4", plan.batches[0].batch_id,
            plan.work_units[0].work_unit_id, "measurement-fixture", (input_ref,), "fixture/v1", {},
        )
        backend.submit(task)
        first = backend.claim("interrupted-worker", lease_seconds=1)
        assert first is not None
        if state == "released":
            backend.release(first, reason="interrupted with unreported usage")
        elif state == "cancelled":
            backend.cancel(task.task_id, reason="operator cancelled worker")
        elif state == "expired":
            now += dt.timedelta(seconds=2)
        if state in {"released", "expired"}:
            second = backend.claim("replacement-worker")
            assert second is not None and second.attempt == 2
            output_ref = manager.artifacts.put_text("completed").artifact_id
            backend.collect(second, TaskResult(
                True, output_ref, "retry completed",
                {"agent_runs": 1, "wall_seconds": 1, "input_tokens": 2,
                 "cache_read_tokens": 0, "output_tokens": 1},
                execution_configuration_fixture(),
            ))
        report = CampaignCloser(manager, "CMP-r4", plan).close(CampaignClosure(
            architecture_overview="Interrupted task accounting fixture.",
            unreviewed_scope=(), residual_risks=(), limitations=(), lessons=(),
            knowledge_nominations=(), skill_issues=(),
        ))
        usage = report["execution_measurements"]["attempt_usage"]
        assert usage["usage_complete"] is False
        assert usage["attempts_missing_usage"] == 1
        assert usage["missing_attempts"][0]["event_type"] == "TASK_CLAIMED"
        assert usage["attempt_count"] == (2 if state in {"released", "expired"} else 1)
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
        campaign_issues = (
            tmp_path / ".audit_vnext" / "campaigns" / "CMP-r4" / "skill-issues.md"
        ).read_text(encoding="utf-8")
        assert "language alias was not enumerated" in campaign_issues
        lessons = (tmp_path / ".audit_vnext" / "skill-regression.md").read_text(
            encoding="utf-8"
        )
        assert "language alias was not enumerated" in lessons

        manager.create_campaign(
            campaign_id="CMP-next",
            snapshot_id="fixture:next",
            audit_mode=CampaignAuditMode.FOLLOW_UP,
            history_source_campaign_ids=("CMP-r4",),
        )
        baseline = next(
            event for event in manager.store.list_events("CMP-next")
            if event.event_type == "SKILL_REGRESSION_BASELINE_RECORDED"
        )
        assert baseline.payload["pending_issue_ids"] == ["SKILL-001"]
    finally:
        manager.close()