"""Event-backed R0-R3 Batch workflow and partial gates."""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

from .analysis_models import (
    Adjudication,
    AdjudicationActor,
    AttackAngle,
    Applicability,
    AxisRun,
    BatchClosure,
    BoundaryReview,
    CanonicalVerdict,
    CategoryAuditPlan,
    CategoryRun,
    CategoryRunStatus,
    DiscoveryAxis,
    EvidenceGrade,
    Experiment,
    ExperimentResult,
    Finding,
    FindingStatus,
    Hypothesis,
    Refutation,
    R5Assessment,
    R5Disposition,
    RevivalReview,
    Surface,
    SurfaceReviewDisposition,
    SurfaceReviewState,
    VerdictKind,
    VerdictSubmission,
)
from .campaign import CampaignManager
from .drift import record_snapshot_drift
from .models import BatchStatus, CampaignStatus, EventRecord, ModelError
from .plan_models import WorkUnit


class BatchWorkflow:
    def __init__(
        self, manager: CampaignManager, campaign_id: str, batch_id: str
    ) -> None:
        self.manager = manager
        self.campaign_id = campaign_id
        self.batch_id = batch_id
        self.campaign = manager.store.get_campaign(campaign_id)
        self.batch = manager.store.get_batch(campaign_id, batch_id)

    def run_r0(self) -> str:
        work_units = self._work_units()
        if not work_units:
            raise ModelError("Batch manifest has no canonical Work Unit definitions")
        scoped_paths = []
        seen_work_units = set()
        for work_unit in work_units:
            work_unit_id = str(work_unit.get("work_unit_id", ""))
            if not work_unit_id or work_unit_id in seen_work_units:
                raise ModelError("Batch manifest contains invalid or duplicate Work Unit IDs")
            seen_work_units.add(work_unit_id)
            for source_path in work_unit.get("source_files", []):
                path = PurePosixPath(str(source_path))
                if path.is_absolute() or ".." in path.parts:
                    raise ModelError(f"source path escapes Batch scope: {source_path}")
                scoped_paths.append(path.as_posix())
        baseline = self.manager.load_snapshot_baseline(self.campaign_id)
        baseline_files = baseline.get("files", {})
        if not isinstance(baseline_files, dict):
            raise ModelError("Campaign snapshot baseline has invalid file entries")
        observed_digests: dict[str, str | None] = {}
        expected_digests: dict[str, str] = {}
        changed_paths = []
        for source_path in scoped_paths:
            expected = baseline_files.get(source_path)
            if not isinstance(expected, str):
                raise ModelError(f"scoped source is absent from snapshot baseline: {source_path}")
            expected_digests[source_path] = expected
            file_path = self.manager.target_root / source_path
            observed = None
            if file_path.is_file():
                digest = hashlib.sha256()
                with file_path.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(chunk)
                observed = digest.hexdigest()
            observed_digests[source_path] = observed
            if observed != expected:
                changed_paths.append(source_path)
        if changed_paths:
            plan_id = str(self.batch.manifest.get("plan_id", ""))
            if not plan_id:
                raise ModelError("Batch manifest lacks a plan for drift impact analysis")
            plan = self.manager.load_audit_plan(self.campaign_id, plan_id)
            batch = self.manager.store.get_batch(self.campaign_id, self.batch_id)
            drift_event_id, impact = record_snapshot_drift(
                self.manager,
                campaign_id=self.campaign_id,
                detecting_batch_id=self.batch_id,
                plan=plan,
                changed_paths=changed_paths,
                expected_digests=expected_digests,
                observed_digests=observed_digests,
                detecting_batch_status=batch.status,
            )
            if batch.status is not BatchStatus.BLOCKED:
                self.manager.store.transition_batch(
                    self.campaign_id, self.batch_id, BatchStatus.BLOCKED
                )
            raise ModelError(
                "snapshot drift detected; "
                f"event={drift_event_id}, affected_work_units="
                f"{list(impact.affected_work_unit_ids)}"
            )
        receipt = {
            "schema_version": "1.0",
            "campaign_id": self.campaign_id,
            "batch_id": self.batch_id,
            "snapshot_id": self.campaign.snapshot_id,
            "work_unit_ids": sorted(seen_work_units),
            "scoped_paths": sorted(scoped_paths),
            "file_digests": dict(sorted(observed_digests.items())),
        }
        artifact_id = self._put_json(receipt)
        self.manager.store.append_event(
            campaign_id=self.campaign_id,
            batch_id=self.batch_id,
            entity_type="batch_stage",
            entity_id=self.batch_id,
            event_type="R0_COMPLETED",
            idempotency_key=f"r0:{self.campaign_id}:{self.batch_id}",
            actor="tool",
            payload={"work_units": len(work_units), "source_files": len(scoped_paths)},
            payload_ref=artifact_id,
        )
        batch = self.manager.store.get_batch(self.campaign_id, self.batch_id)
        if batch.status is BatchStatus.PLANNED:
            self.manager.store.transition_batch(
                self.campaign_id, self.batch_id, BatchStatus.READY
            )
        campaign = self.manager.store.get_campaign(self.campaign_id)
        if campaign.status is CampaignStatus.PLANNING:
            self.manager.store.transition_campaign(
                self.campaign_id, CampaignStatus.RUNNING
            )
        return artifact_id

    def record_r1(
        self,
        surfaces: Sequence[Surface],
        boundary_reviews: Sequence[BoundaryReview] = (),
    ) -> str:
        self._require_stage("R0_COMPLETED")
        work_units = {str(item["work_unit_id"]): item for item in self._work_units()}
        plan_id = str(self.batch.manifest.get("plan_id", ""))
        if not plan_id:
            raise ModelError("Batch manifest lacks a plan ID for boundary evidence validation")
        plan = self.manager.load_audit_plan(self.campaign_id, plan_id)
        inventory = self.manager.load_inventory(self.campaign_id)
        inventoried_paths = {source.path for source in inventory.source_files}
        line_count_cache: dict[str, tuple[int, frozenset[int]]] = {}
        boundary_edges = {edge.edge_id: edge for edge in plan.boundary_edges}
        expected_boundary_reviews = {
            (str(edge_id), work_unit_id)
            for work_unit_id, work_unit in work_units.items()
            for edge_id in work_unit.get("boundary_edge_ids", [])
        }
        actual_boundary_reviews = set()
        for review in boundary_reviews:
            key = (review.edge_id, review.work_unit_id)
            if key not in expected_boundary_reviews:
                raise ModelError(
                    f"boundary review is outside R1 Work Unit scope: {review.edge_id}"
                )
            if key in actual_boundary_reviews:
                raise ModelError(f"duplicate boundary review: {review.edge_id}")
            edge = boundary_edges.get(review.edge_id)
            if edge is None:
                raise ModelError(f"boundary review references an unknown edge: {review.edge_id}")
            unit = work_units[review.work_unit_id]
            if unit["component_id"] not in {
                edge.source_component_id, edge.target_component_id,
            }:
                raise ModelError(f"boundary review Work Unit is not an edge endpoint: {review.edge_id}")
            self._validate_boundary_evidence(
                review.evidence_refs, review.edge_id, inventoried_paths, line_count_cache
            )
            actual_boundary_reviews.add(key)
        if actual_boundary_reviews != expected_boundary_reviews:
            missing = sorted(expected_boundary_reviews - actual_boundary_reviews)
            raise ModelError(f"R1 boundary review coverage mismatch: {missing}")
        seen = set()
        for surface in surfaces:
            if surface.surface_id in seen:
                raise ModelError(f"duplicate surface ID: {surface.surface_id}")
            seen.add(surface.surface_id)
            work_unit = work_units.get(surface.work_unit_id)
            if work_unit is None:
                raise ModelError(f"surface is outside Batch Work Units: {surface.surface_id}")
            if surface.component_id != str(work_unit["component_id"]):
                raise ModelError(f"surface component mismatch: {surface.surface_id}")
            if surface.entry_path not in {
                str(item) for item in work_unit.get("source_files", [])
            }:
                raise ModelError(f"surface entry path is outside Work Unit: {surface.surface_id}")
            expected_prefix = f"LOC-{surface.entry_path}:"
            anchors = [
                evidence_ref
                for evidence_ref in surface.evidence_refs
                if evidence_ref.startswith(expected_prefix)
            ]
            if not anchors:
                raise ModelError(
                    f"surface requires a source anchor for its entry path: {surface.surface_id}"
                )
            line_count = self._source_line_count(surface.entry_path, line_count_cache)
            for anchor in anchors:
                line_value = anchor.removeprefix(expected_prefix)
                if not line_value.isdigit() or not 1 <= int(line_value) <= line_count:
                    raise ModelError(
                        f"surface source anchor is outside the file: {anchor}"
                    )
                if int(line_value) not in line_count_cache[surface.entry_path][1]:
                    raise ModelError(
                        f"surface source anchor points to a blank line: {anchor}"
                    )
        value = {
            "schema_version": "1.0",
            "surfaces": [asdict(surface) for surface in surfaces],
            "boundary_reviews": [asdict(review) for review in boundary_reviews],
        }
        artifact_id = self._put_json(value)
        self.manager.store.append_event(
            campaign_id=self.campaign_id,
            batch_id=self.batch_id,
            entity_type="batch_stage",
            entity_id=self.batch_id,
            event_type="R1_COMPLETED",
            idempotency_key=f"r1:{self.campaign_id}:{self.batch_id}",
            actor="agent",
            payload={
                "surface_ids": sorted(seen),
                "boundary_review_count": len(boundary_reviews),
            },
            payload_ref=artifact_id,
        )
        batch = self.manager.store.get_batch(self.campaign_id, self.batch_id)
        if batch.status is BatchStatus.READY:
            self.manager.store.transition_batch(
                self.campaign_id, self.batch_id, BatchStatus.RUNNING
            )
        return artifact_id

    def _source_line_index(
        self, source_path: str, cache: dict[str, tuple[int, frozenset[int]]]
    ) -> tuple[int, frozenset[int]]:
        if source_path not in cache:
            try:
                lines = (
                    self.manager.target_root / source_path
                ).read_text(encoding="utf-8", errors="replace").splitlines()
                cache[source_path] = (
                    len(lines),
                    frozenset(
                        index for index, line in enumerate(lines, start=1)
                        if line.strip()
                    ),
                )
            except OSError as error:
                raise ModelError(
                    f"source anchor file cannot be read: {source_path}"
                ) from error
        return cache[source_path]

    def _source_line_count(
        self, source_path: str, cache: dict[str, tuple[int, frozenset[int]]]
    ) -> int:
        return self._source_line_index(source_path, cache)[0]

    def _validate_boundary_evidence(
        self,
        evidence_refs: Sequence[str],
        edge_id: str,
        inventoried_paths: set[str],
        line_count_cache: dict[str, tuple[int, frozenset[int]]],
    ) -> None:
        for reference in evidence_refs:
            if not reference.startswith("LOC-"):
                raise ModelError(
                    f"boundary evidence must use source LOC anchors: {edge_id}"
                )
            location = reference.removeprefix("LOC-")
            source_path, separator, line_text = location.rpartition(":")
            if not separator or source_path not in inventoried_paths or not line_text.isdigit():
                raise ModelError(f"invalid boundary source anchor: {reference}")
            line_count = self._source_line_count(source_path, line_count_cache)
            if not 1 <= int(line_text) <= line_count:
                raise ModelError(f"boundary source anchor is outside the file: {reference}")
            if int(line_text) not in line_count_cache[source_path][1]:
                raise ModelError(f"boundary source anchor points to a blank line: {reference}")

    def record_r2(
        self,
        hypotheses: Sequence[Hypothesis],
        *,
        axis_evidence: Mapping[str, Sequence[str]],
        axis_runs: Sequence[AxisRun],
    ) -> str:
        r1_event = self._require_stage("R1_COMPLETED")
        surfaces = {
            item["surface_id"]
            for item in self._read_artifact(r1_event.payload_ref)["surfaces"]
        }
        work_units = {str(item["work_unit_id"]): item for item in self._work_units()}
        submitted_axes = set(axis_evidence)
        allowed_axes = {axis.value for axis in DiscoveryAxis}
        if submitted_axes != allowed_axes or any(
            not tuple(evidence) for evidence in axis_evidence.values()
        ):
            raise ModelError("R2 requires evidence for all six discovery axes")
        work_unit_ids = set(work_units)
        axis_run_by_key = {}
        for item in axis_runs:
            work_unit_id = item.work_unit_id
            if work_unit_id is None and len(work_unit_ids) == 1:
                work_unit_id = next(iter(work_unit_ids))
            key = (work_unit_id, item.axis.value)
            if work_unit_id not in work_unit_ids or key in axis_run_by_key:
                raise ModelError("R2 axis run has a missing, invalid, or duplicate Work Unit/axis")
            axis_run_by_key[key] = AxisRun(
                axis=item.axis,
                applicability=item.applicability,
                evidence_refs=item.evidence_refs,
                rationale=item.rationale,
                work_unit_id=work_unit_id,
            )
        expected_axis_runs = {
            (work_unit_id, axis) for work_unit_id in work_unit_ids for axis in allowed_axes
        }
        if set(axis_run_by_key) != expected_axis_runs:
            missing = sorted(expected_axis_runs - set(axis_run_by_key))
            raise ModelError(f"R2 axis disposition coverage mismatch: {missing}")
        for (work_unit_id, axis), run in axis_run_by_key.items():
            if not run.evidence_refs or not run.rationale.strip():
                raise ModelError(
                    f"R2 axis disposition lacks evidence or rationale: {work_unit_id}/{axis}"
                )
        seen = set()
        for hypothesis in hypotheses:
            if hypothesis.hypothesis_id in seen:
                raise ModelError(f"duplicate hypothesis ID: {hypothesis.hypothesis_id}")
            seen.add(hypothesis.hypothesis_id)
            work_unit = work_units.get(hypothesis.work_unit_id)
            if work_unit is None:
                raise ModelError(
                    f"hypothesis is outside Batch Work Units: {hypothesis.hypothesis_id}"
                )
            unknown_surfaces = set(hypothesis.surface_ids) - surfaces
            if unknown_surfaces:
                raise ModelError(
                    f"hypothesis references unknown surfaces: {sorted(unknown_surfaces)}"
                )
            allowed_families = {
                str(item).upper() for item in work_unit.get("category_families", [])
            }
            if hypothesis.mechanism.family not in allowed_families:
                raise ModelError(
                    f"hypothesis mechanism is outside Category plan: {hypothesis.hypothesis_id}"
                )
            if (hypothesis.work_unit_id, hypothesis.origin_axis) not in axis_run_by_key:
                raise ModelError(
                    f"hypothesis origin axis lacks execution evidence: {hypothesis.hypothesis_id}"
                )
            if axis_run_by_key[(hypothesis.work_unit_id, hypothesis.origin_axis)].applicability is not Applicability.APPLICABLE:
                raise ModelError(
                    f"hypothesis originated from a non-applicable axis: {hypothesis.hypothesis_id}"
                )
        value = {
            "schema_version": "1.0",
            "axis_evidence": {
                axis: list(axis_evidence[axis]) for axis in sorted(submitted_axes)
            },
            "axis_runs": [
                asdict(axis_run_by_key[key]) for key in sorted(axis_run_by_key)
            ],
            "hypotheses": [asdict(hypothesis) for hypothesis in hypotheses],
        }
        artifact_id = self._put_json(value)
        self.manager.store.append_event(
            campaign_id=self.campaign_id,
            batch_id=self.batch_id,
            entity_type="batch_stage",
            entity_id=self.batch_id,
            event_type="R2_COMPLETED",
            idempotency_key=f"r2:{self.campaign_id}:{self.batch_id}",
            actor="agent",
            payload={"hypothesis_ids": sorted(seen), "axes": sorted(submitted_axes)},
            payload_ref=artifact_id,
        )
        return artifact_id

    def build_refutation_brief(
        self, hypothesis_id: str, *, refuter_id: str
    ) -> dict[str, Any]:
        if not refuter_id.strip():
            raise ModelError("refuter ID is required")
        hypothesis, verdict = self._refutation_target(hypothesis_id)
        return {
            "schema_version": "1.0",
            "hypothesis": hypothesis,
            "verifier_verdict": verdict,
            "required_perspectives": [
                AttackAngle.CALL_CHAIN.value,
                "one of principal/configuration/deployment/impact",
            ],
            "excluded_context": ["other refuter verdicts", "other refuter rationale"],
        }

    def record_refutation(self, refutation: Refutation) -> str:
        self._refutation_target(refutation.hypothesis_id)
        existing = self._events(
            event_type="REFUTATION_SUBMITTED",
            entity_id=refutation.hypothesis_id,
        )
        if any(event.payload.get("refuter_id") == refutation.refuter_id for event in existing):
            same = next(
                event
                for event in existing
                if event.payload.get("refuter_id") == refutation.refuter_id
            )
            if same.payload_ref:
                previous = self._read_artifact(same.payload_ref)
                if previous != json.loads(json.dumps(asdict(refutation), default=str)):
                    raise ModelError(
                        f"refuter already submitted a different result: {refutation.refuter_id}"
                    )
                return same.payload_ref
        artifact_id = self._put_json(asdict(refutation))
        self.manager.store.append_event(
            campaign_id=self.campaign_id,
            batch_id=self.batch_id,
            entity_type="hypothesis",
            entity_id=refutation.hypothesis_id,
            event_type="REFUTATION_SUBMITTED",
            idempotency_key=f"r35-refute:{self.campaign_id}:{refutation.refutation_id}",
            actor="agent",
            payload={
                "refutation_id": refutation.refutation_id,
                "refuter_id": refutation.refuter_id,
                "attack_angle": refutation.attack_angle.value,
                "verdict": refutation.verdict.value,
            },
            payload_ref=artifact_id,
        )
        return artifact_id

    def record_adjudication(self, adjudication: Adjudication) -> str:
        _, verifier_verdict = self._refutation_target(adjudication.hypothesis_id)
        events = self._events(
            event_type="REFUTATION_SUBMITTED",
            entity_id=adjudication.hypothesis_id,
        )
        refutations = [self._read_artifact(event.payload_ref) for event in events]
        if len({item["refuter_id"] for item in refutations}) < 2:
            raise ModelError("adjudication requires two independent refuters")
        angles = {item["attack_angle"] for item in refutations}
        if AttackAngle.CALL_CHAIN.value not in angles or not angles.intersection({
            AttackAngle.PRINCIPAL.value,
            AttackAngle.CONFIGURATION.value,
            AttackAngle.DEPLOYMENT.value,
            AttackAngle.IMPACT.value,
        }):
            raise ModelError("adjudication requires call-chain and premise perspectives")
        available_ids = {item["refutation_id"] for item in refutations}
        if set(adjudication.refutation_ids) != available_ids:
            raise ModelError("adjudication must reference every submitted refutation")
        refuter_verdicts = {item["verdict"] for item in refutations}
        if len(refuter_verdicts) > 1 and adjudication.actor is not AdjudicationActor.HUMAN:
            raise ModelError("split refutations require human adjudication")
        if (
            verifier_verdict["verdict"] == VerdictKind.REACHABLE.value
            and adjudication.final_verdict is VerdictKind.UNREACHABLE
            and not adjudication.source_verifications
        ):
            raise ModelError(
                "REACHABLE to UNREACHABLE adjudication requires source verification"
            )
        artifact_id = self._put_json(asdict(adjudication))
        self.manager.store.append_event(
            campaign_id=self.campaign_id,
            batch_id=self.batch_id,
            entity_type="hypothesis",
            entity_id=adjudication.hypothesis_id,
            event_type="ADJUDICATION_DECIDED",
            idempotency_key=f"r35-adjudicate:{self.campaign_id}:{adjudication.adjudication_id}",
            actor=adjudication.actor.value,
            payload={
                "adjudication_id": adjudication.adjudication_id,
                "final_verdict": adjudication.final_verdict.value,
                "refutation_ids": list(adjudication.refutation_ids),
            },
            payload_ref=artifact_id,
        )
        return artifact_id

    def record_revival_selection(
        self,
        hypothesis_ids: Sequence[str],
        *,
        rationale: str,
        evidence_refs: Sequence[str],
    ) -> str:
        unreachable = {
            item["hypothesis_id"]
            for item in self._r3_verdicts()
            if item["verdict"] == VerdictKind.UNREACHABLE.value
        }
        selected = set(hypothesis_ids)
        if not selected.issubset(unreachable):
            raise ModelError("revival selection contains a non-UNREACHABLE hypothesis")
        if not rationale.strip() or not evidence_refs:
            raise ModelError("revival selection requires rationale and evidence refs")
        value = {
            "schema_version": "1.0",
            "hypothesis_ids": sorted(selected),
            "rationale": rationale,
            "evidence_refs": list(evidence_refs),
        }
        artifact_id = self._put_json(value)
        self.manager.store.append_event(
            campaign_id=self.campaign_id,
            batch_id=self.batch_id,
            entity_type="batch_stage",
            entity_id=self.batch_id,
            event_type="REVIVAL_SAMPLE_SELECTED",
            idempotency_key=f"r35-revival-selection:{self.campaign_id}:{self.batch_id}",
            actor="agent",
            payload={"hypothesis_ids": sorted(selected)},
            payload_ref=artifact_id,
        )
        return artifact_id

    def record_revival_review(self, review: RevivalReview) -> str:
        selection = self._require_stage("REVIVAL_SAMPLE_SELECTED")
        selected = set(self._read_artifact(selection.payload_ref)["hypothesis_ids"])
        if review.hypothesis_id not in selected:
            raise ModelError("revival review hypothesis was not selected")
        artifact_id = self._put_json(asdict(review))
        self.manager.store.append_event(
            campaign_id=self.campaign_id,
            batch_id=self.batch_id,
            entity_type="hypothesis",
            entity_id=review.hypothesis_id,
            event_type="REVIVAL_REVIEWED",
            idempotency_key=f"r35-revival:{self.campaign_id}:{review.revival_id}",
            actor="agent",
            payload={"revival_id": review.revival_id, "outcome": review.outcome.value},
            payload_ref=artifact_id,
        )
        return artifact_id

    def complete_r35(self) -> str:
        self._require_stage("R3_COMPLETED")
        verdicts = self._r3_verdicts()
        eligible = {
            item["hypothesis_id"]
            for item in verdicts
            if item["verdict"] == VerdictKind.REACHABLE.value
            and item["evidence_grade"] == EvidenceGrade.EDGE_PROVEN.value
        }
        adjudicated = {
            event.entity_id
            for event in self._events(event_type="ADJUDICATION_DECIDED")
        }
        if eligible != adjudicated:
            raise ModelError(
                f"R3.5 adjudication coverage mismatch: expected={sorted(eligible)}, "
                f"actual={sorted(adjudicated)}"
            )
        selection = self._require_stage("REVIVAL_SAMPLE_SELECTED")
        selected = set(self._read_artifact(selection.payload_ref)["hypothesis_ids"])
        reviewed = {
            event.entity_id
            for event in self._events(event_type="REVIVAL_REVIEWED")
        }
        if selected != reviewed:
            raise ModelError(
                f"R3.5 revival coverage mismatch: expected={sorted(selected)}, "
                f"actual={sorted(reviewed)}"
            )
        value = {
            "schema_version": "1.0",
            "adjudicated_hypothesis_ids": sorted(adjudicated),
            "revived_hypothesis_ids": sorted(reviewed),
        }
        artifact_id = self._put_json(value)
        self.manager.store.append_event(
            campaign_id=self.campaign_id,
            batch_id=self.batch_id,
            entity_type="batch_stage",
            entity_id=self.batch_id,
            event_type="R3_5_COMPLETED",
            idempotency_key=f"r35:{self.campaign_id}:{self.batch_id}",
            actor="tool",
            payload=value,
            payload_ref=artifact_id,
        )
        return artifact_id

    def record_category_audit_plan(
        self, plans: Sequence[CategoryAuditPlan]
    ) -> str:
        self._require_stage("R3_5_COMPLETED")
        work_units = {
            str(item["work_unit_id"]): WorkUnit.from_dict(item)
            for item in self._work_units()
        }
        expected = {
            (work_unit.work_unit_id, family)
            for work_unit in work_units.values()
            for family in work_unit.category_families
        }
        actual = {(plan.work_unit_id, plan.family) for plan in plans}
        if expected != actual or len(actual) != len(plans):
            raise ModelError(
                f"CategoryAuditPlan coverage mismatch: expected={sorted(expected)}, "
                f"actual={sorted(actual)}"
            )
        for plan in plans:
            work_unit = work_units[plan.work_unit_id]
            if tuple(plan.discovery_axes) != tuple(work_unit.discovery_axes):
                raise ModelError(
                    f"CategoryAuditPlan axes differ from Work Unit: {plan.category_plan_id}"
                )
        artifact_id = self._put_json({
            "schema_version": "1.0",
            "category_plans": [asdict(plan) for plan in plans],
        })
        self.manager.store.append_event(
            campaign_id=self.campaign_id,
            batch_id=self.batch_id,
            entity_type="batch_stage",
            entity_id=self.batch_id,
            event_type="CATEGORY_AUDIT_PLAN_RECORDED",
            idempotency_key=f"category-plan:{self.campaign_id}:{self.batch_id}",
            actor="tool",
            payload={"category_plan_ids": sorted(
                plan.category_plan_id for plan in plans
            )},
            payload_ref=artifact_id,
        )
        return artifact_id

    def record_r4_screening_runs(self, runs: Sequence[CategoryRun]) -> str:
        plan_event = self._require_stage("CATEGORY_AUDIT_PLAN_RECORDED")
        r2_event = self._require_stage("R2_COMPLETED")
        if plan_event.payload_ref is None or r2_event.payload_ref is None:
            raise ModelError("R4 screening requires CategoryAuditPlan and R2 artifacts")
        plans = {
            str(item["category_plan_id"]): item
            for item in self._read_artifact(plan_event.payload_ref)["category_plans"]
        }
        r2 = self._read_artifact(r2_event.payload_ref)
        axis_runs = {
            (str(item["work_unit_id"]), str(item["axis"])): item
            for item in r2["axis_runs"]
        }
        hypotheses_by_work_unit: dict[str, list[str]] = {}
        for hypothesis in r2["hypotheses"]:
            hypotheses_by_work_unit.setdefault(
                str(hypothesis["work_unit_id"]), []
            ).append(str(hypothesis["hypothesis_id"]))

        expected_screening = set()
        for plan_id, plan in plans.items():
            work_unit_id = str(plan["work_unit_id"])
            planned_axes = tuple(str(axis) for axis in plan["discovery_axes"])
            if (
                planned_axes
                and not hypotheses_by_work_unit.get(work_unit_id)
                and all(
                    axis_runs.get((work_unit_id, axis), {}).get("applicability")
                    == Applicability.NOT_APPLICABLE.value
                    for axis in planned_axes
                )
            ):
                expected_screening.add(plan_id)
        actual_screening = {run.category_plan_id for run in runs}
        if actual_screening != expected_screening or len(runs) != len(actual_screening):
            raise ModelError(
                "R4 screening coverage must exactly match all fully NOT_APPLICABLE plans"
            )
        for run in runs:
            plan = plans[run.category_plan_id]
            work_unit_id = str(plan["work_unit_id"])
            expected_axes = tuple(str(axis) for axis in plan["discovery_axes"])
            expected_axis_runs = [
                axis_runs[(work_unit_id, axis)] for axis in expected_axes
            ]
            if (
                run.work_unit_id != work_unit_id
                or run.family != str(plan["family"])
                or run.applicability is not Applicability.NOT_APPLICABLE
                or run.status is not CategoryRunStatus.COMPLETE
                or tuple(item.axis.value for item in run.axis_runs) != expected_axes
                or any(
                    item.applicability is not Applicability.NOT_APPLICABLE
                    for item in run.axis_runs
                )
                or any(
                    tuple(item.evidence_refs) != tuple(source["evidence_refs"])
                    for item, source in zip(run.axis_runs, expected_axis_runs)
                )
                or run.hypothesis_ids
                or run.finding_ids
            ):
                raise ModelError(
                    f"R4 screening result is not backed by R2 dispositions: {run.category_run_id}"
                )
        artifact_id = self._put_json({
            "schema_version": "1.0",
            "category_runs": [asdict(run) for run in runs],
        })
        self.manager.store.append_event(
            campaign_id=self.campaign_id,
            batch_id=self.batch_id,
            entity_type="batch_stage",
            entity_id=self.batch_id,
            event_type="R4_SCREENING_COVERAGE_RECORDED",
            idempotency_key=(
                f"r4-screening:{self.campaign_id}:{self.batch_id}:{artifact_id}"
            ),
            actor="tool",
            payload={"category_plan_ids": sorted(actual_screening)},
            payload_ref=artifact_id,
        )
        return artifact_id

    def record_r4(self, runs: Sequence[CategoryRun]) -> str:
        plan_event = self._require_stage("CATEGORY_AUDIT_PLAN_RECORDED")
        plans = {
            item["category_plan_id"]: item
            for item in self._read_artifact(plan_event.payload_ref)["category_plans"]
        }
        if {run.category_plan_id for run in runs} != set(plans) or len(runs) != len(plans):
            raise ModelError("R4 must contain exactly one run per CategoryAuditPlan")
        r2_event = self._require_stage("R2_COMPLETED")
        hypotheses = {
            item["hypothesis_id"]: item
            for item in self._read_artifact(r2_event.payload_ref)["hypotheses"]
        }
        recorded_findings = {
            event.entity_id
            for event in self._events(event_type="FINDING_RECORDED")
        }
        for run in runs:
            plan = plans[run.category_plan_id]
            if run.work_unit_id != plan["work_unit_id"] or run.family != plan["family"]:
                raise ModelError(f"CategoryRun does not match plan: {run.category_run_id}")
            axes = [axis_run.axis.value for axis_run in run.axis_runs]
            if len(axes) != len(set(axes)) or set(axes) != set(plan["discovery_axes"]):
                raise ModelError(
                    f"CategoryRun axis coverage mismatch: {run.category_run_id}"
                )
            if run.applicability is Applicability.APPLICABLE and set(
                run.mechanism_variants_examined
            ) != set(plan["mechanism_variants"]):
                raise ModelError(
                    f"CategoryRun mechanism coverage mismatch: {run.category_run_id}"
                )
            for hypothesis_id in run.hypothesis_ids:
                hypothesis = hypotheses.get(hypothesis_id)
                if hypothesis is None:
                    raise ModelError(f"CategoryRun references unknown hypothesis: {hypothesis_id}")
                if (
                    hypothesis["work_unit_id"] != run.work_unit_id
                    or hypothesis["mechanism"]["family"] != run.family
                ):
                    raise ModelError(
                        f"CategoryRun hypothesis is outside its scope: {hypothesis_id}"
                    )
            if not set(run.finding_ids).issubset(recorded_findings):
                raise ModelError(
                    f"CategoryRun references unrecorded findings: {run.category_run_id}"
                )
        artifact_id = self._put_json({
            "schema_version": "1.0",
            "category_runs": [asdict(run) for run in runs],
        })
        self.manager.store.append_event(
            campaign_id=self.campaign_id,
            batch_id=self.batch_id,
            entity_type="batch_stage",
            entity_id=self.batch_id,
            event_type="R4_COMPLETED",
            idempotency_key=f"r4:{self.campaign_id}:{self.batch_id}",
            actor="agent",
            payload={
                "category_run_ids": sorted(run.category_run_id for run in runs),
                "linked_finding_count": len({
                    finding_id for run in runs for finding_id in run.finding_ids
                }),
            },
            payload_ref=artifact_id,
        )
        return artifact_id

    def record_r5(
        self,
        experiments: Sequence[Experiment],
        assessments: Sequence[R5Assessment],
    ) -> str:
        self._require_stage("R4_COMPLETED")
        verdicts = {
            item["hypothesis_id"]: item for item in self._r3_verdicts()
        }
        experiment_by_id = {item.experiment_id: item for item in experiments}
        if len(experiment_by_id) != len(experiments):
            raise ModelError("duplicate R5 experiment ID")
        assessment_by_hypothesis = {
            item.hypothesis_id: item for item in assessments
        }
        if len(assessment_by_hypothesis) != len(assessments):
            raise ModelError("duplicate R5 hypothesis assessment")
        if set(assessment_by_hypothesis) != set(verdicts):
            raise ModelError("R5 assessment coverage must match R3 verdict coverage")
        harness_events = (
            self.manager.store.list_events(
                self.campaign_id, event_type="HARNESS_EXECUTION_COMPLETED"
            )
            if any(
                assessment.disposition is R5Disposition.EMPIRICALLY_CONFIRMED
                for assessment in assessments
            )
            else ()
        )
        for experiment in experiments:
            if experiment.hypothesis_id not in verdicts:
                raise ModelError(
                    f"experiment references unknown hypothesis: {experiment.experiment_id}"
                )
        for assessment in assessments:
            experiment = (
                experiment_by_id.get(assessment.experiment_id)
                if assessment.experiment_id
                else None
            )
            if assessment.disposition is R5Disposition.NOT_FEASIBLE:
                if not assessment.experiment_required or assessment.experiment_id is not None:
                    raise ModelError(
                        "NOT_FEASIBLE requires a required experiment and no experiment ID"
                    )
                if any(
                    item.hypothesis_id == assessment.hypothesis_id
                    for item in experiments
                ):
                    raise ModelError(
                        "NOT_FEASIBLE cannot accompany an attempted experiment; "
                        "use NEEDS_REVIEW for an inconclusive run"
                    )
            elif assessment.experiment_required and experiment is None:
                raise ModelError("required R5 experiment is missing")
            if assessment.experiment_id and experiment is None:
                raise ModelError(
                    f"R5 assessment references unknown experiment: {assessment.experiment_id}"
                )
            if experiment and experiment.hypothesis_id != assessment.hypothesis_id:
                raise ModelError("R5 experiment belongs to a different hypothesis")
            if assessment.disposition is R5Disposition.EMPIRICALLY_CONFIRMED:
                if experiment is None or not experiment.supports_empirical_upgrade:
                    raise ModelError(
                        "empirical upgrade requires a confirmed real-target or equivalent experiment"
                    )
                self._validate_empirical_harness_evidence(experiment, harness_events)
            if assessment.disposition is R5Disposition.REFUTED:
                if experiment is None or experiment.result is not ExperimentResult.REFUTED:
                    raise ModelError("R5 REFUTED disposition requires a refuting experiment")
            if (
                assessment.experiment_required
                and experiment is not None
                and experiment.result is ExperimentResult.INCONCLUSIVE
                and assessment.disposition is not R5Disposition.NEEDS_REVIEW
            ):
                raise ModelError(
                    "inconclusive required experiment must result in NEEDS_REVIEW"
                )
        value = {
            "schema_version": "1.0",
            "experiments": [asdict(item) for item in experiments],
            "assessments": [asdict(item) for item in assessments],
        }
        artifact_id = self._put_json(value)
        self.manager.store.append_event(
            campaign_id=self.campaign_id,
            batch_id=self.batch_id,
            entity_type="batch_stage",
            entity_id=self.batch_id,
            event_type="R5_COMPLETED",
            idempotency_key=f"r5:{self.campaign_id}:{self.batch_id}",
            actor="agent",
            payload={
                "experiment_ids": sorted(experiment_by_id),
                "empirically_confirmed": sorted(
                    assessment.hypothesis_id
                    for assessment in assessments
                    if assessment.disposition is R5Disposition.EMPIRICALLY_CONFIRMED
                ),
            },
            payload_ref=artifact_id,
        )
        return artifact_id

    def _validate_empirical_harness_evidence(
        self,
        experiment: Experiment,
        harness_events: Sequence[EventRecord] | None = None,
    ) -> None:
        command_refs = set(experiment.command_refs)
        observation_refs = set(experiment.observation_refs)
        if harness_events is None:
            harness_events = self.manager.store.list_events(
                self.campaign_id, event_type="HARNESS_EXECUTION_COMPLETED"
            )
        for event in harness_events:
            if (
                event.event_type != "HARNESS_EXECUTION_COMPLETED"
                or event.actor != "tool"
                or event.payload_ref not in command_refs
            ):
                continue
            try:
                report = json.loads(self.manager.artifacts.get_bytes(event.payload_ref))
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            if (
                not isinstance(report, dict)
                or report.get("schema_version") != "1.0"
                or report.get("campaign_id") != self.campaign_id
                or report.get("snapshot_id") != self.campaign.snapshot_id
                or report.get("hypothesis_id") != experiment.hypothesis_id
                or not isinstance(report.get("command"), list)
                or not report["command"]
            ):
                continue
            output_refs = {
                str(report.get("stdout_artifact_id", "")),
                str(report.get("stderr_artifact_id", "")),
            }
            if "" in output_refs or not output_refs.issubset(observation_refs):
                continue
            try:
                for reference in output_refs:
                    self.manager.artifacts.get_bytes(reference)
            except (OSError, ValueError):
                continue
            if (
                event.payload.get("snapshot_id") != self.campaign.snapshot_id
                or event.payload.get("hypothesis_id") != experiment.hypothesis_id
                or event.payload.get("stdout_artifact_id") != report["stdout_artifact_id"]
                or event.payload.get("stderr_artifact_id") != report["stderr_artifact_id"]
            ):
                continue
            return
        raise ModelError(
            "empirical upgrade requires a registered harness execution and captured output artifacts"
        )

    def record_finding(self, finding: Finding) -> str:
        self._require_stage("R3_5_COMPLETED")
        hypotheses = {
            item["hypothesis_id"]: item
            for item in self._read_artifact(
                self._require_stage("R2_COMPLETED").payload_ref
            )["hypotheses"]
        }
        if not set(finding.hypothesis_ids).issubset(hypotheses):
            raise ModelError(f"Finding references unknown hypotheses: {finding.finding_id}")
        work_units = {
            str(item["work_unit_id"]): item for item in self._work_units()
        }
        allowed_components = {
            str(item["component_id"]) for item in work_units.values()
        }
        if not set(finding.affected_component_ids).issubset(allowed_components):
            raise ModelError(f"Finding references components outside Batch: {finding.finding_id}")
        families = {
            hypotheses[hypothesis_id]["mechanism"]["family"]
            for hypothesis_id in finding.hypothesis_ids
        }
        if families != {finding.mechanism.family}:
            raise ModelError(f"Finding mechanism family mismatch: {finding.finding_id}")
        adjudicated = {
            event.entity_id: event.payload["final_verdict"]
            for event in self._events(event_type="ADJUDICATION_DECIDED")
        }
        empirically_confirmed: set[str] = set()
        if finding.evidence_grade is EvidenceGrade.EMPIRICALLY_CONFIRMED:
            r5 = self._read_artifact(self._require_stage("R5_COMPLETED").payload_ref)
            empirically_confirmed = {
                str(item["hypothesis_id"])
                for item in r5["assessments"]
                if item["disposition"] == R5Disposition.EMPIRICALLY_CONFIRMED.value
            }
            if not set(finding.hypothesis_ids).issubset(empirically_confirmed):
                raise ModelError(
                    "empirically confirmed Finding requires empirical R5 assessment for every hypothesis"
                )
        if finding.status is FindingStatus.CONFIRMED:
            adjudication_confirms_all = all(
                adjudicated.get(hypothesis_id) == VerdictKind.REACHABLE.value
                for hypothesis_id in finding.hypothesis_ids
            )
            r5_confirms_all = (
                finding.evidence_grade is EvidenceGrade.EMPIRICALLY_CONFIRMED
                and set(finding.hypothesis_ids).issubset(empirically_confirmed)
            )
            if not adjudication_confirms_all and not r5_confirms_all:
                raise ModelError(
                    f"confirmed Finding requires a REACHABLE R3.5 adjudication or "
                    f"empirical R5 confirmation for every hypothesis: {finding.finding_id}"
                )
        artifact_id = self._put_json(asdict(finding))
        self.manager.store.append_event(
            campaign_id=self.campaign_id,
            batch_id=self.batch_id,
            entity_type="finding",
            entity_id=finding.finding_id,
            event_type="FINDING_RECORDED",
            idempotency_key=f"finding:{self.campaign_id}:{finding.finding_id}",
            actor="agent",
            payload={
                "root_cause_key": finding.root_cause_key,
                "status": finding.status.value,
                "severity": finding.severity.value,
            },
            payload_ref=artifact_id,
        )
        return artifact_id

    def close_r6(self, closure: BatchClosure) -> dict[str, Any]:
        required_stages = (
            "R0_COMPLETED",
            "R1_COMPLETED",
            "R2_COMPLETED",
            "R3_COMPLETED",
            "R3_5_COMPLETED",
            "R4_COMPLETED",
            "R5_COMPLETED",
        )
        stage_events = {
            stage: self._stage_event(stage) for stage in required_stages
        }
        gates: dict[str, dict[str, Any]] = {}
        gates["BG1"] = {
            "pass": all(stage_events.values()),
            "detail": "all Work Units reached the R5 closure boundary",
        }
        verdicts = self._r3_verdicts() if stage_events["R3_COMPLETED"] else []
        r5 = (
            self._read_artifact(stage_events["R5_COMPLETED"].payload_ref)
            if stage_events["R5_COMPLETED"]
            else {"assessments": []}
        )
        r1_artifact = (
            self._read_artifact(stage_events["R1_COMPLETED"].payload_ref)
            if stage_events["R1_COMPLETED"]
            else {"surfaces": []}
        )
        surfaces_by_id = {
            str(item["surface_id"]): item for item in r1_artifact["surfaces"]
        }
        supplied_surface_dispositions = {
            item.surface_id: item for item in closure.surface_dispositions
        }
        if len(supplied_surface_dispositions) != len(closure.surface_dispositions):
            raise ModelError("R6 contains duplicate Surface review dispositions")
        unknown_surface_ids = set(supplied_surface_dispositions) - set(surfaces_by_id)
        if unknown_surface_ids:
            raise ModelError(
                f"R6 dispositions reference unknown Surfaces: {sorted(unknown_surface_ids)}"
            )
        surface_review_dispositions = [
            asdict(supplied_surface_dispositions.get(
                surface_id,
                SurfaceReviewDisposition(
                    surface_id=surface_id,
                    state=SurfaceReviewState.UNREVIEWED,
                    evidence_refs=(),
                    rationale="No per-Surface disposition was supplied at Batch closure.",
                ),
            ))
            for surface_id in sorted(surfaces_by_id)
        ]
        surface_review_disposition_counts = {
            state.value: sum(
                item["state"] == state.value for item in surface_review_dispositions
            )
            for state in SurfaceReviewState
        }
        r5_by_hypothesis = {
            str(item["hypothesis_id"]): item for item in r5["assessments"]
        }
        weak_reachable = {
            str(item["hypothesis_id"])
            for item in verdicts
            if item["verdict"] == VerdictKind.REACHABLE.value
            and item["evidence_grade"] == EvidenceGrade.STATIC_ONLY.value
        }
        unresolved_static = sorted(
            hypothesis_id for hypothesis_id in weak_reachable
            if hypothesis_id not in r5_by_hypothesis
            or r5_by_hypothesis[hypothesis_id]["disposition"] not in {
                R5Disposition.STATIC_VERDICT_RETAINED.value,
                R5Disposition.NEEDS_REVIEW.value,
                R5Disposition.NOT_FEASIBLE.value,
                R5Disposition.EMPIRICALLY_CONFIRMED.value,
                R5Disposition.REFUTED.value,
            }
        )
        gates["BG2"] = {
            "pass": not unresolved_static,
            "detail": {
                "static_only_reachable": sorted(weak_reachable),
                "explicitly_dispositioned_by_r5": sorted(weak_reachable - set(unresolved_static)),
                "missing_or_invalid_r5_disposition": unresolved_static,
                "static_only_r5_dispositions": {
                    hypothesis_id: r5_by_hypothesis[hypothesis_id]["disposition"]
                    for hypothesis_id in sorted(weak_reachable)
                    if hypothesis_id in r5_by_hypothesis
                },
            },
        }
        invalid_r5 = [
            item["hypothesis_id"]
            for item in r5["assessments"]
            if item["experiment_required"]
            and item["disposition"]
            not in {
                R5Disposition.EMPIRICALLY_CONFIRMED.value,
                R5Disposition.REFUTED.value,
                R5Disposition.NEEDS_REVIEW.value,
                R5Disposition.NOT_FEASIBLE.value,
            }
        ]
        gates["BG3"] = {
            "pass": not invalid_r5,
            "detail": {"invalid_r5_assessments": invalid_r5},
        }
        r4 = (
            self._read_artifact(stage_events["R4_COMPLETED"].payload_ref)
            if stage_events["R4_COMPLETED"]
            else {"category_runs": []}
        )
        invalid_category_runs = [
            item["category_run_id"]
            for item in r4["category_runs"]
            if item["status"] not in {"COMPLETE", "DEFERRED"}
            or not item["evidence_refs"]
            or not item["rationale"]
        ]
        gates["BG4"] = {
            "pass": not invalid_category_runs and bool(r4["category_runs"]),
            "detail": {"invalid_category_runs": invalid_category_runs},
        }
        plan_id = str(self.batch.manifest.get("plan_id", ""))
        plan = self.manager.load_audit_plan(self.campaign_id, plan_id)
        expected_handoff_ids = {
            handoff.handoff_id for handoff in plan.handoffs
            if self.batch_id in {handoff.from_batch, handoff.owner_batch}
        }
        manifest_handoff_ids = self.batch.manifest.get("handoff_ids")
        actual_handoff_ids = (
            set(manifest_handoff_ids)
            if isinstance(manifest_handoff_ids, list)
            and all(isinstance(item, str) for item in manifest_handoff_ids)
            else set()
        )
        gates["BG5"] = {
            "pass": actual_handoff_ids == expected_handoff_ids
            and len(manifest_handoff_ids) == len(actual_handoff_ids)
            if isinstance(manifest_handoff_ids, list) else False,
            "detail": {
                "expected_handoff_ids": sorted(expected_handoff_ids),
                "actual_handoff_ids": sorted(actual_handoff_ids),
            },
        }
        r35_valid, r35_detail = self._validate_r35_coverage(
            stage_events["R3_5_COMPLETED"], verdicts
        )
        gates["BG6"] = {"pass": r35_valid, "detail": r35_detail}
        drift_events = self._events(event_type="SNAPSHOT_DRIFT")
        resolved_drift_ids = {
            str(event.payload["drift_event_id"])
            for event in self._events(event_type="SNAPSHOT_DRIFT_RESOLVED")
        }
        unresolved_drift = [
            event.event_id
            for event in drift_events
            if event.event_id not in resolved_drift_ids
        ]
        gates["BG7"] = {
            "pass": not unresolved_drift,
            "detail": {"snapshot_drift_events": unresolved_drift},
        }
        deferred_runs = [
            item["category_run_id"]
            for item in r4["category_runs"]
            if item["status"] == "DEFERRED"
        ]
        gates["BG8"] = {
            "pass": bool(closure.budget_used)
            and (not deferred_runs or bool(closure.unreviewed_scope)),
            "detail": {
                "budget_used": dict(closure.budget_used),
                "deferred_category_runs": deferred_runs,
                "unreviewed_scope": list(closure.unreviewed_scope),
            },
        }
        failed = [gate_id for gate_id, gate in gates.items() if not gate["pass"]]
        if failed:
            raise ModelError(f"Batch gates failed: {', '.join(failed)}")

        findings = [
            self._read_artifact(event.payload_ref)
            for event in self._events(event_type="FINDING_RECORDED")
        ]
        report = {
            "schema_version": "1.0",
            "campaign_id": self.campaign_id,
            "batch_id": self.batch_id,
            "snapshot_id": self.campaign.snapshot_id,
            "work_unit_ids": list(self.batch.manifest.get("work_unit_ids", [])),
            "category_run_ids": [
                item["category_run_id"] for item in r4["category_runs"]
            ],
            "findings": findings,
            "surface_review_dispositions": surface_review_dispositions,
            "surface_review_disposition_counts": surface_review_disposition_counts,
            "needs_review_hypothesis_ids": [
                item["hypothesis_id"]
                for item in r5["assessments"]
                if item["disposition"] in {
                    R5Disposition.NEEDS_REVIEW.value,
                    R5Disposition.STATIC_VERDICT_RETAINED.value,
                    R5Disposition.NOT_FEASIBLE.value,
                }
            ],
            "not_feasible_experiment_hypothesis_ids": sorted(
                item["hypothesis_id"]
                for item in r5["assessments"]
                if item["disposition"] == R5Disposition.NOT_FEASIBLE.value
            ),
            "static_only_retained_as_review": sorted(
                weak_reachable
                & {
                    str(item["hypothesis_id"])
                    for item in r5["assessments"]
                    if item["disposition"] == R5Disposition.STATIC_VERDICT_RETAINED.value
                }
            ),
            "static_only_reachable_hypothesis_ids": sorted(weak_reachable),
            "static_only_r5_dispositions": {
                hypothesis_id: r5_by_hypothesis[hypothesis_id]["disposition"]
                for hypothesis_id in sorted(weak_reachable)
                if hypothesis_id in r5_by_hypothesis
            },
            "handoff_ids": list(self.batch.manifest.get("handoff_ids", [])),
            "closure": asdict(closure),
            "gates": gates,
            "status": "PASS",
        }
        artifact_id = self._put_json(report)
        self.manager.store.append_event(
            campaign_id=self.campaign_id,
            batch_id=self.batch_id,
            entity_type="batch_stage",
            entity_id=self.batch_id,
            event_type="R6_COMPLETED",
            idempotency_key=f"r6:{self.campaign_id}:{self.batch_id}:{artifact_id}",
            actor="tool",
            payload={
                "status": "PASS",
                "finding_ids": sorted(item["finding_id"] for item in findings),
            },
            payload_ref=artifact_id,
        )
        batch = self.manager.store.get_batch(self.campaign_id, self.batch_id)
        if batch.status is not BatchStatus.COMPLETE:
            self.manager.store.transition_batch(
                self.campaign_id, self.batch_id, BatchStatus.COMPLETE
            )
        return {**report, "artifact_id": artifact_id}

    def build_transmission_metrics(self) -> dict[str, Any]:
        r2 = self._read_artifact(self._require_stage("R2_COMPLETED").payload_ref)
        r4 = self._read_artifact(self._require_stage("R4_COMPLETED").payload_ref)
        hypotheses_by_axis = {axis.value: 0 for axis in DiscoveryAxis}
        for hypothesis in r2["hypotheses"]:
            hypotheses_by_axis[hypothesis["origin_axis"]] += 1
        discovery_axis_applicability = {
            axis.value: {value.value: 0 for value in Applicability}
            for axis in DiscoveryAxis
        }
        for axis_run in r2.get("axis_runs", []):
            discovery_axis_applicability[axis_run["axis"]][axis_run["applicability"]] += 1
        axis_runs = {axis.value: 0 for axis in DiscoveryAxis}
        axis_applicable = {axis.value: 0 for axis in DiscoveryAxis}
        seed_cards_planned = 0
        plan_event = self._require_stage("CATEGORY_AUDIT_PLAN_RECORDED")
        for plan in self._read_artifact(plan_event.payload_ref)["category_plans"]:
            seed_cards_planned += len(plan["seed_card_ids"])
        linked_finding_ids = set()
        for category_run in r4["category_runs"]:
            linked_finding_ids.update(category_run["finding_ids"])
            for axis_run in category_run["axis_runs"]:
                axis_runs[axis_run["axis"]] += 1
                if axis_run["applicability"] == Applicability.APPLICABLE.value:
                    axis_applicable[axis_run["axis"]] += 1
        total_hypotheses = len(r2["hypotheses"])
        finding_ids = {
            event.entity_id for event in self._events(event_type="FINDING_RECORDED")
        }
        finding_count = len(finding_ids)
        metrics = {
            "schema_version": "1.0",
            "batch_id": self.batch_id,
            "axis_runs": axis_runs,
            "axis_applicable_runs": axis_applicable,
            "discovery_axis_applicability": discovery_axis_applicability,
            "hypotheses_by_axis": hypotheses_by_axis,
            "hypothesis_yield_per_axis_run": {
                axis: (
                    hypotheses_by_axis[axis] / axis_runs[axis]
                    if axis_runs[axis]
                    else None
                )
                for axis in axis_runs
            },
            "seed_cards_planned": seed_cards_planned,
            "hypothesis_count": total_hypotheses,
            "finding_count": finding_count,
            "finding_yield": finding_count / total_hypotheses if total_hypotheses else None,
            "r4_linked_finding_count": len(linked_finding_ids),
            "gate_effect": "NONE",
        }
        artifact_id = self._put_json(metrics)
        self.manager.store.append_event(
            campaign_id=self.campaign_id,
            batch_id=self.batch_id,
            entity_type="capability_metrics",
            entity_id=self.batch_id,
            event_type="TRANSMISSION_METRICS_RECORDED",
            idempotency_key=f"transmission-metrics:{self.campaign_id}:{self.batch_id}:{artifact_id}",
            actor="tool",
            payload={"gate_effect": "NONE"},
            payload_ref=artifact_id,
        )
        return metrics

    def record_r3(self, submissions: Sequence[VerdictSubmission]) -> str:
        r2_event = self._require_stage("R2_COMPLETED")
        hypothesis_ids = {
            item["hypothesis_id"]
            for item in self._read_artifact(r2_event.payload_ref)["hypotheses"]
        }
        submitted_ids = [submission.hypothesis_id for submission in submissions]
        if len(submitted_ids) != len(set(submitted_ids)):
            raise ModelError("R3 contains duplicate hypothesis verdicts")
        if set(submitted_ids) != hypothesis_ids:
            raise ModelError(
                "R3 verdict coverage mismatch: "
                f"expected={sorted(hypothesis_ids)}, actual={sorted(submitted_ids)}"
            )
        verdicts = []
        inventory = self.manager.load_inventory(self.campaign_id)
        inventoried_paths = {
            source.path for source in inventory.source_files
        } | {
            manifest
            for component in inventory.components
            for manifest in component.build_manifests
        }
        line_count_cache: dict[str, tuple[int, frozenset[int]]] = {}
        for submission in sorted(submissions, key=lambda item: item.hypothesis_id):
            for anchor in submission.call_chain:
                self._validate_source_location(
                    anchor, inventoried_paths, line_count_cache=line_count_cache
                )
            for reference in (
                *submission.edge_evidence_ids,
                *submission.blocking_evidence_ids,
            ):
                self._validate_evidence_reference(
                    reference,
                    inventoried_paths,
                    line_count_cache=line_count_cache,
                )
            submission_value = asdict(submission)
            submission_digest = self._put_json(submission_value)
            adjudication = self.manager.store.append_event(
                campaign_id=self.campaign_id,
                batch_id=self.batch_id,
                entity_type="hypothesis",
                entity_id=submission.hypothesis_id,
                event_type="VERDICT_ADJUDICATED",
                idempotency_key=(
                    f"r3-adjudicate:{self.campaign_id}:{self.batch_id}:"
                    f"{submission.hypothesis_id}:{submission_digest}"
                ),
                actor="agent",
                payload=submission_value,
                payload_ref=submission_digest,
            )
            verdicts.append(CanonicalVerdict(
                hypothesis_id=submission.hypothesis_id,
                verdict=submission.verdict,
                evidence_grade=submission.evidence_grade,
                principal=submission.principal,
                preconditions=submission.preconditions,
                call_chain=submission.call_chain,
                edge_evidence_ids=submission.edge_evidence_ids,
                blocking_evidence_ids=submission.blocking_evidence_ids,
                experiment_ids=submission.experiment_ids,
                refutation_ids=(),
                rationale=submission.rationale,
                adjudication_event_id=adjudication.event_id,
            ))
        value = {
            "schema_version": "1.0",
            "verdicts": [asdict(verdict) for verdict in verdicts],
        }
        artifact_id = self._put_json(value)
        self.manager.store.append_event(
            campaign_id=self.campaign_id,
            batch_id=self.batch_id,
            entity_type="batch_stage",
            entity_id=self.batch_id,
            event_type="R3_COMPLETED",
            idempotency_key=f"r3:{self.campaign_id}:{self.batch_id}",
            actor="tool",
            payload={"hypothesis_ids": sorted(hypothesis_ids)},
            payload_ref=artifact_id,
        )
        return artifact_id

    def _validate_evidence_reference(
        self,
        reference: str,
        inventoried_paths: set[str] | None,
        *,
        line_count_cache: dict[str, tuple[int, frozenset[int]]] | None = None,
    ) -> None:
        if reference.startswith("LOC-"):
            self._validate_source_location(
                reference,
                inventoried_paths,
                line_count_cache=line_count_cache,
                allow_evidence_only=True,
            )
            return
        if reference.startswith("sha256:"):
            try:
                self.manager.artifacts.get_bytes(reference)
            except (OSError, ValueError) as error:
                raise ModelError(f"evidence artifact cannot be resolved: {reference}") from error
            return
        raise ModelError(
            f"evidence reference must resolve to a LOC anchor or content-addressed artifact: {reference}"
        )

    def _validate_source_location(
        self,
        reference: str,
        inventoried_paths: set[str] | None,
        *,
        line_count_cache: dict[str, tuple[int, frozenset[int]]] | None = None,
        allow_evidence_only: bool = False,
    ) -> None:
        if not reference.startswith("LOC-"):
            raise ModelError(f"call-chain item must be a source LOC anchor: {reference}")
        path_and_line = reference.removeprefix("LOC-")
        source_path, separator, line_text = path_and_line.rpartition(":")
        relative_path = PurePosixPath(source_path)
        forbidden_evidence_roots = {
            ".audit_vnext", ".audit_results", ".git", ".hg", ".svn",
        }
        if (
            not separator
            or not line_text.isdigit()
            or relative_path.is_absolute()
            or ".." in relative_path.parts
            or (
                allow_evidence_only
                and any(part.casefold() in forbidden_evidence_roots for part in relative_path.parts)
            )
            or (
                not allow_evidence_only
                and not (
                    source_path in inventoried_paths
                    if inventoried_paths is not None
                    else self.manager.store.has_evidence_path(
                        self.campaign_id,
                        source_path,
                        roles=("source", "build_manifest"),
                    )
                )
            )
        ):
            raise ModelError(f"source anchor is not in the Campaign inventory: {reference}")
        resolved_path = (self.manager.target_root / source_path).resolve()
        if (
            not resolved_path.is_relative_to(self.manager.target_root)
            or not resolved_path.is_file()
        ):
            raise ModelError(f"source anchor file is outside the target or missing: {source_path}")
        cache = line_count_cache if line_count_cache is not None else {}
        line_number = int(line_text)
        line_count, nonblank_lines = self._source_line_index(source_path, cache)
        if not 1 <= line_number <= line_count:
            raise ModelError(f"source anchor line is outside the file: {reference}")
        if line_number not in nonblank_lines:
            raise ModelError(f"source anchor points to a blank line: {reference}")

    def build_r0_r3_report(self) -> dict[str, Any]:
        required = ("R0_COMPLETED", "R1_COMPLETED", "R2_COMPLETED", "R3_COMPLETED")
        stage_events = {event_type: self._stage_event(event_type) for event_type in required}
        gates = {
            event_type.removesuffix("_COMPLETED").lower(): event is not None
            for event_type, event in stage_events.items()
        }
        r1 = self._read_artifact(stage_events["R1_COMPLETED"].payload_ref) if gates["r1"] else {"surfaces": []}
        r2 = self._read_artifact(stage_events["R2_COMPLETED"].payload_ref) if gates["r2"] else {"hypotheses": []}
        r3 = self._read_artifact(stage_events["R3_COMPLETED"].payload_ref) if gates["r3"] else {"verdicts": []}
        verdict_counts: dict[str, int] = {}
        for verdict in r3["verdicts"]:
            verdict_counts[verdict["verdict"]] = verdict_counts.get(verdict["verdict"], 0) + 1
        report = {
            "schema_version": "1.0",
            "campaign_id": self.campaign_id,
            "batch_id": self.batch_id,
            "scope": "R0-R3",
            "status": "PASS" if all(gates.values()) else "BLOCKED",
            "gates": gates,
            "surface_count": len(r1["surfaces"]),
            "hypothesis_count": len(r2["hypotheses"]),
            "verdict_counts": verdict_counts,
            "batch_complete": False,
            "limitations": [
                "This R0-R3 slice report is not Batch completion; R3.5-R6 remain required"
            ],
        }
        artifact_id = self._put_json(report)
        self.manager.store.append_event(
            campaign_id=self.campaign_id,
            batch_id=self.batch_id,
            entity_type="batch_report",
            entity_id=self.batch_id,
            event_type="R0_R3_SLICE_REPORTED",
            idempotency_key=f"r0-r3-report:{self.campaign_id}:{self.batch_id}:{artifact_id}",
            actor="tool",
            payload={"status": report["status"]},
            payload_ref=artifact_id,
        )
        return report

    def _work_units(self) -> list[Mapping[str, Any]]:
        value = self.batch.manifest.get("work_units", [])
        return list(value) if isinstance(value, list) else []

    def _events(
        self,
        *,
        event_type: str | None = None,
        event_types: set[str] | frozenset[str] | None = None,
        entity_type: str | None = None,
        entity_id: str | None = None,
    ) -> list[EventRecord]:
        return self.manager.store.list_batch_events(
            self.campaign_id,
            self.batch_id,
            event_type=event_type,
            event_types=event_types,
            entity_type=entity_type,
            entity_id=entity_id,
        )

    def _r3_verdicts(self) -> list[Mapping[str, Any]]:
        event = self._require_stage("R3_COMPLETED")
        return list(self._read_artifact(event.payload_ref)["verdicts"])

    def _validate_r35_coverage(
        self, stage_event: EventRecord | None, verdicts: Sequence[Mapping[str, Any]],
    ) -> tuple[bool, dict[str, Any]]:
        errors = []
        if stage_event is None or stage_event.payload_ref is None:
            return False, {"errors": ["R3_5_COMPLETED artifact is missing"]}
        stage = self._read_artifact(stage_event.payload_ref)
        eligible = {
            str(item["hypothesis_id"])
            for item in verdicts
            if item["verdict"] == VerdictKind.REACHABLE.value
            and item["evidence_grade"] == EvidenceGrade.EDGE_PROVEN.value
        }
        events = self._events(event_types={
            "REFUTATION_SUBMITTED",
            "ADJUDICATION_DECIDED",
            "REVIVAL_SAMPLE_SELECTED",
            "REVIVAL_REVIEWED",
        })
        refutations: dict[str, list[Mapping[str, Any]]] = {}
        for event in events:
            if event.event_type != "REFUTATION_SUBMITTED" or event.payload_ref is None:
                continue
            try:
                item = self._read_artifact(event.payload_ref)
            except (OSError, ValueError, json.JSONDecodeError):
                errors.append(f"unreadable refutation artifact: {event.entity_id}")
                continue
            refutations.setdefault(event.entity_id, []).append(item)
        adjudications = {
            event.entity_id: event for event in events
            if event.event_type == "ADJUDICATION_DECIDED"
        }
        if set(adjudications) != eligible:
            errors.append("adjudication coverage differs from eligible R3 verdicts")
        for hypothesis_id in eligible:
            items = refutations.get(hypothesis_id, [])
            refuter_ids = {str(item.get("refuter_id", "")) for item in items}
            angles = {str(item.get("attack_angle", "")) for item in items}
            if len(refuter_ids) < 2:
                errors.append(f"fewer than two distinct refuter IDs: {hypothesis_id}")
            if "call_chain" not in angles or not angles.intersection({
                "principal", "configuration", "deployment", "impact",
            }):
                errors.append(f"required refutation perspectives missing: {hypothesis_id}")
            adjudication = adjudications.get(hypothesis_id)
            expected_refutation_ids = {str(item.get("refutation_id", "")) for item in items}
            if adjudication is None or set(adjudication.payload.get("refutation_ids", [])) != expected_refutation_ids:
                errors.append(f"adjudication does not cover submitted refutations: {hypothesis_id}")
        reported_adjudications = set(stage.get("adjudicated_hypothesis_ids", []))
        if reported_adjudications != set(adjudications):
            errors.append("R3.5 artifact adjudication summary does not match events")

        selection = next((
            event for event in events if event.event_type == "REVIVAL_SAMPLE_SELECTED"
        ), None)
        selected = set()
        if selection is None or selection.payload_ref is None:
            errors.append("revival selection artifact is missing")
        else:
            selected = set(self._read_artifact(selection.payload_ref).get("hypothesis_ids", []))
        reviewed = {
            event.entity_id for event in events if event.event_type == "REVIVAL_REVIEWED"
        }
        reported_revived = set(stage.get("revived_hypothesis_ids", []))
        if selected != reviewed or reported_revived != reviewed:
            errors.append("R3.5 revival selection, review events, and summary differ")
        return not errors, {
            "eligible_hypothesis_ids": sorted(eligible),
            "adjudicated_hypothesis_ids": sorted(adjudications),
            "refutation_counts": {
                hypothesis_id: len(refutations.get(hypothesis_id, []))
                for hypothesis_id in sorted(eligible)
            },
            "revival_selected_ids": sorted(selected),
            "revival_reviewed_ids": sorted(reviewed),
            "errors": errors,
        }

    def _refutation_target(
        self, hypothesis_id: str
    ) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
        r2_event = self._require_stage("R2_COMPLETED")
        hypotheses = {
            item["hypothesis_id"]: item
            for item in self._read_artifact(r2_event.payload_ref)["hypotheses"]
        }
        verdicts = {
            item["hypothesis_id"]: item for item in self._r3_verdicts()
        }
        hypothesis = hypotheses.get(hypothesis_id)
        verdict = verdicts.get(hypothesis_id)
        if hypothesis is None or verdict is None:
            raise ModelError(f"unknown R3 hypothesis: {hypothesis_id}")
        if verdict["verdict"] != VerdictKind.REACHABLE.value or verdict[
            "evidence_grade"
        ] != EvidenceGrade.EDGE_PROVEN.value:
            raise ModelError(
                f"refutation requires REACHABLE edge-proven hypothesis: {hypothesis_id}"
            )
        return hypothesis, verdict

    def _stage_event(self, event_type: str) -> EventRecord | None:
        events = self._events(event_type=event_type)
        return events[-1] if events else None

    def _require_stage(self, event_type: str) -> EventRecord:
        event = self._stage_event(event_type)
        if event is None:
            raise ModelError(f"required Batch stage is missing: {event_type}")
        return event

    def _put_json(self, value: Any) -> str:
        encoded = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
        )
        return self.manager.artifacts.put_text(encoded).artifact_id

    def _read_artifact(self, artifact_id: str | None) -> Any:
        if artifact_id is None:
            raise ModelError("stage event is missing its artifact")
        return json.loads(self.manager.artifacts.get_bytes(artifact_id))