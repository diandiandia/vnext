import json
from dataclasses import replace
from pathlib import Path

import pytest

from conftest import axis_runs_from_evidence
from reachable_audit.analysis_models import (
    DiscoveryAxis, Surface, Applicability, CategoryRun, CategoryRunStatus, BatchClosure,
)
from reachable_audit.knowledge import create_category_audit_plans
from reachable_audit.inventory import build_inventory
from reachable_audit.campaign import CampaignManager
from reachable_audit.plan_models import PlanPathDisposition, PlanPathState
from reachable_audit.planning import create_audit_plan
from test_category_runs import _card
from test_planning import _fixture_monorepo
from reachable_audit.batch_workflow import BatchWorkflow
from reachable_audit.coverage_critic import (
    POLICY, apply_coverage_extension, commit_critic, coverage_context,
    require_critic, schedule_critic, validate_critic_output, reject_coverage_proposals, _digest,
)
from reachable_audit.execution import ManualExecutionBackend, TaskResult
from reachable_audit.models import ModelError
from test_batch_workflow import _workflow


def _ready(tmp_path: Path):
    manager, workflow, plan = _workflow(tmp_path, constraints=(POLICY,))
    workflow.run_r0()
    unit = plan.work_units[0]
    workflow.record_r1([Surface(
        "S-handler", unit.work_unit_id, unit.component_id, "entry", "app.py",
        "handle", "caller", ("LOC-app.py:1",),
    )])
    evidence = {axis.value: ("LOC-app.py:1",) for axis in DiscoveryAxis}
    workflow.record_r2([], axis_evidence=evidence, axis_runs=axis_runs_from_evidence(evidence))
    return manager, workflow, plan


def _result(workflow, *, proposals=False, phase="initial"):
    context = coverage_context(workflow, phase)
    return {
        "schema_version": "1.0", "context": context,
        "missing_units": ([{"paths": ["app.py"], "reason": "check alternate lifecycle",
                            "evidence_refs": ["LOC-app.py:1"]}] if proposals else []),
        "reassign_ids": [], "stop": not proposals,
        "reviewed_paths": ["app.py"],
        "checks": [{"invariant": "handler entry and alternate paths",
                    "result": "checked the current local source",
                    "evidence_refs": ["LOC-app.py:1"]}],
    }


def _collect(manager, workflow, value, worker="critic-a"):
    view = schedule_critic(workflow, value["context"]["phase"])
    backend = ManualExecutionBackend(manager, workflow.campaign_id)
    lease = backend.claim(worker, task_id_filter=view.task.task_id)
    assert lease is not None
    ref = manager.artifacts.put_text(json.dumps(value)).artifact_id
    backend.collect(lease, TaskResult(
        True, ref, "read-only coverage reviewed", {"agent_runs": 1, "wall_seconds": 1},
    ))
    return view


def _extension(plan):
    return {
        "schema_version": "1.0", "base_plan_id": plan.plan_id,
        "reason": "review lifecycle coverage", "approved_by": "operator",
        "evidence_refs": ["LOC-app.py:1"], "include_paths": [],
        "boundary_edges": [], "recheck_work_unit_ids": [plan.work_units[0].work_unit_id],
    }


def test_critic_gates_r3_and_preserves_no_gap_limit(tmp_path: Path):
    manager, workflow, plan = _ready(tmp_path)
    try:
        with pytest.raises(ModelError, match="critic is missing"):
            r3 = workflow.record_r3([])
            assert workflow.record_r3([]) == r3
            require_critic(workflow, "initial")
        first = schedule_critic(workflow, "initial")
        assert schedule_critic(workflow, "initial").task.task_id == first.task.task_id
        _collect(manager, workflow, _result(workflow))
        ref = commit_critic(workflow, "initial")
        assert commit_critic(workflow, "initial") == ref
        require_critic(workflow, "initial")
        workflow.record_r3([])
        require_critic(workflow, "initial", allow_newer_stages=True)
        with pytest.raises(ModelError, match="requires committed"):
            schedule_critic(workflow, "final")
    finally:
        manager.close()


