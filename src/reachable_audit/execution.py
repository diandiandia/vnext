"""Durable execution tasks and the manual backend contract."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
import datetime as dt
from enum import StrEnum
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Callable, Mapping, Sequence

from .analysis_models import (
    Adjudication,
    AdjudicationActor,
    AttackAngle,
    Applicability,
    AxisRun,
    BatchClosure,
    BoundaryReview,
    CategoryRun,
    CategoryRunStatus,
    DiscoveryAxis,
    Experiment,
    Hypothesis,
    R5Assessment,
    Refutation,
    RevivalReview,
    Surface,
    VerdictSubmission,
)
from .batch_workflow import BatchWorkflow
from .campaign import CampaignManager
from .discovery.hotspots import scan_work_unit_hotspots
from .adapters.languages import LANGUAGE_ADAPTERS
from .knowledge_catalog import KnowledgeCatalog, default_knowledge_root
from .experiments.harness_catalog import DEFAULT_HARNESS_CATALOG
from .models import ModelError
from .runtime_policy import execution_policy_digest
from .store import NotFoundError


_SURFACE_INSTRUCTIONS = (
    "Enumerate externally or cross-trust-boundary reachable entry points, identify the "
    "effective principal, and anchor every Surface to an exact source line. Every "
    "Surface entry_path must be one of this Work Unit's source_files; a Surface in "
    "another file belongs to that file's Work Unit or to a Handoff."
)

_AXIS_INSTRUCTIONS = {
    DiscoveryAxis.SURFACE.value: (
        "Trace each Surface toward sensitive operations and record plausible unguarded paths."
    ),
    DiscoveryAxis.MECHANISM.value: (
        "Apply each planned mechanism family to the scoped code, including guards and counterevidence."
    ),
    DiscoveryAxis.STATE.value: (
        "Inspect lifecycle, ownership, authorization, concurrency, and transition invariants."
    ),
    DiscoveryAxis.FIX_VARIANT.value: (
        "Look for incomplete fixes, sibling implementations, aliases, and alternate call paths."
    ),
    DiscoveryAxis.BOUNDARY.value: (
        "Inspect trust changes across module, process, RPC, IPC, FFI, serialization, and storage edges."
    ),
    DiscoveryAxis.DIFFERENTIAL.value: (
        "Compare modes, configurations, implementations, versions, and error paths for divergent security behavior."
    ),
}

_VERIFICATION_INSTRUCTIONS = (
    "Determine reachability from a declared principal. REACHABLE requires an explicit "
    "call chain and edge evidence; UNREACHABLE requires blocking evidence; uncertainty "
    "must remain NEEDS_REVIEW. Do not claim empirical confirmation in R3."
)

_HOTSPOT_CONTRACT = (
    "Static hotspot locations are candidate review leads, not vulnerability verdicts. "
    "Verify the exact call/API semantics, attacker-controlled inputs, guards, and any "
    "source-to-sink path before forming a hypothesis. Report provider coverage and "
    "limitations; no match or unavailable provider is not evidence of safety."
)


# Hard collection/amendment ceiling. 4 MiB leaves headroom for Work Units whose
# *mandatory* content cannot fit in 1 MiB (observed: a 5,453-boundary-review WU whose
# minimal valid result is ~1.48 MiB once every review carries its required evidence
# anchor and rationale).
_MAX_TASK_OUTPUT_BYTES = 4 * 1024 * 1024
# What agents are asked to target — kept tight so the ceiling stays a backstop, not
# a budget.
_OUTPUT_DISCIPLINE_BYTES = 1024 * 1024

_OUTPUT_DISCIPLINE = (
    "Compose the complete result once and write it in a single call; do not rewrite or "
    "patch it incrementally. Cover every required element — every surface and every "
    "boundary review the task lists — even when that is thousands of items: never drop, "
    "sample, or truncate required coverage to save space. Keep each item terse: cite "
    "anchors instead of quoting source, one concise sentence per evidence item, and "
    f"omit fields the contract does not ask for, so the total targets under "
    f"{_OUTPUT_DISCIPLINE_BYTES} bytes. If full coverage genuinely needs more, write it "
    f"anyway and stay within the {_MAX_TASK_OUTPUT_BYTES}-byte hard ceiling — coverage "
    "always wins over the size target, and the ceiling is never exceeded."
)


class TaskStatus(StrEnum):
    PENDING = "PENDING"
    LEASED = "LEASED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


_TASK_OUTPUT_CONTRACTS = {
    "discover_surfaces": "surface-set/v1",
    "generate_hypotheses:": "hypothesis-set/v1",
    "generate_hypotheses_compact": "compact-hypothesis-set/v1",
    "verify_reachability": "verdict-submission/v1",
    "refute_reachability": "refutation/v1",
    "adjudicate_refutations": "adjudication/v1",
    "review_unreachable_verdict": "revival-review/v1",
    "run_category_audit": "category-run/v1",
    "assess_experiment": "r5-assessment/v1",
    "collect_batch_closure_evidence": "batch-closure-evidence/v1",
}
_TASK_OUTPUT_REQUIRED_FIELDS = {
    "surface-set/v1": {"reviewed_paths", "surfaces", "boundary_reviews"},
    "hypothesis-set/v1": {"reviewed_paths", "axis_run", "hypotheses"},
    "compact-hypothesis-set/v1": {"reviewed_paths", "axis_runs", "hypotheses"},
    "verdict-submission/v1": {"verdict"},
    "refutation/v1": {"refutation"},
    "adjudication/v1": {"adjudication"},
    "revival-review/v1": {"revival_review"},
    "category-run/v1": {"category_run"},
    "r5-assessment/v1": {"experiments", "assessment"},
    "batch-closure-evidence/v1": {"closure"},
}


@dataclass(frozen=True)
class TaskSpec:
    task_id: str
    campaign_id: str
    batch_id: str
    work_unit_id: str
    operation: str
    input_refs: tuple[str, ...]
    required_output: str
    budget: Mapping[str, int]
    max_attempts: int = 3

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TaskSpec":
        task = cls(
            task_id=str(value["task_id"]),
            campaign_id=str(value["campaign_id"]),
            batch_id=str(value["batch_id"]),
            work_unit_id=str(value["work_unit_id"]),
            operation=str(value["operation"]),
            input_refs=tuple(str(item) for item in value.get("input_refs", [])),
            required_output=str(value["required_output"]),
            budget={str(key): int(amount) for key, amount in value.get("budget", {}).items()},
            max_attempts=int(value.get("max_attempts", 3)),
        )
        if not all((
            task.task_id,
            task.campaign_id,
            task.batch_id,
            task.work_unit_id,
            task.operation,
            task.required_output,
        )):
            raise ModelError("execution task identity and operation fields are required")
        if not task.input_refs:
            raise ModelError("execution task requires artifact input references")
        if any(amount < 0 for amount in task.budget.values()):
            raise ModelError("execution task budget cannot be negative")
        if task.max_attempts < 1:
            raise ModelError("execution task max_attempts must be positive")
        return task


@dataclass(frozen=True)
class TaskLease:
    task: TaskSpec
    worker_id: str
    attempt: int
    lease_expires_at: str


@dataclass(frozen=True)
class TaskResult:
    succeeded: bool
    output_ref: str | None
    summary: str
    measurements: Mapping[str, int]
    configuration: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.succeeded and not self.output_ref:
            raise ModelError("successful execution task requires an output artifact")
        if not self.summary.strip():
            raise ModelError("execution task result requires a summary")
        if any(amount < 0 for amount in self.measurements.values()):
            raise ModelError("execution task measurements cannot be negative")
        required_measurements = {"agent_runs", "wall_seconds"}
        missing_measurements = required_measurements - set(self.measurements)
        if missing_measurements:
            raise ModelError(
                f"execution result requires measurements: {sorted(missing_measurements)}"
            )
        if any(not str(key).strip() or not str(value).strip() for key, value in self.configuration.items()):
            raise ModelError("execution configuration attestations cannot be empty")
        host_policy_digest = self.configuration.get("host_tool_policy_digest")
        if host_policy_digest and not re.fullmatch(r"sha256:[0-9a-f]{64}", host_policy_digest):
            raise ModelError(
                "host_tool_policy_digest must be a sha256:<64 lowercase hex> value"
            )


@dataclass(frozen=True)
class TaskView:
    task: TaskSpec
    status: TaskStatus
    worker_id: str | None
    attempt: int
    lease_expires_at: str | None
    output_ref: str | None




class ManualExecutionBackend:
    """Artifact-only inbox backend for a human or host Agent worker."""

    def __init__(
        self,
        manager: CampaignManager,
        campaign_id: str,
        *,
        clock: Callable[[], dt.datetime] | None = None,
    ) -> None:
        self.manager = manager
        self.campaign_id = campaign_id
        self._clock = clock or (lambda: dt.datetime.now(dt.UTC))


    def submit(self, task: TaskSpec) -> TaskView:
        if task.campaign_id != self.campaign_id:
            raise ModelError("execution task belongs to another Campaign")
        self.manager.store.get_batch(task.campaign_id, task.batch_id)
        encoded = json.dumps(
            asdict(task), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        artifact = self.manager.artifacts.put_text(encoded)
        existing_submissions = self.manager.store.list_events(
            self.campaign_id,
            entity_type="execution_task",
            entity_id=task.task_id,
            event_type="TASK_SUBMITTED",
        )
        if existing_submissions and any(
            event.payload_ref != artifact.artifact_id for event in existing_submissions
        ):
            # Re-scheduling an already-submitted task whose payload was revised (e.g. an
            # output_discipline text change between skill versions) must not silently
            # rewrite a task that may be in flight or complete: the first submitted spec
            # stays authoritative and re-scheduling is a no-op. Only a change of task
            # identity remains an error.
            existing_spec = TaskSpec.from_dict(json.loads(
                self.manager.artifacts.get_bytes(existing_submissions[-1].payload_ref)
            ))
            same_identity = (
                existing_spec.work_unit_id == task.work_unit_id
                and existing_spec.operation == task.operation
                and existing_spec.required_output == task.required_output
            )
            if not same_identity:
                raise ModelError(f"execution task ID reused with different spec: {task.task_id}")
            return self.poll(task.task_id)
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        self.manager.store.append_event(
            campaign_id=task.campaign_id,
            batch_id=task.batch_id,
            entity_type="execution_task",
            entity_id=task.task_id,
            event_type="TASK_SUBMITTED",
            idempotency_key=f"task:submit:{task.campaign_id}:{task.task_id}:{digest}",
            actor="scheduler",
            payload={
                "work_unit_id": task.work_unit_id,
                "operation": task.operation,
                "required_output": task.required_output,
                "max_attempts": task.max_attempts,
            },
            payload_ref=artifact.artifact_id,
        )
        return self.poll(task.task_id)

    def poll(self, task_id: str) -> TaskView:
        events = self._task_events(task_id)
        submitted = events[0]
        if submitted.payload_ref is None:
            raise ModelError(f"execution task has no specification artifact: {task_id}")
        task = TaskSpec.from_dict(json.loads(
            self.manager.artifacts.get_bytes(submitted.payload_ref)
        ))
        claims = [event for event in events if event.event_type == "TASK_CLAIMED"]
        state_events = [event for event in events if event.event_type in {
            "TASK_CLAIMED", "TASK_LEASE_RELEASED", "TASK_COMPLETED",
            "TASK_FAILED", "TASK_RETRY_AUTHORIZED", "TASK_CANCELLED",
        }]
        latest_state = state_events[-1] if state_events else None
        if latest_state is not None and latest_state.event_type in {
            "TASK_COMPLETED", "TASK_FAILED", "TASK_CANCELLED",
        }:
            status = {
                "TASK_COMPLETED": TaskStatus.SUCCEEDED,
                "TASK_FAILED": TaskStatus.FAILED,
                "TASK_CANCELLED": TaskStatus.CANCELLED,
            }[latest_state.event_type]
        elif latest_state is not None and latest_state.event_type == "TASK_CLAIMED":
            status = TaskStatus.LEASED
        else:
            status = TaskStatus.PENDING
        claim = claims[-1] if claims else None
        output_ref = (
            latest_state.payload_ref
            if latest_state is not None and latest_state.event_type in {
                "TASK_COMPLETED", "TASK_FAILED", "TASK_CANCELLED",
            } else None
        )
        amendments = self.manager.store.list_events(
            self.campaign_id,
            entity_type="execution_task_amendment",
            entity_id=task_id,
            event_type="TASK_OUTPUT_AMENDED",
        )
        for amendment in amendments:
            if amendment.payload.get("prior_output_ref") != output_ref:
                raise ModelError(f"task output amendment chain is invalid: {task_id}")
            output_ref = amendment.payload_ref
        return TaskView(
            task=task,
            status=status,
            worker_id=claim.actor if claim else None,
            attempt=int(claim.payload["attempt"]) if claim else 0,
            lease_expires_at=str(claim.payload["lease_expires_at"]) if claim else None,
            output_ref=output_ref,
        )

    def claim(
        self, worker_id: str, *, lease_seconds: int = 900,
        operation: str | None = None, batch_id: str | None = None,
        task_id_filter: str | None = None,
    ) -> TaskLease | None:
        if not worker_id.strip() or lease_seconds <= 0:
            raise ModelError("task claim requires a worker and positive lease duration")
        now = self._now()
        for candidate_task_id in self._task_ids():
            if task_id_filter is not None and candidate_task_id != task_id_filter:
                continue
            view = self.poll(candidate_task_id)
            if operation is not None and view.task.operation != operation:
                continue
            if batch_id is not None and view.task.batch_id != batch_id:
                continue
            event = self.manager.store.claim_task(
                campaign_id=self.campaign_id,
                task_id=candidate_task_id,
                worker_id=worker_id,
                lease_expires_at=(
                    dt.datetime.fromisoformat(now) + dt.timedelta(seconds=lease_seconds)
                ).isoformat(),
                now=now,
            )
            if event is None:
                continue
            view = self.poll(candidate_task_id)
            return TaskLease(
                task=view.task,
                worker_id=worker_id,
                attempt=int(event.payload["attempt"]),
                lease_expires_at=str(event.payload["lease_expires_at"]),
            )
        return None

    def collect(self, lease: TaskLease, result: TaskResult) -> TaskView:
        if lease.task.campaign_id != self.campaign_id:
            raise ModelError("execution lease belongs to another Campaign")
        if result.succeeded and lease.task.required_output in _TASK_OUTPUT_REQUIRED_FIELDS:
            if result.output_ref is None:
                raise ModelError("successful execution task requires an output artifact")
            self._validate_task_output(lease.task, result.output_ref)
        exceeded = {
            name: (result.measurements[name], limit)
            for name, limit in lease.task.budget.items()
            if name in result.measurements and result.measurements[name] > limit
        }
        if exceeded:
            raise ModelError(f"execution task exceeded budget: {exceeded}")
        self.manager.store.finalize_task(
            campaign_id=self.campaign_id,
            task_id=lease.task.task_id,
            worker_id=lease.worker_id,
            attempt=lease.attempt,
            succeeded=result.succeeded,
            payload={
                "summary": result.summary,
                "measurements": dict(result.measurements),
                "configuration": {
                    **dict(result.configuration),
                    "vnext_policy_digest": execution_policy_digest(),
                },
            },
            payload_ref=result.output_ref,
            now=self._now(),
        )
        return self.poll(lease.task.task_id)

    def amend_completed_output(
        self,
        task_id: str,
        replacement_output_ref: str,
        *,
        reason: str,
        evidence_refs: Sequence[str],
        actor: str = "operator",
    ) -> TaskView:
        view = self.poll(task_id)
        if view.status is not TaskStatus.SUCCEEDED or view.output_ref is None:
            raise ModelError("only a successfully collected task output can be amended")
        if replacement_output_ref == view.output_ref:
            raise ModelError("task output amendment must replace the current artifact")
        if not reason.strip() or not actor.strip() or not evidence_refs:
            raise ModelError("task output amendment requires actor, reason, and evidence")
        stage_by_operation = {
            "discover_surfaces": "R1_COMPLETED",
            "generate_hypotheses": "R2_COMPLETED",
            "generate_hypotheses_compact": "R2_COMPLETED",
            "verify_reachability": "R3_COMPLETED",
        }
        committed_stage = stage_by_operation.get(view.task.operation)
        if committed_stage is None:
            raise ModelError(
                f"task output amendment is not supported for operation: {view.task.operation}"
            )
        if self.manager.store.list_batch_events(
            self.campaign_id,
            view.task.batch_id,
            event_type=committed_stage,
        ):
            raise ModelError(
                "task output cannot be amended after its stage has committed; "
                "downstream stage amendment is required"
            )
        self._validate_task_output(view.task, replacement_output_ref)
        for evidence_ref in evidence_refs:
            try:
                self.manager.artifacts.get_bytes(evidence_ref)
            except (OSError, ValueError) as error:
                raise ModelError(
                    f"task amendment evidence artifact cannot be resolved: {evidence_ref}"
                ) from error
        self.manager.store.append_event(
            campaign_id=self.campaign_id,
            batch_id=view.task.batch_id,
            entity_type="execution_task_amendment",
            entity_id=task_id,
            event_type="TASK_OUTPUT_AMENDED",
            idempotency_key=(
                f"task-output-amend:{self.campaign_id}:{task_id}:"
                f"{view.output_ref}:{replacement_output_ref}"
            ),
            actor=actor,
            payload={
                "prior_output_ref": view.output_ref,
                "replacement_output_ref": replacement_output_ref,
                "reason": reason.strip(),
                "evidence_refs": list(evidence_refs),
                "stage": committed_stage,
            },
            payload_ref=replacement_output_ref,
        )
        return self.poll(task_id)

    def _validate_task_output(self, task: TaskSpec, output_ref: str) -> Mapping[str, Any]:
        try:
            output_bytes = self.manager.artifacts.get_bytes(output_ref)
            output = json.loads(output_bytes)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            raise ModelError(f"task output is not valid JSON: {task.task_id}") from error
        if len(output_bytes) > _MAX_TASK_OUTPUT_BYTES:
            raise ModelError(
                f"task output exceeds {_MAX_TASK_OUTPUT_BYTES} bytes ({len(output_bytes)}); "
                f"resubmit a compact result: {task.task_id}"
            )
        if not isinstance(output, dict) or output.get("schema_version") != "1.0":
            raise ModelError(f"task output schema_version mismatch: {task.task_id}")
        required = _TASK_OUTPUT_REQUIRED_FIELDS.get(task.required_output)
        if required is not None:
            missing = required - set(output)
            if missing:
                raise ModelError(
                    f"task output contract missing {sorted(missing)}: {task.task_id}"
                )
        if task.required_output == "verdict-submission/v1":
            self._validate_verdict_output(task, output)
        if task.required_output == "surface-set/v1":
            self._validate_surface_coverage(task, output)
        return output

    def _validate_surface_coverage(
        self, task: TaskSpec, output: Mapping[str, Any],
    ) -> None:
        try:
            task_input = json.loads(self.manager.artifacts.get_bytes(task.input_refs[0]))
        except (IndexError, OSError, ValueError):
            return
        work_unit = task_input.get("work_unit") if isinstance(task_input, dict) else None
        if not isinstance(work_unit, dict):
            return
        DiscoveryCoordinator._validate_reviewed_paths(output, work_unit, task.task_id)
        expected = {str(edge["edge_id"]) for edge in task_input.get("boundary_edges", [])}
        reviews = output.get("boundary_reviews")
        if not isinstance(reviews, list):
            raise ModelError(f"task output requires boundary_reviews: {task.task_id}")
        reviewed = [
            str(item.get("edge_id", "")) if isinstance(item, dict) else "" for item in reviews
        ]
        actual = set(reviewed)
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        duplicated = len(reviewed) - len(actual)
        if missing or extra or duplicated:
            raise ModelError(
                f"boundary review coverage mismatch: {task.task_id}; "
                f"expected={len(expected)}, delivered={len(actual)}, "
                f"missing={len(missing)} (first {missing[:10]}), "
                f"extra={len(extra)} (first {extra[:10]}), duplicates={duplicated}; "
                "resubmit one review for every supplied boundary edge"
            )

    def _validate_verdict_output(
        self, task: TaskSpec, output: Mapping[str, Any],
    ) -> None:
        verdict_value = output.get("verdict")
        if not isinstance(verdict_value, dict):
            raise ModelError(f"task output requires a verdict object: {task.task_id}")
        submission = VerdictSubmission.from_dict(verdict_value)
        workflow = BatchWorkflow(self.manager, task.campaign_id, task.batch_id)
        line_count_cache: dict[str, tuple[int, frozenset[int]]] = {}
        evidence_paths = None
        if not self.manager.store.has_evidence_path_index(task.campaign_id):
            inventory = self.manager.load_inventory(task.campaign_id)
            evidence_paths = {source.path for source in inventory.source_files}
            evidence_paths.update(
                manifest
                for component in inventory.components
                for manifest in component.build_manifests
            )
        for reference in submission.call_chain:
            workflow._validate_source_location(
                reference, evidence_paths, line_count_cache=line_count_cache
            )
        for reference in (
            *submission.edge_evidence_ids,
            *submission.blocking_evidence_ids,
        ):
            workflow._validate_evidence_reference(
                reference, evidence_paths, line_count_cache=line_count_cache
            )

    def release(
        self, lease: TaskLease, *, reason: str = "worker released lease",
    ) -> TaskView:
        if lease.task.campaign_id != self.campaign_id:
            raise ModelError("execution lease belongs to another Campaign")
        self.manager.store.release_task(
            campaign_id=self.campaign_id,
            task_id=lease.task.task_id,
            worker_id=lease.worker_id,
            attempt=lease.attempt,
            reason=reason,
            now=self._now(),
        )
        return self.poll(lease.task.task_id)

    def retry(
        self, task_id: str, *, reason: str, actor: str = "operator",
    ) -> TaskView:
        self.manager.store.authorize_task_retry(
            campaign_id=self.campaign_id,
            task_id=task_id,
            actor=actor,
            reason=reason,
            now=self._now(),
        )
        return self.poll(task_id)

    def current_lease(self, task_id: str, worker_id: str) -> TaskLease:
        view = self.poll(task_id)
        if view.status is not TaskStatus.LEASED or view.worker_id != worker_id:
            raise ModelError(f"worker does not hold the task lease: {task_id}")
        if view.lease_expires_at is None:
            raise ModelError(f"leased task has no expiration: {task_id}")
        return TaskLease(
            task=view.task,
            worker_id=worker_id,
            attempt=view.attempt,
            lease_expires_at=view.lease_expires_at,
        )

    def describe_lease(self, lease: TaskLease) -> Mapping[str, Any]:
        inputs = []
        for artifact_id in lease.task.input_refs:
            raw = self.manager.artifacts.get_bytes(artifact_id)
            try:
                value: Any = json.loads(raw)
            except json.JSONDecodeError:
                value = raw.decode("utf-8", errors="replace")
            inputs.append({"artifact_id": artifact_id, "value": value})
        return {"lease": asdict(lease), "inputs": inputs}

    def cancel(self, task_id: str, *, reason: str) -> TaskView:
        if not reason.strip():
            raise ModelError("task cancellation requires a reason")
        self.manager.store.cancel_task(
            campaign_id=self.campaign_id,
            task_id=task_id,
            reason=reason,
            actor="scheduler",
            now=self._now(),
        )
        return self.poll(task_id)

    def list_tasks(
        self,
        *,
        operation: str | None = None,
        batch_id: str | None = None,
        operation_prefix: str | None = None,
    ) -> tuple[TaskView, ...]:
        views = tuple(
            self.poll(task_id) for task_id in self._task_ids(batch_id=batch_id)
        )
        return tuple(
            view for view in views
            if (operation is None or view.task.operation == operation)
            and (
                operation_prefix is None
                or view.task.operation.startswith(operation_prefix)
            )
        )

    def _task_events(self, task_id: str) -> list[Any]:
        events = self.manager.store.list_events(
            self.campaign_id,
            entity_type="execution_task",
            entity_id=task_id,
        )
        if not events:
            raise NotFoundError(f"execution task not found: {task_id}")
        return events

    def _task_ids(self, *, batch_id: str | None = None) -> Sequence[str]:
        return self.manager.store.list_entity_ids(
            self.campaign_id,
            entity_type="execution_task",
            event_type="TASK_SUBMITTED",
            batch_id=batch_id,
        )

    def _now(self) -> str:
        value = self._clock()
        if value.tzinfo is None:
            raise ModelError("execution clock must return a timezone-aware datetime")
        return value.astimezone(dt.UTC).isoformat()


class DiscoveryCoordinator:
    """Split R1/R2 by Work Unit and axis, then commit canonical stage artifacts."""

    def __init__(
        self,
        workflow: BatchWorkflow,
        backend: ManualExecutionBackend,
        knowledge_catalog: KnowledgeCatalog | None = None,
    ) -> None:
        if workflow.campaign_id != backend.campaign_id:
            raise ModelError("workflow and execution backend belong to different Campaigns")
        self.workflow = workflow
        self.backend = backend
        self.knowledge_catalog = knowledge_catalog or KnowledgeCatalog.load(
            default_knowledge_root()
        )

    @staticmethod
    def _language_adapter_context(work_unit: Mapping[str, Any]) -> list[dict[str, Any]]:
        output = []
        for language in sorted(set(str(item) for item in work_unit.get("languages", []))):
            adapter = LANGUAGE_ADAPTERS.get(language)
            if adapter is None:
                output.append({
                    "language_id": language,
                    "status": "recognized_unsupported",
                    "limitation": "no vNext language adapter is registered",
                })
                continue
            output.append({
                "language_id": adapter.language_id,
                "status": "portfolio_adapter",
                "extensions": sorted(adapter.extensions),
                "import_pattern": adapter.import_pattern,
                "boundary_markers": list(adapter.boundary_markers),
                "toolchain_probe": list(adapter.toolchain_probe),
                "generated_path_markers": list(adapter.generated_path_markers),
            })
        return output

    def _boundary_edges_for_work_unit(
        self, work_unit: Mapping[str, Any]
    ) -> list[dict[str, Any]]:
        edge_ids = set(str(item) for item in work_unit.get("boundary_edge_ids", []))
        if not edge_ids:
            return []
        plan_id = str(self.workflow.batch.manifest.get("plan_id", ""))
        if not plan_id:
            raise ModelError("Work Unit has boundary edges but Batch has no plan ID")
        plan = self.workflow.manager.load_audit_plan(self.workflow.campaign_id, plan_id)
        edges = [asdict(edge) for edge in plan.boundary_edges if edge.edge_id in edge_ids]
        if {edge["edge_id"] for edge in edges} != edge_ids:
            raise ModelError("Work Unit references unknown boundary edges")
        return edges

    def schedule_r1(self) -> tuple[TaskView, ...]:
        self._require_stage("R0_COMPLETED")
        views = []
        for work_unit in self._work_units():
            boundary_edges = self._boundary_edges_for_work_unit(work_unit)
            input_ref = self._put_json({
                "schema_version": "1.0",
                "operation": "discover_surfaces",
                "snapshot_id": self.workflow.campaign.snapshot_id,
                "work_unit": work_unit,
                "hotspot_report": scan_work_unit_hotspots(
                    self.workflow.manager.target_root,
                    work_unit.get("source_files", []),
                ),
                "hotspot_contract": _HOTSPOT_CONTRACT,
                "language_adapters": self._language_adapter_context(work_unit),
                "boundary_edges": boundary_edges,
                "analysis_contract": (
                    _SURFACE_INSTRUCTIONS
                    + " Review every supplied boundary edge as confirmed, rejected, or unresolved. "
                    "Return a BoundaryReview for each edge with evidence and rationale."
                ),
                "output_contract": {
                    "schema_version": "1.0",
                    "reviewed_paths": "exact array of Work Unit source_files",
                    "surfaces": "array<Surface>",
                    "boundary_reviews": "array<BoundaryReview>, one per supplied boundary edge",
                },
            })
            views.append(self.backend.submit(TaskSpec(
                task_id=self._task_id("discover_surfaces", str(work_unit["work_unit_id"])),
                campaign_id=self.workflow.campaign_id,
                batch_id=self.workflow.batch_id,
                work_unit_id=str(work_unit["work_unit_id"]),
                operation="discover_surfaces",
                input_refs=(input_ref,),
                required_output="surface-set/v1",
                budget={"agent_runs": 1},
            )))
        return tuple(views)

    def commit_r1(self) -> str:
        expected = {
            self._task_id(
                "discover_surfaces", str(work_unit["work_unit_id"])
            ): work_unit
            for work_unit in self._work_units()
        }
        views = self._successful_tasks("discover_surfaces", expected)
        surfaces = []
        boundary_reviews = []
        for view in views:
            value = self._read_output(view)
            work_unit = expected[view.task.task_id]
            self._validate_reviewed_paths(value, work_unit, view.task.task_id)
            for item in value.get("surfaces", []):
                surface = Surface.from_dict(item)
                if surface.work_unit_id != str(work_unit["work_unit_id"]):
                    raise ModelError(
                        f"surface task returned another Work Unit: {surface.surface_id}"
                    )
                surfaces.append(surface)
            for item in value.get("boundary_reviews", []):
                review = BoundaryReview.from_dict(item)
                if review.work_unit_id != str(work_unit["work_unit_id"]):
                    raise ModelError(
                        f"boundary review task scope mismatch: {review.edge_id}"
                    )
                boundary_reviews.append(review)
        return self.workflow.record_r1(surfaces, boundary_reviews)

    def schedule_r2(self) -> tuple[TaskView, ...]:
        r1_event = self._require_stage("R1_COMPLETED")
        if r1_event.payload_ref is None:
            raise ModelError("R1 stage is missing its artifact")
        r1 = json.loads(self.workflow.manager.artifacts.get_bytes(r1_event.payload_ref))
        surfaces_by_work_unit: dict[str, list[Mapping[str, Any]]] = {}
        for surface in r1["surfaces"]:
            surfaces_by_work_unit.setdefault(str(surface["work_unit_id"]), []).append(surface)
        views = []
        for work_unit in self._work_units():
            work_unit_id = str(work_unit["work_unit_id"])
            hotspot_report = scan_work_unit_hotspots(
                self.workflow.manager.target_root,
                work_unit.get("source_files", []),
            )
            for axis in DiscoveryAxis:
                knowledge_context = self.knowledge_catalog.task_context(
                    work_unit.get("languages", []),
                    families=work_unit.get("category_families", []),
                    max_entries=12,
                ).to_dict()
                input_ref = self._put_json({
                    "schema_version": "1.0",
                    "operation": "generate_hypotheses",
                    "axis": axis.value,
                    "snapshot_id": self.workflow.campaign.snapshot_id,
                    "work_unit": work_unit,
                    "hotspot_report": hotspot_report,
                    "hotspot_contract": _HOTSPOT_CONTRACT,
                    "surfaces": surfaces_by_work_unit.get(work_unit_id, []),
                    "language_adapters": self._language_adapter_context(work_unit),
                    "knowledge_context": knowledge_context,
                    "analysis_contract": _AXIS_INSTRUCTIONS[axis.value],
                    "output_contract": {
                        "schema_version": "1.0",
                        "reviewed_paths": "exact array of Work Unit source_files",
                        "axis_run": "AxisRun with APPLICABLE/NOT_APPLICABLE/DEFERRED, evidence_refs, rationale",
                        "hypotheses": "array<Hypothesis>",
                    },
                })
                views.append(self.backend.submit(TaskSpec(
                    task_id=self._task_id(
                        "generate_hypotheses", work_unit_id, axis.value
                    ),
                    campaign_id=self.workflow.campaign_id,
                    batch_id=self.workflow.batch_id,
                    work_unit_id=work_unit_id,
                    operation=f"generate_hypotheses:{axis.value}",
                    input_refs=(input_ref, r1_event.payload_ref),
                    required_output="hypothesis-set/v1",
                    budget={"agent_runs": 1},
                )))
        return tuple(views)

    def schedule_r2_compact(self) -> tuple[TaskView, ...]:
        """Schedule one consolidated six-axis task per Work Unit."""
        r1_event = self._require_stage("R1_COMPLETED")
        if r1_event.payload_ref is None:
            raise ModelError("R1 stage is missing its artifact")
        r1 = json.loads(self.workflow.manager.artifacts.get_bytes(r1_event.payload_ref))
        surfaces_by_work_unit: dict[str, list[Mapping[str, Any]]] = {}
        for surface in r1["surfaces"]:
            surfaces_by_work_unit.setdefault(str(surface["work_unit_id"]), []).append(surface)
        views = []
        axes = [axis.value for axis in DiscoveryAxis]
        for work_unit in self._work_units():
            work_unit_id = str(work_unit["work_unit_id"])
            hotspot_report = scan_work_unit_hotspots(
                self.workflow.manager.target_root,
                work_unit.get("source_files", []),
            )
            knowledge_context = self.knowledge_catalog.task_context(
                work_unit.get("languages", []),
                families=work_unit.get("category_families", []),
                max_entries=12,
            ).to_dict()
            input_ref = self._put_json({
                "schema_version": "1.0",
                "operation": "generate_hypotheses_compact",
                "snapshot_id": self.workflow.campaign.snapshot_id,
                "work_unit": work_unit,
                "hotspot_report": hotspot_report,
                "hotspot_contract": _HOTSPOT_CONTRACT,
                "surfaces": surfaces_by_work_unit.get(work_unit_id, []),
                "language_adapters": self._language_adapter_context(work_unit),
                "knowledge_context": knowledge_context,
                "analysis_contract": {
                    axis: _AXIS_INSTRUCTIONS[axis] for axis in axes
                },
                "output_contract": {
                    "schema_version": "1.0",
                    "reviewed_paths": "exact array of Work Unit source_files",
                    "axis_runs": "exactly one evidenced AxisRun per listed axis",
                    "hypotheses": "array<Hypothesis>, each with its origin_axis",
                },
                "required_axes": axes,
            })
            views.append(self.backend.submit(TaskSpec(
                task_id=self._task_id("generate_hypotheses_compact", work_unit_id),
                campaign_id=self.workflow.campaign_id,
                batch_id=self.workflow.batch_id,
                work_unit_id=work_unit_id,
                operation="generate_hypotheses_compact",
                input_refs=(input_ref, r1_event.payload_ref),
                required_output="compact-hypothesis-set/v1",
                budget={"agent_runs": 1},
            )))
        return tuple(views)

    def commit_r2_compact(self) -> str:
        expected = {
            self._task_id(
                "generate_hypotheses_compact", str(work_unit["work_unit_id"])
            ): work_unit
            for work_unit in self._work_units()
        }
        views = self._successful_tasks("generate_hypotheses_compact", expected)
        required_axes = {axis.value for axis in DiscoveryAxis}
        hypotheses = []
        axis_runs = []
        for view in views:
            work_unit = expected[view.task.task_id]
            work_unit_id = str(work_unit["work_unit_id"])
            value = self._read_output(view)
            self._validate_reviewed_paths(value, work_unit, view.task.task_id)
            raw_axis_runs = value.get("axis_runs")
            if not isinstance(raw_axis_runs, list):
                raise ModelError(f"compact R2 task requires axis_runs: {view.task.task_id}")
            parsed_axis_runs = [
                replace(AxisRun.from_dict(item), work_unit_id=work_unit_id)
                for item in raw_axis_runs
            ]
            axes_seen = [item.axis.value for item in parsed_axis_runs]
            if set(axes_seen) != required_axes or len(axes_seen) != len(required_axes):
                raise ModelError(f"compact R2 axis coverage mismatch: {view.task.task_id}")
            applicability = {item.axis.value: item.applicability for item in parsed_axis_runs}
            for item in value.get("hypotheses", []):
                hypothesis = Hypothesis.from_dict(item)
                if hypothesis.work_unit_id != work_unit_id:
                    raise ModelError(f"compact R2 hypothesis scope mismatch: {hypothesis.hypothesis_id}")
                if hypothesis.origin_axis not in required_axes:
                    raise ModelError(f"compact R2 hypothesis has unknown axis: {hypothesis.origin_axis}")
                if applicability[hypothesis.origin_axis] is not Applicability.APPLICABLE:
                    raise ModelError(
                        f"compact R2 non-applicable axis returned a hypothesis: {hypothesis.hypothesis_id}"
                    )
                allowed_families = {str(item).upper() for item in work_unit.get("category_families", [])}
                if hypothesis.mechanism.family not in allowed_families:
                    raise ModelError(f"compact R2 family outside plan: {hypothesis.hypothesis_id}")
                hypotheses.append(hypothesis)
            axis_runs.extend(parsed_axis_runs)
        axis_evidence: dict[str, list[str]] = {axis: [] for axis in required_axes}
        for run in axis_runs:
            axis_evidence[run.axis.value].extend(run.evidence_refs)
        return self.workflow.record_r2(
            hypotheses,
            axis_evidence=axis_evidence,
            axis_runs=axis_runs,
        )

    def commit_r2(self) -> str:
        expected: dict[str, tuple[Mapping[str, Any], str]] = {}
        for work_unit in self._work_units():
            work_unit_id = str(work_unit["work_unit_id"])
            for axis in DiscoveryAxis:
                expected[
                    self._task_id("generate_hypotheses", work_unit_id, axis.value)
                ] = (work_unit, axis.value)
        views = self._successful_tasks("generate_hypotheses:", expected, prefix=True)
        hypotheses = []
        axis_runs = []
        axis_evidence: dict[str, list[str]] = {axis.value: [] for axis in DiscoveryAxis}
        for view in views:
            work_unit, axis = expected[view.task.task_id]
            work_unit_id = str(work_unit["work_unit_id"])
            if view.output_ref is None:
                raise ModelError(f"successful task has no output: {view.task.task_id}")
            value = self._read_output(view)
            self._validate_reviewed_paths(value, work_unit, view.task.task_id)
            if not isinstance(value.get("axis_run"), dict):
                raise ModelError(f"R2 task output requires an axis_run: {view.task.task_id}")
            axis_run = AxisRun.from_dict(value["axis_run"])
            if axis_run.axis.value != axis:
                raise ModelError(f"R2 axis disposition mismatch: {view.task.task_id}")
            if axis_run.work_unit_id not in (None, work_unit_id):
                raise ModelError(f"R2 axis disposition Work Unit mismatch: {view.task.task_id}")
            axis_run = replace(axis_run, work_unit_id=work_unit_id)
            if axis_run.applicability is not Applicability.APPLICABLE and value.get("hypotheses"):
                raise ModelError(
                    f"non-applicable or deferred R2 axis returned hypotheses: {view.task.task_id}"
                )
            axis_evidence[axis].extend(axis_run.evidence_refs)
            axis_runs.append(axis_run)
            for item in value.get("hypotheses", []):
                hypothesis = Hypothesis.from_dict(item)
                if hypothesis.work_unit_id != work_unit_id or hypothesis.origin_axis != axis:
                    raise ModelError(
                        f"hypothesis task scope mismatch: {hypothesis.hypothesis_id}"
                    )
                hypotheses.append(hypothesis)
        return self.workflow.record_r2(
            hypotheses, axis_evidence=axis_evidence, axis_runs=axis_runs
        )

    def schedule_r3(self) -> tuple[TaskView, ...]:
        r1_event = self._require_stage("R1_COMPLETED")
        r2_event = self._require_stage("R2_COMPLETED")
        if r1_event.payload_ref is None or r2_event.payload_ref is None:
            raise ModelError("R1/R2 stage is missing its artifact")
        r2 = json.loads(self.workflow.manager.artifacts.get_bytes(r2_event.payload_ref))
        views = []
        for hypothesis in r2["hypotheses"]:
            hypothesis_id = str(hypothesis["hypothesis_id"])
            input_ref = self._put_json({
                "schema_version": "1.0",
                "operation": "verify_reachability",
                "snapshot_id": self.workflow.campaign.snapshot_id,
                "hypothesis": hypothesis,
                "analysis_contract": _VERIFICATION_INSTRUCTIONS,
                "output_contract": {
                    "schema_version": "1.0",
                    "verdict": "VerdictSubmission",
                },
            })
            views.append(self.backend.submit(TaskSpec(
                task_id=self._task_id("verify_reachability", hypothesis_id),
                campaign_id=self.workflow.campaign_id,
                batch_id=self.workflow.batch_id,
                work_unit_id=str(hypothesis["work_unit_id"]),
                operation="verify_reachability",
                input_refs=(input_ref, r1_event.payload_ref, r2_event.payload_ref),
                required_output="verdict-submission/v1",
                budget={"agent_runs": 1},
            )))
        return tuple(views)

    def commit_r3(self) -> str:
        r2_event = self._require_stage("R2_COMPLETED")
        if r2_event.payload_ref is None:
            raise ModelError("R2 stage is missing its artifact")
        r2 = json.loads(self.workflow.manager.artifacts.get_bytes(r2_event.payload_ref))
        expected = {
            self._task_id("verify_reachability", str(item["hypothesis_id"])): str(
                item["hypothesis_id"]
            )
            for item in r2["hypotheses"]
        }
        views = self._successful_tasks("verify_reachability", expected)
        submissions = []
        for view in views:
            value = self._read_output(view)
            verdict_value = value.get("verdict")
            if not isinstance(verdict_value, dict):
                raise ModelError(f"R3 task output requires a verdict: {view.task.task_id}")
            submission = VerdictSubmission.from_dict(verdict_value)
            if submission.hypothesis_id != expected[view.task.task_id]:
                raise ModelError(
                    f"R3 task returned another hypothesis: {submission.hypothesis_id}"
                )
            submissions.append(submission)
        return self.workflow.record_r3(submissions)

    def schedule_r35_refutations(self) -> tuple[TaskView, ...]:
        self._require_stage("R3_COMPLETED")
        views = []
        for hypothesis_id, work_unit_id in self._r35_eligible().items():
            assignments = (
                ("call-chain", AttackAngle.CALL_CHAIN.value),
                ("premise", "one of principal/configuration/deployment/impact"),
            )
            for slot, perspective in assignments:
                refuter_id = f"refuter:{self.workflow.batch_id}:{hypothesis_id}:{slot}"
                brief = self.workflow.build_refutation_brief(
                    hypothesis_id, refuter_id=refuter_id
                )
                input_ref = self._put_json({
                    **brief,
                    "operation": "refute_reachability",
                    "refuter_id": refuter_id,
                    "assigned_perspective": perspective,
                    "output_contract": {
                        "schema_version": "1.0",
                        "refutation": "Refutation",
                    },
                })
                views.append(self.backend.submit(TaskSpec(
                    task_id=self._task_id(
                        "refute_reachability", hypothesis_id, slot
                    ),
                    campaign_id=self.workflow.campaign_id,
                    batch_id=self.workflow.batch_id,
                    work_unit_id=work_unit_id,
                    operation="refute_reachability",
                    input_refs=(input_ref,),
                    required_output="refutation/v1",
                    budget={"agent_runs": 1},
                )))
        return tuple(views)

    def commit_r35_refutations(self) -> tuple[str, ...]:
        expected: dict[str, tuple[str, str, frozenset[AttackAngle]]] = {}
        premise_angles = frozenset({
            AttackAngle.PRINCIPAL,
            AttackAngle.CONFIGURATION,
            AttackAngle.DEPLOYMENT,
            AttackAngle.IMPACT,
        })
        for hypothesis_id in self._r35_eligible():
            for slot, angles in (
                ("call-chain", frozenset({AttackAngle.CALL_CHAIN})),
                ("premise", premise_angles),
            ):
                refuter_id = f"refuter:{self.workflow.batch_id}:{hypothesis_id}:{slot}"
                expected[
                    self._task_id("refute_reachability", hypothesis_id, slot)
                ] = (hypothesis_id, refuter_id, angles)
        views = self._successful_tasks("refute_reachability", expected)
        artifact_ids = []
        workers_by_hypothesis: dict[str, set[str]] = {}
        for view in views:
            hypothesis_id, refuter_id, allowed_angles = expected[view.task.task_id]
            if view.worker_id is None:
                raise ModelError(
                    f"R3.5 refutation task has no claimed worker: {view.task.task_id}"
                )
            value = self._read_output(view)
            refutation_value = value.get("refutation")
            if not isinstance(refutation_value, dict):
                raise ModelError(
                    f"R3.5 task output requires a refutation: {view.task.task_id}"
                )
            refutation = Refutation.from_dict(refutation_value)
            if (
                refutation.hypothesis_id != hypothesis_id
                or refutation.refuter_id != refuter_id
                or refutation.attack_angle not in allowed_angles
            ):
                raise ModelError(
                    f"R3.5 refutation task scope mismatch: {refutation.refutation_id}"
                )
            workers = workers_by_hypothesis.setdefault(hypothesis_id, set())
            if view.worker_id in workers:
                raise ModelError(
                    f"R3.5 refutations for a hypothesis require distinct claimed workers: {hypothesis_id}"
                )
            workers.add(view.worker_id)
            artifact_ids.append(self.workflow.record_refutation(refutation))
        return tuple(artifact_ids)

    def schedule_r35_adjudications(self) -> tuple[TaskView, ...]:
        views = []
        for hypothesis_id, work_unit_id in self._r35_eligible().items():
            refutations = self._r35_refutations(hypothesis_id)
            if len(refutations) != 2:
                raise ModelError(
                    f"R3.5 adjudication requires two refutations: {hypothesis_id}"
                )
            input_ref = self._put_json({
                "schema_version": "1.0",
                "operation": "adjudicate_refutations",
                "hypothesis_id": hypothesis_id,
                "refutations": refutations,
                "analysis_contract": (
                    "Resolve the verifier/refuter evidence. Use actor AUTO only when the "
                    "refuter verdicts agree; a split decision requires a human:* worker."
                ),
                "output_contract": {
                    "schema_version": "1.0",
                    "adjudication": "Adjudication",
                },
            })
            views.append(self.backend.submit(TaskSpec(
                task_id=self._task_id("adjudicate_refutations", hypothesis_id),
                campaign_id=self.workflow.campaign_id,
                batch_id=self.workflow.batch_id,
                work_unit_id=work_unit_id,
                operation="adjudicate_refutations",
                input_refs=(input_ref,),
                required_output="adjudication/v1",
                budget={"agent_runs": 1},
            )))
        return tuple(views)

    def commit_r35_adjudications(self) -> tuple[str, ...]:
        expected = {
            self._task_id("adjudicate_refutations", hypothesis_id): hypothesis_id
            for hypothesis_id in self._r35_eligible()
        }
        views = self._successful_tasks("adjudicate_refutations", expected)
        artifact_ids = []
        for view in views:
            hypothesis_id = expected[view.task.task_id]
            value = self._read_output(view)
            adjudication_value = value.get("adjudication")
            if not isinstance(adjudication_value, dict):
                raise ModelError(
                    f"R3.5 task output requires an adjudication: {view.task.task_id}"
                )
            adjudication = Adjudication.from_dict(adjudication_value)
            refuter_ids = {
                str(item["refuter_id"])
                for item in self._r35_refutations(hypothesis_id)
            }
            if adjudication.hypothesis_id != hypothesis_id:
                raise ModelError(
                    f"R3.5 adjudication task scope mismatch: {adjudication.adjudication_id}"
                )
            if adjudication.actor is AdjudicationActor.HUMAN:
                if view.worker_id is None or not view.worker_id.startswith("human:"):
                    raise ModelError("human adjudication requires a human:* worker")
            elif view.worker_id in refuter_ids:
                raise ModelError("a refuter cannot adjudicate its own R3.5 result")
            artifact_ids.append(self.workflow.record_adjudication(adjudication))
        return tuple(artifact_ids)

    def schedule_r35_revivals(self) -> tuple[TaskView, ...]:
        r2_event = self._require_stage("R2_COMPLETED")
        r3_event = self._require_stage("R3_COMPLETED")
        if r2_event.payload_ref is None or r3_event.payload_ref is None:
            raise ModelError("R2/R3 stage is missing its artifact")
        r2 = json.loads(self.workflow.manager.artifacts.get_bytes(r2_event.payload_ref))
        r3 = json.loads(self.workflow.manager.artifacts.get_bytes(r3_event.payload_ref))
        hypotheses = {
            str(item["hypothesis_id"]): item for item in r2["hypotheses"]
        }
        verdicts = {
            str(item["hypothesis_id"]): item
            for item in r3["verdicts"]
            if item["verdict"] == "UNREACHABLE"
        }
        selection_event = self.workflow._stage_event("REVIVAL_SAMPLE_SELECTED")
        if selection_event is not None and selection_event.payload_ref is not None:
            selected = sorted(
                self.workflow._read_artifact(selection_event.payload_ref)["hypothesis_ids"]
            )
        else:
            selected = sorted(verdicts)
            self.workflow.record_revival_selection(
                selected,
                rationale="review every initial R3 UNREACHABLE verdict",
                evidence_refs=(r3_event.payload_ref,),
            )
        views = []
        for hypothesis_id in selected:
            hypothesis = hypotheses[hypothesis_id]
            reviewer_id = (
                f"revival-reviewer:{self.workflow.batch_id}:{hypothesis_id}"
            )
            input_ref = self._put_json({
                "schema_version": "1.0",
                "operation": "review_unreachable_verdict",
                "reviewer_id": reviewer_id,
                "hypothesis": hypothesis,
                "verifier_verdict": verdicts[hypothesis_id],
                "analysis_contract": (
                    "Attempt to revive the rejected hypothesis using an alternate path, "
                    "principal, configuration, or deployment premise."
                ),
                "output_contract": {
                    "schema_version": "1.0",
                    "revival_review": "RevivalReview",
                },
            })
            views.append(self.backend.submit(TaskSpec(
                task_id=self._task_id("review_unreachable_verdict", hypothesis_id),
                campaign_id=self.workflow.campaign_id,
                batch_id=self.workflow.batch_id,
                work_unit_id=str(hypothesis["work_unit_id"]),
                operation="review_unreachable_verdict",
                input_refs=(input_ref,),
                required_output="revival-review/v1",
                budget={"agent_runs": 1},
            )))
        return tuple(views)

    def commit_r35_revivals(self) -> str:
        selection = self._require_stage("REVIVAL_SAMPLE_SELECTED")
        if selection.payload_ref is None:
            raise ModelError("R3.5 revival selection is missing its artifact")
        value = json.loads(
            self.workflow.manager.artifacts.get_bytes(selection.payload_ref)
        )
        expected = {
            self._task_id("review_unreachable_verdict", str(hypothesis_id)): str(
                hypothesis_id
            )
            for hypothesis_id in value["hypothesis_ids"]
        }
        views = self._successful_tasks("review_unreachable_verdict", expected)
        for view in views:
            hypothesis_id = expected[view.task.task_id]
            output = self._read_output(view)
            review_value = output.get("revival_review")
            if not isinstance(review_value, dict):
                raise ModelError(
                    f"R3.5 task output requires a revival review: {view.task.task_id}"
                )
            review = RevivalReview.from_dict(review_value)
            expected_reviewer = (
                f"revival-reviewer:{self.workflow.batch_id}:{hypothesis_id}"
            )
            if (
                review.hypothesis_id != hypothesis_id
                or review.reviewer_id != expected_reviewer
                or view.worker_id is None
            ):
                raise ModelError(
                    f"R3.5 revival task scope mismatch: {review.revival_id}"
                )
            self.workflow.record_revival_review(review)
        return self.workflow.complete_r35()

    def schedule_r4(self) -> tuple[TaskView, ...]:
        plan_event = self._require_stage("CATEGORY_AUDIT_PLAN_RECORDED")
        r2_event = self._require_stage("R2_COMPLETED")
        r3_event = self._require_stage("R3_COMPLETED")
        if any(event.payload_ref is None for event in (plan_event, r2_event, r3_event)):
            raise ModelError("R4 input stage is missing its artifact")
        value = json.loads(
            self.workflow.manager.artifacts.get_bytes(plan_event.payload_ref)
        )
        work_units = {
            str(item["work_unit_id"]): item for item in self._work_units()
        }
        r2 = json.loads(
            self.workflow.manager.artifacts.get_bytes(r2_event.payload_ref)
        )
        axis_runs = {
            (str(item["work_unit_id"]), str(item["axis"])): item
            for item in r2["axis_runs"]
        }
        hypotheses_by_work_unit: dict[str, list[Mapping[str, Any]]] = {}
        for hypothesis in r2["hypotheses"]:
            hypotheses_by_work_unit.setdefault(
                str(hypothesis["work_unit_id"]), []
            ).append(hypothesis)
        views = []
        screening_runs = []
        for category_plan in value["category_plans"]:
            category_plan_id = str(category_plan["category_plan_id"])
            work_unit_id = str(category_plan["work_unit_id"])
            planned_axes = tuple(str(axis) for axis in category_plan["discovery_axes"])
            if (
                planned_axes
                and not hypotheses_by_work_unit.get(work_unit_id)
                and all(
                    axis_runs.get((work_unit_id, axis), {}).get("applicability")
                    == Applicability.NOT_APPLICABLE.value
                    for axis in planned_axes
                )
            ):
                source_runs = [axis_runs[(work_unit_id, axis)] for axis in planned_axes]
                screening_runs.append(CategoryRun(
                    category_run_id=f"CR-screening-{category_plan_id}",
                    category_plan_id=category_plan_id,
                    work_unit_id=work_unit_id,
                    family=str(category_plan["family"]),
                    mechanism_variants_examined=(),
                    axis_runs=tuple(AxisRun.from_dict(item) for item in source_runs),
                    applicability=Applicability.NOT_APPLICABLE,
                    status=CategoryRunStatus.COMPLETE,
                    evidence_refs=tuple(dict.fromkeys(
                        reference
                        for item in source_runs
                        for reference in item["evidence_refs"]
                    )),
                    rationale=(
                        "All planned discovery axes were explicitly NOT_APPLICABLE "
                        "in R2; no category-analysis task was required."
                    ),
                    hypothesis_ids=(),
                    finding_ids=(),
                ))
                continue
            seed_card_ids = tuple(str(item) for item in category_plan["seed_card_ids"])
            mechanism_cards = [
                self.knowledge_catalog.cards[card_id]
                for card_id in seed_card_ids
            ]
            knowledge_context = self.knowledge_catalog.task_context(
                work_units[work_unit_id].get("languages", []),
                families=[str(category_plan["family"])],
                max_entries=10,
            ).to_dict()
            input_ref = self._put_json({
                "schema_version": "1.0",
                "operation": "run_category_audit",
                "snapshot_id": self.workflow.campaign.snapshot_id,
                "category_plan": category_plan,
                "work_unit": work_units[work_unit_id],
                "language_adapters": self._language_adapter_context(work_units[work_unit_id]),
                "knowledge_context": knowledge_context,
                "mechanism_cards": mechanism_cards,
                "analysis_contract": (
                    "Execute every planned discovery axis and mechanism variant. Record "
                    "evidence for positive and zero-finding outcomes; do not omit an axis."
                ),
                "output_contract": {
                    "schema_version": "1.0",
                    "category_run": "CategoryRun",
                },
            })
            views.append(self.backend.submit(TaskSpec(
                task_id=self._task_id("run_category_audit", category_plan_id),
                campaign_id=self.workflow.campaign_id,
                batch_id=self.workflow.batch_id,
                work_unit_id=work_unit_id,
                operation="run_category_audit",
                input_refs=(
                    input_ref,
                    plan_event.payload_ref,
                    r2_event.payload_ref,
                    r3_event.payload_ref,
                ),
                required_output="category-run/v1",
                budget={
                    str(name): int(amount)
                    for name, amount in category_plan.get("budget", {}).items()
                },
            )))
        if screening_runs:
            self.workflow.record_r4_screening_runs(screening_runs)
        return tuple(views)

    def commit_r4(self) -> str:
        plan_event = self._require_stage("CATEGORY_AUDIT_PLAN_RECORDED")
        if plan_event.payload_ref is None:
            raise ModelError("CategoryAuditPlan stage is missing its artifact")
        value = json.loads(
            self.workflow.manager.artifacts.get_bytes(plan_event.payload_ref)
        )
        plans = {
            str(item["category_plan_id"]): item for item in value["category_plans"]
        }
        screening_event = next((
            event for event in self.workflow.manager.store.list_batch_events(
                self.workflow.campaign_id,
                self.workflow.batch_id,
                event_type="R4_SCREENING_COVERAGE_RECORDED",
            )
        ), None)
        screening_runs = []
        screening_plan_ids = set()
        if screening_event is not None and screening_event.payload_ref:
            screening_artifact = json.loads(
                self.workflow.manager.artifacts.get_bytes(screening_event.payload_ref)
            )
            screening_runs = [
                CategoryRun.from_dict(item)
                for item in screening_artifact["category_runs"]
            ]
            screening_plan_ids = {
                run.category_plan_id for run in screening_runs
            }
        expected = {
            self._task_id("run_category_audit", category_plan_id): category_plan_id
            for category_plan_id in plans
            if category_plan_id not in screening_plan_ids
        }
        views = self._successful_tasks("run_category_audit", expected)
        runs = list(screening_runs)
        for view in views:
            category_plan_id = expected[view.task.task_id]
            output = self._read_output(view)
            run_value = output.get("category_run")
            if not isinstance(run_value, dict):
                raise ModelError(
                    f"R4 task output requires a CategoryRun: {view.task.task_id}"
                )
            run = CategoryRun.from_dict(run_value)
            plan = plans[category_plan_id]
            if (
                run.category_plan_id != category_plan_id
                or run.work_unit_id != str(plan["work_unit_id"])
                or run.family != str(plan["family"])
            ):
                raise ModelError(f"R4 task scope mismatch: {run.category_run_id}")
            runs.append(run)
        return self.workflow.record_r4(runs)

    def schedule_r5(self) -> tuple[TaskView, ...]:
        r2_event = self._require_stage("R2_COMPLETED")
        r3_event = self._require_stage("R3_COMPLETED")
        r4_event = self._require_stage("R4_COMPLETED")
        if any(event.payload_ref is None for event in (r2_event, r3_event, r4_event)):
            raise ModelError("R5 input stage is missing its artifact")
        r2 = json.loads(self.workflow.manager.artifacts.get_bytes(r2_event.payload_ref))
        r3 = json.loads(self.workflow.manager.artifacts.get_bytes(r3_event.payload_ref))
        hypotheses = {
            str(item["hypothesis_id"]): item for item in r2["hypotheses"]
        }
        work_units = {
            str(item["work_unit_id"]): item for item in self._work_units()
        }
        views = []
        for verdict in r3["verdicts"]:
            hypothesis_id = str(verdict["hypothesis_id"])
            hypothesis = hypotheses[hypothesis_id]
            work_unit = work_units[str(hypothesis["work_unit_id"])]
            family = str(hypothesis["mechanism"]["family"])
            harness_recipes = DEFAULT_HARNESS_CATALOG.recipes(
                work_unit.get("languages", []), family
            )
            input_ref = self._put_json({
                "schema_version": "1.0",
                "operation": "assess_experiment",
                "snapshot_id": self.workflow.campaign.snapshot_id,
                "hypothesis": hypothesis,
                "verdict": verdict,
                "language_adapters": self._language_adapter_context(work_unit),
                "harness_recipes": [asdict(recipe) for recipe in harness_recipes],
                "analysis_contract": (
                    "Decide whether an experiment is required. Empirical confirmation "
                    "requires a real-target or equivalence-proven confirmed experiment; "
                    "otherwise preserve the supported non-empirical disposition."
                ),
                "output_contract": {
                    "schema_version": "1.0",
                    "experiments": "array<Experiment>",
                    "assessment": "R5Assessment",
                },
            })
            views.append(self.backend.submit(TaskSpec(
                task_id=self._task_id("assess_experiment", hypothesis_id),
                campaign_id=self.workflow.campaign_id,
                batch_id=self.workflow.batch_id,
                work_unit_id=str(hypothesis["work_unit_id"]),
                operation="assess_experiment",
                input_refs=(
                    input_ref,
                    r3_event.payload_ref,
                    r4_event.payload_ref,
                ),
                required_output="r5-assessment/v1",
                budget={"agent_runs": 1},
            )))
        return tuple(views)

    def commit_r5(self) -> str:
        r3_event = self._require_stage("R3_COMPLETED")
        if r3_event.payload_ref is None:
            raise ModelError("R3 stage is missing its artifact")
        r3 = json.loads(self.workflow.manager.artifacts.get_bytes(r3_event.payload_ref))
        expected = {
            self._task_id("assess_experiment", str(item["hypothesis_id"])): str(
                item["hypothesis_id"]
            )
            for item in r3["verdicts"]
        }
        views = self._successful_tasks("assess_experiment", expected)
        experiments = []
        assessments = []
        for view in views:
            hypothesis_id = expected[view.task.task_id]
            output = self._read_output(view)
            experiment_values = output.get("experiments", [])
            assessment_value = output.get("assessment")
            if not isinstance(experiment_values, list) or not isinstance(
                assessment_value, dict
            ):
                raise ModelError(f"R5 task output is malformed: {view.task.task_id}")
            task_experiments = [
                Experiment.from_dict(item) for item in experiment_values
            ]
            assessment = R5Assessment.from_dict(assessment_value)
            if assessment.hypothesis_id != hypothesis_id or any(
                experiment.hypothesis_id != hypothesis_id
                for experiment in task_experiments
            ):
                raise ModelError(f"R5 task scope mismatch: {view.task.task_id}")
            task_experiment_ids = {
                experiment.experiment_id for experiment in task_experiments
            }
            if (
                assessment.experiment_id is not None
                and assessment.experiment_id not in task_experiment_ids
            ):
                raise ModelError(
                    f"R5 assessment references an experiment outside its task: "
                    f"{assessment.experiment_id}"
                )
            experiments.extend(task_experiments)
            assessments.append(assessment)
        return self.workflow.record_r5(experiments, assessments)

    def schedule_r6(self) -> TaskView:
        stage_refs = []
        for event_type in (
            "R1_COMPLETED",
            "R2_COMPLETED",
            "R3_COMPLETED",
            "R3_5_COMPLETED",
            "R4_COMPLETED",
            "R5_COMPLETED",
        ):
            event = self._require_stage(event_type)
            if event.payload_ref is None:
                raise ModelError(f"{event_type} is missing its artifact")
            stage_refs.append(event.payload_ref)
        input_ref = self._put_json({
            "schema_version": "1.0",
            "operation": "collect_batch_closure_evidence",
            "snapshot_id": self.workflow.campaign.snapshot_id,
            "batch_id": self.workflow.batch_id,
            "analysis_contract": (
                "Report observed constraints, unreviewed scope, residual risks, and "
                "reusable lessons. Do not report gate outcomes or budget usage; the "
                "coordinator derives those from canonical events."
            ),
            "output_contract": {
                "schema_version": "1.0",
                "closure": {
                    "constraints_observed": "array<string>",
                    "unreviewed_scope": "array<string>",
                    "residual_risks": "array<string>",
                    "lessons": "array<string>",
                },
            },
        })
        return self.backend.submit(TaskSpec(
            task_id=self._task_id("collect_batch_closure_evidence"),
            campaign_id=self.workflow.campaign_id,
            batch_id=self.workflow.batch_id,
            work_unit_id=self.workflow.batch_id,
            operation="collect_batch_closure_evidence",
            input_refs=(input_ref, *stage_refs),
            required_output="batch-closure-evidence/v1",
            budget={"agent_runs": 1},
        ))

    def commit_r6(self) -> Mapping[str, Any]:
        task_id = self._task_id("collect_batch_closure_evidence")
        view = self._successful_tasks(
            "collect_batch_closure_evidence", {task_id: self.workflow.batch_id}
        )[0]
        output = self._read_output(view)
        closure_value = output.get("closure")
        if not isinstance(closure_value, dict):
            raise ModelError(f"R6 task output requires closure evidence: {task_id}")
        forbidden = {"budget_used", "gates", "status"}.intersection(closure_value)
        if forbidden:
            raise ModelError(
                f"R6 worker cannot declare tool-owned fields: {sorted(forbidden)}"
            )
        closure = BatchClosure.from_dict({
            **closure_value,
            "budget_used": self._measured_task_budget(),
        })
        return self.workflow.close_r6(closure)

    def _measured_task_budget(self) -> dict[str, int]:
        completed = self.workflow.manager.store.list_batch_events(
            self.workflow.campaign_id,
            self.workflow.batch_id,
            entity_type="execution_task",
            event_type="TASK_COMPLETED",
        )
        budget: dict[str, int] = {"task_count": len(completed)}
        for event in completed:
            measurements = event.payload.get("measurements", {})
            if not isinstance(measurements, dict):
                continue
            for name, amount in measurements.items():
                if isinstance(amount, int) and amount >= 0:
                    budget[str(name)] = budget.get(str(name), 0) + amount
        return budget

    def _r35_refutations(self, hypothesis_id: str) -> list[Mapping[str, Any]]:
        return [
            json.loads(self.workflow.manager.artifacts.get_bytes(event.payload_ref))
            for event in self.workflow.manager.store.list_batch_events(
                self.workflow.campaign_id,
                self.workflow.batch_id,
                entity_type="hypothesis",
                entity_id=hypothesis_id,
                event_type="REFUTATION_SUBMITTED",
            )
            if event.payload_ref is not None
        ]

    def _r35_eligible(self) -> dict[str, str]:
        r2_event = self._require_stage("R2_COMPLETED")
        r3_event = self._require_stage("R3_COMPLETED")
        if r2_event.payload_ref is None or r3_event.payload_ref is None:
            raise ModelError("R2/R3 stage is missing its artifact")
        r2 = json.loads(self.workflow.manager.artifacts.get_bytes(r2_event.payload_ref))
        r3 = json.loads(self.workflow.manager.artifacts.get_bytes(r3_event.payload_ref))
        work_units = {
            str(item["hypothesis_id"]): str(item["work_unit_id"])
            for item in r2["hypotheses"]
        }
        return {
            str(item["hypothesis_id"]): work_units[str(item["hypothesis_id"])]
            for item in r3["verdicts"]
            if item["verdict"] == "REACHABLE"
            and item["evidence_grade"] == "edge_proven"
        }

    def _work_units(self) -> list[Mapping[str, Any]]:
        value = self.workflow.batch.manifest.get("work_units", [])
        if not isinstance(value, list) or not value:
            raise ModelError("Batch manifest has no canonical Work Units")
        return list(value)

    def _require_stage(self, event_type: str) -> Any:
        events = self.workflow.manager.store.list_batch_events(
            self.workflow.campaign_id,
            self.workflow.batch_id,
            event_type=event_type,
        )
        if not events:
            raise ModelError(f"required Batch stage is missing: {event_type}")
        return events[-1]

    def _successful_tasks(
        self,
        operation: str,
        expected: Mapping[str, Any],
        *,
        prefix: bool = False,
    ) -> tuple[TaskView, ...]:
        if not expected:
            return ()
        if not expected:
            return ()
        views = tuple(
            self.backend.list_tasks(
                operation=None if prefix else operation,
                operation_prefix=operation if prefix else None,
                batch_id=self.workflow.batch_id,
            )
        )
        actual = {view.task.task_id for view in views}
        if actual != set(expected):
            raise ModelError(
                f"execution task coverage mismatch: missing={sorted(set(expected) - actual)}"
            )
        incomplete = [
            view.task.task_id for view in views if view.status is not TaskStatus.SUCCEEDED
        ]
        if incomplete:
            raise ModelError(f"execution tasks are not successful: {sorted(incomplete)}")
        expected_output = _TASK_OUTPUT_CONTRACTS.get(operation)
        if expected_output is None:
            raise ModelError(f"no required output contract registered for operation: {operation}")
        mismatched_outputs = [
            view.task.task_id for view in views
            if view.task.required_output != expected_output
        ]
        if mismatched_outputs:
            raise ModelError(
                f"execution task output contract mismatch: {sorted(mismatched_outputs)}"
            )
        return views

    def _read_output(self, view: TaskView) -> Mapping[str, Any]:
        if view.output_ref is None:
            raise ModelError(f"successful task has no output: {view.task.task_id}")
        value = json.loads(self.workflow.manager.artifacts.get_bytes(view.output_ref))
        if not isinstance(value, dict):
            raise ModelError(f"task output must be a JSON object: {view.task.task_id}")
        if value.get("schema_version") != "1.0":
            raise ModelError(f"task output schema_version mismatch: {view.task.task_id}")
        return value

    def _put_json(self, value: Mapping[str, Any]) -> str:
        if "output_contract" in value:
            value = {**value, "output_discipline": _OUTPUT_DISCIPLINE}
        encoded = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        return self.workflow.manager.artifacts.put_text(encoded).artifact_id

    @staticmethod
    def _validate_reviewed_paths(
        value: Mapping[str, Any],
        work_unit: Mapping[str, Any],
        task_id: str,
    ) -> None:
        reviewed = value.get("reviewed_paths")
        if not isinstance(reviewed, list) or any(
            not isinstance(item, str) for item in reviewed
        ):
            raise ModelError(f"task output requires reviewed_paths: {task_id}")
        expected = {str(item) for item in work_unit.get("source_files", [])}
        actual = set(reviewed)
        if actual != expected or len(reviewed) != len(actual):
            raise ModelError(
                f"task reviewed path coverage mismatch: {task_id}; "
                f"missing={sorted(expected - actual)}, extra={sorted(actual - expected)}"
            )

    def _task_id(self, operation: str, *parts: str) -> str:
        source = ":".join((
            self.workflow.campaign_id,
            self.workflow.batch_id,
            operation,
            *parts,
        ))
        return f"TASK-{hashlib.sha256(source.encode('utf-8')).hexdigest()[:20]}"