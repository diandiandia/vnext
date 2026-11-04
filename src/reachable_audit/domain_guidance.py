"""Small, source-evidenced domain companions, independent of language rankings."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from .batch_workflow import BatchWorkflow
from .models import CampaignStatus, ModelError


POLICY = "domain_guidance_v1"
DOMAIN_GUIDANCE = {
    "ai_agent": {
        "discipline": (
            "Trace untrusted content through context, retrieval, memory and tool dispatch "
            "to a protected effect. Identify writer, consuming principal, execution identity "
            "and resource. Model output and peer metadata cannot grant authority."
        ),
        "moves": (
            "Compare tenant filters and cache keys, persisted memory provenance, tool-handler "
            "authorization, approval-to-argument binding, retries and delegated capabilities."
        ),
        "counterevidence": (
            "Persuasive text alone is not a vulnerability. Check deterministic authorization "
            "and exact-action approval separately: the affected principal's permission "
            "does not establish their intent. Same-principal intended actions are not "
            "cross-boundary defects. Unknown provider behavior remains an explicit blocker."
        ),
        "validation": (
            "Cite the actual boundary-enforcing code and a complete source path. Record "
            "unproven model, provider or deployment premises. No target execution in workers."
        ),
    },
    "data_lifecycle": {
        "discipline": (
            "Follow one protected object through primary storage, derived copies, export, "
            "deletion, revocation and restore. Establish owner and reader at each transition."
        ),
        "moves": (
            "Compare request, batch, background and migration predicates; trace cache/search "
            "invalidation, signed references, backups and restoration of stale authority."
        ),
        "counterevidence": (
            "An owner field alone is not enforcement, but missing local filtering is not "
            "a defect if an evidenced dominating policy enforces the same boundary. "
            "Retention preference alone is not unauthorized access. External storage "
            "policy and replica behavior require matched evidence, not assumed defaults."
        ),
        "validation": (
            "Name the protected record, lower-trust reader or writer, intended lifecycle "
            "guarantee and alternate path. Distinguish source evidence from unknown storage facts."
        ),
    },
    "supply_chain": {
        "discipline": (
            "Trace lower-trust repository, dependency and workflow input to build, signing "
            "or release authority. Establish who controls input and which identity acts."
        ),
        "moves": (
            "Compare untrusted-change and trusted-release paths, reusable workflows, artifact "
            "identity, dependency resolution, signature verification and update rollback rules."
        ),
        "counterevidence": (
            "A powerful release action is not a defect if only its authorized owner can "
            "select the exact verified input. Check immutable identity and approval binding. "
            "Do not infer registry ownership, runner isolation or deployed signing policy."
        ),
        "validation": (
            "Cite input provenance, trust transition and protected operation. Treat absent "
            "hosted configuration as a blocker. Never fetch dependencies or publish artifacts."
        ),
    },
}


def guidance_digest() -> str:
    return "sha256:" + hashlib.sha256(json.dumps(
        DOMAIN_GUIDANCE, sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()


def record_domain_selection(
    workflow: BatchWorkflow, value: Mapping[str, Any],
) -> str:
    if POLICY not in workflow.campaign.constraints:
        raise ModelError("domain selection requires frozen domain_guidance_v1 constraint")
    if workflow.campaign.status is CampaignStatus.COMPLETE or workflow.manager.store.list_events(
        workflow.campaign_id, event_type="CAMPAIGN_ABORTED",
    ) or any(
        e.event_type == "BATCH_SUPERSEDED" for e in workflow._events()
    ):
        raise ModelError("domain selection requires an active Batch")
    if workflow._stage_event("R2_COMPLETED") is not None or any(
        e.event_type == "TASK_SUBMITTED"
        and e.payload.get("operation") != "discover_surfaces"
        for e in workflow._events()
    ):
        raise ModelError("domain selection is frozen after R2 scheduling; use an approved Plan replay")
    if not isinstance(value, dict) or set(value) != {"work_unit_id", "domain_id", "reason", "evidence_refs"}:
        raise ModelError("domain selection fields mismatch")
    if not isinstance(value["domain_id"], str) or value["domain_id"] not in DOMAIN_GUIDANCE:
        raise ModelError("unsupported domain guidance")
    if not isinstance(value["reason"], str) or not value["reason"].strip():
        raise ModelError("domain selection requires a reason")
    unit = next((u for u in workflow.batch.manifest["work_units"]
                 if u["work_unit_id"] == value["work_unit_id"]), None)
    if unit is None:
        raise ModelError("domain selection Work Unit is outside the Batch")
    refs = value["evidence_refs"]
    if not isinstance(refs, list) or not refs or not all(
        isinstance(r, str) and r.startswith("LOC-")
        and r[4:].rpartition(":")[0] in unit["source_files"] for r in refs
    ):
        raise ModelError("domain selection requires Work Unit source anchors")
    workflow.validate_concrete_evidence(refs)
    selection = {
        **value, "schema_version": "1.0", "guidance_digest": guidance_digest(),
        "snapshot_id": workflow.campaign.snapshot_id,
        "plan_id": workflow.batch.manifest["plan_id"],
    }
    artifact = workflow.manager.artifacts.put_text(json.dumps(
        selection, sort_keys=True, separators=(",", ":"),
    ))
    workflow.manager.store.append_event(
        campaign_id=workflow.campaign_id, batch_id=workflow.batch_id,
        entity_type="domain_selection", entity_id=f"{value['work_unit_id']}:{value['domain_id']}",
        event_type="DOMAIN_GUIDANCE_SELECTED",
        idempotency_key=f"domain:{workflow.campaign_id}:{workflow.batch_id}:{artifact.artifact_id}",
        actor="coordinator", payload={"work_unit_id": value["work_unit_id"],
                                     "domain_id": value["domain_id"]},
        payload_ref=artifact.artifact_id,
    )
    return artifact.artifact_id


def domain_context(workflow: BatchWorkflow, work_unit_id: str) -> dict[str, Any]:
    if POLICY not in workflow.campaign.constraints:
        return {}
    selections = {}
    for event in workflow._events():
        if event.event_type == "DOMAIN_GUIDANCE_SELECTED" and event.payload["work_unit_id"] == work_unit_id:
            selection = json.loads(workflow.manager.artifacts.get_bytes(event.payload_ref))
            if selection["guidance_digest"] != guidance_digest():
                raise ModelError("frozen domain guidance content changed; use the frozen engine")
            selections[selection["domain_id"]] = selection
    result = {
        "schema_version": "1.0", "guidance_digest": guidance_digest(),
        "selection_status": "selected" if selections else "not_assessed",
        "selection_contract": (
            "Selections are source-evidenced coordinator declarations, not observed "
            "applicability. Missing tags are not exclusion. Report uncovered domain "
            "boundaries to the coordinator for explicit selection and rescheduling; "
            "do not infer safety from absent guidance."
        ),
        "selections": [selections[key] for key in sorted(selections)],
        "blocks": {key: DOMAIN_GUIDANCE[key] for key in sorted(selections)},
    }
    if len(json.dumps(result).encode()) > 16 * 1024:
        raise ModelError("domain guidance exceeds the task context limit")
    return result
