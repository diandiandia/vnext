"""Campaign service boundary and portable JSON exports."""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Any, Mapping
import uuid

from .artifacts import ArtifactStore
from .models import BatchRecord, BatchStatus, CampaignAuditMode, CampaignRecord
from .analysis_models import SkillIssue, SkillIssueStatus
from .plan_models import AuditPlan, ComponentGraph, PlanAmendment, ProjectInventory
from .planning import (
    batch_manifest,
    inventory_digest,
    validate_plan,
    validate_plan_amendment,
)
from .store import AuditStore


class SnapshotError(RuntimeError):
    """Raised when the target cannot be assigned a stable snapshot."""


def detect_clean_git_snapshot(target_root: str | Path) -> str:
    root = Path(target_root).resolve()
    try:
        commit = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as error:
        raise SnapshotError(
            "target is not a readable Git worktree; provide --snapshot-id explicitly"
        ) from error
    if dirty:
        raise SnapshotError(
            "target Git worktree is dirty; freeze it or provide an explicit snapshot ID"
        )
    return f"git:{commit}"


class CampaignManager:
    def __init__(self, target_root: str | Path, state_dir: str | Path = ".audit_vnext") -> None:
        self.target_root = Path(target_root).resolve()
        if not self.target_root.is_dir():
            raise ValueError(f"target root is not a directory: {self.target_root}")
        state_path = Path(state_dir)
        self.state_dir = (
            state_path if state_path.is_absolute() else self.target_root / state_path
        )
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.store = AuditStore(self.state_dir / "state.db")
        self.artifacts = ArtifactStore(self.state_dir / "artifacts")

    def close(self) -> None:
        self.store.close()

    def __enter__(self) -> "CampaignManager":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def create_campaign(
        self,
        *,
        snapshot_id: str,
        budget: Mapping[str, Any] | None = None,
        constraints: list[str] | tuple[str, ...] | None = None,
        campaign_id: str | None = None,
        audit_mode: CampaignAuditMode = CampaignAuditMode.FRESH,
        history_source_campaign_ids: tuple[str, ...] = (),
    ) -> CampaignRecord:
        identifier = campaign_id or f"CMP-{uuid.uuid4().hex}"
        if len(history_source_campaign_ids) != len(set(history_source_campaign_ids)):
            raise ValueError("history source Campaign IDs must be unique")
        if audit_mode is CampaignAuditMode.FRESH and history_source_campaign_ids:
            raise ValueError("fresh Campaigns cannot declare historical Campaign sources")
        if audit_mode is CampaignAuditMode.FOLLOW_UP and not history_source_campaign_ids:
            raise ValueError("follow-up Campaigns require explicit history sources")
        if audit_mode is CampaignAuditMode.LEGACY:
            raise ValueError("legacy is reserved for migrated Campaign records")
        for source_id in history_source_campaign_ids:
            source = self.store.get_campaign(source_id)
            if source.target_root != str(self.target_root):
                raise ValueError("history sources must belong to the same target")
        record = self.store.create_campaign(
            campaign_id=identifier,
            target_root=str(self.target_root),
            snapshot_id=snapshot_id,
            budget=budget,
            constraints=constraints,
            audit_mode=audit_mode,
            history_source_campaign_ids=history_source_campaign_ids,
        )
        self._write_campaign_export(record)
        self._record_skill_regression_baseline(
            record.campaign_id,
            source_campaign_ids=(
                record.history_source_campaign_ids
                if record.audit_mode is CampaignAuditMode.FOLLOW_UP
                else ()
            ),
        )
        return record

    def record_skill_review(
        self, campaign_id: str, issues: tuple[SkillIssue, ...]
    ) -> str:
        self.store.get_campaign(campaign_id)
        issue_ids = [issue.issue_id for issue in issues]
        if len(issue_ids) != len(set(issue_ids)):
            raise ValueError("skill review contains duplicate issue IDs")
        value = {
            "schema_version": "1.0",
            "campaign_id": campaign_id,
            "issues": [asdict(issue) for issue in issues],
        }
        encoded = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        artifact = self.artifacts.put_text(encoded)
        for issue in issues:
            issue_value = asdict(issue)
            issue_artifact = self.artifacts.put_text(json.dumps(
                issue_value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ))
            self.store.append_event(
                campaign_id=campaign_id,
                batch_id=None,
                entity_type="skill_issue",
                entity_id=issue.issue_id,
                event_type="SKILL_ISSUE_RECORDED",
                idempotency_key=(
                    f"skill-issue:{campaign_id}:{issue.issue_id}:"
                    f"{issue_artifact.artifact_id}"
                ),
                actor="agent",
                payload={"kind": issue.kind.value, "status": issue.status.value},
                payload_ref=issue_artifact.artifact_id,
            )
        self.store.append_event(
            campaign_id=campaign_id,
            batch_id=None,
            entity_type="skill_review",
            entity_id=campaign_id,
            event_type="SKILL_REVIEW_COMPLETED",
            idempotency_key=f"skill-review:{campaign_id}:{artifact.artifact_id}",
            actor="agent",
            payload={"issue_ids": sorted(issue_ids)},
            payload_ref=artifact.artifact_id,
        )
        self._write_campaign_skill_issues(campaign_id, issues)
        self._write_skill_regression_exports()
        return artifact.artifact_id

    def abort_campaign(
        self,
        campaign_id: str,
        *,
        reason: str,
        skill_issues: tuple[SkillIssue, ...],
    ) -> dict[str, Any]:
        from .resource_cleanup import cleanup_campaign_resources

        if not reason.strip():
            raise ValueError("Campaign abort requires a reason")
        campaign = self.store.get_campaign(campaign_id)
        if campaign.status.value == "COMPLETE":
            raise ValueError("completed Campaign cannot be aborted")
        skill_review_artifact_id = self.record_skill_review(campaign_id, skill_issues)
        artifact = self.artifacts.put_text(json.dumps({
            "schema_version": "1.0",
            "campaign_id": campaign_id,
            "reason": reason,
            "skill_review_artifact_id": skill_review_artifact_id,
        }, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        self.store.append_event(
            campaign_id=campaign_id,
            batch_id=None,
            entity_type="campaign_lifecycle",
            entity_id=campaign_id,
            event_type="CAMPAIGN_ABORTED",
            idempotency_key=f"campaign-abort:{campaign_id}:{artifact.artifact_id}",
            actor="user",
            payload={"reason": reason, "skill_review_artifact_id": skill_review_artifact_id},
            payload_ref=artifact.artifact_id,
        )
        campaign = self.store.get_campaign(campaign_id)
        if campaign.status.value != "BLOCKED":
            self.store.transition_campaign(campaign_id, type(campaign.status).BLOCKED)
        cleanup_error = None
        try:
            cleanup = cleanup_campaign_resources(self, campaign_id)
        except Exception as error:
            cleanup = {"failures": [], "error": str(error)}
            cleanup_error = str(error)
        report = {
            "schema_version": "1.0",
            "campaign_id": campaign_id,
            "snapshot_id": campaign.snapshot_id,
            "status": "ABORTED",
            "reason": reason,
            "skill_review_artifact_id": skill_review_artifact_id,
            "resource_cleanup": cleanup,
            "cleanup_error": cleanup_error,
        }
        self._atomic_json(
            self.state_dir / "campaigns" / campaign_id / "abort-report.json", report
        )
        self.write_campaign_closure_lessons(
            campaign_id,
            unreviewed_scope=(reason,),
            residual_risks=(reason,),
            lessons=("Campaign was explicitly aborted by an operator.",),
        )
        if cleanup_error is not None:
            raise ValueError(f"Campaign aborted but resource cleanup failed: {cleanup_error}")
        return report

    def write_campaign_closure_lessons(
        self,
        campaign_id: str,
        *,
        unreviewed_scope: tuple[str, ...] = (),
        residual_risks: tuple[str, ...] = (),
        limitations: tuple[str, ...] = (),
        lessons: tuple[str, ...] = (),
        knowledge_nominations: tuple[str, ...] = (),
    ) -> None:
        sections = {
            "Unreviewed scope": unreviewed_scope,
            "Residual risks": residual_risks,
            "Limitations": limitations,
            "Lessons": lessons,
            "Knowledge nominations": knowledge_nominations,
        }
        lines = [f"## Campaign closure: {campaign_id}"]
        for title, values in sections.items():
            lines.extend(("", f"### {title}"))
            lines.extend(f"- {value}" for value in values)
            if not values:
                lines.append("- None recorded.")
        section = "\n".join(lines).rstrip()
        digest = hashlib.sha256(section.encode("utf-8")).hexdigest()
        marker = f"<!-- vnext-closure-lessons:sha256:{digest} -->"
        path = self.state_dir / "campaigns" / campaign_id / "lessons.md"
        existing = path.read_text(encoding="utf-8") if path.is_file() else ""
        if marker in existing:
            return
        prefix = existing.rstrip()
        content = f"{prefix}\n\n" if prefix else ""
        self._atomic_text(path, f"{content}{marker}\n{section}\n")

    def _write_campaign_skill_issues(
        self, campaign_id: str, issues: tuple[SkillIssue, ...]
    ) -> None:
        lines = [
            "# Campaign Skill Issues",
            "",
            f"Campaign: `{campaign_id}`",
            "",
        ]
        if not issues:
            lines.append("Skill review completed; no skill issues were reported.")
        for issue in issues:
            lines.extend((
                f"## {issue.issue_id}: {issue.summary.replace(chr(10), ' ')}",
                "",
                f"- Kind: `{issue.kind.value}`",
                f"- Stage: `{issue.stage}`",
                f"- Evidence: {', '.join(issue.evidence_refs)}",
                f"- Regression expectation: {issue.regression_expectation.replace(chr(10), ' ')}",
                f"- Status: `{issue.status.value}`",
                "",
            ))
        section = "\n".join(lines).rstrip()
        digest = hashlib.sha256(section.encode("utf-8")).hexdigest()
        marker = f"<!-- vnext-skill-issues:sha256:{digest} -->"
        path = self.state_dir / "campaigns" / campaign_id / "skill-issues.md"
        existing = path.read_text(encoding="utf-8") if path.is_file() else ""
        if marker not in existing:
            separator = "\n\n" if existing and not existing.endswith("\n\n") else ""
            self._atomic_text(path, f"{existing}{separator}{marker}\n{section}\n")

    def load_skill_regression_backlog(
        self, source_campaign_ids: tuple[str, ...] | None = None
    ) -> tuple[dict[str, Any], ...]:
        latest: dict[str, tuple[int, dict[str, Any]]] = {}
        for campaign in self.store.list_campaigns():
            if source_campaign_ids is not None and campaign.campaign_id not in source_campaign_ids:
                continue
            for event in self.store.list_events(campaign.campaign_id):
                if event.event_type != "SKILL_ISSUE_RECORDED" or not event.payload_ref:
                    continue
                value = json.loads(self.artifacts.get_bytes(event.payload_ref))
                if not isinstance(value, dict):
                    raise ValueError("skill issue artifact must be a JSON object")
                previous = latest.get(event.entity_id)
                if previous is None or event.sequence > previous[0]:
                    latest[event.entity_id] = (
                        event.sequence,
                        {**value, "source_campaign_id": campaign.campaign_id},
                    )
        return tuple(
            value
            for _, value in sorted(latest.values(), key=lambda item: item[1]["issue_id"])
            if value["status"] == SkillIssueStatus.REGRESSION_PENDING.value
        )

    def _record_skill_regression_baseline(
        self, campaign_id: str, *, source_campaign_ids: tuple[str, ...]
    ) -> None:
        backlog = self.load_skill_regression_backlog(source_campaign_ids)
        value = {"schema_version": "1.0", "issues": list(backlog)}
        artifact = self.artifacts.put_text(json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ))
        self.store.append_event(
            campaign_id=campaign_id,
            batch_id=None,
            entity_type="skill_regression_baseline",
            entity_id=campaign_id,
            event_type="SKILL_REGRESSION_BASELINE_RECORDED",
            idempotency_key=f"skill-regression-baseline:{campaign_id}",
            actor="tool",
            payload={"pending_issue_ids": sorted(item["issue_id"] for item in backlog)},
            payload_ref=artifact.artifact_id,
        )

    def _write_skill_regression_exports(self) -> None:
        pending = self.load_skill_regression_backlog()
        self._atomic_json(
            self.state_dir / "skill-regression.json",
            {"schema_version": "1.0", "pending_issues": list(pending)},
        )
        lines = ["# Audit Skill Regression Ledger", ""]
        if not pending:
            lines.append("No pending skill issues.")
        for issue in pending:
            lines.extend((
                f"## {issue['issue_id']}: {issue['summary']}",
                "",
                f"- Kind: `{issue['kind']}`",
                f"- Stage: `{issue['stage']}`",
                f"- Source Campaign: `{issue['source_campaign_id']}`",
                f"- Evidence: {', '.join(issue['evidence_refs'])}",
                f"- Regression expectation: {issue['regression_expectation']}",
                f"- Status: `{issue['status']}`",
                "",
            ))
        self._atomic_text(self.state_dir / "skill-regression.md", "\n".join(lines))

    def add_batch(
        self,
        *,
        campaign_id: str,
        batch_id: str,
        manifest: Mapping[str, Any],
    ) -> BatchRecord:
        record = self.store.add_batch(
            campaign_id=campaign_id, batch_id=batch_id, manifest=manifest
        )
        self._write_batch_export(record)
        return record

    def record_inventory(self, *, campaign_id: str, inventory: ProjectInventory) -> str:
        campaign = self.store.get_campaign(campaign_id)
        if inventory.snapshot_id != campaign.snapshot_id:
            raise ValueError(
                f"inventory snapshot does not match Campaign: {inventory.snapshot_id} != {campaign.snapshot_id}"
            )
        value = asdict(inventory)
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        baseline = {
            "schema_version": "1.0",
            "snapshot_id": inventory.snapshot_id,
            "repository_size_bytes": inventory.repository_size_bytes,
            "files": {
                source.path: self._file_digest(self.target_root / source.path)
                for source in inventory.source_files
            },
        }
        baseline_encoded = json.dumps(
            baseline, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        existing_inventories = self.store.list_events(
            campaign_id,
            entity_type="campaign",
            entity_id=campaign_id,
            event_type="INVENTORY_RECORDED",
        )
        if existing_inventories:
            existing = existing_inventories[-1]
            if (
                existing.payload_ref is None
                or self.artifacts.get_bytes(existing.payload_ref) != encoded.encode("utf-8")
            ):
                raise ValueError(
                    "Campaign inventory is write-once; changed source scope requires a new Campaign"
                )
        existing_baselines = self.store.list_events(
            campaign_id,
            entity_type="snapshot_baseline",
            entity_id=campaign_id,
            event_type="SNAPSHOT_BASELINE_RECORDED",
        )
        if existing_baselines:
            existing = existing_baselines[-1]
            if (
                existing.payload_ref is None
                or self.artifacts.get_bytes(existing.payload_ref)
                != baseline_encoded.encode("utf-8")
            ):
                raise ValueError(
                    "Campaign snapshot baseline is write-once; changed source content requires a new Campaign"
                )
        elif existing_inventories:
            raise ValueError(
                "Campaign inventory exists without a durable snapshot baseline; create a new Campaign"
            )
        self.store.record_evidence_paths(
            campaign_id,
            tuple(
                (source.path, "source", source.component_id)
                for source in inventory.source_files
            ) + tuple(
                (manifest, "build_manifest", component.component_id)
                for component in inventory.components
                for manifest in component.build_manifests
            ),
        )
        artifact = self.artifacts.put_text(encoded)
        self.store.append_event(
            campaign_id=campaign_id,
            batch_id=None,
            entity_type="campaign",
            entity_id=campaign_id,
            event_type="INVENTORY_RECORDED",
            idempotency_key=f"inventory:{campaign_id}:{artifact.artifact_id}",
            actor="tool",
            payload={"components": len(inventory.components), "source_files": len(inventory.source_files)},
            payload_ref=artifact.artifact_id,
        )
        baseline_artifact = self.artifacts.put_text(baseline_encoded)
        self.store.append_event(
            campaign_id=campaign_id,
            batch_id=None,
            entity_type="snapshot_baseline",
            entity_id=campaign_id,
            event_type="SNAPSHOT_BASELINE_RECORDED",
            idempotency_key=(
                f"snapshot-baseline:{campaign_id}:{baseline_artifact.artifact_id}"
            ),
            actor="tool",
            payload={
                "files": len(baseline["files"]),
                "repository_size_bytes": inventory.repository_size_bytes,
            },
            payload_ref=baseline_artifact.artifact_id,
        )
        self._atomic_json(
            self.state_dir / "campaigns" / campaign_id / "inventory.json", value
        )
        self._atomic_json(
            self.state_dir / "campaigns" / campaign_id / "snapshot-baseline.json",
            baseline,
        )
        return artifact.artifact_id

    def record_plan(
        self, *, campaign_id: str, plan: AuditPlan, inventory: ProjectInventory
    ) -> str:
        return self._record_plan(
            campaign_id=campaign_id,
            plan=plan,
            inventory=inventory,
            replacing_plan_id=None,
        )

    def _record_plan(
        self,
        *,
        campaign_id: str,
        plan: AuditPlan,
        inventory: ProjectInventory,
        replacing_plan_id: str | None,
    ) -> str:
        campaign = self.store.get_campaign(campaign_id)
        if plan.campaign_id != campaign_id:
            raise ValueError(f"plan Campaign mismatch: {plan.campaign_id} != {campaign_id}")
        if plan.snapshot_id != campaign.snapshot_id:
            raise ValueError(f"plan snapshot mismatch: {plan.snapshot_id} != {campaign.snapshot_id}")
        inventory_events = self.store.list_events(
            campaign_id,
            entity_type="campaign",
            entity_id=campaign_id,
            event_type="INVENTORY_RECORDED",
        )
        if not inventory_events or inventory_events[-1].payload_ref is None:
            raise ValueError("Campaign inventory must be recorded before its Plan")
        recorded_inventory = ProjectInventory.from_dict(json.loads(
            self.artifacts.get_bytes(inventory_events[-1].payload_ref)
        ))
        if inventory_digest(inventory) != inventory_digest(recorded_inventory):
            raise ValueError("Plan inventory does not match the durable Campaign inventory")
        validate_plan(plan, inventory)
        value = asdict(plan)
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        prior_plans = self.store.list_events(
            campaign_id, entity_type="plan", event_type="PLAN_RECORDED",
        )
        if prior_plans:
            latest = prior_plans[-1]
            if latest.entity_id == plan.plan_id:
                if (
                    latest.payload_ref is None
                    or self.artifacts.get_bytes(latest.payload_ref) != encoded.encode("utf-8")
                ):
                    raise ValueError("recorded Plan ID conflicts with its durable content")
            elif latest.entity_id != replacing_plan_id:
                raise ValueError(
                    "Plan replacement requires a Plan Amendment based on the latest Plan"
                )
        elif replacing_plan_id is not None:
            raise ValueError("Plan Amendment base Plan is not recorded")
        artifact = self.artifacts.put_text(encoded)
        self.store.append_event(
            campaign_id=campaign_id,
            batch_id=None,
            entity_type="plan",
            entity_id=plan.plan_id,
            event_type="PLAN_RECORDED",
            idempotency_key=f"plan:{campaign_id}:{plan.plan_id}:{artifact.artifact_id}",
            actor="tool",
            payload={
                "batches": len(plan.batches),
                "work_units": len(plan.work_units),
                "handoffs": len(plan.handoffs),
            },
            payload_ref=artifact.artifact_id,
        )
        for batch in plan.batches:
            self.add_batch(
                campaign_id=campaign_id,
                batch_id=batch.batch_id,
                manifest=batch_manifest(plan, batch),
            )
        self._atomic_json(
            self.state_dir / "campaigns" / campaign_id / "plans" / f"{plan.plan_id}.json",
            value,
        )
        return artifact.artifact_id

    def record_component_graph(
        self, *, campaign_id: str, graph: ComponentGraph
    ) -> str:
        campaign = self.store.get_campaign(campaign_id)
        if graph.snapshot_id != campaign.snapshot_id:
            raise ValueError(
                f"component graph snapshot mismatch: {graph.snapshot_id} != {campaign.snapshot_id}"
            )
        value = asdict(graph)
        encoded = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        artifact = self.artifacts.put_text(encoded)
        self.store.append_event(
            campaign_id=campaign_id,
            batch_id=None,
            entity_type="component_graph",
            entity_id=campaign_id,
            event_type="COMPONENT_GRAPH_RECORDED",
            idempotency_key=f"component-graph:{campaign_id}:{artifact.artifact_id}",
            actor="tool",
            payload={
                "build_units": len(graph.build_units),
                "edges": len(graph.edges),
                "diagnostics": len(graph.diagnostics),
            },
            payload_ref=artifact.artifact_id,
        )
        self._atomic_json(
            self.state_dir / "campaigns" / campaign_id / "component_graph.json", value
        )
        return artifact.artifact_id

    def record_plan_amendment(
        self,
        *,
        campaign_id: str,
        base_plan: AuditPlan,
        amended_plan: AuditPlan,
        amendment: PlanAmendment,
        inventory: ProjectInventory,
    ) -> str:
        if amendment.campaign_id != campaign_id:
            raise ValueError("Plan Amendment Campaign mismatch")
        if amendment.base_plan_id != base_plan.plan_id:
            raise ValueError("Plan Amendment base plan mismatch")
        if amendment.amended_plan_id != amended_plan.plan_id:
            raise ValueError("Plan Amendment result plan mismatch")
        validate_plan(base_plan, inventory)
        validate_plan(amended_plan, inventory)
        base_plan_events = self.store.list_events(
            campaign_id,
            entity_type="plan",
            entity_id=base_plan.plan_id,
            event_type="PLAN_RECORDED",
        )
        if not base_plan_events or base_plan_events[-1].payload_ref is None:
            raise ValueError("Plan Amendment base Plan artifact is missing")
        durable_base_plan = json.loads(
            self.artifacts.get_bytes(base_plan_events[-1].payload_ref)
        )
        supplied_base_plan = json.loads(json.dumps(
            asdict(base_plan),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ))
        if durable_base_plan != supplied_base_plan:
            raise ValueError("Plan Amendment base Plan differs from its durable artifact")
        validate_plan_amendment(base_plan, amended_plan, amendment)
        existing_amendments = self.store.list_events(
            campaign_id,
            entity_type="plan_amendment",
            entity_id=amendment.amendment_id,
            event_type="PLAN_AMENDED",
        )
        amendment_value = asdict(amendment)
        amendment_json = json.dumps(
            amendment_value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        if existing_amendments:
            existing = existing_amendments[-1]
            if (
                existing.payload_ref is None
                or existing.payload.get("base_plan_id") != amendment.base_plan_id
                or existing.payload.get("amended_plan_id") != amendment.amended_plan_id
                or json.loads(self.artifacts.get_bytes(existing.payload_ref))
                != json.loads(amendment_json)
            ):
                raise ValueError("Plan Amendment ID conflicts with its recorded content")
            self._atomic_json(
                self.state_dir
                / "campaigns"
                / campaign_id
                / "amendments"
                / f"{amendment.amendment_id}.json",
                amendment_value,
            )
            return existing.payload_ref
        plan_events = self.store.list_events(
            campaign_id, entity_type="plan", event_type="PLAN_RECORDED",
        )
        if not plan_events:
            raise ValueError("Plan Amendment base is not the latest recorded Plan")
        latest_plan = plan_events[-1]
        if latest_plan.entity_id == amended_plan.plan_id:
            expected_plan = json.loads(json.dumps(
                asdict(amended_plan),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ))
            if (
                latest_plan.payload_ref is None
                or json.loads(self.artifacts.get_bytes(latest_plan.payload_ref))
                != expected_plan
            ):
                raise ValueError(
                    "latest Plan content conflicts with the requested Amendment"
                )
        elif latest_plan.entity_id != base_plan.plan_id:
            raise ValueError("Plan Amendment base is not the latest recorded Plan")
        mutable_statuses = {BatchStatus.PLANNED, BatchStatus.DEFERRED}
        base_batches = [
            self.store.get_batch(campaign_id, batch.batch_id)
            for batch in base_plan.batches
        ]
        immutable = [
            batch.batch_id for batch in base_batches if batch.status not in mutable_statuses
        ]
        if immutable:
            raise ValueError(
                "cannot amend a plan with scheduled or executed batches: "
                + ", ".join(sorted(immutable))
            )

        self._record_plan(
            campaign_id=campaign_id,
            plan=amended_plan,
            inventory=inventory,
            replacing_plan_id=base_plan.plan_id,
        )
        for batch in base_batches:
            if batch.status is BatchStatus.PLANNED:
                self.store.transition_batch(
                    campaign_id, batch.batch_id, BatchStatus.DEFERRED
                )
        artifact = self.artifacts.put_text(amendment_json)
        self.store.append_event(
            campaign_id=campaign_id,
            batch_id=None,
            entity_type="plan_amendment",
            entity_id=amendment.amendment_id,
            event_type="PLAN_AMENDED",
            idempotency_key=f"plan-amendment:{campaign_id}:{amendment.amendment_id}",
            actor="tool",
            payload={
                "base_plan_id": amendment.base_plan_id,
                "amended_plan_id": amendment.amended_plan_id,
                "retired_batches": len(amendment.batch_replacements),
            },
            payload_ref=artifact.artifact_id,
        )
        self._atomic_json(
            self.state_dir
            / "campaigns"
            / campaign_id
            / "amendments"
            / f"{amendment.amendment_id}.json",
            amendment_value,
        )
        return artifact.artifact_id

    def load_inventory(self, campaign_id: str) -> ProjectInventory:
        campaign = self.store.get_campaign(campaign_id)
        events = self.store.list_events(
            campaign_id,
            entity_type="campaign",
            entity_id=campaign_id,
            event_type="INVENTORY_RECORDED",
        )
        if not events or events[-1].payload_ref is None:
            raise ValueError("Campaign inventory is missing; run the inventory command first")
        value = json.loads(self.artifacts.get_bytes(events[-1].payload_ref))
        if not isinstance(value, dict):
            raise ValueError("Campaign inventory artifact must be a JSON object")
        inventory = ProjectInventory.from_dict(value)
        if inventory.snapshot_id != campaign.snapshot_id:
            raise ValueError("recorded inventory does not match the Campaign snapshot")
        path = self.state_dir / "campaigns" / campaign_id / "inventory.json"
        exported = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        if not path.exists() or path.read_text(encoding="utf-8") != exported:
            self._atomic_json(path, value)
        return inventory

    def load_component_graph(self, campaign_id: str) -> ComponentGraph:
        campaign = self.store.get_campaign(campaign_id)
        events = self.store.list_events(
            campaign_id,
            entity_type="component_graph",
            entity_id=campaign_id,
            event_type="COMPONENT_GRAPH_RECORDED",
        )
        if not events or events[-1].payload_ref is None:
            raise ValueError("Campaign component graph is missing; run the graph command first")
        value = json.loads(self.artifacts.get_bytes(events[-1].payload_ref))
        if not isinstance(value, dict):
            raise ValueError("Campaign component graph artifact must be a JSON object")
        graph = ComponentGraph.from_dict(value)
        if graph.snapshot_id != campaign.snapshot_id:
            raise ValueError("recorded component graph does not match the Campaign snapshot")
        path = self.state_dir / "campaigns" / campaign_id / "component_graph.json"
        exported = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        if not path.exists() or path.read_text(encoding="utf-8") != exported:
            self._atomic_json(path, value)
        return graph

    def load_audit_plan(self, campaign_id: str, plan_id: str) -> AuditPlan:
        campaign = self.store.get_campaign(campaign_id)
        path = (
            self.state_dir / "campaigns" / campaign_id / "plans" / f"{plan_id}.json"
        )
        if not path.exists():
            raise ValueError(f"Campaign plan is missing: {plan_id}")
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("Campaign plan must be a JSON object")
        plan = AuditPlan.from_dict(value)
        if plan.campaign_id != campaign_id or plan.snapshot_id != campaign.snapshot_id:
            raise ValueError("stored plan does not match the Campaign")
        return plan

    def load_snapshot_baseline(self, campaign_id: str) -> Mapping[str, Any]:
        campaign = self.store.get_campaign(campaign_id)
        path = (
            self.state_dir
            / "campaigns"
            / campaign_id
            / "snapshot-baseline.json"
        )
        if not path.exists():
            raise ValueError("Campaign snapshot baseline is missing; record inventory first")
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or value.get("snapshot_id") != campaign.snapshot_id:
            raise ValueError("stored snapshot baseline does not match the Campaign")
        return value

    def write_campaign_report_exports(
        self, campaign_id: str, report: Mapping[str, Any], markdown: str
    ) -> None:
        export_root = self.state_dir / "campaigns" / campaign_id / "report"
        self._atomic_json(export_root / "report.json", report)
        self._atomic_text(export_root / "report.md", markdown)

    def _write_campaign_export(self, record: CampaignRecord) -> None:
        portable = asdict(record)
        portable["status"] = record.status.value
        portable["target_root"] = "<runtime-only>"
        self._atomic_json(self.state_dir / "campaign.json", portable)

    def _write_batch_export(self, record: BatchRecord) -> None:
        portable = asdict(record)
        portable["status"] = record.status.value
        path = self.state_dir / "batches" / record.batch_id / "manifest.json"
        self._atomic_json(path, portable)

    @staticmethod
    def _file_digest(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(value, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    @staticmethod
    def _atomic_text(path: Path, value: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(value)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