@pytest.mark.parametrize("mutation", ["stop", "unknown", "badloc", "stale", "scope", "duplicate"])
def test_critic_rejects_malformed_or_stale_proposals(tmp_path: Path, mutation: str):
    manager, workflow, _ = _ready(tmp_path)
    try:
        value = _result(workflow, proposals=True)
        if mutation == "stop":
            value["stop"] = "false"
        elif mutation == "unknown":
            value["finding"] = "invented"
        elif mutation == "badloc":
            value["missing_units"][0]["evidence_refs"] = ["LOC-app.py:9999"]
        elif mutation == "stale":
            value["context"] = {**value["context"], "plan_id": "other"}
        elif mutation == "scope":
            value["missing_units"][0]["paths"] = ["../outside.py"]
        else:
            value["missing_units"] *= 2
        context = coverage_context(workflow, "initial")
        with pytest.raises(ModelError):
            validate_critic_output(workflow, context, value)
    finally:
        manager.close()


def test_proposals_block_r3_until_explicit_plan_replay(tmp_path: Path):
    manager, workflow, plan = _ready(tmp_path)
    try:
        _collect(manager, workflow, _result(workflow, proposals=True))
        commit_critic(workflow, "initial")
        with pytest.raises(ModelError, match="unresolved"):
            require_critic(workflow, "initial")
        request = _extension(plan)
        identifier = apply_coverage_extension(manager, workflow.campaign_id, request)
        assert apply_coverage_extension(manager, workflow.campaign_id, request) == identifier
        extended = manager.load_audit_plan(workflow.campaign_id, identifier)
        assert extended.snapshot_id == plan.snapshot_id
        assert extended.category_families == plan.category_families
        assert extended.discovery_axes == plan.discovery_axes
        assert set(b.batch_id for b in extended.batches).isdisjoint(b.batch_id for b in plan.batches)
        assert manager.load_audit_plan(workflow.campaign_id, plan.plan_id) == plan
        assert manager.store.list_batch_events(
            workflow.campaign_id, workflow.batch_id, event_type="BATCH_SUPERSEDED",
        )
        new_workflow = BatchWorkflow(manager, workflow.campaign_id, extended.batches[0].batch_id)
        assert new_workflow._stage_event("R1_COMPLETED") is None
        new_workflow.run_r0()
        with pytest.raises(ModelError, match="requires committed"):
            schedule_critic(new_workflow, "initial")
        with pytest.raises(ModelError, match="superseded"):
            require_critic(workflow, "initial")
    finally:
        manager.close()


def test_extension_rejects_active_tasks_and_stale_base(tmp_path: Path):
    manager, workflow, plan = _ready(tmp_path)
    try:
        task = schedule_critic(workflow, "initial")
        with pytest.raises(ValueError, match="unfinished execution task"):
            apply_coverage_extension(manager, workflow.campaign_id, _extension(plan))
        backend = ManualExecutionBackend(manager, workflow.campaign_id)
        backend.cancel(task.task.task_id, reason="prepare approved replay")
        identifier = apply_coverage_extension(manager, workflow.campaign_id, _extension(plan))
        assert identifier != plan.plan_id
        stale = {**_extension(plan), "reason": "different request against old base"}
        with pytest.raises(ModelError, match="stale"):
            apply_coverage_extension(manager, workflow.campaign_id, stale)
    finally:
        manager.close()


def test_legacy_policy_does_not_add_critic_gate(tmp_path: Path):
    manager, workflow, _ = _workflow(tmp_path)
    try:
        require_critic(workflow, "initial")
        with pytest.raises(ModelError, match="frozen"):
            schedule_critic(workflow, "initial")
    finally:
        manager.close()


def test_source_evidenced_operator_rejection_preserves_original(tmp_path: Path):
    manager, workflow, _ = _ready(tmp_path)
    try:
        value = _result(workflow, proposals=True)
        task = _collect(manager, workflow, value)
        ref = commit_critic(workflow, "initial")
        decisions = {"approved_by": "operator", "decisions": [{
            "proposal_digest": _digest(value["missing_units"][0]),
            "reason": "the proposed alternative is already inspected at this source location",
            "evidence_refs": ["LOC-app.py:1"],
        }]}
        with pytest.raises(ModelError, match="own proposals"):
            reject_coverage_proposals(workflow, task.task.task_id, {
                **decisions, "approved_by": "critic-a",
            })
        reject_coverage_proposals(workflow, task.task.task_id, decisions)
        require_critic(workflow, "initial")
        assert json.loads(manager.artifacts.get_bytes(ref)) == value
    finally:
        manager.close()


