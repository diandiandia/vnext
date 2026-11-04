"""Revision-bound coverage proposals; never vulnerability verdicts."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from typing import Any, Mapping

from .batch_workflow import BatchWorkflow
from .campaign import CampaignManager
from .models import BatchStatus, CampaignStatus, ModelError
from .plan_models import BoundaryEdge, PlanPathDisposition, PlanPathState
from .planning import create_audit_plan, _stable_id


POLICY = "coverage_critic_v1"
_STAGES = ("R0_COMPLETED", "R1_COMPLETED", "R2_COMPLETED", "R3_COMPLETED",
           "R3_5_COMPLETED", "R4_COMPLETED", "R5_COMPLETED")


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode()).hexdigest()


def _put(manager: CampaignManager, value: Any) -> str:
    return manager.artifacts.put_text(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    )).artifact_id


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ModelError(f"{label} requires normalized nonempty text")
    return value


def coverage_context(workflow: BatchWorkflow, phase: str) -> dict[str, Any]:
    if phase not in {"initial", "final"}:
        raise ModelError("coverage critic phase must be initial or final")
    if POLICY not in workflow.campaign.constraints:
        raise ModelError("coverage critic requires frozen coverage_critic_v1 constraint")
    if workflow.campaign.status is CampaignStatus.COMPLETE or workflow.manager.store.list_events(
        workflow.campaign_id, event_type="CAMPAIGN_ABORTED",
    ):
        raise ModelError("coverage critic requires an open Campaign")
    if any(e.event_type == "BATCH_SUPERSEDED" for e in workflow._events()):
        raise ModelError("coverage critic cannot inspect a superseded Batch")
    plans = workflow.manager.store.list_events(
        workflow.campaign_id, entity_type="plan", event_type="PLAN_RECORDED",
    )
    if not plans or workflow.batch.manifest.get("plan_id") != plans[-1].entity_id:
        raise ModelError("coverage critic requires the current recorded Plan")
    revisions = {
        stage: event.payload_ref
        for stage in (_STAGES[:3] if phase == "initial" else _STAGES)
        if (event := workflow._stage_event(stage)) is not None
    }
    required = ("R1_COMPLETED", "R2_COMPLETED") if phase == "initial" else _STAGES
    if any(stage not in revisions for stage in required):
        raise ModelError(f"coverage critic {phase} requires committed {required}")
    return {
        "schema_version": "1.0", "phase": phase,
        "plan_id": plans[-1].entity_id,
        "plan_artifact_ref": plans[-1].payload_ref,
        "domain_selection_refs": [
            e.payload_ref for e in workflow._events()
            if e.event_type == "DOMAIN_GUIDANCE_SELECTED"
        ],
        "snapshot_id": workflow.campaign.snapshot_id,
        "batch_id": workflow.batch_id,
        "revisions": revisions,
    }


def schedule_critic(workflow: BatchWorkflow, phase: str) -> Any:
    from .execution import ManualExecutionBackend, TaskSpec

    workflow.run_r0()
    context = coverage_context(workflow, phase)
    if phase == "final":
        require_critic(workflow, "initial", allow_newer_stages=True)
    task_input = {
        **context, "operation": "coverage_critic",
        "work_units": workflow.batch.manifest["work_units"],
        "handoffs": workflow.batch.manifest.get("handoffs", []),
        "analysis_contract": (
            "Read-only independent coverage review, not vulnerability discovery. "
            "Inspect current source for missing entry surfaces, parallel paths, lifecycle "
            "modes, cross-unit contracts and unsupported exclusions. Do not execute target "
            "code or load prior Campaign answers. Existing stage artifacts are declarations, "
            "not observed reads. Return source-backed proposals only, never modify the Plan "
            "or assert complete safety. Unreviewed external scope is a limitation."
            " Consult the current Plan artifact for cross-Batch endpoints and Handoff "
            "ownership; do not treat a per-Batch no-new-work result as global completeness."
        ),
        "output_contract": {
            "schema_version": "1.0", "context": context,
            "missing_units": "array<{paths: array<inventoried path>, reason, evidence_refs}>",
            "reassign_ids": "array<{work_unit_id, reason, evidence_refs}>",
            "reviewed_paths": "array<path>, exactly the current Batch source paths, an Agent declaration",
            "checks": "nonempty array<{invariant, result, evidence_refs: array<LOC anchor>}>",
            "stop": "boolean, true exactly when both proposal arrays are empty",
        },
    }
    from .domain_guidance import POLICY as DOMAIN_POLICY, domain_context
    if DOMAIN_POLICY in workflow.campaign.constraints:
        selected = {
            unit["work_unit_id"]: domain_context(workflow, unit["work_unit_id"])
            for unit in workflow.batch.manifest["work_units"]
        }
        if len(json.dumps(selected).encode()) > 64 * 1024:
            raise ModelError("critic domain guidance exceeds the combined task context limit")
        task_input["domain_guidance"] = selected
        task_input["domain_review_contract"] = (
            "Check current source for missing domain selections and guidance misuse. "
            "Unselected is NOT ASSESSED, never not applicable. Propose source-backed "
            "re-review rather than modifying knowledge or inventing an axis."
        )
    input_ref = _put(workflow.manager, task_input)
    return ManualExecutionBackend(workflow.manager, workflow.campaign_id).submit(TaskSpec(
        task_id="TASK-critic-" + _digest(context)[:24],
        campaign_id=workflow.campaign_id, batch_id=workflow.batch_id,
        work_unit_id=workflow.batch.manifest["work_unit_ids"][0],
        operation=f"coverage_critic:{phase}", input_refs=(input_ref,),
        required_output="coverage-critic/v1", budget={"agent_runs": 1},
    ))


def validate_critic_output(
    workflow: BatchWorkflow, task_input: Mapping[str, Any], value: Mapping[str, Any],
) -> None:
    phase = task_input.get("phase")
    context = coverage_context(workflow, str(phase))
    expected = {key: task_input.get(key) for key in context}
    if expected != context or value.get("context") != context:
        raise ModelError("coverage critic context is stale or mismatched")
    if set(value) != {"schema_version", "context", "missing_units", "reassign_ids", "stop",
                     "reviewed_paths", "checks"}:
        raise ModelError("coverage critic output has unexpected or missing fields")
    if value["schema_version"] != "1.0" or type(value["stop"]) is not bool:
        raise ModelError("coverage critic output requires schema 1.0 and boolean stop")
    units = set(workflow.batch.manifest["work_unit_ids"])
    inventory_paths = {s.path for s in workflow.manager.load_inventory(
        workflow.campaign_id,
    ).source_files}
    reviewed = value["reviewed_paths"]
    expected_paths = {p for u in workflow.batch.manifest["work_units"] for p in u["source_files"]}
    if not isinstance(reviewed, list) or not all(isinstance(p, str) for p in reviewed) or (
        len(reviewed) != len(set(reviewed)) or set(reviewed) != expected_paths
    ):
        raise ModelError("coverage critic must declare exact reviewed Batch paths")
    checks = value["checks"]
    if not isinstance(checks, list) or not checks or len(checks) > 1024:
        raise ModelError("coverage critic requires bounded evidenced checks")
    for check in checks:
        if not isinstance(check, dict) or set(check) != {"invariant", "result", "evidence_refs"}:
            raise ModelError("coverage check fields mismatch")
        for field in ("invariant", "result"):
            _text(check[field], f"coverage check {field}")
        refs = check["evidence_refs"]
        if not isinstance(refs, list) or not refs or not all(
            isinstance(r, str) and r.startswith("LOC-")
            and r[4:].rpartition(":")[0] in expected_paths for r in refs
        ):
            raise ModelError("coverage check requires Batch source anchors")
        workflow.validate_concrete_evidence(refs)
    seen: set[str] = set()
    for field in ("missing_units", "reassign_ids"):
        proposals = value[field]
        if not isinstance(proposals, list) or len(proposals) > 256:
            raise ModelError(f"coverage critic {field} must be a bounded array")
        for proposal in proposals:
            if not isinstance(proposal, dict):
                raise ModelError("coverage proposal must be an object")
            keys = {"reason", "evidence_refs", "paths" if field == "missing_units" else "work_unit_id"}
            if set(proposal) != keys:
                raise ModelError("coverage proposal fields mismatch")
            _text(proposal["reason"], "coverage reason")
            refs = proposal["evidence_refs"]
            if not isinstance(refs, list) or not refs or not all(
                isinstance(ref, str) and ref.startswith("LOC-") for ref in refs
            ):
                raise ModelError("coverage proposal requires concrete source anchors")
            # Missing coverage can refer to an inventoried path outside this Batch.
            from .campaign_closure import CampaignCloser
            checker = CampaignCloser(
                workflow.manager, workflow.campaign_id,
                workflow.manager.load_audit_plan(workflow.campaign_id, context["plan_id"]),
            )
            for ref in refs:
                if not checker._valid_source_anchor(ref, inventory_paths):
                    raise ModelError(f"invalid coverage proposal source anchor: {ref}")
            if field == "missing_units":
                paths = proposal["paths"]
                if not isinstance(paths, list) or not paths or any(
                    not isinstance(p, str) or p not in inventory_paths for p in paths
                ) or len(paths) != len(set(paths)):
                    raise ModelError("coverage proposal paths must be unique inventoried paths")
            elif proposal["work_unit_id"] not in units:
                raise ModelError("coverage reassign Work Unit is outside the Batch")
            key = _digest(proposal)
            if key in seen:
                raise ModelError("duplicate coverage proposal")
            seen.add(key)
    if value["stop"] != (not value["missing_units"] and not value["reassign_ids"]):
        raise ModelError("coverage stop disagrees with proposed work")
    task_id = "TASK-critic-" + _digest(context)[:24]
    claims = [e for e in workflow._events() if e.event_type == "TASK_CLAIMED"]
    own_claims = [e for e in claims if e.entity_id == task_id]
    if own_claims and own_claims[-1].actor in {
        e.actor for e in claims if e.entity_id != task_id
    }:
        raise ModelError("coverage critic must have an independently declared worker identity")


def commit_critic(workflow: BatchWorkflow, phase: str) -> str:
    from .execution import ManualExecutionBackend, TaskStatus

    workflow.run_r0()
    context = coverage_context(workflow, phase)
    backend = ManualExecutionBackend(workflow.manager, workflow.campaign_id)
    view = backend.poll("TASK-critic-" + _digest(context)[:24])
    if view.status is not TaskStatus.SUCCEEDED or view.output_ref is None:
        raise ModelError("coverage critic task has not succeeded")
    value = json.loads(workflow.manager.artifacts.get_bytes(view.output_ref))
    task_input = json.loads(workflow.manager.artifacts.get_bytes(view.task.input_refs[0]))
    validate_critic_output(workflow, task_input, value)
    workers = {
        e.actor for e in workflow._events()
        if e.event_type == "TASK_CLAIMED" and e.entity_id != view.task.task_id
    }
    if view.worker_id in workers:
        raise ModelError("coverage critic must have an independently declared worker identity")
    workflow.manager.store.append_event(
        campaign_id=workflow.campaign_id, batch_id=workflow.batch_id,
        entity_type="coverage_critic", entity_id=view.task.task_id,
        event_type="COVERAGE_CRITIC_COMPLETED",
        idempotency_key=f"critic:{workflow.campaign_id}:{view.task.task_id}:{view.output_ref}",
        actor=view.worker_id or "unknown",
        payload={"context": context, "stop": value["stop"], "task_id": view.task.task_id},
        payload_ref=view.output_ref,
    )
    return view.output_ref


def require_critic(
    workflow: BatchWorkflow, phase: str, *, allow_newer_stages: bool = False,
) -> None:
    if POLICY not in workflow.campaign.constraints:
        return
    current = coverage_context(workflow, phase)
    for event in reversed(workflow._events()):
        if event.event_type != "COVERAGE_CRITIC_COMPLETED":
            continue
        context = event.payload.get("context", {})
        if allow_newer_stages:
            matches = (
                all(context.get(key) == value for key, value in current.items()
                    if key != "revisions")
                and all(current["revisions"].get(k) == v
                        for k, v in context.get("revisions", {}).items())
            )
        else:
            matches = context == current
        if matches:
            if event.payload.get("stop") is True:
                return
            rejections = workflow.manager.store.list_events(
                workflow.campaign_id, entity_type="coverage_disposition",
                entity_id=event.entity_id, event_type="COVERAGE_PROPOSALS_REJECTED",
            )
            if any(r.payload.get("critic_output_ref") == event.payload_ref for r in rejections):
                return
    raise ModelError(f"current independent {phase} coverage critic is missing or has unresolved proposals")


def reject_coverage_proposals(
    workflow: BatchWorkflow, task_id: str, value: Mapping[str, Any],
) -> str:
    """Record an explicit, source-evidenced operator rejection without rewriting the critic."""
    if not isinstance(value, dict) or set(value) != {"approved_by", "decisions"}:
        raise ModelError("coverage disposition fields mismatch")
    actor = _text(value["approved_by"], "approved_by")
    events = workflow.manager.store.list_events(
        workflow.campaign_id, entity_type="coverage_critic", entity_id=task_id,
        event_type="COVERAGE_CRITIC_COMPLETED",
    )
    if not events or events[-1].batch_id != workflow.batch_id:
        raise ModelError("coverage disposition requires a committed critic in this Batch")
    event = events[-1]
    context = coverage_context(workflow, event.payload["context"]["phase"])
    if event.payload["context"] != context:
        raise ModelError("coverage disposition cannot reject stale proposals")
    if actor == event.actor:
        raise ModelError("critic cannot approve rejection of its own proposals")
    output = json.loads(workflow.manager.artifacts.get_bytes(event.payload_ref))
    proposals = output["missing_units"] + output["reassign_ids"]
    expected = {_digest(p) for p in proposals}
    decisions = value["decisions"]
    if not isinstance(decisions, list) or not expected or len(decisions) != len(expected):
        raise ModelError("coverage disposition must address every current proposal")
    actual = set()
    from .campaign_closure import CampaignCloser
    checker = CampaignCloser(
        workflow.manager, workflow.campaign_id,
        workflow.manager.load_audit_plan(workflow.campaign_id, context["plan_id"]),
    )
    paths = {s.path for s in workflow.manager.load_inventory(workflow.campaign_id).source_files}
    for decision in decisions:
        if not isinstance(decision, dict) or set(decision) != {
            "proposal_digest", "reason", "evidence_refs",
        }:
            raise ModelError("coverage rejection decision fields mismatch")
        _text(decision["reason"], "rejection reason")
        digest = decision["proposal_digest"]
        if not isinstance(digest, str) or digest not in expected or digest in actual:
            raise ModelError("coverage rejection proposal identity mismatch")
        actual.add(digest)
        refs = decision["evidence_refs"]
        if not isinstance(refs, list) or not refs or not all(
            isinstance(r, str) and r.startswith("LOC-")
            and checker._valid_source_anchor(r, paths) for r in refs
        ):
            raise ModelError("coverage rejection requires valid source evidence")
    artifact = _put(workflow.manager, dict(value))
    workflow.manager.store.append_event(
        campaign_id=workflow.campaign_id, batch_id=workflow.batch_id,
        entity_type="coverage_disposition", entity_id=task_id,
        event_type="COVERAGE_PROPOSALS_REJECTED",
        idempotency_key=f"critic-rejected:{workflow.campaign_id}:{task_id}:{event.payload_ref}:{artifact}",
        actor=actor, payload={"critic_output_ref": event.payload_ref}, payload_ref=artifact,
    )
    return artifact


def critic_status(workflow: BatchWorkflow, phase: str) -> dict[str, Any]:
    context = coverage_context(workflow, phase)
    events = workflow.manager.store.list_events(
        workflow.campaign_id, batch_id=workflow.batch_id,
        entity_type="coverage_critic", event_type="COVERAGE_CRITIC_COMPLETED",
    )
    matching = [e for e in events if e.payload.get("context") == context]
    if not matching:
        return {"context": context, "status": "NOT_RECORDED"}
    event = matching[-1]
    output = json.loads(workflow.manager.artifacts.get_bytes(event.payload_ref))
    proposals = [
        {"proposal_digest": _digest(p), "proposal": p}
        for p in output["missing_units"] + output["reassign_ids"]
    ]
    return {
        "context": context, "status": "RECORDED", "task_id": event.entity_id,
        "output_ref": event.payload_ref, "stop": output["stop"], "proposals": proposals,
        "operator_rejections": [
            {"artifact_ref": e.payload_ref, "approved_by": e.actor}
            for e in workflow.manager.store.list_events(
                workflow.campaign_id, entity_type="coverage_disposition",
                entity_id=event.entity_id, event_type="COVERAGE_PROPOSALS_REJECTED",
            ) if e.payload.get("critic_output_ref") == event.payload_ref
        ],
    }


def apply_coverage_extension(
    manager: CampaignManager, campaign_id: str, request: Mapping[str, Any],
) -> str:
    """Create a new Plan version and replay Batches, preserving all old evidence."""
    allowed = {"schema_version", "base_plan_id", "reason", "approved_by",
               "evidence_refs", "include_paths", "boundary_edges", "recheck_work_unit_ids"}
    if not isinstance(request, dict) or set(request) != allowed or request["schema_version"] != "1.0":
        raise ModelError("coverage extension request fields/schema mismatch")
    for key in ("base_plan_id", "reason", "approved_by"):
        _text(request[key], key)
    identifier = "EXT-" + _digest(request)[:24]
    with manager.store.atomic_events():
        # Acquire a write lock before reading current Plan/state, including separate connections.
        manager.store._connection.execute(
            "UPDATE campaigns SET updated_at=updated_at WHERE campaign_id=?", (campaign_id,),
        )
        campaign = manager.store.get_campaign(campaign_id)
        if (
            POLICY not in campaign.constraints or campaign.status is CampaignStatus.COMPLETE
            or manager.store.list_events(campaign_id, event_type="CAMPAIGN_ABORTED")
        ):
            raise ModelError("coverage extension requires an enabled, open Campaign")
        existing = manager.store.list_events(
            campaign_id, entity_type="coverage_extension", entity_id=identifier,
            event_type="COVERAGE_PLAN_EXTENDED",
        )
        if existing:
            return str(existing[-1].payload["plan_id"])
        plans = manager.store.list_events(
            campaign_id, entity_type="plan", event_type="PLAN_RECORDED",
        )
        if not plans or plans[-1].entity_id != request["base_plan_id"]:
            raise ModelError("coverage extension base Plan is stale")
        base = manager.load_audit_plan(campaign_id, request["base_plan_id"])
        inventory = manager.load_inventory(campaign_id)
        paths = {s.path for s in inventory.source_files}
        refs = request["evidence_refs"]
        if not isinstance(refs, list) or not refs or not all(isinstance(r, str) for r in refs):
            raise ModelError("coverage extension requires evidence_refs")
        from .campaign_closure import CampaignCloser
        checker = CampaignCloser(manager, campaign_id, base)
        if not all(r.startswith("LOC-") and checker._valid_source_anchor(r, paths) for r in refs):
            raise ModelError("coverage extension requires valid inventoried LOC evidence")
        includes, rechecks, edges = (request[key] for key in (
            "include_paths", "recheck_work_unit_ids", "boundary_edges",
        ))
        for items in (includes, rechecks, edges):
            if not isinstance(items, list) or len(items) > 256:
                raise ModelError("coverage extension collections must be bounded arrays")
        if any(not isinstance(p, str) or p not in paths for p in includes):
            raise ModelError("coverage extension cannot add un-inventoried source")
        if any(not isinstance(u, str) or u not in {x.work_unit_id for x in base.work_units}
               for u in rechecks):
            raise ModelError("coverage extension recheck is outside the Plan")
        if len(includes) != len(set(includes)) or len(rechecks) != len(set(rechecks)):
            raise ModelError("duplicate coverage extension paths or rechecks")
        if not any((includes, rechecks, edges)):
            raise ModelError("coverage extension requires additional or repeated review")
        if any(not isinstance(e, dict) for e in edges):
            raise ModelError("coverage extension boundary edges must be objects")
        additions = tuple(BoundaryEdge.from_dict(e) for e in edges)
        dispositions = tuple(
            PlanPathDisposition(p.path, PlanPathState.INCLUDED, request["reason"])
            if p.path in includes else p for p in base.path_dispositions
        )
        proposed = create_audit_plan(
            campaign_id=campaign_id, inventory=inventory,
            category_families=base.category_families,
            boundary_edges=tuple(replace(e, owner_work_unit_id=None) for e in base.boundary_edges) + additions,
            path_dispositions=dispositions, discovery_axes=base.discovery_axes,
            max_source_files_per_work_unit=max(1, max(
                (len(u.source_files) for u in base.work_units), default=1,
            )),
            max_source_files_per_batch=max(1, max(
                (b.source_file_count for b in base.batches), default=1,
            )),
            max_work_units_per_batch=max(1, max(
                (len(b.work_unit_ids) for b in base.batches), default=1,
            )),
        )
        new_id = "PLAN-" + _digest({"base": base.plan_id, "extension": identifier})[:24]
        batch_ids = {b.batch_id: f"B-{identifier[4:16]}-{i:04d}"
                     for i, b in enumerate(proposed.batches, 1)}
        proposed = replace(
            proposed, plan_id=new_id,
            batches=tuple(replace(
                b, batch_id=batch_ids[b.batch_id],
                dependencies=tuple(batch_ids[d] for d in b.dependencies),
            ) for b in proposed.batches),
            handoffs=tuple(replace(
                h, handoff_id=_stable_id("HO", new_id, h.edge_id),
                from_batch=batch_ids[h.from_batch], owner_batch=batch_ids[h.owner_batch],
            ) for h in proposed.handoffs),
        )
        old_batches = [manager.store.get_batch(campaign_id, b.batch_id) for b in base.batches]
        manager._require_batches_quiescent_for_replay(campaign_id, old_batches)
        manager._record_plan(
            campaign_id=campaign_id, plan=proposed, inventory=inventory,
            replacing_plan_id=base.plan_id,
        )
        for batch in old_batches:
            manager.store.append_event(
                campaign_id=campaign_id, batch_id=batch.batch_id,
                entity_type="batch_lifecycle", entity_id=batch.batch_id,
                event_type="BATCH_SUPERSEDED",
                idempotency_key=f"coverage-superseded:{campaign_id}:{identifier}:{batch.batch_id}",
                actor=request["approved_by"],
                payload={"base_plan_id": base.plan_id, "amended_plan_id": new_id,
                         "replacement_batch_ids": list(batch_ids.values())},
            )
            if batch.status not in {BatchStatus.DEFERRED, BatchStatus.COMPLETE}:
                manager.store.transition_batch(campaign_id, batch.batch_id, BatchStatus.DEFERRED)
        artifact = _put(manager, dict(request))
        manager.store.append_event(
            campaign_id=campaign_id, batch_id=None, entity_type="coverage_extension",
            entity_id=identifier, event_type="COVERAGE_PLAN_EXTENDED",
            idempotency_key=f"coverage-extension:{campaign_id}:{identifier}",
            actor=request["approved_by"], payload={
                "base_plan_id": base.plan_id, "plan_id": new_id,
                "replay_policy": "ALL_BATCHES_NO_CONCLUSION_REUSE",
            }, payload_ref=artifact,
        )
    return new_id
