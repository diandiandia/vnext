"""Campaign service boundary and portable JSON exports."""

from __future__ import annotations

from dataclasses import asdict
import datetime as dt
import hashlib
import hmac
import json
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Any, Mapping
import uuid

from .artifacts import ArtifactStore
from .models import (
    AppendResult,
    BatchRecord,
    BatchStatus,
    CampaignAuditMode,
    CampaignRecord,
    CampaignStatus,
)
from .analysis_models import ExternalObservation, SkillIssue, SkillIssueStatus
from .plan_models import AuditPlan, ComponentGraph, PlanAmendment, ProjectInventory
from .planning import (
    batch_manifest,
    inventory_digest,
    validate_boundary_edge_endpoints,
    validate_inventory,
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

    def effective_wall_limit_seconds(self, campaign_id: str) -> int | None:
        return self.store.effective_wall_limit_seconds(campaign_id)

    def authorize_expired_task_recovery(
        self,
        campaign_id: str,
        *,
        task_id: str,
        worker_id: str,
        attempt: int,
        output_ref: str,
        lease_expires_at: str,
        reason: str,
        evidence_refs: tuple[str, ...],
        actor: str = "operator",
        now: str | None = None,
    ) -> AppendResult:
        if not evidence_refs or isinstance(evidence_refs, (str, bytes)):
            raise ValueError("expired-lease recovery requires evidence references")
        self.artifacts.get_bytes(output_ref)
        for evidence_ref in evidence_refs:
            self.artifacts.get_bytes(evidence_ref)
        return self.store.authorize_expired_task_recovery(
            campaign_id=campaign_id,
            task_id=task_id,
            worker_id=worker_id,
            attempt=attempt,
            output_ref=output_ref,
            lease_expires_at=lease_expires_at,
            actor=actor,
            reason=reason,
            evidence_refs=evidence_refs,
            now=now or dt.datetime.now(dt.UTC).isoformat(),
        )

    def amend_wall_budget(
        self,
        campaign_id: str,
        approved_max_wall_seconds: int,
        *,
        reason: str,
        evidence_refs: tuple[str, ...] | list[str],
        actor: str = "operator",
        now: str | None = None,
    ) -> AppendResult:
        if isinstance(evidence_refs, (str, bytes)):
            raise ValueError("wall-budget amendment requires evidence references")
        normalized_evidence = tuple(evidence_refs)
        if not normalized_evidence:
            raise ValueError("wall-budget amendment requires evidence references")
        for evidence_ref in normalized_evidence:
            self.artifacts.get_bytes(evidence_ref)
        return self.store.amend_campaign_wall_budget(
            campaign_id=campaign_id,
            approved_max_wall_seconds=approved_max_wall_seconds,
            actor=actor,
            reason=reason,
            evidence_refs=normalized_evidence,
            now=now or dt.datetime.now(dt.UTC).isoformat(),
        )

    def record_inventory(self, *, campaign_id: str, inventory: ProjectInventory) -> str:
        campaign = self.store.get_campaign(campaign_id)
        if inventory.snapshot_id != campaign.snapshot_id:
            raise ValueError(
                f"inventory snapshot does not match Campaign: {inventory.snapshot_id} != {campaign.snapshot_id}"
            )
        validate_inventory(inventory)
        target_root = self.target_root.resolve()
        for source in inventory.source_files:
            relative_path = Path(source.path)
            source_path = target_root / relative_path
            try:
                resolved_path = source_path.resolve(strict=True)
            except OSError as error:
                raise ValueError(
                    f"inventory source path is not a readable regular file: {source.path}"
                ) from error
            if (
                relative_path.is_absolute()
                or ".." in relative_path.parts
                or relative_path.as_posix() != source.path
                or source_path.is_symlink()
                or not resolved_path.is_relative_to(target_root)
                or not resolved_path.is_file()
            ):
                raise ValueError(
                    f"inventory source path escapes or is not a regular file: {source.path}"
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
        inventory = self.load_inventory(campaign_id)
        self._validate_component_graph(graph, inventory)
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

    def record_external_observation(
        self, observation: ExternalObservation,
    ) -> str:
        value = json.loads(json.dumps(
            asdict(observation), ensure_ascii=False, sort_keys=True,
        ))
        observation = ExternalObservation.from_dict(value)
        campaign = self.store.get_campaign(observation.campaign_id)
        if campaign.status is CampaignStatus.COMPLETE:
            raise ValueError("external observations cannot be registered after Campaign completion")
        if observation.snapshot_id != campaign.snapshot_id:
            raise ValueError("external observation snapshot does not match Campaign")
        if observation.target_ref != campaign.target_root:
            raise ValueError("external observation target does not match Campaign")
        try:
            observed_at = dt.datetime.fromisoformat(
                observation.observed_at.replace("Z", "+00:00")
            )
        except ValueError as error:
            raise ValueError("external observation observed_at must be ISO-8601") from error
        if observed_at.tzinfo is None:
            raise ValueError("external observation observed_at must include a timezone")
        self.store.get_batch(observation.campaign_id, observation.batch_id)
        r2_events = self.store.list_batch_events(
            observation.campaign_id,
            observation.batch_id,
            event_type="R2_COMPLETED",
        )
        if not r2_events or r2_events[-1].payload_ref is None:
            raise ValueError("external observation requires a committed R2 hypothesis")
        r2 = json.loads(self.artifacts.get_bytes(r2_events[-1].payload_ref))
        if observation.hypothesis_id not in {
            str(item.get("hypothesis_id", "")) for item in r2.get("hypotheses", [])
        }:
            raise ValueError("external observation hypothesis is outside its Batch R2 scope")

        artifact_owners = self.store.artifact_campaign_owners(
            set(observation.evidence_refs)
        )
        for reference in observation.evidence_refs:
            if not reference.startswith("sha256:"):
                raise ValueError("external observation evidence must use Campaign artifact refs")
            try:
                self.artifacts.get_bytes(reference)
            except (OSError, ValueError) as error:
                raise ValueError(
                    f"external observation evidence artifact is missing: {reference}"
                ) from error
            if observation.campaign_id not in artifact_owners.get(reference, set()):
                raise ValueError(
                    f"external observation evidence is not owned by this Campaign: {reference}"
                )

        secret = os.environ.get("VNA_R5_EXTERNAL_OBSERVATION_HMAC_KEY", "").encode("utf-8")
        if len(secret) < 32:
            raise ValueError(
                "VNA_R5_EXTERNAL_OBSERVATION_HMAC_KEY must contain at least 32 bytes"
            )
        unsigned = asdict(observation)
        unsigned.pop("signature")
        canonical = json.dumps(
            unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        expected_signature = hmac.new(secret, canonical, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(observation.signature, expected_signature):
            raise ValueError("external observation signature is invalid")

        encoded = json.dumps(
            asdict(observation),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        artifact = self.artifacts.put_text(encoded)
        existing = self.store.list_events(
            observation.campaign_id,
            entity_type="external_observation",
            entity_id=observation.observation_id,
            event_type="OUT_OF_BAND_OBSERVATION_RECORDED",
        )
        if existing and any(event.payload_ref != artifact.artifact_id for event in existing):
            raise ValueError("external observation ID conflicts with prior signed content")
        self.store.append_event(
            campaign_id=observation.campaign_id,
            batch_id=observation.batch_id,
            entity_type="external_observation",
            entity_id=observation.observation_id,
            event_type="OUT_OF_BAND_OBSERVATION_RECORDED",
            idempotency_key=(
                f"external-observation:{observation.campaign_id}:{observation.observation_id}"
            ),
            actor="tool",
            payload={
                "hypothesis_id": observation.hypothesis_id,
                "observer_id": observation.observer_id,
                "snapshot_id": observation.snapshot_id,
                "r5_effect": "EVIDENCE_ONLY_NOT_CONFIRMING",
            },
            payload_ref=artifact.artifact_id,
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
        if self.store.get_campaign(campaign_id).status is CampaignStatus.COMPLETE:
            raise ValueError("Plan Amendment is not allowed after Campaign completion")
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
        base_batches = [
            self.store.get_batch(campaign_id, batch.batch_id)
            for batch in base_plan.batches
        ]
        self._require_batches_quiescent_for_replay(campaign_id, base_batches)
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
            self._record_plan_supersession(
                campaign_id,
                base_plan,
                amended_plan,
                amendment,
                base_batches,
                amendment_artifact_id=existing.payload_ref,
            )
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
        self._record_plan(
            campaign_id=campaign_id,
            plan=amended_plan,
            inventory=inventory,
            replacing_plan_id=base_plan.plan_id,
        )
        artifact = self.artifacts.put_text(amendment_json)
        self._record_plan_supersession(
            campaign_id,
            base_plan,
            amended_plan,
            amendment,
            base_batches,
            amendment_artifact_id=artifact.artifact_id,
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

    def _require_batches_quiescent_for_replay(
        self, campaign_id: str, batches: list[BatchRecord],
    ) -> None:
        state_event_types = {
            "TASK_CLAIMED", "TASK_LEASE_RELEASED", "TASK_COMPLETED",
            "TASK_FAILED", "TASK_RETRY_AUTHORIZED", "TASK_CANCELLED",
        }
        for batch in batches:
            events = self.store.list_batch_events(
                campaign_id,
                batch.batch_id,
                entity_type="execution_task",
            )
            states_by_task: dict[str, list[str]] = {}
            submitted_task_ids = set()
            for event in events:
                if event.event_type == "TASK_SUBMITTED":
                    submitted_task_ids.add(event.entity_id)
                if event.event_type in state_event_types:
                    states_by_task.setdefault(event.entity_id, []).append(
                        event.event_type
                    )
            for task_id in submitted_task_ids:
                task_states = states_by_task.get(task_id, [])
                if not task_states or task_states[-1] not in {
                    "TASK_COMPLETED", "TASK_CANCELLED",
                }:
                    raise ValueError(
                        f"cannot replay Batch with an unfinished execution task: {task_id}"
                    )

    def _record_plan_supersession(
        self,
        campaign_id: str,
        base_plan: AuditPlan,
        amended_plan: AuditPlan,
        amendment: PlanAmendment,
        base_batches: list[BatchRecord],
        *,
        amendment_artifact_id: str | None = None,
    ) -> None:
        replacement_by_batch = {
            item.retired_batch_id: item.replacement_batch_ids
            for item in amendment.batch_replacements
        }
        events = [{
            "batch_id": batch.batch_id,
            "entity_type": "batch_lifecycle",
            "entity_id": batch.batch_id,
            "event_type": "BATCH_SUPERSEDED",
            "idempotency_key": (
                f"batch-superseded:{campaign_id}:{base_plan.plan_id}:"
                f"{amended_plan.plan_id}:{batch.batch_id}"
            ),
            "actor": "tool",
            "payload": {
                "base_plan_id": base_plan.plan_id,
                "amended_plan_id": amended_plan.plan_id,
                "replacement_batch_ids": list(
                    replacement_by_batch[batch.batch_id]
                ),
            },
            "payload_ref": None,
        } for batch in base_batches]
        events.append({
            "batch_id": None,
            "entity_type": "plan_amendment",
            "entity_id": amendment.amendment_id,
            "event_type": "PLAN_AMENDED",
            "idempotency_key": f"plan-amendment:{campaign_id}:{amendment.amendment_id}",
            "actor": "tool",
            "payload": {
                "base_plan_id": amendment.base_plan_id,
                "amended_plan_id": amendment.amended_plan_id,
                "retired_batches": len(amendment.batch_replacements),
            },
            "payload_ref": amendment_artifact_id,
        })
        self.store.append_events_batch(campaign_id, events)
        for batch in base_batches:
            current = self.store.get_batch(campaign_id, batch.batch_id)
            if current.status not in {BatchStatus.DEFERRED, BatchStatus.COMPLETE}:
                self.store.transition_batch(
                    campaign_id, batch.batch_id, BatchStatus.DEFERRED,
                )

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
        validate_inventory(inventory)
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
        self._validate_component_graph(graph, self.load_inventory(campaign_id))
        path = self.state_dir / "campaigns" / campaign_id / "component_graph.json"
        exported = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        if not path.exists() or path.read_text(encoding="utf-8") != exported:
            self._atomic_json(path, value)
        return graph

    @staticmethod
    def _validate_component_graph(
        graph: ComponentGraph, inventory: ProjectInventory,
    ) -> None:
        validate_inventory(inventory)
        components = {component.component_id: component for component in inventory.components}
        validate_boundary_edge_endpoints(
            graph.edges,
            set(components),
            {source.path: source.component_id for source in inventory.source_files},
        )
        build_unit_ids = [unit.build_unit_id for unit in graph.build_units]
        if len(build_unit_ids) != len(set(build_unit_ids)):
            raise ValueError("component graph duplicates BuildUnit IDs")
        for unit in graph.build_units:
            component = components.get(unit.component_id)
            if component is None:
                raise ValueError(
                    f"component graph BuildUnit has an unknown component: {unit.build_unit_id}"
                )
            if unit.manifest_path not in component.build_manifests:
                raise ValueError(
                    f"component graph BuildUnit manifest is not owned by its component: {unit.build_unit_id}"
                )

    def load_audit_plan(self, campaign_id: str, plan_id: str) -> AuditPlan:
        campaign = self.store.get_campaign(campaign_id)
        events = self.store.list_events(
            campaign_id,
            entity_type="plan",
            entity_id=plan_id,
            event_type="PLAN_RECORDED",
        )
        if not events or events[-1].payload_ref is None:
            raise ValueError(f"Campaign plan is missing: {plan_id}")
        value = json.loads(self.artifacts.get_bytes(events[-1].payload_ref))
        if not isinstance(value, dict):
            raise ValueError("Campaign plan artifact must be a JSON object")
        plan = AuditPlan.from_dict(value)
        if plan.plan_id != plan_id or plan.campaign_id != campaign_id or plan.snapshot_id != campaign.snapshot_id:
            raise ValueError("recorded plan does not match the Campaign")
        validate_plan(plan, self.load_inventory(campaign_id))
        path = (
            self.state_dir / "campaigns" / campaign_id / "plans" / f"{plan_id}.json"
        )
        exported = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        if not path.exists() or path.read_text(encoding="utf-8") != exported:
            self._atomic_json(path, value)
        return plan

    def load_snapshot_baseline(self, campaign_id: str) -> Mapping[str, Any]:
        campaign = self.store.get_campaign(campaign_id)
        events = self.store.list_events(
            campaign_id,
            entity_type="snapshot_baseline",
            entity_id=campaign_id,
            event_type="SNAPSHOT_BASELINE_RECORDED",
        )
        if not events or events[-1].payload_ref is None:
            raise ValueError("Campaign snapshot baseline is missing; record inventory first")
        value = json.loads(self.artifacts.get_bytes(events[-1].payload_ref))
        if (
            not isinstance(value, dict)
            or value.get("snapshot_id") != campaign.snapshot_id
            or not isinstance(value.get("files"), dict)
        ):
            raise ValueError("recorded snapshot baseline does not match the Campaign")
        path = (
            self.state_dir
            / "campaigns"
            / campaign_id
            / "snapshot-baseline.json"
        )
        exported = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        if not path.exists() or path.read_text(encoding="utf-8") != exported:
            self._atomic_json(path, value)
        return value

    def register_evidence_files(
        self, campaign_id: str, paths: list[str], *, reason: str,
    ) -> str:
        campaign = self.store.get_campaign(campaign_id)
        if campaign.status is CampaignStatus.COMPLETE or self.store.list_events(
            campaign_id, event_type="R0_COMPLETED",
        ):
            raise ValueError("supporting evidence must be registered before the first R0")
        if (
            not reason.strip() or not paths or len(paths) > 1024
            or any(not isinstance(path, str) for path in paths)
            or len(paths) != len(set(paths))
        ):
            raise ValueError("evidence registration requires reason and 1..1024 unique paths")
        baseline = self.load_snapshot_baseline(campaign_id)
        existing = dict(baseline["files"])
        for event in self.store.list_events(
            campaign_id, event_type="EVIDENCE_FILES_REGISTERED",
        ):
            existing.update(event.payload["file_digests"])
        digests = {}
        total_bytes = 0
        for path in sorted(paths):
            relative = Path(path)
            resolved = (self.target_root / relative).resolve()
            if (
                relative.is_absolute() or ".." in relative.parts
                or relative.as_posix() != path
                or any(part in {".git", ".hg", ".svn", ".audit_vnext", ".audit_results"}
                       for part in relative.parts)
                or (self.target_root / relative).is_symlink()
                or not resolved.is_relative_to(self.target_root)
                or resolved == self.state_dir or self.state_dir in resolved.parents
                or not resolved.is_file() or resolved.stat().st_size > 16 * 1024**2
            ):
                raise ValueError(f"supporting evidence path is unsafe, missing or oversized: {path}")
            total_bytes += resolved.stat().st_size
            if total_bytes > 64 * 1024**2:
                raise ValueError("supporting evidence registration exceeds 64 MiB")
            digest = self._file_digest(resolved)
            if path in existing and existing[path] != digest:
                raise ValueError(f"registered evidence content changed: {path}")
            digests[path] = digest
        value = {
            "schema_version": "1.0", "snapshot_id": campaign.snapshot_id,
            "file_digests": digests, "reason": reason.strip(),
        }
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"))
        artifact = self.artifacts.put_text(encoded)
        self.store.append_event(
            campaign_id=campaign_id, batch_id=None,
            entity_type="supporting_evidence", entity_id=campaign_id,
            event_type="EVIDENCE_FILES_REGISTERED",
            idempotency_key=f"evidence-files:{campaign_id}:{artifact.artifact_id}",
            actor="operator", payload=value, payload_ref=artifact.artifact_id,
        )
        return artifact.artifact_id

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
