"""Campaign gates, root-cause deduplication, and derived final reporting."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .analysis_models import CampaignClosure, R5Disposition
from .campaign import CampaignManager
from .models import BatchStatus, CampaignStatus, ModelError
from .plan_models import AuditPlan
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

    def close(self, closure: CampaignClosure) -> dict[str, Any]:
        events = self.manager.store.list_events(self.campaign_id)
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
        inventory_components = {
            component.component_id for component in inventory.components
        }
        build_components = {unit.component_id for unit in graph.build_units}
        inventory_source_files = {source.path for source in inventory.source_files}
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
        gates["CG2"] = {
            "pass": inventory_components.issubset(owned_components)
            and build_components.issubset(owned_components)
            and inventory_source_files == planned_source_file_set
            and not duplicate_source_files,
            "detail": {
                "unowned_components": sorted(inventory_components - owned_components),
                "unowned_build_units": sorted(build_components - owned_components),
                "missing_source_files": sorted(
                    inventory_source_files - planned_source_file_set
                ),
                "unexpected_source_files": sorted(
                    planned_source_file_set - inventory_source_files
                ),
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
        batch_reports = []
        metrics = []
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
                    batch_reports.append(artifact)
                elif event.event_type == "TRANSMISSION_METRICS_RECORDED":
                    metrics.append(artifact)
        surface_ids = [item["surface_id"] for item in surfaces]
        analyzed_surface_ids = {
            surface_id
            for hypothesis in hypotheses
            for surface_id in hypothesis["surface_ids"]
        }
        hypothesis_ids = {item["hypothesis_id"] for item in hypotheses}
        verdict_hypothesis_ids = {item["hypothesis_id"] for item in verdicts}
        gates["CG3"] = {
            "pass": len(surface_ids) == len(set(surface_ids))
            and set(surface_ids) == analyzed_surface_ids
            and hypothesis_ids == verdict_hypothesis_ids,
            "detail": {
                "surface_count": len(surface_ids),
                "unanalyzed_surfaces": sorted(set(surface_ids) - analyzed_surface_ids),
                "unknown_surface_refs": sorted(analyzed_surface_ids - set(surface_ids)),
                "hypotheses_without_verdict": sorted(
                    hypothesis_ids - verdict_hypothesis_ids
                ),
            },
        }

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
        completed_task_measurements = []
        for event in execution_task_events:
            if event.event_type != "TASK_COMPLETED":
                continue
            task_spec = {}
            submission = next((
                item for item in execution_task_events
                if item.entity_id == event.entity_id and item.event_type == "TASK_SUBMITTED"
            ), None)
            if submission is not None and submission.payload_ref:
                task_spec = json.loads(self.manager.artifacts.get_bytes(submission.payload_ref))
            completed_task_measurements.append({
                "task_id": event.entity_id,
                "operation": task_spec.get("operation", "unknown"),
                "work_unit_id": task_spec.get("work_unit_id", "unknown"),
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
        gates["CG10"] = {
            "pass": not blank_closure_items,
            "detail": {
                "blank_items": blank_closure_items,
                **{name: list(items) for name, items in closure_statements.items()},
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
            "architecture_overview": closure.architecture_overview,
            "coverage": {
                "components": len(inventory.components),
                "build_units": len(graph.build_units),
                "work_units": len(self.plan.work_units),
                "surfaces": len(surfaces),
                "boundary_reviews": len(boundary_reviews),
                "unresolved_boundary_reviews": sum(
                    item["disposition"] == "unresolved" for item in boundary_reviews
                ),
                "category_runs": len(category_runs),
                "boundary_edges": len(self.plan.boundary_edges),
                "handoffs": len(self.plan.handoffs),
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
            "boundary_reviews": boundary_reviews,
            "batches": [
                {"batch_id": batch_id, "status": batches[batch_id].status.value}
                for batch_id in sorted(planned_batch_ids)
            ],
            "unreviewed_scope": list(closure.unreviewed_scope),
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
            "gates": gates,
            "capability_metrics": metrics,
            "execution_measurements": {
                "task_count": len({
                    event.entity_id for event in execution_task_events
                    if event.event_type == "TASK_SUBMITTED"
                }),
                "completed_task_count": len(completed_task_measurements),
                "totals": measurement_totals,
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
        lines = [
            "# Campaign Report", "",
            f"- Campaign: `{report['campaign_id']}`",
            f"- Snapshot: `{report['snapshot_id']}`",
            f"- Status: **{report['status']}**",
            f"- Findings: {len(report['findings'])}", "",
            "## Architecture", "", report["architecture_overview"], "",
            "## Coverage", "",
        ]
        lines.extend(
            f"- {name}: {count}" for name, count in report["coverage"].items()
        )
        lines.extend(["", "## Residual Risk", ""])
        lines.extend(
            f"- {risk}" for risk in (report["residual_risks"] or ["None recorded."])
        )
        lines.extend(["", "## Campaign Gates", ""])
        lines.extend(
            f"- {gate_id}: {'PASS' if gate['pass'] else 'FAIL'}"
            for gate_id, gate in report["gates"].items()
        )
        return "\n".join(lines) + "\n"


def _counts(values: Any) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in values:
        result[value] = result.get(value, 0) + 1
    return dict(sorted(result.items()))