def test_extension_rolls_back_plan_batches_and_markers_together(tmp_path: Path, monkeypatch):
    manager, workflow, plan = _ready(tmp_path)
    try:
        before = manager.store.list_events(workflow.campaign_id)
        batches = manager.store.list_batches(workflow.campaign_id)
        original = manager.store.append_event
        def fail_final(**kwargs):
            if kwargs["event_type"] == "COVERAGE_PLAN_EXTENDED":
                raise ModelError("injected final registration failure")
            return original(**kwargs)
        monkeypatch.setattr(manager.store, "append_event", fail_final)
        with pytest.raises(ModelError, match="injected"):
            apply_coverage_extension(manager, workflow.campaign_id, _extension(plan))
        assert manager.store.list_events(workflow.campaign_id) == before
        assert manager.store.list_batches(workflow.campaign_id) == batches
    finally:
        manager.close()


def test_final_critic_gates_after_real_r5_and_before_r6(tmp_path: Path):
    manager, workflow, plan = _ready(tmp_path)
    try:
        _collect(manager, workflow, _result(workflow))
        commit_critic(workflow, "initial")
        workflow.record_r3([])
        workflow.record_revival_selection(
            [], rationale="no unreachable hypotheses",
            evidence_refs=["LOC-app.py:1"],
        )
        workflow.complete_r35()
        category_plan, = create_category_audit_plans(
            plan.work_units, [replace(_card(), family="INJECTION")], budget={},
        )
        workflow.record_category_audit_plan([category_plan])
        evidence = {axis.value: ("LOC-app.py:1",) for axis in DiscoveryAxis}
        workflow.record_r4([CategoryRun(
            "CR-critic", category_plan.category_plan_id, category_plan.work_unit_id,
            "INJECTION", category_plan.mechanism_variants,
            axis_runs_from_evidence(evidence), Applicability.APPLICABLE,
            CategoryRunStatus.COMPLETE, ("LOC-app.py:1",), "source reviewed",
            (), (),
        )])
        workflow.record_r5([], [])
        closure = BatchClosure(
            budget_used={"agent_runs": 2}, constraints_observed=("static-only",),
            unreviewed_scope=(), residual_risks=("external deployment not reviewed",),
            lessons=("synthetic lifecycle regression only",),
        )
        with pytest.raises(ModelError, match="final coverage critic is missing"):
            workflow.close_r6(closure)
        _collect(manager, workflow, _result(workflow, phase="final"), worker="final-critic")
        commit_critic(workflow, "final")
        require_critic(workflow, "final")
        workflow.build_transmission_metrics()
        report = workflow.close_r6(closure)
        assert report["status"] == "PASS"
    finally:
        manager.close()


def test_extension_adds_previously_deferred_source_and_cross_batch_handoff(tmp_path: Path):
    _fixture_monorepo(tmp_path)
    inventory = build_inventory(tmp_path, "fixture:extension")
    dispositions = tuple(PlanPathDisposition(
        p, PlanPathState.DEFERRED, "pending approved scope", "operator",
        ("LOC-services/api/main.py:1",),
    ) for p in ("libs/core/src/lib.rs", "libs/core/src/state.rs"))
    plan = create_audit_plan(
        campaign_id="CMP-extension", inventory=inventory, category_families=["INJECTION"],
        max_work_units_per_batch=1, path_dispositions=dispositions,
    )
    with CampaignManager(tmp_path) as manager:
        manager.create_campaign(
            campaign_id=plan.campaign_id, snapshot_id=plan.snapshot_id, constraints=(POLICY,),
        )
        manager.record_inventory(campaign_id=plan.campaign_id, inventory=inventory)
        manager.record_plan(campaign_id=plan.campaign_id, plan=plan, inventory=inventory)
        components = {c.root: c.component_id for c in inventory.components}
        request = {
            **_extension(plan), "evidence_refs": ["LOC-services/api/main.py:1"],
            "include_paths": ["libs/core/src/lib.rs"], "recheck_work_unit_ids": [],
            "boundary_edges": [{
                "edge_id": "EDGE-extension", "source_component_id": components["services/api"],
                "target_component_id": components["libs/core"], "kind": "ffi",
                "evidence": "synthetic cross-component contract",
                "source_path": "services/api/main.py", "target_path": "libs/core/src/lib.rs",
                "evidence_refs": ["LOC-services/api/main.py:1", "LOC-libs/core/src/lib.rs:1"],
            }],
        }
        extended = manager.load_audit_plan(
            plan.campaign_id, apply_coverage_extension(manager, plan.campaign_id, request),
        )
        assert "libs/core/src/lib.rs" in {p for u in extended.work_units for p in u.source_files}
        assert len(extended.handoffs) == 1
        assert extended.handoffs[0].edge_id == "EDGE-extension"
        assert next(d for d in extended.path_dispositions if d.path.endswith("state.rs")).state is PlanPathState.DEFERRED
