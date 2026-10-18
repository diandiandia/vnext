"""Campaign gates, root-cause deduplication, and derived final reporting."""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .analysis_models import (
    CampaignClosure,
    R5Disposition,
    ReviewAltitude,
    ScopeDispositionKind,
)
from .campaign import CampaignManager
from .models import BatchStatus, CampaignStatus, ModelError
from .plan_models import AuditPlan, PlanPathState
from .resource_cleanup import cleanup_campaign_resources
from .runtime_policy import execution_policy_digest


_SEVERITY_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}


def _stable_id(prefix: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


class CampaignCloser:
    def __init__(
        self, manager: CampaignManager, campaign_id: str, plan: AuditPlan
    ) -> None:
        if plan.campaign_id != campaign_id:
            raise ModelError("Campaign closing plan does not belong to Campaign")
        self.manager = manager
        self.campaign_id = campaign_id
        self.plan = plan
        self.campaign = manager.store.get_campaign(campaign_id)

    def _scope_disposition_errors(
        self,
        closure: CampaignClosure,
        *,
        inventory_source_files: set[str],
    ) -> list[str]:
        errors: list[str] = []
        dispositions = closure.scope_dispositions
        refs = [item.scope_ref for item in dispositions]
        if len(refs) != len(set(refs)):
            errors.append("scope dispositions contain duplicate scope_ref values")
        if len(closure.unreviewed_scope) != len(set(closure.unreviewed_scope)):
            errors.append("unreviewed_scope contains duplicate entries")
        if set(refs) != set(closure.unreviewed_scope):
            errors.append("scope dispositions must match unreviewed_scope exactly")

        artifact_refs = {
            evidence_ref
            for item in dispositions
            for evidence_ref in item.evidence_refs
            if evidence_ref.startswith("sha256:")
        }
        artifact_owners = self.manager.store.artifact_campaign_owners(artifact_refs)

        for item in dispositions:
            scope_label = f"scope {item.scope_ref!r}"
            if item.disposition not in {
                ScopeDispositionKind.EXCLUDED,
                ScopeDispositionKind.DEFERRED,
            }:
                errors.append(f"{scope_label} has an invalid disposition")
            if item.snapshot_id != self.campaign.snapshot_id:
                errors.append(f"{scope_label} is not bound to the current snapshot")
            if not item.rationale.strip() or not item.approved_by.strip():
                errors.append(f"{scope_label} requires rationale and approver")
            if not item.evidence_refs:
                errors.append(f"{scope_label} requires evidence")
            if item.history_source_campaign_id:
                if self.campaign.audit_mode.value == "fresh":
                    errors.append(f"{scope_label} cites historical data in fresh mode")
                elif item.history_source_campaign_id not in (
                    self.campaign.history_source_campaign_ids
                ):
                    errors.append(f"{scope_label} cites an undeclared history source")
            for evidence_ref in item.evidence_refs:
                if evidence_ref.startswith("LOC-"):
                    if not self._valid_source_anchor(
                        evidence_ref, inventory_source_files
                    ):
                        errors.append(f"{scope_label} has an invalid source anchor")
                elif evidence_ref.startswith("sha256:"):
                    owners = artifact_owners.get(evidence_ref, set())
                    allowed_owners = {self.campaign_id}
                    if item.history_source_campaign_id:
                        allowed_owners.add(item.history_source_campaign_id)
                    try:
                        self.manager.artifacts.get_bytes(evidence_ref)
                    except (OSError, ValueError):
                        owners = set()
                    if not owners or not owners.issubset(allowed_owners):
                        errors.append(
                            f"{scope_label} references an artifact not owned by this review"
                        )
                else:
                    errors.append(
                        f"{scope_label} evidence must be a LOC anchor or Campaign artifact"
                    )
        return errors

    def _valid_source_anchor(
        self, evidence_ref: str, inventory_source_files: set[str]
    ) -> bool:
        path_text, separator, line_text = evidence_ref[4:].rpartition(":")
        if not separator or not line_text.isdigit() or int(line_text) < 1:
            return False
        relative_path = Path(path_text)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            return False
        if relative_path.as_posix() not in inventory_source_files:
            return False
        source_path = (self.manager.target_root / relative_path).resolve()
        if not source_path.is_relative_to(self.manager.target_root) or not source_path.is_file():
            return False
        try:
            with source_path.open("rb") as source:
                for _ in range(int(line_text)):
                    if not source.readline():
                        return False
        except OSError:
            return False
        return True

    def _path_scope_evidence_errors(
        self, inventory_source_files: set[str]
    ) -> list[str]:
        evidence_refs = {
            ref
            for item in self.plan.path_dispositions
            if item.state is not PlanPathState.INCLUDED
            for ref in item.evidence_refs
            if ref.startswith("sha256:")
        }
        artifact_owners = self.manager.store.artifact_campaign_owners(evidence_refs)
        errors = []
        for item in self.plan.path_dispositions:
            if item.state is PlanPathState.INCLUDED:
                continue
            label = f"path {item.path!r}"
            for ref in item.evidence_refs:
                if ref.startswith("LOC-"):
                    if not self._valid_source_anchor(ref, inventory_source_files):
                        errors.append(f"{label} has an invalid source anchor")
                elif ref.startswith("sha256:"):
                    try:
                        self.manager.artifacts.get_bytes(ref)
                    except (OSError, ValueError):
                        errors.append(f"{label} references a missing evidence artifact")
                        continue
                    if artifact_owners.get(ref, set()) != {self.campaign_id}:
                        errors.append(
                            f"{label} references an artifact not owned by this Campaign"
                        )
                else:
                    errors.append(
                        f"{label} evidence must be a LOC anchor or Campaign artifact"
                    )
        return errors

    def close(self, closure: CampaignClosure) -> dict[str, Any]:
        events = self.manager.store.list_events(self.campaign_id)
        recorded_plans = [
            event for event in events if event.event_type == "PLAN_RECORDED"
        ]
        if not recorded_plans or recorded_plans[-1].entity_id != self.plan.plan_id:
            raise ModelError(
                "Campaign closure Plan is not the latest recorded Plan"
            )
        plan_event = recorded_plans[-1]
        if plan_event.payload_ref is None:
            raise ModelError("latest Campaign Plan event has no durable artifact")
        try:
            event_plan = AuditPlan.from_dict(json.loads(
                self.manager.artifacts.get_bytes(plan_event.payload_ref)
            ))
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise ModelError("latest Campaign Plan artifact is invalid") from error
        if asdict(event_plan) != asdict(self.plan):
            raise ModelError("Campaign closure Plan differs from latest Plan artifact")
        try:
            stored_plan = self.manager.load_audit_plan(
                self.campaign_id, self.plan.plan_id
            )
        except (OSError, ValueError) as error:
            raise ModelError("Campaign closure Plan is not durably recorded") from error
        if asdict(stored_plan) != asdict(self.plan):
            raise ModelError(
                "Campaign closure Plan file differs from latest Plan artifact"
            )
        pending_r6_amendments: dict[str, int] = {}
        for event in events:
            if event.batch_id is None:
                continue
            if (
                event.event_type == "TASK_OUTPUT_AMENDED"
                and event.payload.get("stage") == "R6_COMPLETED"
            ):
                pending_r6_amendments[event.batch_id] = event.sequence
            elif (
                event.event_type == "R6_COMPLETED"
                and event.batch_id in pending_r6_amendments
                and event.sequence > pending_r6_amendments[event.batch_id]
            ):
                del pending_r6_amendments[event.batch_id]
        if pending_r6_amendments:
            raise ModelError(
                "Campaign closure requires R6 task amendments to be recommitted for "
                f"Batches: {sorted(pending_r6_amendments)}"
            )
        event_by_batch: dict[str, list[Any]] = {}
        for event in events:
            if event.batch_id:
                event_by_batch.setdefault(event.batch_id, []).append(event)
        batches = {
            batch.batch_id: batch
            for batch in self.manager.store.list_batches(self.campaign_id)
        }
        planned_batch_ids = {batch.batch_id for batch in self.plan.batches}
        incomplete_batches = sorted(
            batch_id
            for batch_id in planned_batch_ids
            if batch_id not in batches
            or batches[batch_id].status is not BatchStatus.COMPLETE
        )
        plan_work_units = {unit.work_unit_id for unit in self.plan.work_units}
        completed_work_units = {
            work_unit_id
            for batch_id in planned_batch_ids
            if batch_id in batches and batches[batch_id].status is BatchStatus.COMPLETE
            for work_unit_id in batches[batch_id].manifest.get("work_unit_ids", [])
        }
        gates: dict[str, dict[str, Any]] = {
            "CG1": {
                "pass": not incomplete_batches and completed_work_units == plan_work_units,
                "detail": {
                    "incomplete_batches": incomplete_batches,
                    "missing_work_units": sorted(plan_work_units - completed_work_units),
                },
            }
        }

        inventory = self.manager.load_inventory(self.campaign_id)
        graph = self.manager.load_component_graph(self.campaign_id)
        owned_components = {unit.component_id for unit in self.plan.work_units}
        build_components = {unit.component_id for unit in graph.build_units}
        inventory_source_files = {source.path for source in inventory.source_files}
        path_dispositions = list(self.plan.path_dispositions)
        path_state_by_path = {
            item.path: item.state for item in path_dispositions
        }
        included_source_files = {
            path for path, state in path_state_by_path.items()
            if state is PlanPathState.INCLUDED
        }
        excluded_source_files = {
            path for path, state in path_state_by_path.items()
            if state is PlanPathState.EXCLUDED
        }
        deferred_source_files = {
            path for path, state in path_state_by_path.items()
            if state is PlanPathState.DEFERRED
        }
        planned_source_files = [
            source_path
            for work_unit in self.plan.work_units
            for source_path in work_unit.source_files
        ]
        duplicate_source_files = sorted({
            source_path
            for source_path in planned_source_files
            if planned_source_files.count(source_path) > 1
        })
        planned_source_file_set = set(planned_source_files)
        boundary_components = {
            component_id
            for edge in self.plan.boundary_edges
            for component_id in (edge.source_component_id, edge.target_component_id)
        }
        included_components = {
            source.component_id for source in inventory.source_files
            if source.path in included_source_files
        }
        path_state_counts = {
            state.value: sum(item.state is state for item in path_dispositions)
            for state in PlanPathState
        }
        required_components = build_components | boundary_components | included_components
        path_scope_coverage_valid = (
            len(path_dispositions) == len(path_state_by_path)
            and set(path_state_by_path) == inventory_source_files
        )
        path_scope_evidence_errors = self._path_scope_evidence_errors(
            inventory_source_files
        )
        gates["CG2"] = {
            "pass": required_components.issubset(owned_components)
            and path_scope_coverage_valid
            and not path_scope_evidence_errors
            and included_source_files == planned_source_file_set
            and not duplicate_source_files,
            "detail": {
                "unowned_components": sorted(required_components - owned_components),
                "unowned_build_units": sorted(build_components - owned_components),
                "unclassified_source_files": sorted(
                    inventory_source_files - set(path_state_by_path)
                ),
                "unknown_scope_paths": sorted(
                    set(path_state_by_path) - inventory_source_files
                ),
                "included_paths_without_work_unit": sorted(
                    included_source_files - planned_source_file_set
                ),
                "work_unit_paths_not_included": sorted(
                    planned_source_file_set - included_source_files
                ),
                "excluded_source_files": sorted(excluded_source_files),
                "deferred_source_files": sorted(deferred_source_files),
                "path_scope_evidence_errors": path_scope_evidence_errors,
                "duplicate_source_files": duplicate_source_files,
            },
        }

        surfaces = []
        boundary_reviews = []
        discovery_axis_runs = []
        hypotheses = []
        verdicts = []
        category_runs = []
        r5_assessments = []
        batch_reports_by_id: dict[str, Mapping[str, Any]] = {}
        metrics = []
        path_review_claims: list[dict[str, str]] = []
        path_review_claim_errors: list[str] = []
        unit_paths = {
            unit.work_unit_id: set(unit.source_files)
            for unit in self.plan.work_units
        }
        seen_path_review_claims: set[tuple[str, str]] = set()
        artifact_event_types = {
            "R1_COMPLETED", "R2_COMPLETED", "R3_COMPLETED", "R4_COMPLETED", "R5_COMPLETED",
            "R6_COMPLETED", "TRANSMISSION_METRICS_RECORDED",
        }
        for batch_id in planned_batch_ids:
            for event in event_by_batch.get(batch_id, []):
                if event.payload_ref is None or event.event_type not in artifact_event_types:
                    continue
                artifact = json.loads(
                    self.manager.artifacts.get_bytes(event.payload_ref)
                )
                if event.event_type == "R1_COMPLETED":
                    surfaces.extend(artifact["surfaces"])
                    boundary_reviews.extend(artifact.get("boundary_reviews", []))
                    for item in artifact.get("path_review_claims", []):
                        if not isinstance(item, dict):
                            path_review_claim_errors.append(
                                "R1 path review claim is not an object"
                            )
                            continue
                        work_unit_id = str(item.get("work_unit_id", ""))
                        path = str(item.get("path", ""))
                        claim = str(item.get("claim", ""))
                        altitude = str(item.get("altitude", "NOT_RECORDED"))
                        key = (work_unit_id, path)
                        if claim != "AGENT_DECLARED_REVIEWED":
                            path_review_claim_errors.append(
                                f"invalid path review claim: {work_unit_id}/{path}"
                            )
                        elif path not in unit_paths.get(work_unit_id, set()):
                            path_review_claim_errors.append(
                                f"path review claim is outside its Work Unit: {work_unit_id}/{path}"
                            )
                        elif path not in included_source_files:
                            path_review_claim_errors.append(
                                f"path review claim is not for an INCLUDED path: {path}"
                            )
                        elif altitude != "NOT_RECORDED" and altitude not in {
                            state.value for state in ReviewAltitude
                        }:
                            path_review_claim_errors.append(
                                f"invalid path review altitude: {work_unit_id}/{path}"
                            )
                        elif key in seen_path_review_claims:
                            path_review_claim_errors.append(
                                f"duplicate path review claim: {work_unit_id}/{path}"
                            )
                        else:
                            seen_path_review_claims.add(key)
                            path_review_claims.append({
                                "batch_id": batch_id,
                                "work_unit_id": work_unit_id,
                                "path": path,
                                "claim": claim,
                                "altitude": altitude,
                            })
                elif event.event_type == "R2_COMPLETED":
                    hypotheses.extend(artifact["hypotheses"])
                    discovery_axis_runs.extend(artifact.get("axis_runs", []))
                elif event.event_type == "R3_COMPLETED":
                    verdicts.extend(artifact["verdicts"])
                elif event.event_type == "R4_COMPLETED":
                    category_runs.extend(artifact["category_runs"])
                elif event.event_type == "R5_COMPLETED":
                    r5_assessments.extend(artifact["assessments"])
                elif event.event_type == "R6_COMPLETED":
                    batch_reports_by_id[batch_id] = artifact
                elif event.event_type == "TRANSMISSION_METRICS_RECORDED":
                    metrics.append(artifact)
        batch_reports = list(batch_reports_by_id.values())
        surface_review_dispositions = [
            {"batch_id": batch_id, **item}
            for batch_id, batch_report in sorted(batch_reports_by_id.items())
            for item in batch_report.get("surface_review_dispositions", [])
        ]
        surface_review_state_counts = _counts(
            item["state"] for item in surface_review_dispositions
        )
        path_review_altitude_counts = _counts(
            item["altitude"] for item in path_review_claims
        )
        surface_ids = [item["surface_id"] for item in surfaces]
        analyzed_surface_ids = {
            surface_id
            for hypothesis in hypotheses
            for surface_id in hypothesis["surface_ids"]
        }
        surface_work_units = {str(item["work_unit_id"]) for item in surfaces}
        reviewed_surface_work_units = {
            str(item["work_unit_id"])
            for item in discovery_axis_runs
            if item["axis"] == "surface"
        }
        work_unit_ids = {unit.work_unit_id for unit in self.plan.work_units}
        axis_applicability: dict[str, dict[str, str]] = {}
        for item in discovery_axis_runs:
            axis_applicability.setdefault(
                str(item.get("work_unit_id", "")),
                {},
            )[str(item["axis"])] = str(item["applicability"])
        hypotheses_by_work_unit: dict[str, int] = {}
        for item in hypotheses:
            work_unit_id = str(item["work_unit_id"])
            hypotheses_by_work_unit[work_unit_id] = (
                hypotheses_by_work_unit.get(work_unit_id, 0) + 1
            )
        screening_work_unit_ids = sorted(
            work_unit_id for work_unit_id in work_unit_ids
            if set(axis_applicability.get(work_unit_id, {})) == set(self.plan.discovery_axes)
            and all(
                axis_applicability[work_unit_id][axis] == "NOT_APPLICABLE"
                for axis in self.plan.discovery_axes
            )
            and hypotheses_by_work_unit.get(work_unit_id, 0) == 0
        )
        substantive_work_unit_ids = sorted(
            work_unit_id for work_unit_id in work_unit_ids
            if any(
                applicability == "APPLICABLE"
                for applicability in axis_applicability.get(work_unit_id, {}).values()
            )
        )
        screening_fraction = (
            len(screening_work_unit_ids) / len(work_unit_ids)
            if work_unit_ids else 0.0
        )
        screening_ceiling = self.campaign.budget.get("max_screening_fraction")
        screening_ceiling_configured = (
            isinstance(screening_ceiling, (int, float))
            and not isinstance(screening_ceiling, bool)
            and 0 <= screening_ceiling <= 1
        )
        screening_ceiling_status = (
            "WITHIN_CEILING"
            if screening_fraction == 0
            else "NOT_CONFIGURED"
            if not screening_ceiling_configured
            else "WITHIN_CEILING"
            if screening_fraction <= screening_ceiling
            else "EXCEEDS_CEILING"
        )
        expected_axis_coverage = {
            (work_unit_id, axis)
            for work_unit_id in work_unit_ids
            for axis in self.plan.discovery_axes
        }
        actual_axis_coverage = {
            (str(item.get("work_unit_id", "")), str(item["axis"]))
            for item in discovery_axis_runs
        }
        unknown_surface_refs = sorted(analyzed_surface_ids - set(surface_ids))
        surfaces_without_review = sorted(surface_work_units - reviewed_surface_work_units)
        hypothesis_ids = {item["hypothesis_id"] for item in hypotheses}
        verdict_hypothesis_ids = {item["hypothesis_id"] for item in verdicts}
        gates["CG3"] = {
            "pass": len(surface_ids) == len(set(surface_ids))
            and surface_work_units.issubset(work_unit_ids)
            and not surfaces_without_review
            and actual_axis_coverage == expected_axis_coverage
            and not unknown_surface_refs
            and hypothesis_ids == verdict_hypothesis_ids,
            "detail": {
                "surface_count": len(surface_ids),
                "surfaces_without_hypothesis": sorted(set(surface_ids) - analyzed_surface_ids),
                "surfaces_without_work_unit_review": surfaces_without_review,
                "missing_axis_reviews": sorted(expected_axis_coverage - actual_axis_coverage),
                "unexpected_axis_reviews": sorted(actual_axis_coverage - expected_axis_coverage),
                "unknown_surface_refs": unknown_surface_refs,
                "hypotheses_without_verdict": sorted(
                    hypothesis_ids - verdict_hypothesis_ids
                ),
            },
        }
        if path_review_claim_errors:
            gates["CG2"]["pass"] = False
            gates["CG2"]["detail"]["path_review_claim_errors"] = (
                path_review_claim_errors
            )

        expected_category_coverage = {
            (unit.work_unit_id, family)
            for unit in self.plan.work_units
            for family in unit.category_families
        }
        actual_category_coverage = {
            (item["work_unit_id"], item["family"]) for item in category_runs
        }
        gates["CG4"] = {
            "pass": expected_category_coverage == actual_category_coverage,
            "detail": {
                "missing": sorted(expected_category_coverage - actual_category_coverage),
            },
        }

        resolution_by_handoff = {
            event.entity_id: event
            for event in events
            if event.event_type == "HANDOFF_RESOLVED"
        }
        integrated_handoffs = {
            event.entity_id
            for event in events
            if event.event_type == "HANDOFF_INTEGRATED"
        }
        unresolved_handoffs = []
        unintegrated_proven_handoffs = []
        for handoff in self.plan.handoffs:
            resolution = resolution_by_handoff.get(handoff.handoff_id)
            if resolution is None:
                unresolved_handoffs.append(handoff.handoff_id)
            elif (
                resolution.payload.get("outcome") == "EDGE_PROVEN"
                and handoff.handoff_id not in integrated_handoffs
            ):
                unintegrated_proven_handoffs.append(handoff.handoff_id)
        gates["CG5"] = {
            "pass": not unresolved_handoffs and not unintegrated_proven_handoffs,
            "detail": {
                "unresolved": unresolved_handoffs,
                "unintegrated_edge_proven": unintegrated_proven_handoffs,
            },
        }

        finding_events = [
            event for event in events if event.event_type == "FINDING_RECORDED"
        ]
        findings = [
            json.loads(self.manager.artifacts.get_bytes(event.payload_ref))
            for event in finding_events
            if event.payload_ref
        ]
        merged_findings = self._deduplicate_findings(findings)
        execution_task_events = [
            event for event in events if event.entity_type == "execution_task"
        ]
        task_specs = {}
        for event in execution_task_events:
            if event.event_type == "TASK_SUBMITTED" and event.payload_ref:
                task_specs[event.entity_id] = json.loads(
                    self.manager.artifacts.get_bytes(event.payload_ref)
                )
        completed_task_measurements = []
        for event in execution_task_events:
            if event.event_type != "TASK_COMPLETED":
                continue
            task_spec = task_specs.get(event.entity_id, {})
            completed_task_measurements.append({
                "task_id": event.entity_id,
                "operation": task_spec.get("operation", "unknown"),
                "work_unit_id": task_spec.get("work_unit_id", "unknown"),
                "work_unit_ids": task_spec.get(
                    "work_unit_ids", [task_spec.get("work_unit_id", "unknown")]
                ),
                "bundle_item_ids": task_spec.get("bundle_item_ids", []),
                "input_artifact_refs": list(task_spec.get("input_refs", [])),
                "budget": task_spec.get("budget", {}),
                "configuration": event.payload.get("configuration", {}),
                "measurements": event.payload.get("measurements", {}),
                "output_artifact_id": event.payload_ref,
            })
        host_configuration_keys = (
            "model_id", "runtime_version", "host_tool_policy_digest",
        )
        unreported_configuration_tasks = [
            item["task_id"] for item in completed_task_measurements
            if not set(host_configuration_keys).issubset(item["configuration"])
        ]
        configuration_rows = sorted({
            tuple((key, item["configuration"][key]) for key in host_configuration_keys)
            for item in completed_task_measurements
            if set(host_configuration_keys).issubset(item["configuration"])
        })
        execution_config_digest = (
            "sha256:" + hashlib.sha256(json.dumps(
                [dict(row) for row in configuration_rows],
                ensure_ascii=False, sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")).hexdigest()
            if completed_task_measurements and not unreported_configuration_tasks
            else None
        )
        measurement_totals: dict[str, int] = {}
        for task_measurement in completed_task_measurements:
            for name, amount in task_measurement["measurements"].items():
                measurement_totals[name] = measurement_totals.get(name, 0) + int(amount)
        totals_by_operation: dict[str, dict[str, int]] = {}
        for task_measurement in completed_task_measurements:
            operation_totals = totals_by_operation.setdefault(task_measurement["operation"], {})
            operation_totals["tasks"] = operation_totals.get("tasks", 0) + 1
            for name, amount in task_measurement["measurements"].items():
                operation_totals[name] = operation_totals.get(name, 0) + int(amount)
        usage_reported_tasks = [
            item["task_id"] for item in completed_task_measurements
            if {"input_tokens", "cache_read_tokens", "output_tokens"}.issubset(item["measurements"])
        ]
        terminal_attempts = [
            event for event in execution_task_events
            if event.event_type in {"TASK_COMPLETED", "TASK_FAILED"}
        ]
        latest_claims = {}
        finalized_claim_ids = set()
        for event in execution_task_events:
            if event.event_type == "TASK_CLAIMED":
                latest_claims[event.entity_id] = event
            elif event.event_type in {"TASK_COMPLETED", "TASK_FAILED"}:
                claim = latest_claims.get(event.entity_id)
                if claim is not None:
                    finalized_claim_ids.add(claim.event_id)
        unreported_claims = [
            event for event in execution_task_events
            if event.event_type == "TASK_CLAIMED" and event.event_id not in finalized_claim_ids
        ]
        attempt_usage_by_operation: dict[str, dict[str, int]] = {}
        missing_usage_attempts = [{
            "task_id": event.entity_id,
            "event_id": event.event_id,
            "event_type": event.event_type,
            "reason": "claimed attempt has no completed or failed usage record",
        } for event in unreported_claims]
        for event in terminal_attempts:
            task_spec = task_specs.get(event.entity_id, {})
            measurements = event.payload.get("measurements", {})
            token_fields = {"input_tokens", "cache_read_tokens", "output_tokens"}
            if not isinstance(measurements, dict) or not token_fields.issubset(measurements):
                missing_usage_attempts.append({
                    "task_id": event.entity_id,
                    "event_id": event.event_id,
                    "event_type": event.event_type,
                })
                continue
            operation = str(task_spec.get("operation", "unknown"))
            operation_totals = attempt_usage_by_operation.setdefault(operation, {})
            operation_totals["attempts_reporting_usage"] = (
                operation_totals.get("attempts_reporting_usage", 0) + 1
            )
            for name in token_fields:
                operation_totals[name] = operation_totals.get(name, 0) + int(
                    measurements[name]
                )
        attempt_usage_totals = {
            name: sum(values.get(name, 0) for values in attempt_usage_by_operation.values())
            for name in ("input_tokens", "cache_read_tokens", "output_tokens")
        }
        input_total = measurement_totals.get("input_tokens", 0)
        cache_read_total = measurement_totals.get("cache_read_tokens", 0)
        cache_hit_ratio = (
            round(cache_read_total / (cache_read_total + input_total), 4)
            if cache_read_total + input_total else None
        )
        gates["CG6"] = {
            "pass": len({item["root_cause_key"] for item in merged_findings})
            == len(merged_findings),
            "detail": {
                "batch_findings": len(findings),
                "root_causes": len(merged_findings),
            },
        }

        invalid_strong_claims = [
            item["hypothesis_id"]
            for item in r5_assessments
            if item["experiment_required"]
            and item["disposition"]
            not in {
                R5Disposition.EMPIRICALLY_CONFIRMED.value,
                R5Disposition.REFUTED.value,
                R5Disposition.NEEDS_REVIEW.value,
                R5Disposition.NOT_FEASIBLE.value,
            }
        ]
        gates["CG7"] = {
            "pass": not invalid_strong_claims,
            "detail": {"invalid_strong_claims": invalid_strong_claims},
        }
        resolved_drift_ids = {
            str(event.payload["drift_event_id"])
            for event in events
            if event.event_type == "SNAPSHOT_DRIFT_RESOLVED"
        }
        unresolved_drift = [
            event.event_id
            for event in events
            if event.event_type == "SNAPSHOT_DRIFT"
            and event.event_id not in resolved_drift_ids
        ]
        gates["CG8"] = {
            "pass": not unresolved_drift,
            "detail": {"snapshot_drift_events": unresolved_drift},
        }
        r6_finding_ids = {
            finding["finding_id"]
            for report in batch_reports
            for finding in report["findings"]
        }
        event_finding_ids = {item["finding_id"] for item in findings}
        gates["CG9"] = {
            "pass": r6_finding_ids == event_finding_ids,
            "detail": {
                "missing_from_reports": sorted(event_finding_ids - r6_finding_ids),
                "missing_from_events": sorted(r6_finding_ids - event_finding_ids),
            },
        }
        closure_statements = {
            "unreviewed_scope": closure.unreviewed_scope,
            "residual_risks": closure.residual_risks,
            "limitations": closure.limitations,
            "lessons": closure.lessons,
            "knowledge_nominations": closure.knowledge_nominations,
        }
        blank_closure_items = {
            name: [index for index, item in enumerate(items) if not item.strip()]
            for name, items in closure_statements.items()
            if any(not item.strip() for item in items)
        }
        scope_errors = self._scope_disposition_errors(
            closure,
            inventory_source_files={source.path for source in inventory.source_files},
        )
        gates["CG10"] = {
            "pass": not blank_closure_items and not scope_errors,
            "detail": {
                "blank_items": blank_closure_items,
                "scope_disposition_errors": scope_errors,
                **{name: list(items) for name, items in closure_statements.items()},
                "scope_dispositions": [
                    {
                        "scope_ref": item.scope_ref,
                        "disposition": item.disposition.value,
                        "snapshot_id": item.snapshot_id,
                        "rationale": item.rationale,
                        "approved_by": item.approved_by,
                        "evidence_refs": list(item.evidence_refs),
                        "history_source_campaign_id": item.history_source_campaign_id,
                    }
                    for item in closure.scope_dispositions
                ],
            },
        }

        failed = [gate_id for gate_id, gate in gates.items() if not gate["pass"]]
        if failed:
            raise ModelError(f"Campaign gates failed: {', '.join(failed)}")
        skill_review_artifact_id = self.manager.record_skill_review(
            self.campaign_id, closure.skill_issues
        )
        resource_cleanup = cleanup_campaign_resources(
            self.manager, self.campaign_id
        )
        report = {
            "schema_version": "1.0",
            "campaign_id": self.campaign_id,
            "snapshot_id": self.campaign.snapshot_id,
            "plan_id": self.plan.plan_id,
            "scope_digest": self.plan.inventory_digest,
            "repository_size_bytes": inventory.repository_size_bytes,
            "status": "PASS",
            "audit_mode": self.campaign.audit_mode.value,
            "history_source_campaign_ids": list(
                self.campaign.history_source_campaign_ids
            ),
            "architecture_overview": closure.architecture_overview,
            "coverage": {
                "components": len(inventory.components),
                "build_units": len(graph.build_units),
                "work_units": len(self.plan.work_units),
                "inventory_source_files": len(inventory_source_files),
                "included_source_files": len(included_source_files),
                "excluded_source_files": len(excluded_source_files),
                "deferred_source_files": len(deferred_source_files),
                "agent_declared_reviewed_paths": len({
                    item["path"] for item in path_review_claims
                }),
                "agent_declared_path_review_altitudes": path_review_altitude_counts,
                "surfaces": len(surfaces),
                "surface_review_dispositions": len(surface_review_dispositions),
                "boundary_reviews": len(boundary_reviews),
                "unresolved_boundary_reviews": sum(
                    item["disposition"] == "unresolved" for item in boundary_reviews
                ),
                "category_runs": len(category_runs),
                "boundary_edges": len(self.plan.boundary_edges),
                "handoffs": len(self.plan.handoffs),
                "screened_work_units": len(screening_work_unit_ids),
                "substantive_work_units": len(substantive_work_unit_ids),
                "deferred_work_units": (
                    len(work_unit_ids)
                    - len(screening_work_unit_ids)
                    - len(substantive_work_unit_ids)
                ),
            },
            "screening_coverage": {
                "screened_work_unit_ids": screening_work_unit_ids,
                "screened_work_unit_count": len(screening_work_unit_ids),
                "total_work_unit_count": len(work_unit_ids),
                "screened_fraction": screening_fraction,
                "max_screening_fraction": screening_ceiling if screening_ceiling_configured else None,
                "ceiling_status": screening_ceiling_status,
                "release_eligible": screening_ceiling_status == "WITHIN_CEILING",
            },
            "attack_surface": {
                "kinds": _counts(item["kind"] for item in surfaces),
                "principals": _counts(item["principal"] for item in surfaces),
            },
            "discovery_axes": {
                axis: {
                    applicability: sum(
                        item["axis"] == axis and item["applicability"] == applicability
                        for item in discovery_axis_runs
                    )
                    for applicability in ("APPLICABLE", "NOT_APPLICABLE", "DEFERRED")
                }
                for axis in sorted({item["axis"] for item in discovery_axis_runs})
            },
            "findings": merged_findings,
            "surface_review_dispositions": surface_review_dispositions,
            "surface_review_state_counts": surface_review_state_counts,
            "not_feasible_experiment_hypothesis_ids": sorted(
                item["hypothesis_id"]
                for item in r5_assessments
                if item["disposition"] == R5Disposition.NOT_FEASIBLE.value
            ),
            "boundary_reviews": boundary_reviews,
            "batches": [
                {"batch_id": batch_id, "status": batches[batch_id].status.value}
                for batch_id in sorted(planned_batch_ids)
            ],
            "unreviewed_scope": list(closure.unreviewed_scope),
            "scope_completeness": (
                "WITH_SCREENING_ONLY_WORK_UNITS"
                if screening_work_unit_ids
                else (
                    "WITH_DECLARED_UNREVIEWED_SCOPE"
                    if closure.unreviewed_scope
                    else "NO_DECLARED_UNREVIEWED_SCOPE"
                )
            ),
            "scope_dispositions": gates["CG10"]["detail"]["scope_dispositions"],
            "path_scope_counts": path_state_counts,
            "path_scope_dispositions": [
                {
                    "path": item.path,
                    "state": item.state.value,
                    "rationale": item.rationale,
                    "approved_by": item.approved_by,
                    "evidence_refs": list(item.evidence_refs),
                }
                for item in path_dispositions
            ],
            "path_review_claims": path_review_claims,
            "path_review_altitude_counts": path_review_altitude_counts,
            "residual_risks": list(closure.residual_risks),
            "limitations": list(closure.limitations),
            "lessons": list(closure.lessons),
            "knowledge_nominations": list(closure.knowledge_nominations),
            "skill_issues": [
                {
                    "issue_id": issue.issue_id,
                    "kind": issue.kind.value,
                    "stage": issue.stage,
                    "summary": issue.summary,
                    "evidence_refs": list(issue.evidence_refs),
                    "regression_expectation": issue.regression_expectation,
                    "status": issue.status.value,
                }
                for issue in closure.skill_issues
            ],
            "skill_review_artifact_id": skill_review_artifact_id,
            "knowledge_published": False,
            "knowledge_binding": next((
                {"knowledge_version": event.payload["knowledge_version"],
                 "catalog_artifact_id": event.payload_ref}
                for event in events if event.event_type == "KNOWLEDGE_BOUND"
            ), None),
            "gates": gates,
            "capability_metrics": metrics,
            "execution_measurements": {
                "task_count": len({
                    event.entity_id for event in execution_task_events
                    if event.event_type == "TASK_SUBMITTED"
                }),
                "completed_task_count": len(completed_task_measurements),
                "totals": measurement_totals,
                "totals_by_operation": totals_by_operation,
                "usage": {
                    "tasks_reporting_usage": len(usage_reported_tasks),
                    "tasks_missing_usage": len(completed_task_measurements) - len(usage_reported_tasks),
                    "usage_complete": len(usage_reported_tasks) == len(completed_task_measurements),
                    "cache_hit_ratio": cache_hit_ratio,
                },
                "attempt_usage": {
                    "attempt_count": len(terminal_attempts) + len(unreported_claims),
                    "attempts_reporting_usage": len(terminal_attempts) + len(unreported_claims) - len(missing_usage_attempts),
                    "attempts_missing_usage": len(missing_usage_attempts),
                    "usage_complete": not missing_usage_attempts,
                    "totals": attempt_usage_totals,
                    "totals_by_operation": attempt_usage_by_operation,
                    "missing_attempts": missing_usage_attempts,
                },
                "configuration_digest": execution_config_digest,
                "vnext_policy_digest": execution_policy_digest(),
                "host_configuration_profiles": [dict(row) for row in configuration_rows],
                "configuration_complete": not unreported_configuration_tasks,
                "unreported_configuration_task_ids": unreported_configuration_tasks,
                "tasks": completed_task_measurements,
            },
            "resource_cleanup": resource_cleanup,
        }
        encoded = json.dumps(
            report, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        artifact = self.manager.artifacts.put_text(encoded)
        existing_reports = [
            event for event in events if event.event_type == "CAMPAIGN_REPORT_CREATED"
        ]
        if existing_reports and any(
            event.payload_ref != artifact.artifact_id for event in existing_reports
        ):
            raise ModelError("Campaign already has a different final report")
        if not existing_reports:
            self.manager.store.append_event(
                campaign_id=self.campaign_id,
                batch_id=None,
                entity_type="campaign_report",
                entity_id=self.campaign_id,
                event_type="CAMPAIGN_REPORT_CREATED",
                idempotency_key=(
                    f"campaign-report:{self.campaign_id}:{artifact.artifact_id}"
                ),
                actor="tool",
                payload={"status": "PASS", "finding_count": len(merged_findings)},
                payload_ref=artifact.artifact_id,
            )
        self.manager.write_campaign_report_exports(
            self.campaign_id, report, self._markdown(report)
        )
        self.manager.write_campaign_closure_lessons(
            self.campaign_id,
            unreviewed_scope=closure.unreviewed_scope,
            residual_risks=closure.residual_risks,
            limitations=closure.limitations,
            lessons=closure.lessons,
            knowledge_nominations=closure.knowledge_nominations,
        )
        campaign = self.manager.store.get_campaign(self.campaign_id)
        if campaign.status is CampaignStatus.RUNNING:
            self.manager.store.transition_campaign(
                self.campaign_id, CampaignStatus.INTEGRATING
            )
        campaign = self.manager.store.get_campaign(self.campaign_id)
        if campaign.status is CampaignStatus.INTEGRATING:
            self.manager.store.transition_campaign(
                self.campaign_id, CampaignStatus.COMPLETE
            )
        return {**report, "artifact_id": artifact.artifact_id}

    @staticmethod
    def _deduplicate_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
        by_root: dict[str, list[dict[str, Any]]] = {}
        for finding in findings:
            by_root.setdefault(finding["root_cause_key"], []).append(finding)
        merged = []
        for root_cause_key, group in sorted(by_root.items()):
            representative = max(
                group, key=lambda item: _SEVERITY_ORDER[item["severity"]]
            )
            merged.append({
                **representative,
                "finding_id": _stable_id("FND", root_cause_key),
                "source_finding_ids": sorted(item["finding_id"] for item in group),
                "hypothesis_ids": sorted({
                    value for item in group for value in item["hypothesis_ids"]
                }),
                "affected_component_ids": sorted({
                    value for item in group for value in item["affected_component_ids"]
                }),
                "evidence_refs": sorted({
                    value for item in group for value in item["evidence_refs"]
                }),
            })
        return merged

    @staticmethod
    def _markdown(report: dict[str, Any]) -> str:
        findings = list(report.get("findings", []))
        severity_order = ("CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN")

        def severity_of(finding: dict[str, Any]) -> str:
            severity = str(finding.get("severity", "UNKNOWN")).upper()
            return severity if severity in severity_order else "UNKNOWN"

        def cell(value: Any) -> str:
            return str(value).replace("|", "\\|").replace("\n", " ").strip()

        severity_counts = _counts(severity_of(finding) for finding in findings)
        status_counts = _counts(
            str(finding.get("status", "UNKNOWN")).upper() for finding in findings
        )
        evidence_counts = _counts(
            str(finding.get("evidence_grade", "UNKNOWN")) for finding in findings
        )
        sorted_findings = sorted(
            findings,
            key=lambda finding: (
                severity_order.index(severity_of(finding)),
                str(finding.get("title", "" )).casefold(),
                str(finding.get("finding_id", "")),
            ),
        )
        execution = report.get("execution_measurements", {})
        coverage = report.get("coverage", {})
        unreviewed_scope = report.get("unreviewed_scope", [])
        path_scope = report.get("path_scope_dispositions", [])
        scope_completeness = report.get(
            "scope_completeness",
            "LEGACY_REPORT_WITH_UNSTRUCTURED_UNREVIEWED_SCOPE"
            if unreviewed_scope
            else "NO_DECLARED_UNREVIEWED_SCOPE",
        )
        audit_mode = report.get("audit_mode", "NOT_RECORDED (legacy report schema)")
        lines = [
            "# Campaign Audit Report", "",
            f"- Campaign: `{report['campaign_id']}`",
            f"- Snapshot: `{report['snapshot_id']}`",
            f"- Status: **{report['status']}**",
            f"- Audit mode: `{audit_mode}`",
            f"- Scope completeness: `{scope_completeness}`",
            "- Screening-only Work Units: "
            f"{report.get('screening_coverage', {}).get('screened_work_unit_count', 'not recorded')} / "
            f"{report.get('screening_coverage', {}).get('total_work_unit_count', 'not recorded')}",
            "- Screening ceiling: "
            f"{report.get('screening_coverage', {}).get('ceiling_status', 'not recorded')}",
            "",
            "## 1. Audit Summary", "",
            f"- Findings: {len(findings)}",
            "- Severity: " + ", ".join(
                f"{severity} {severity_counts.get(severity, 0)}"
                for severity in severity_order[:-1]
            ),
            "- Status: " + ", ".join(
                f"{status} {count}" for status, count in status_counts.items()
            ) if status_counts else "- Status: None",
            "- Evidence grade: " + ", ".join(
                f"{grade} {count}" for grade, count in evidence_counts.items()
            ) if evidence_counts else "- Evidence grade: None",
            "",
            "### Coverage", "",
        ]
        lines.extend(
            f"- {name}: {count}" for name, count in coverage.items()
        )
        lines.extend([
            "",
            "### Declared Path Review",
            "",
            "These are Agent declarations, not host-observed file reads or safety proof.",
            "- Altitudes: " + ", ".join(
                f"{altitude} {count}"
                for altitude, count in report.get("path_review_altitude_counts", {}).items()
            ) if report.get("path_review_altitude_counts") else "- Altitudes: NOT_RECORDED",
        ])
        if report.get("path_review_claims"):
            lines.extend(
                f"- `{item['path']}` in `{item['batch_id']}` / "
                f"`{item['work_unit_id']}`: `{item['claim']}` "
                f"(`{item['altitude']}`)"
                for item in report["path_review_claims"]
            )
        else:
            lines.append("- No path review claims recorded.")
        not_feasible_experiments = report.get(
            "not_feasible_experiment_hypothesis_ids", []
        )
        if not_feasible_experiments:
            lines.extend([
                "",
                "### Required Experiments Not Feasible",
                "",
                "These hypotheses remain unresolved; infeasibility is not evidence "
                "of safety, confirmation, or refutation.",
                *(
                    f"- `{hypothesis_id}`"
                    for hypothesis_id in not_feasible_experiments
                ),
            ])
        if execution:
            totals = execution.get("totals", {})
            lines.extend([
                f"- Tasks completed: {execution.get('completed_task_count', 0)} / "
                f"{execution.get('task_count', 0)}",
                f"- Agent runs: {totals.get('agent_runs', 'not recorded')}",
                f"- Delegated agent runs: {totals.get('delegated_agent_runs', 'not recorded')}",
                f"- Wall seconds: {totals.get('wall_seconds', 'not recorded')}",
                f"- Host configuration complete: "
                f"{execution.get('configuration_complete', 'not recorded')}",
                "- Cache-hit ratio: "
                f"{execution.get('usage', {}).get('cache_hit_ratio', 'not recorded')}",
                "- Usage reported for every task: "
                f"{execution.get('usage', {}).get('usage_complete', 'not recorded')}",
            ])
        lines.extend([
            "",
            "### Architecture", "", report.get("architecture_overview", "Not recorded."),
            "",
        ])
        lines.extend(["### Path Scope", ""])
        if path_scope:
            lines.extend(
                f"- **{item['state']}** `{cell(item['path'])}`. {cell(item['rationale'])}"
                + (
                    f" Approved by `{cell(item['approved_by'])}`."
                    if item.get("approved_by") else ""
                )
                + (
                    f" Evidence: {', '.join(cell(ref) for ref in item['evidence_refs'])}."
                    if item.get("evidence_refs") else ""
                )
                for item in path_scope
            )
        else:
            lines.append("- No paths recorded in the plan.")
        if report.get("history_source_campaign_ids"):
            lines.extend([
                "", "## Declared History Sources", "",
                *(
                    f"- `{campaign_id}`"
                    for campaign_id in report["history_source_campaign_ids"]
                ),
            ])
        lines.extend(["", "### Unreviewed Scope", ""])
        if report.get("scope_dispositions"):
            lines.extend(
                f"- **{item['disposition']}** `{item['scope_ref']}`; approved by "
                f"`{item['approved_by']}` for snapshot `{item['snapshot_id']}`. "
                f"{item['rationale']} Evidence: {', '.join(item['evidence_refs'])}"
                for item in report["scope_dispositions"]
            )
        elif unreviewed_scope:
            lines.extend(f"- {item}" for item in unreviewed_scope)
            lines.append(
                "- Structured scope dispositions were not recorded in this report version."
            )
        else:
            lines.append("- None recorded.")
        lines.extend(["", "### Limitations", ""])
        lines.extend(f"- {item}" for item in report.get("limitations", []) or ["None recorded."])
        lines.extend(["", "### Residual Risk", ""])
        lines.extend(
            f"- {risk}" for risk in (report.get("residual_risks", []) or ["None recorded."])
        )
        lines.extend(["", "## 2. Findings Overview", ""])
        lines.extend([
            "| Severity | Finding ID | Status | Issue | Root cause |",
            "|---|---|---|---|---|",
        ])
        if sorted_findings:
            lines.extend(
                "| " + " | ".join((
                    severity_of(finding),
                    cell(finding.get("finding_id", "unknown")),
                    cell(finding.get("status", "UNKNOWN")),
                    cell(finding.get("title", "Untitled finding")),
                    cell(finding.get("root_cause_key", "not recorded")),
                )) + " |"
                for finding in sorted_findings
            )
        else:
            lines.append("| - | - | - | No findings recorded. | - |")

        lines.extend(["", "## 3. Detailed Findings by Severity", ""])
        for severity in severity_order[:-1]:
            severity_findings = [
                finding for finding in sorted_findings
                if severity_of(finding) == severity
            ]
            lines.extend([f"### {severity.title()}", ""])
            if not severity_findings:
                lines.extend(["No findings at this severity.", ""])
                continue
            for finding in severity_findings:
                mechanism = finding.get("mechanism") or {}
                if not isinstance(mechanism, dict):
                    mechanism = {"description": str(mechanism)}
                lines.extend([
                    f"#### {cell(finding.get('finding_id', 'Unknown finding'))}: "
                    f"{cell(finding.get('title', 'Untitled finding'))}",
                    "",
                    f"- Status: **{cell(finding.get('status', 'UNKNOWN'))}**",
                    f"- Evidence grade: `{cell(finding.get('evidence_grade', 'unknown'))}`",
                    f"- Root cause: `{cell(finding.get('root_cause_key', 'not recorded'))}`",
                    f"- Mechanism: {cell(mechanism.get('family', 'not recorded'))} / "
                    f"{cell(mechanism.get('variant', 'not recorded'))}",
                ])
                detail = mechanism.get("freeform") or mechanism.get("description")
                if detail:
                    lines.append(f"- Detail: {cell(detail)}")
                for label, values in (
                    ("Affected components", finding.get("affected_component_ids", [])),
                    ("Hypotheses", finding.get("hypothesis_ids", [])),
                    ("Source findings", finding.get("source_finding_ids", [])),
                ):
                    lines.append(
                        f"- {label}: " + (", ".join(f"`{cell(value)}`" for value in values)
                                           if values else "Not recorded")
                    )
                evidence_refs = finding.get("evidence_refs", [])
                lines.append("- Evidence:")
                lines.extend(
                    f"  - `{cell(evidence_ref)}`" for evidence_ref in evidence_refs
                )
                if not evidence_refs:
                    lines.append("  - Not recorded")
                lines.append("")

        lines.extend(["## Campaign Gates", ""])
        lines.extend(
            f"- {gate_id}: {'PASS' if gate['pass'] else 'FAIL'}"
            for gate_id, gate in report.get("gates", {}).items()
        )
        return "\n".join(lines) + "\n"


def _counts(values: Any) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in values:
        result[value] = result.get(value, 0) + 1
    return dict(sorted(result.items()))