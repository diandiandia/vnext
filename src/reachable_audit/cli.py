"""Command-line interface for Campaign planning, execution, and closure."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any

from .campaign import CampaignManager, SnapshotError, detect_clean_git_snapshot
from .adapters.languages import LANGUAGE_ADAPTERS
from .compatibility import scan_runtime_compatibility
from .campaign_closure import CampaignCloser
from .analysis_models import (
    Adjudication,
    AxisRun,
    BatchClosure,
    CampaignClosure,
    BoundaryReview,
    CategoryRun,
    ExternalObservation,
    Experiment,
    Finding,
    HandoffResolution,
    Hypothesis,
    MechanismCard,
    Refutation,
    R5Assessment,
    RevivalReview,
    SkillIssue,
    Surface,
    VerdictSubmission,
)
from .batch_workflow import BatchWorkflow
from .evaluation import evaluate_release, write_evaluation_report
from .experiments.environment import probe_toolchain
from .experiments.runner import run_harness
from .execution import DiscoveryCoordinator, ManualExecutionBackend, TaskResult
from .runtime_policy import (
    R2_LARGE_SOURCE_FILE_WARNING_BYTES,
    TASK_OUTPUT_MAX_BYTES,
)
from .drift import resolve_snapshot_drift
from .graph import build_component_graph
from .handoffs import HandoffResolver
from .inventory import build_inventory
from .knowledge import create_category_audit_plans
from .knowledge_catalog import KnowledgeCatalog, default_knowledge_root
from .plan_models import BoundaryEdge, PlanPathDisposition, PlanPathState, WorkUnit
from .planning import (
    DEFAULT_MAX_SOURCE_FILES_PER_WORK_UNIT, amend_plan, create_audit_plan,
    discovery_output_floor_bytes, forecast_plan_cost,
)
from .resource_cleanup import (
    cleanup_campaign_resources,
    create_campaign_temp_directory,
    register_process_group,
)
from .models import CampaignAuditMode, ModelError, dynamic_execution_policy


def _default_cli_state_dir(target: str | Path) -> Path:
    target_root = Path(target).resolve()
    configured_state_home = os.environ.get("XDG_STATE_HOME", "").strip()
    state_home = Path(configured_state_home).expanduser() if configured_state_home else Path()
    if not configured_state_home or not state_home.is_absolute():
        state_home = Path.home() / ".local" / "state"
    state_home = state_home.resolve()
    identity = hashlib.sha256(os.fsencode(str(target_root))).hexdigest()[:24]
    state_dir = (state_home / "reachable-audit" / identity).resolve()
    if target_root == state_dir or target_root in state_dir.parents:
        raise ValueError(
            "default state directory would be inside the target; set XDG_STATE_HOME "
            "outside the target or pass --state-dir explicitly"
        )
    return state_dir


def _cli_state_dir(
    target: str | Path,
    requested: str | Path | None,
    *,
    prefer_external: bool = False,
) -> str | Path:
    if requested is not None:
        target_root = Path(target).resolve()
        state_path = Path(requested)
        state_path = (
            state_path if state_path.is_absolute() else target_root / state_path
        ).resolve()
        if target_root == state_path or target_root in state_path.parents:
            if prefer_external or not (state_path / "state.db").is_file():
                raise ValueError(
                    "state directory resolves inside the target; use an absolute "
                    "--state-dir outside the frozen source tree"
                )
            print(
                "warning: using an existing in-target state store for legacy recovery; "
                "this is not an isolated source-search boundary",
                file=sys.stderr,
            )
        return state_path
    target_root = Path(target).resolve()
    new_state = _default_cli_state_dir(target_root)
    legacy_state = target_root / ".audit_vnext"
    legacy_exists = any(
        (legacy_state / filename).is_file()
        for filename in ("state.db", "campaign.json")
    )
    new_exists = any(
        (new_state / filename).is_file()
        for filename in ("state.db", "campaign.json")
    )
    if legacy_exists and new_exists:
        raise ValueError(
            "both legacy and external Campaign state exist; pass --state-dir "
            f"explicitly (legacy: {legacy_state}; external: {new_state})"
        )
    if legacy_exists and not prefer_external:
        return legacy_state
    return new_state


def _print(value: Any) -> None:
    def default(item: Any) -> Any:
        return getattr(item, "value", str(item))

    print(json.dumps(value, ensure_ascii=False, indent=2, default=default))


def _handle_init(arguments: argparse.Namespace) -> int:
    snapshot_id = arguments.snapshot_id or detect_clean_git_snapshot(arguments.target)
    if arguments.max_screening_fraction is not None and not (
        0 <= arguments.max_screening_fraction <= 1
    ):
        raise ValueError("max-screening-fraction must be between 0 and 1")
    if (
        arguments.max_delegated_agent_runs is not None
        and arguments.max_delegated_agent_runs < 0
    ):
        raise ValueError("max-delegated-agent-runs must be non-negative")
    if (
        arguments.max_wall_seconds is not None
        and arguments.max_wall_seconds <= 0
    ):
        raise ValueError("max-wall-seconds must be a positive integer")
    budget = {}
    if arguments.max_screening_fraction is not None:
        budget["max_screening_fraction"] = arguments.max_screening_fraction
    if arguments.max_delegated_agent_runs is not None:
        budget["max_delegated_agent_runs"] = arguments.max_delegated_agent_runs
    if arguments.max_wall_seconds is not None:
        budget["max_wall_seconds"] = arguments.max_wall_seconds
    if arguments.require_host_worker_attestation:
        budget["require_host_worker_attestation"] = True
    if arguments.task_budget_policy:
        from .task_budget import validate_policy
        budget["task_budget_policy"] = json.loads(
            Path(arguments.task_budget_policy).read_text(encoding="utf-8")
        )
        validate_policy(budget["task_budget_policy"])
    with CampaignManager(arguments.target, arguments.state_dir) as manager:
        from .store import NotFoundError
        try:
            previous_constraints = manager.store.get_campaign(arguments.campaign_id).constraints
        except NotFoundError:
            previous_constraints = ()
        extras = tuple(
            policy for flag, policy in (
                (arguments.coverage_critic, "coverage_critic_v1"),
                (arguments.domain_guidance, "domain_guidance_v1"),
            ) if flag is True or (flag is None and policy in previous_constraints)
        )
        defer_splits = arguments.defer_r35_splits
        if defer_splits is None:
            try:
                existing = manager.store.get_campaign(arguments.campaign_id)
            except NotFoundError:
                defer_splits = True
            else:
                defer_splits = "defer_r35_splits" in existing.constraints
        campaign = manager.create_campaign(
            snapshot_id=snapshot_id,
            campaign_id=arguments.campaign_id,
            budget=budget or None,
            audit_mode=CampaignAuditMode(arguments.audit_mode),
            history_source_campaign_ids=tuple(arguments.history_source),
            constraints=(
                (("experimental_go_hotspots",) if arguments.experimental_go_hotspots else ())
                + (("experimental_java_hotspots",) if arguments.experimental_java_hotspots else ())
                + (("static_challenges",) if arguments.static_challenges else ())
                + (("static_only",) if arguments.static_only else ())
                + (("defer_r35_splits",) if defer_splits else ())
                + extras
            ),
        )
        _print(asdict(campaign))
    return 0


def _handle_status(arguments: argparse.Namespace) -> int:
    from .store import AuditStore

    target_root = Path(arguments.target).resolve()
    if not target_root.is_dir():
        raise ValueError(f"target root is not a directory: {target_root}")
    state_path = Path(arguments.state_dir)
    database = state_path / "state.db"
    if not database.is_file():
        raise ValueError(
            f"Campaign state database does not exist: {database}; "
            "check --state-dir or explicitly initialize a new Campaign"
        )
    with AuditStore(database, read_only=True) as store:
        stored_campaigns = store.list_campaigns()
        target_campaigns = [
            campaign for campaign in stored_campaigns
            if Path(campaign.target_root).resolve() == target_root
        ]
        if not target_campaigns:
            raise ValueError("state store has no Campaigns for this target")
        campaigns = []
        for campaign in target_campaigns:
            campaigns.append({
                **asdict(campaign),
                "dynamic_execution_policy": dynamic_execution_policy(campaign),
                "batches": [
                    asdict(batch)
                    for batch in store.list_batches(campaign.campaign_id)
                ],
            })
        _print({"campaigns": campaigns})
    return 0


def _handle_wall_budget_amend(arguments: argparse.Namespace) -> int:
    with CampaignManager(arguments.target, arguments.state_dir) as manager:
        result = manager.amend_wall_budget(
            arguments.campaign_id,
            arguments.approved_max_wall_seconds,
            reason=arguments.reason,
            evidence_refs=tuple(arguments.evidence_ref),
            actor=arguments.actor,
        )
        _print({
            **asdict(result),
            "effective_max_wall_seconds": manager.effective_wall_limit_seconds(
                arguments.campaign_id
            ),
        })
    return 0


def _handle_skill_backlog(arguments: argparse.Namespace) -> int:
    with CampaignManager(arguments.target, arguments.state_dir) as manager:
        campaign = manager.store.get_campaign(arguments.campaign_id)
        source_ids = (
            campaign.history_source_campaign_ids
            if campaign.audit_mode is CampaignAuditMode.FOLLOW_UP
            else ()
        )
        _print({
            "purpose": "tool_regression_only",
            "campaign_id": campaign.campaign_id,
            "pending_issues": manager.load_skill_regression_backlog(source_ids),
        })
    return 0


def _handle_evidence_register(arguments: argparse.Namespace) -> int:
    value = json.loads(Path(arguments.input).read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("paths"), list):
        raise ValueError("evidence registration input requires a paths array and reason")
    if not isinstance(value.get("reason"), str):
        raise ValueError("evidence registration requires a reason string")
    with CampaignManager(arguments.target, arguments.state_dir) as manager:
        artifact_id = manager.register_evidence_files(
            arguments.campaign_id, value["paths"], reason=value["reason"],
        )
        _print({"artifact_id": artifact_id})
    return 0


def _handle_skill_review(arguments: argparse.Namespace) -> int:
    value = json.loads(Path(arguments.input).read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("skill_issues"), list):
        raise ValueError("skill review input requires a skill_issues array")
    with CampaignManager(arguments.target, arguments.state_dir) as manager:
        artifact_id = manager.record_skill_review(
            arguments.campaign_id,
            tuple(SkillIssue.from_dict(item) for item in value["skill_issues"]),
        )
        _print({"artifact_id": artifact_id})
    return 0


def _handle_resource_register_process(arguments: argparse.Namespace) -> int:
    with CampaignManager(arguments.target, arguments.state_dir) as manager:
        event_id = register_process_group(
            manager,
            arguments.campaign_id,
            arguments.process_group_id,
            label=arguments.label,
        )
        _print({"event_id": event_id})
    return 0


def _handle_resource_create_temp(arguments: argparse.Namespace) -> int:
    with CampaignManager(arguments.target, arguments.state_dir) as manager:
        path = create_campaign_temp_directory(
            manager, arguments.campaign_id, label=arguments.label
        )
        _print({"path": str(path)})
    return 0


def _handle_resource_cleanup(arguments: argparse.Namespace) -> int:
    with CampaignManager(arguments.target, arguments.state_dir) as manager:
        _print(cleanup_campaign_resources(manager, arguments.campaign_id))
    return 0


def _handle_inventory(arguments: argparse.Namespace) -> int:
    with CampaignManager(arguments.target, arguments.state_dir) as manager:
        campaign = manager.store.get_campaign(arguments.campaign_id)
        inventory = build_inventory(arguments.target, campaign.snapshot_id)
        artifact_id = manager.record_inventory(
            campaign_id=arguments.campaign_id, inventory=inventory
        )
        _print({
            "artifact_id": artifact_id,
            "components": len(inventory.components),
            "source_files": len(inventory.source_files),
        })
    return 0


def _handle_graph(arguments: argparse.Namespace) -> int:
    with CampaignManager(arguments.target, arguments.state_dir) as manager:
        inventory = manager.load_inventory(arguments.campaign_id)
        graph = build_component_graph(arguments.target, inventory)
        artifact_id = manager.record_component_graph(
            campaign_id=arguments.campaign_id, graph=graph
        )
        _print({
            "artifact_id": artifact_id,
            "build_units": len(graph.build_units),
            "edges": len(graph.edges),
            "diagnostics": [asdict(item) for item in graph.diagnostics],
        })
    return 0


def _handle_toolchain_probe(arguments: argparse.Namespace) -> int:
    adapter = LANGUAGE_ADAPTERS.get(arguments.language)
    if adapter is None:
        raise ValueError(f"no registered language adapter: {arguments.language}")
    results = [probe_toolchain(command) for command in adapter.toolchain_probe]
    _print({
        "language": adapter.language_id,
        "probes": [asdict(result) for result in results],
    })
    return 0


def _handle_compatibility_scan(arguments: argparse.Namespace) -> int:
    report = scan_runtime_compatibility(
        arguments.root,
        [
            line.strip()
            for line in Path(arguments.forbidden_tokens_file).read_text(
                encoding="utf-8"
            ).splitlines()
            if line.strip()
        ] if arguments.forbidden_tokens_file else (),
    )
    _print(report)
    return 0 if report["passed"] else 1


def _handle_harness_run(arguments: argparse.Namespace) -> int:
    value = json.loads(Path(arguments.input).read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("command"), list):
        raise ValueError("harness-run input requires a command argv array")
    with CampaignManager(arguments.target, arguments.state_dir) as manager:
        result = run_harness(
            manager,
            arguments.campaign_id,
            command=value["command"],
            profile=value.get("profile"),
            isolation=arguments.isolation or value.get("isolation"),
            cwd=str(value.get("cwd", ".")),
            timeout_seconds=int(value.get("timeout_seconds", 30)),
            environment=value.get("environment"),
            output_limit_bytes=int(value.get("output_limit_bytes", 1_048_576)),
            cpu_limit_seconds=(
                int(value["cpu_limit_seconds"])
                if value.get("cpu_limit_seconds") is not None else None
            ),
            memory_limit_bytes=(
                int(value["memory_limit_bytes"])
                if value.get("memory_limit_bytes") is not None else None
            ),
            hypothesis_id=(
                str(value["hypothesis_id"])
                if value.get("hypothesis_id") is not None else None
            ),
            execution_provenance=value.get("execution_provenance"),
        )
        _print(result)
    return 0


def _handle_plan(arguments: argparse.Namespace) -> int:
    boundaries = []
    if arguments.boundaries:
        boundary_value = json.loads(Path(arguments.boundaries).read_text(encoding="utf-8"))
        if not isinstance(boundary_value, list):
            raise ValueError("boundaries must be a JSON array")
        boundaries = [BoundaryEdge.from_dict(item) for item in boundary_value]
    path_dispositions = []
    if arguments.path_dispositions:
        path_value = json.loads(
            Path(arguments.path_dispositions).read_text(encoding="utf-8")
        )
        if not isinstance(path_value, list):
            raise ValueError("path dispositions must be a JSON array")
        path_dispositions = [
            PlanPathDisposition.from_dict(item) for item in path_value
        ]
    with CampaignManager(arguments.target, arguments.state_dir) as manager:
        inventory = manager.load_inventory(arguments.campaign_id)
        graph = manager.load_component_graph(arguments.campaign_id)
        plan = create_audit_plan(
            campaign_id=arguments.campaign_id,
            inventory=inventory,
            category_families=arguments.categories.split(","),
            boundary_edges=[*graph.edges, *boundaries],
            path_dispositions=path_dispositions,
            max_source_files_per_work_unit=arguments.max_work_unit_files,
            max_source_files_per_batch=arguments.max_batch_files,
            max_work_units_per_batch=arguments.max_batch_work_units,
        )
        forecast = None
        if arguments.cost_profile:
            profile = json.loads(
                Path(arguments.cost_profile).read_text(encoding="utf-8")
            )
            if not isinstance(profile, dict):
                raise ValueError("cost profile must be a JSON object")
            forecast = forecast_plan_cost(plan, profile)
        files_by_unit = {
            unit.work_unit_id: unit.source_files for unit in plan.work_units
        }
        floor_by_unit = {
            unit.work_unit_id: discovery_output_floor_bytes(unit)
            for unit in plan.work_units
        }
        boundary_reviews_by_unit = {
            unit.work_unit_id: len(unit.boundary_edge_ids)
            for unit in plan.work_units
        }

        def _size(path: str) -> int:
            try:
                return (manager.target_root / path).stat().st_size
            except OSError as error:
                raise OSError(
                    f"cannot measure planned source file size: {path}"
                ) from error

        source_sizes = {
            path: _size(path)
            for paths in files_by_unit.values()
            for path in paths
        }
        artifact_id = manager.record_plan(
            campaign_id=arguments.campaign_id, plan=plan, inventory=inventory
        )

        _print({
            "artifact_id": artifact_id,
            "plan_id": plan.plan_id,
            "work_units": len(plan.work_units),
            "omitted_empty_components": list(plan.omitted_empty_component_ids),
            "path_scope_counts": {
                state.value: sum(
                    item.state is state for item in plan.path_dispositions
                )
                for state in PlanPathState
            },
            "batches": len(plan.batches),
            "handoffs": len(plan.handoffs),
            "output_ceiling_bytes": TASK_OUTPUT_MAX_BYTES,
            "oversize_work_units": [
                {
                    "work_unit_id": unit_id,
                    "estimated_r1_output_floor_bytes": floor,
                    "boundary_review_count": boundary_reviews_by_unit[unit_id],
                }
                for unit_id, floor in sorted(floor_by_unit.items())
                if floor > TASK_OUTPUT_MAX_BYTES
            ],
            "r2_large_source_files": [
                {
                    "path": path,
                    "size_bytes": size,
                    "work_unit_id": unit_id,
                    "warning_threshold_bytes": R2_LARGE_SOURCE_FILE_WARNING_BYTES,
                    "action": (
                        "review against host context/time limits; if full source "
                        "coverage cannot be completed, do not claim it and resolve "
                        "the path through an approved scope decision"
                    ),
                }
                for unit_id, paths in sorted(files_by_unit.items())
                for path in paths
                if (size := source_sizes[path]) >= R2_LARGE_SOURCE_FILE_WARNING_BYTES
            ],
            "batch_summaries": [
                {
                    "batch_id": batch.batch_id,
                    "work_units": len(batch.work_unit_ids),
                    "source_files": batch.source_file_count,
                    "source_bytes": sum(
                        source_sizes[path]
                        for unit_id in batch.work_unit_ids
                        for path in files_by_unit[unit_id]
                    ),
                    "max_estimated_r1_output_floor_bytes": max(
                        floor_by_unit[unit_id] for unit_id in batch.work_unit_ids
                    ),
                    "max_boundary_review_count": max(
                        boundary_reviews_by_unit[unit_id]
                        for unit_id in batch.work_unit_ids
                    ),
                }
                for batch in plan.batches
            ],
            "cost_forecast": forecast,
        })
    return 0


def _handle_amend(arguments: argparse.Namespace) -> int:
    with CampaignManager(arguments.target, arguments.state_dir) as manager:
        inventory = manager.load_inventory(arguments.campaign_id)
        base_plan = manager.load_audit_plan(
            arguments.campaign_id, arguments.base_plan_id
        )
        amended_plan, amendment = amend_plan(
            base_plan,
            reason=arguments.reason,
            max_source_files_per_batch=arguments.max_batch_files,
            max_work_units_per_batch=arguments.max_batch_work_units,
        )
        artifact_id = manager.record_plan_amendment(
            campaign_id=arguments.campaign_id,
            base_plan=base_plan,
            amended_plan=amended_plan,
            amendment=amendment,
            inventory=inventory,
        )
        _print({
            "artifact_id": artifact_id,
            "amendment_id": amendment.amendment_id,
            "base_plan_id": base_plan.plan_id,
            "amended_plan_id": amended_plan.plan_id,
            "batches": len(amended_plan.batches),
        })
    return 0


def _handle_batch_stage(arguments: argparse.Namespace) -> int:
    with CampaignManager(arguments.target, arguments.state_dir) as manager:
        workflow = BatchWorkflow(manager, arguments.campaign_id, arguments.batch_id)
        if arguments.command == "r0":
            artifact_id = workflow.run_r0()
            _print({
                "artifact_id": artifact_id,
                "supporting_evidence_preflight": workflow.supporting_evidence_preflight(),
            })
        elif arguments.command == "batch-report":
            _print(workflow.build_r0_r3_report())
        else:
            value = json.loads(Path(arguments.input).read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise ValueError("stage input must be a JSON object")
            if arguments.command == "r1":
                artifact_id = workflow.record_r1(
                    [Surface.from_dict(item) for item in value.get("surfaces", [])],
                    [
                        BoundaryReview.from_dict(item)
                        for item in value.get("boundary_reviews", [])
                    ],
                )
            elif arguments.command == "r2":
                if not isinstance(value.get("axis_runs"), list):
                    raise ValueError(
                        "R2 input requires axis_runs for every executed axis"
                    )
                artifact_id = workflow.record_r2(
                    [Hypothesis.from_dict(item) for item in value.get("hypotheses", [])],
                    axis_evidence=value.get("axis_evidence", {}),
                    axis_runs=[AxisRun.from_dict(item) for item in value["axis_runs"]],
                )
            else:
                artifact_id = workflow.record_r3([
                    VerdictSubmission.from_dict(item)
                    for item in value.get("verdicts", [])
                ])
            _print({"artifact_id": artifact_id})
    return 0


def _handle_handoff(arguments: argparse.Namespace) -> int:
    value = json.loads(Path(arguments.input).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Handoff input must be a JSON object")
    with CampaignManager(arguments.target, arguments.state_dir) as manager:
        plan = manager.load_audit_plan(arguments.campaign_id, arguments.plan_id)
        resolver = HandoffResolver(manager, arguments.campaign_id, plan)
        if arguments.command == "handoff-resolve":
            if "resolutions" in value:
                if not isinstance(value["resolutions"], list):
                    raise ValueError("Handoff resolutions must be an array")
                artifact_ids = resolver.resolve_many(tuple(
                    HandoffResolution.from_dict(item)
                    for item in value["resolutions"]
                ))
                _print({"artifact_ids": artifact_ids})
            else:
                artifact_id = resolver.resolve(HandoffResolution.from_dict(value))
                _print({"artifact_id": artifact_id})
        else:
            _print(resolver.integrate(
                arguments.handoff_id,
                known_chain_prefix=value.get("known_chain_prefix", []),
                evidence_refs=value.get("evidence_refs", []),
            ))
    return 0


def _handle_r35(arguments: argparse.Namespace) -> int:
    with CampaignManager(arguments.target, arguments.state_dir) as manager:
        workflow = BatchWorkflow(
            manager, arguments.campaign_id, arguments.batch_id
        )
        if arguments.command == "r35-complete":
            artifact_id = workflow.complete_r35()
        else:
            value = json.loads(Path(arguments.input).read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise ValueError("R3.5 input must be a JSON object")
            if arguments.command == "r35-refute":
                artifact_id = workflow.record_refutation(
                    Refutation.from_dict(value)
                )
            elif arguments.command == "r35-adjudicate":
                artifact_id = workflow.record_adjudication(
                    Adjudication.from_dict(value)
                )
            elif arguments.command == "r35-revival-review":
                artifact_id = workflow.record_revival_review(
                    RevivalReview.from_dict(value)
                )
            else:
                artifact_id = workflow.record_revival_selection(
                    value.get("hypothesis_ids", []),
                    rationale=str(value.get("rationale", "")),
                    evidence_refs=value.get("evidence_refs", []),
                )
        _print({"artifact_id": artifact_id})
    return 0


def _handle_category_plan_or_r4(arguments: argparse.Namespace) -> int:
    value = json.loads(Path(arguments.input).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("R4 input must be a JSON object")
    with CampaignManager(arguments.target, arguments.state_dir) as manager:
        workflow = BatchWorkflow(
            manager, arguments.campaign_id, arguments.batch_id
        )
        if arguments.command == "category-plan":
            work_units = [
                WorkUnit.from_dict(item)
                for item in workflow.batch.manifest.get("work_units", [])
            ]
            if "cards" in value:
                raise ValueError(
                    "category-plan accepts approved card_ids, not inline card definitions"
                )
            catalog = KnowledgeCatalog.load(default_knowledge_root())
            card_ids = set(str(item) for item in value.get("card_ids", []))
            if card_ids:
                unknown_cards = card_ids - set(catalog.cards)
                if unknown_cards:
                    raise ValueError(
                        f"unknown approved Mechanism Card IDs: {sorted(unknown_cards)}"
                    )
                selected_cards = [catalog.cards[item] for item in sorted(card_ids)]
            else:
                selected_cards = list(catalog.cards.values())
            plans = create_category_audit_plans(
                work_units,
                [MechanismCard.from_dict(item) for item in selected_cards],
                budget=value.get("budget", {}),
            )
            artifact_id = workflow.record_category_audit_plan(plans)
        else:
            artifact_id = workflow.record_r4([
                CategoryRun.from_dict(item)
                for item in value.get("category_runs", [])
            ])
        _print({"artifact_id": artifact_id})
    return 0


def _handle_r5_or_metrics(arguments: argparse.Namespace) -> int:
    with CampaignManager(arguments.target, arguments.state_dir) as manager:
        workflow = BatchWorkflow(
            manager, arguments.campaign_id, arguments.batch_id
        )
        if arguments.command == "metrics":
            _print(workflow.build_transmission_metrics())
        else:
            value = json.loads(Path(arguments.input).read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise ValueError("R5 input must be a JSON object")
            artifact_id = workflow.record_r5(
                [Experiment.from_dict(item) for item in value.get("experiments", [])],
                [R5Assessment.from_dict(item) for item in value.get("assessments", [])],
            )
            _print({"artifact_id": artifact_id})
    return 0


def _handle_finding_or_r6(arguments: argparse.Namespace) -> int:
    value = json.loads(Path(arguments.input).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Finding/R6 input must be a JSON object")
    with CampaignManager(arguments.target, arguments.state_dir) as manager:
        workflow = BatchWorkflow(
            manager, arguments.campaign_id, arguments.batch_id
        )
        if arguments.command == "finding":
            _print({
                "artifact_id": workflow.record_finding(Finding.from_dict(value))
            })
        else:
            _print(workflow.close_r6(BatchClosure.from_dict(value)))
    return 0


def _handle_r5_observation_register(arguments: argparse.Namespace) -> int:
    value = json.loads(Path(arguments.input).read_text(encoding="utf-8"))
    with CampaignManager(arguments.target, arguments.state_dir) as manager:
        artifact_id = manager.record_external_observation(
            ExternalObservation.from_dict(value)
        )
        _print({
            "artifact_id": artifact_id,
            "effect": "EVIDENCE_ONLY_NOT_CONFIRMING",
        })
    return 0


def _handle_drift_resolve(arguments: argparse.Namespace) -> int:
    value = json.loads(Path(arguments.input).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("drift resolution input must be a JSON object")
    with CampaignManager(arguments.target, arguments.state_dir) as manager:
        event_id = resolve_snapshot_drift(
            manager,
            campaign_id=arguments.campaign_id,
            drift_event_id=arguments.drift_event_id,
            evidence_refs=tuple(str(item) for item in value.get("evidence_refs", [])),
        )
        _print({"event_id": event_id})
    return 0


def _handle_batch_add(arguments: argparse.Namespace) -> int:
    manifest = json.loads(Path(arguments.manifest).read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("batch manifest must be a JSON object")
    with CampaignManager(arguments.target, arguments.state_dir) as manager:
        batch = manager.add_batch(
            campaign_id=arguments.campaign_id,
            batch_id=arguments.batch_id,
            manifest=manifest,
        )
        _print(asdict(batch))
    return 0


def _handle_campaign_abort(arguments: argparse.Namespace) -> int:
    value = json.loads(Path(arguments.input).read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("skill_issues"), list):
        raise ValueError("campaign-abort input requires a skill_issues array")
    with CampaignManager(arguments.target, arguments.state_dir) as manager:
        report = manager.abort_campaign(
            arguments.campaign_id,
            reason=arguments.reason,
            skill_issues=tuple(
                SkillIssue.from_dict(item) for item in value["skill_issues"]
            ),
        )
        _print(report)
    return 0


def _handle_campaign_close(arguments: argparse.Namespace) -> int:
    value = json.loads(Path(arguments.input).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Campaign closure input must be a JSON object")
    with CampaignManager(arguments.target, arguments.state_dir) as manager:
        plan = manager.load_audit_plan(arguments.campaign_id, arguments.plan_id)
        report = CampaignCloser(manager, arguments.campaign_id, plan).close(
            CampaignClosure.from_dict(value)
        )
        _print(report)
    return 0


def _handle_shadow_evaluate(arguments: argparse.Namespace) -> int:
    value = json.loads(Path(arguments.input).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("shadow evaluation input must be a JSON object")
    report = evaluate_release(value)
    if arguments.output:
        write_evaluation_report(arguments.output, report)
    _print(report)
    return 0


def _handle_task(arguments: argparse.Namespace) -> int:
    with CampaignManager(arguments.target, arguments.state_dir) as manager:
        backend = ManualExecutionBackend(manager, arguments.campaign_id)
        if arguments.command == "task-list":
            tasks = []
            for view in backend.list_tasks(
                operation=arguments.operation,
                batch_id=arguments.batch_id,
                operation_prefix=arguments.operation_prefix,
            ):
                task = asdict(view)
                if view.status.value == "FAILED":
                    if view.attempt >= view.task.max_attempts:
                        task["operator_hint"] = (
                            "attempts exhausted; authorize one bounded retry with: "
                            f"task-retry {arguments.target} {arguments.campaign_id} "
                            f"{view.task.task_id} --reason <reason>"
                        )
                    else:
                        task["operator_hint"] = (
                            "retry remains within the automatic attempt budget; "
                            "claim this task again"
                        )
                tasks.append(task)
            _print({"tasks": tasks})
        elif arguments.command == "task-claim":
            lease = backend.claim(
                arguments.worker_id,
                lease_seconds=arguments.lease_seconds,
                operation=arguments.operation,
                batch_id=arguments.batch_id,
                task_id_filter=arguments.task_id,
            )
            _print(None if lease is None else backend.describe_lease(lease))
        elif arguments.command == "task-collect":
            if arguments.recovery:
                if (
                    not arguments.reason or not arguments.reason.strip()
                    or not arguments.evidence_ref or arguments.attempt is None
                    or arguments.attempt <= 0
                ):
                    raise ValueError(
                        "recovery requires --reason, --evidence-ref and original --attempt"
                    )
            elif arguments.reason or arguments.evidence_ref or arguments.attempt is not None:
                raise ValueError("recovery options require explicit --recovery")
            value = json.loads(Path(arguments.input).read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise ValueError("task result input must be a JSON object")
            if arguments.recovery and (
                type(value.get("succeeded")) is not bool
                or not isinstance(value.get("measurements"), dict)
                or not isinstance(value.get("configuration", {}), dict)
            ):
                raise ValueError(
                    "recovery requires a boolean succeeded and explicit measurement/configuration objects"
                )
            succeeded = bool(value.get("succeeded", False))
            output_ref = None
            if value.get("output") is not None:
                output_ref = manager.artifacts.put_text(json.dumps(
                    value["output"],
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )).artifact_id
            lease = backend.current_lease(arguments.task_id, arguments.worker_id)
            if arguments.recovery and lease.attempt != arguments.attempt:
                raise ValueError("recovery original attempt is stale or superseded")
            result = TaskResult(
                succeeded=succeeded,
                output_ref=output_ref,
                summary=str(value.get("summary", "")),
                measurements=value.get("measurements", {}) if arguments.recovery else {
                    str(key): int(amount)
                    for key, amount in value.get("measurements", {}).items()
                },
                configuration={
                    str(key): str(item)
                    for key, item in value.get("configuration", {}).items()
                },
            )
            _print(asdict(backend.collect(
                lease, result,
                recovery_reason=arguments.reason if arguments.recovery else None,
                recovery_evidence_refs=tuple(arguments.evidence_ref),
                recovery_actor=arguments.actor,
            )))
        elif arguments.command == "task-amend":
            value = json.loads(Path(arguments.input).read_text(encoding="utf-8"))
            if not isinstance(value, dict) or not isinstance(value.get("output"), dict):
                raise ValueError("task amendment input requires an output object")
            output_ref = manager.artifacts.put_text(json.dumps(
                value["output"],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )).artifact_id
            view = backend.amend_completed_output(
                arguments.task_id,
                output_ref,
                reason=str(value.get("reason", "")),
                evidence_refs=tuple(str(item) for item in value.get("evidence_refs", [])),
                actor=str(value.get("actor", "operator")),
            )
            _print(asdict(view))
        elif arguments.command == "task-release":
            lease = backend.current_lease(arguments.task_id, arguments.worker_id)
            _print(asdict(backend.release(lease, reason=arguments.reason)))
        elif arguments.command == "task-retry":
            _print(asdict(backend.retry(
                arguments.task_id,
                reason=arguments.reason,
                actor=arguments.actor,
            )))
        elif arguments.command == "task-cancel":
            _print(asdict(backend.cancel(
                arguments.task_id, reason=arguments.reason
            )))
        else:
            workflow = BatchWorkflow(
                manager, arguments.campaign_id, arguments.batch_id
            )
            coordinator = DiscoveryCoordinator(workflow, backend)
            if arguments.command == "task-schedule-r1":
                _print({"tasks": [asdict(view) for view in coordinator.schedule_r1()]})
            elif arguments.command == "task-commit-r1":
                _print({"artifact_id": coordinator.commit_r1()})
            elif arguments.command == "task-schedule-r2":
                checklist = json.loads(
                    Path(arguments.entrypoint_checklist).read_text(encoding="utf-8")
                )
                if not isinstance(checklist, list):
                    raise ModelError("R2 entrypoint checklist file must contain a JSON array")
                _print({"tasks": [asdict(view) for view in coordinator.schedule_r2_compact(
                    entrypoint_checklist=checklist,
                )]})
            elif arguments.command == "task-commit-r2":
                _print({"artifact_id": coordinator.commit_r2_compact()})
            elif arguments.command == "task-schedule-r2-per-axis":
                checklist = json.loads(
                    Path(arguments.entrypoint_checklist).read_text(encoding="utf-8")
                )
                if not isinstance(checklist, list):
                    raise ModelError("R2 entrypoint checklist file must contain a JSON array")
                _print({"tasks": [asdict(view) for view in coordinator.schedule_r2(
                    entrypoint_checklist=checklist,
                )]})
            elif arguments.command == "task-commit-r2-per-axis":
                _print({"artifact_id": coordinator.commit_r2()})
            elif arguments.command == "task-schedule-r3":
                _print({"tasks": [asdict(view) for view in coordinator.schedule_r3()]})
            elif arguments.command == "task-commit-r3":
                _print({"artifact_id": coordinator.commit_r3()})
            elif arguments.command == "task-schedule-r35-refutations":
                _print({"tasks": [
                    asdict(view) for view in coordinator.schedule_r35_refutations()
                ]})
            elif arguments.command == "task-commit-r35-refutations":
                _print({"artifact_ids": list(coordinator.commit_r35_refutations())})
            elif arguments.command == "task-schedule-r35-adjudications":
                _print({"tasks": [
                    asdict(view) for view in coordinator.schedule_r35_adjudications()
                ]})
            elif arguments.command == "task-commit-r35-adjudications":
                _print({"artifact_ids": list(coordinator.commit_r35_adjudications())})
            elif arguments.command == "task-approve-r35-adjudication":
                value = json.loads(Path(arguments.input).read_text(encoding="utf-8"))
                if (
                    not isinstance(value, dict)
                    or not isinstance(value.get("evidence_refs"), list)
                    or not all(isinstance(ref, str) for ref in value["evidence_refs"])
                    or not all(
                        isinstance(value.get(key), str)
                        for key in ("output_ref", "reviewer", "rationale")
                    )
                ):
                    raise ValueError(
                        "human review requires output_ref, reviewer, rationale strings "
                        "and an evidence_refs array"
                    )
                _print({"artifact_id": coordinator.approve_r35_adjudication(
                    arguments.task_id,
                    output_ref=str(value.get("output_ref", "")),
                    reviewer=str(value.get("reviewer", "")),
                    rationale=str(value.get("rationale", "")),
                    evidence_refs=tuple(value.get("evidence_refs", [])),
                )})
            elif arguments.command == "task-schedule-r35-revivals":
                _print({"tasks": [
                    asdict(view) for view in coordinator.schedule_r35_revivals()
                ]})
            elif arguments.command == "task-commit-r35-revivals":
                _print({"artifact_id": coordinator.commit_r35_revivals()})
            elif arguments.command == "task-schedule-r4":
                if arguments.bundle_work_units == 1:
                    scheduled = coordinator.schedule_r4()
                else:
                    scheduled = coordinator.schedule_r4_bundled(
                        max_work_units_per_task=arguments.bundle_work_units,
                        max_task_input_bytes=arguments.bundle_max_input_bytes,
                    )
                _print({"tasks": [asdict(view) for view in scheduled]})
            elif arguments.command == "task-commit-r4":
                _print({"artifact_id": coordinator.commit_r4()})
            elif arguments.command == "task-schedule-r5":
                _print({"tasks": [asdict(view) for view in coordinator.schedule_r5()]})
            elif arguments.command == "task-commit-r5":
                _print({"artifact_id": coordinator.commit_r5()})
            elif arguments.command == "task-schedule-r6":
                task = asdict(coordinator.schedule_r6())
                _print({"tasks": [task], "task": task})
            else:
                _print(coordinator.commit_r6())
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="reachable-audit")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser(
        "host-capabilities",
        help="report host transfer and isolation capabilities without target execution",
    )

    init = subparsers.add_parser("init", help="create a Campaign state store")
    init.add_argument("target")
    init.add_argument("--snapshot-id")
    init.add_argument("--state-dir", default=".audit_vnext")
    init.add_argument("--campaign-id")
    init.add_argument(
        "--audit-mode", choices=("fresh", "follow-up"), default="fresh",
        help="fresh isolates prior Campaign context; follow-up requires explicit history sources",
    )
    init.add_argument(
        "--history-source", action="append", default=[], metavar="CAMPAIGN_ID",
        help="prior Campaign used only for follow-up QA/regression context",
    )
    init.add_argument(
        "--max-screening-fraction", type=float,
        help="predeclare the maximum fraction of Work Units allowed as screening-only (0..1)",
    )
    init.add_argument(
        "--max-delegated-agent-runs", type=int,
        help="reserve no more than this many delegated agent runs across the Campaign",
    )
    init.add_argument(
        "--max-wall-seconds", type=int,
        help="stop accepting execution-task claims after this Campaign wall-clock budget",
    )
    init.add_argument(
        "--require-host-worker-attestation", action="store_true",
        help="require task-result HMAC attestations from the host wrapper",
    )
    init.add_argument(
        "--experimental-go-hotspots", action="store_true",
        help="opt into offline Go AST candidate hints; requires local Go, not release-qualified",
    )
    init.add_argument(
        "--experimental-java-hotspots", action="store_true",
        help="opt into bounded offline Java AST candidate hints; not release-qualified",
    )
    init.add_argument(
        "--static-challenges", action="store_true",
        help="freeze opt-in static R3.5 challenge generation for this Campaign",
    )
    init.add_argument(
        "--static-only", action="store_true",
        help="freeze a Campaign constraint forbidding dynamic execution, including managed harnesses",
    )
    init.add_argument("--coverage-critic", action=argparse.BooleanOptionalAction, default=None,
                      help="freeze opt-in independent coverage review gates")
    init.add_argument("--domain-guidance", action=argparse.BooleanOptionalAction, default=None,
                      help="freeze opt-in source-evidenced bounded domain guidance")
    init.add_argument("--task-budget-policy", help="JSON file declaring opt-in task budget admission")
    init.add_argument(
        "--defer-r35-splits", action=argparse.BooleanOptionalAction, default=None,
        help="retain unresolved R3.5 splits for post-run review (default for new Campaigns); "
        "--no-defer-r35-splits requires human split adjudication",
    )

    review_queue = subparsers.add_parser(
        "review-queue", help="derive unresolved review packets from active stage evidence",
    )
    review_queue.add_argument("target")
    review_queue.add_argument("campaign_id")
    review_queue.add_argument("--state-dir", default=".audit_vnext")

    recovery = subparsers.add_parser(
        "recovery-plan", help="derive read-only stage revision recovery instructions",
    )
    recovery.add_argument("target")
    recovery.add_argument("campaign_id")
    recovery.add_argument("--state-dir", default=".audit_vnext")

    wall_amend = subparsers.add_parser(
        "campaign-wall-budget-amend",
        help="authorize a monotone Campaign wall-budget extension without resetting its clock",
    )
    wall_amend.add_argument("target")
    wall_amend.add_argument("campaign_id")
    wall_amend.add_argument("--approved-max-wall-seconds", required=True, type=int)
    wall_amend.add_argument("--reason", required=True)
    wall_amend.add_argument("--evidence-ref", required=True, action="append")
    wall_amend.add_argument("--actor", default="operator")
    wall_amend.add_argument("--state-dir", default=".audit_vnext")

    status = subparsers.add_parser("status", help="show Campaign and Batch state")
    status.add_argument("target")
    status.add_argument("--state-dir", default=".audit_vnext")

    batch = subparsers.add_parser("batch-add", help="add a planned Batch")
    batch.add_argument("target")
    batch.add_argument("campaign_id")
    batch.add_argument("batch_id")
    batch.add_argument("--manifest", required=True)
    batch.add_argument("--state-dir", default=".audit_vnext")

    inventory = subparsers.add_parser(
        "inventory", help="discover build-boundary components and source ownership"
    )
    inventory.add_argument("target")
    inventory.add_argument("campaign_id")
    inventory.add_argument("--state-dir", default=".audit_vnext")

    graph = subparsers.add_parser(
        "graph", help="resolve repository-local build dependencies"
    )
    graph.add_argument("target")
    graph.add_argument("campaign_id")
    graph.add_argument("--state-dir", default=".audit_vnext")

    probe = subparsers.add_parser(
        "toolchain-probe", help="probe only registered version commands for a language"
    )
    probe.add_argument("language")

    compatibility_scan = subparsers.add_parser(
        "compatibility-scan", help="scan vNext runtime imports and knowledge for legacy coupling"
    )
    compatibility_scan.add_argument(
        "--root", default=str(Path(__file__).resolve().parents[2])
    )
    compatibility_scan.add_argument(
        "--forbidden-tokens-file",
        help="operator-supplied file with one project-specific token per line",
    )

    harness_run = subparsers.add_parser(
        "harness-run",
        description=(
            "Run an argv harness bound to the current Campaign and source snapshot. "
            "Set input.hypothesis_id to make the captured execution eligible for "
            "R5 empirical-upgrade review. Set input.execution_provenance to classify "
            "target-tree versus built-copy runs. Optional profiles are 'go-offline' "
            "and 'jvm-bounded'."
        ),
        epilog=(
            "input.cwd must be an existing directory under the target root. CPU, "
            "address-space, output-file, descriptor, timeout, and process-group "
            "limits are resource controls, not an OS sandbox for hostile native code. "
            "go-offline is not an OS network sandbox. jvm-bounded uses a 4 GiB "
            "default address-space cap; set JVM heap limits in command argv."
        ),
        help=(
            "run a bounded argv harness; input.hypothesis_id binds output to an R5 "
            "claim, and input.cwd must stay inside the target"
        ),
    )
    harness_run.add_argument("target")
    harness_run.add_argument("campaign_id")
    harness_run.add_argument("--input", required=True)
    harness_run.add_argument("--state-dir", default=".audit_vnext")
    harness_run.add_argument(
        "--isolation",
        choices=("linux-bwrap",),
        help="require qualified Linux bubblewrap isolation; fail closed if unavailable",
    )

    plan = subparsers.add_parser("plan", help="create Work Units and planned Batches")
    plan.add_argument("target")
    plan.add_argument("campaign_id")
    plan.add_argument(
        "--categories",
        required=True,
        help=(
            "hard audit scope: only these mechanism families are planned; "
            "out-of-scope hypotheses are rejected"
        ),
    )
    plan.add_argument("--boundaries")
    plan.add_argument(
        "--path-dispositions",
        help=(
            "JSON array of per-path state records; paths omitted from the array "
            "default to INCLUDED"
        ),
    )
    plan.add_argument(
        "--max-work-unit-files", type=int, default=DEFAULT_MAX_SOURCE_FILES_PER_WORK_UNIT,
    )
    plan.add_argument("--max-batch-files", type=int, default=2000)
    plan.add_argument("--max-batch-work-units", type=int, default=4)
    plan.add_argument(
        "--cost-profile",
        help=(
            "JSON profile with measured per-task costs and low/expected/high "
            "hypotheses-per-Work-Unit assumptions; forecast only, never replans"
        ),
    )
    plan.add_argument("--state-dir", default=".audit_vnext")

    evidence_register = subparsers.add_parser(
        "evidence-register", help="freeze supporting resource file digests before the first R0",
    )
    evidence_register.add_argument("target")
    evidence_register.add_argument("campaign_id")
    evidence_register.add_argument("--input", required=True)
    evidence_register.add_argument("--state-dir", default=".audit_vnext")

    amend = subparsers.add_parser(
        "amend", help="repack an unstarted plan at Work Unit boundaries"
    )
    amend.add_argument("target")
    amend.add_argument("campaign_id")
    amend.add_argument("base_plan_id")
    amend.add_argument("--reason", required=True)
    amend.add_argument("--max-batch-files", type=int, required=True)
    amend.add_argument("--max-batch-work-units", type=int, required=True)
    amend.add_argument("--state-dir", default=".audit_vnext")

    for command, help_text in (
        ("r0", "validate Batch inputs and report pre-registered supporting evidence"),
        ("r1", "record scoped surfaces from JSON"),
        ("r2", "record surface/mechanism hypotheses from JSON"),
        ("r3", "record canonical reachability verdicts from JSON"),
        ("batch-report", "derive the current R0-R3 Batch report"),
    ):
        stage = subparsers.add_parser(command, help=help_text)
        stage.add_argument("target")
        stage.add_argument("campaign_id")
        stage.add_argument("batch_id")
        if command in {"r1", "r2", "r3"}:
            stage.add_argument("--input", required=True)
        stage.add_argument("--state-dir", default=".audit_vnext")

    handoff_resolve = subparsers.add_parser(
        "handoff-resolve", help="submit owner evidence for a cross-Batch Handoff"
    )
    handoff_resolve.add_argument("target")
    handoff_resolve.add_argument("campaign_id")
    handoff_resolve.add_argument("plan_id")
    handoff_resolve.add_argument("--input", required=True)
    handoff_resolve.add_argument("--state-dir", default=".audit_vnext")

    handoff_integrate = subparsers.add_parser(
        "handoff-integrate", help="merge a resolved Handoff call chain"
    )
    handoff_integrate.add_argument("target")
    handoff_integrate.add_argument("campaign_id")
    handoff_integrate.add_argument("plan_id")
    handoff_integrate.add_argument("handoff_id")
    handoff_integrate.add_argument("--input", required=True)
    handoff_integrate.add_argument("--state-dir", default=".audit_vnext")

    for command, help_text in (
        ("r35-refute", "submit one independent refutation"),
        ("r35-adjudicate", "adjudicate independent refutations"),
        ("r35-revival-review", "review one sampled UNREACHABLE hypothesis"),
    ):
        stage = subparsers.add_parser(command, help=help_text)
        stage.add_argument("target")
        stage.add_argument("campaign_id")
        stage.add_argument("batch_id")
        stage.add_argument("--input", required=True)
        stage.add_argument("--state-dir", default=".audit_vnext")

    revival_select = subparsers.add_parser(
        "r35-revival-select", help="record the UNREACHABLE revival sample"
    )
    revival_select.add_argument("target")
    revival_select.add_argument("campaign_id")
    revival_select.add_argument("batch_id")
    revival_select.add_argument("--input", required=True)
    revival_select.add_argument("--state-dir", default=".audit_vnext")

    r35_complete = subparsers.add_parser(
        "r35-complete", help="close R3.5 after refutation and revival coverage"
    )
    r35_complete.add_argument("target")
    r35_complete.add_argument("campaign_id")
    r35_complete.add_argument("batch_id")
    r35_complete.add_argument("--state-dir", default=".audit_vnext")

    category_plan = subparsers.add_parser(
        "category-plan", help="create runtime CategoryAuditPlans from Mechanism Cards"
    )
    category_plan.add_argument("target")
    category_plan.add_argument("campaign_id")
    category_plan.add_argument("batch_id")
    category_plan.add_argument("--input", required=True)
    category_plan.add_argument("--state-dir", default=".audit_vnext")

    r4 = subparsers.add_parser("r4", help="record CategoryRun coverage")
    r4.add_argument("target")
    r4.add_argument("campaign_id")
    r4.add_argument("batch_id")
    r4.add_argument("--input", required=True)
    r4.add_argument("--state-dir", default=".audit_vnext")

    r5 = subparsers.add_parser("r5", help="record experiment fidelity and dispositions")
    r5.add_argument("target")
    r5.add_argument("campaign_id")
    r5.add_argument("batch_id")
    r5.add_argument("--input", required=True)
    r5.add_argument("--state-dir", default=".audit_vnext")

    r5_observation = subparsers.add_parser(
        "r5-observation-register",
        help="register a signed external R5 observation without upgrading a verdict",
    )
    r5_observation.add_argument("target")
    r5_observation.add_argument("campaign_id")
    r5_observation.add_argument("--input", required=True)
    r5_observation.add_argument("--state-dir", default=".audit_vnext")

    metrics = subparsers.add_parser(
        "metrics", help="derive non-gating discovery transmission metrics"
    )
    metrics.add_argument("target")
    metrics.add_argument("campaign_id")
    metrics.add_argument("batch_id")
    metrics.add_argument("--state-dir", default=".audit_vnext")

    finding = subparsers.add_parser("finding", help="record a canonical Batch Finding")
    finding.add_argument("target")
    finding.add_argument("campaign_id")
    finding.add_argument("batch_id")
    finding.add_argument("--input", required=True)
    finding.add_argument("--state-dir", default=".audit_vnext")

    r6 = subparsers.add_parser("r6", help="run Batch gates and close the Batch")
    r6.add_argument("target")
    r6.add_argument("campaign_id")
    r6.add_argument("batch_id")
    r6.add_argument("--input", required=True)
    r6.add_argument("--state-dir", default=".audit_vnext")

    close = subparsers.add_parser(
        "campaign-close", help="run Campaign gates and write the final report"
    )
    close.add_argument("target")
    close.add_argument("campaign_id")
    close.add_argument("plan_id")
    close.add_argument("--input", required=True)
    close.add_argument("--state-dir", default=".audit_vnext")

    abort = subparsers.add_parser(
        "campaign-abort", help="record an abandoned Campaign and release its resources"
    )
    abort.add_argument("target")
    abort.add_argument("campaign_id")
    abort.add_argument("--reason", required=True)
    abort.add_argument("--input", required=True, help="JSON object with skill_issues array")
    abort.add_argument("--state-dir", default=".audit_vnext")

    skill_backlog = subparsers.add_parser(
        "skill-backlog", help="show skill defects pending regression"
    )
    skill_backlog.add_argument("target")
    skill_backlog.add_argument("campaign_id")
    skill_backlog.add_argument("--state-dir", default=".audit_vnext")

    skill_review = subparsers.add_parser(
        "skill-review", help="record audit skill errors and defects for regression"
    )
    skill_review.add_argument("target")
    skill_review.add_argument("campaign_id")
    skill_review.add_argument("--input", required=True)
    skill_review.add_argument("--state-dir", default=".audit_vnext")

    resource_process = subparsers.add_parser(
        "resource-register-process", help="register a Campaign-owned process group"
    )
    resource_process.add_argument("target")
    resource_process.add_argument("campaign_id")
    resource_process.add_argument("process_group_id", type=int)
    resource_process.add_argument("--label", required=True)
    resource_process.add_argument("--state-dir", default=".audit_vnext")

    resource_temp = subparsers.add_parser(
        "resource-create-temp", help="create a Campaign-owned temporary directory"
    )
    resource_temp.add_argument("target")
    resource_temp.add_argument("campaign_id")
    resource_temp.add_argument("--label", required=True)
    resource_temp.add_argument("--state-dir", default=".audit_vnext")

    resource_cleanup = subparsers.add_parser(
        "resource-cleanup", help="release Campaign-owned resources and pending tasks"
    )
    resource_cleanup.add_argument("target")
    resource_cleanup.add_argument("campaign_id")
    resource_cleanup.add_argument("--state-dir", default=".audit_vnext")

    evaluate = subparsers.add_parser(
        "shadow-evaluate", help="evaluate paired v3/vNext release evidence"
    )
    evaluate.add_argument("--input", required=True)
    evaluate.add_argument("--output")

    for command, help_text in (
        ("task-schedule-r1", "schedule Work Unit surface discovery tasks"),
        ("task-commit-r1", "aggregate successful surface tasks into R1"),
        ("task-schedule-r2", "schedule compact six-axis tasks, one per Work Unit"),
        ("task-commit-r2", "aggregate compact Work Unit tasks into R2"),
        ("task-schedule-r2-per-axis", "schedule six separate axis tasks per Work Unit"),
        ("task-commit-r2-per-axis", "aggregate per-axis hypothesis tasks into R2"),
        ("task-schedule-r3", "schedule per-hypothesis reachability verification"),
        ("task-commit-r3", "aggregate successful verifier tasks into R3"),
        ("task-schedule-r35-refutations", "schedule independent refutation tasks"),
        ("task-commit-r35-refutations", "commit independent refutation results"),
        ("task-schedule-r35-adjudications", "schedule refutation adjudications"),
        ("task-commit-r35-adjudications", "commit refutation adjudications"),
        ("task-approve-r35-adjudication", "operator assertion of actual human output review"),
        ("task-schedule-r35-revivals", "schedule rejected-hypothesis reviews"),
        ("task-commit-r35-revivals", "commit reviews and complete R3.5"),
        ("task-schedule-r4", "schedule CategoryAuditPlan execution tasks"),
        ("task-commit-r4", "aggregate CategoryRun tasks into R4"),
        ("task-schedule-r5", "schedule per-hypothesis experiment assessments"),
        ("task-commit-r5", "aggregate experiment assessments into R5"),
        ("task-schedule-r6", "schedule Batch closure evidence collection"),
        ("task-commit-r6", "evaluate gates and close the Batch"),
    ):
        task_stage = subparsers.add_parser(command, help=help_text)
        task_stage.add_argument("target")
        task_stage.add_argument("campaign_id")
        task_stage.add_argument("batch_id")
        task_stage.add_argument("--state-dir", default=".audit_vnext")

    task_schedule_r4 = subparsers.choices["task-schedule-r4"]
    for command in ("task-schedule-r2", "task-schedule-r2-per-axis"):
        subparsers.choices[command].add_argument(
            "--entrypoint-checklist",
            required=True,
            help="JSON array of predeclared entrypoint checks; use [] to declare none",
        )
    human_review = subparsers.choices["task-approve-r35-adjudication"]
    human_review.add_argument("task_id")
    human_review.add_argument("--input", required=True)
    task_schedule_r4.add_argument(
        "--bundle-work-units", type=int, default=1,
        help="opt-in: bundle this many same-family Work Units per R4 agent task",
    )
    task_schedule_r4.add_argument(
        "--bundle-max-input-bytes", type=int, default=512 * 1024,
        help="maximum serialized R4 bundle task input size",
    )

    task_list = subparsers.add_parser("task-list", help="list durable execution tasks")
    task_list.add_argument("target")
    task_list.add_argument("campaign_id")
    task_list.add_argument("--batch-id")
    task_list.add_argument("--operation")
    task_list.add_argument("--operation-prefix")
    task_list.add_argument("--state-dir", default=".audit_vnext")

    task_claim = subparsers.add_parser("task-claim", help="lease the next execution task")
    task_claim.add_argument("target")
    task_claim.add_argument("campaign_id")
    task_claim.add_argument("worker_id")
    task_claim.add_argument("--operation")
    task_claim.add_argument("--batch-id")
    task_claim.add_argument("--task-id")
    task_claim.add_argument("--lease-seconds", type=int, default=900)
    task_claim.add_argument("--state-dir", default=".audit_vnext")

    task_collect = subparsers.add_parser("task-collect", help="collect a leased task result")
    task_collect.add_argument("target")
    task_collect.add_argument("campaign_id")
    task_collect.add_argument("task_id")
    task_collect.add_argument("worker_id")
    task_collect.add_argument("--input", required=True)
    task_collect.add_argument("--state-dir", default=".audit_vnext")
    task_collect.add_argument(
        "--recovery", action="store_true",
        help="explicitly authorize collection of existing output from an expired lease",
    )
    task_collect.add_argument("--attempt", type=int, help="original expired lease attempt")
    task_collect.add_argument("--reason", help="operator recovery authorization reason")
    task_collect.add_argument("--evidence-ref", action="append", default=[])
    task_collect.add_argument("--actor", default="operator")

    task_amend = subparsers.add_parser(
        "task-amend", help="append an evidence-backed correction to a collected stage output"
    )
    task_amend.add_argument("target")
    task_amend.add_argument("campaign_id")
    task_amend.add_argument("task_id")
    task_amend.add_argument("--input", required=True)
    task_amend.add_argument("--state-dir", default=".audit_vnext")

    task_cancel = subparsers.add_parser("task-cancel", help="cancel a pending task")
    task_cancel.add_argument("target")
    task_cancel.add_argument("campaign_id")
    task_cancel.add_argument("task_id")
    task_cancel.add_argument("--reason", required=True)
    task_cancel.add_argument("--state-dir", default=".audit_vnext")

    task_release = subparsers.add_parser(
        "task-release", help="release a task lease back to the compatible-worker queue"
    )
    task_release.add_argument("target")
    task_release.add_argument("campaign_id")
    task_release.add_argument("task_id")
    task_release.add_argument("worker_id")
    task_release.add_argument("--reason", required=True)
    task_release.add_argument("--state-dir", default=".audit_vnext")

    task_retry = subparsers.add_parser(
        "task-retry", help="authorize one bounded retry for an exhausted failed task"
    )
    task_retry.add_argument("target")
    task_retry.add_argument("campaign_id")
    task_retry.add_argument("task_id")
    task_retry.add_argument("--reason", required=True)
    task_retry.add_argument("--actor", default="operator")
    task_retry.add_argument("--state-dir", default=".audit_vnext")

    drift_resolve = subparsers.add_parser(
        "drift-resolve", help="verify source restoration and resolve snapshot drift"
    )
    drift_resolve.add_argument("target")
    drift_resolve.add_argument("campaign_id")
    drift_resolve.add_argument("drift_event_id")
    drift_resolve.add_argument("--input", required=True)
    drift_resolve.add_argument("--state-dir", default=".audit_vnext")

    for name in (
        "task-schedule-coverage-critic", "task-commit-coverage-critic",
        "coverage-extend", "domain-select", "review-plan", "task-budget-status",
        "coverage-reject", "coverage-critic-status",
    ):
        command = subparsers.add_parser(name, help=name.replace("-", " "))
        command.add_argument("target")
        command.add_argument("campaign_id")
        command.add_argument("--state-dir", default=".audit_vnext")
        if name in {"coverage-extend", "domain-select", "review-plan", "coverage-reject"}:
            command.add_argument("--input", required=True)
        if name != "coverage-extend" and name != "task-budget-status":
            command.add_argument("batch_id")
        if name.endswith("coverage-critic") or name == "coverage-critic-status":
            command.add_argument("--phase", choices=("initial", "final"), required=True)
        if name == "review-plan":
            command.add_argument("hypothesis_id")
            command.add_argument("--actor", required=True)
        if name == "coverage-reject":
            command.add_argument("task_id")

    for command_parser in subparsers.choices.values():
        for action in command_parser._actions:
            if action.dest == "state_dir" and action.default == ".audit_vnext":
                action.default = None
                action.help = (
                    "state directory; relative paths are target-relative. New Campaigns "
                    "default to a per-target directory outside the target under "
                    "XDG_STATE_HOME (or ~/.local/state). Non-init commands reuse a "
                    "sole existing .audit_vnext store; if both old and external stores "
                    "exist, pass this option explicitly."
                )
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.command == "host-capabilities":
            from .experiments.safe_artifacts import host_isolation_status
            _print(host_isolation_status())
            return 0

        if hasattr(arguments, "state_dir"):
            arguments.state_dir = _cli_state_dir(
                arguments.target,
                arguments.state_dir,
                prefer_external=arguments.command == "init",
            )
        if arguments.command == "init":
            return _handle_init(arguments)

        if arguments.command in {
            "task-schedule-coverage-critic", "task-commit-coverage-critic",
            "coverage-extend", "domain-select", "review-plan", "task-budget-status",
            "coverage-reject", "coverage-critic-status",
        }:
            with CampaignManager(arguments.target, arguments.state_dir) as manager:
                if arguments.command == "coverage-extend":
                    from .coverage_critic import apply_coverage_extension
                    _print({"plan_id": apply_coverage_extension(
                        manager, arguments.campaign_id,
                        json.loads(Path(arguments.input).read_text(encoding="utf-8")),
                    )})
                elif arguments.command == "task-budget-status":
                    from .task_budget import budget_status
                    _print(budget_status(manager, arguments.campaign_id))
                else:
                    workflow = BatchWorkflow(manager, arguments.campaign_id, arguments.batch_id)
                    if arguments.command == "coverage-critic-status":
                        from .coverage_critic import critic_status
                        _print(critic_status(workflow, arguments.phase))
                    elif arguments.command == "coverage-reject":
                        from .coverage_critic import reject_coverage_proposals
                        _print({"artifact_id": reject_coverage_proposals(
                            workflow, arguments.task_id,
                            json.loads(Path(arguments.input).read_text(encoding="utf-8")),
                        )})
                    elif arguments.command == "domain-select":
                        from .domain_guidance import record_domain_selection
                        _print({"artifact_id": record_domain_selection(
                            workflow, json.loads(Path(arguments.input).read_text(encoding="utf-8")),
                        )})
                    elif arguments.command == "review-plan":
                        from .deferred_review import record_review_delivery
                        _print({"artifact_id": record_review_delivery(
                            workflow, arguments.hypothesis_id,
                            json.loads(Path(arguments.input).read_text(encoding="utf-8")),
                            actor=arguments.actor,
                        )})
                    else:
                        from .coverage_critic import commit_critic, schedule_critic
                        if arguments.command == "task-schedule-coverage-critic":
                            _print(asdict(schedule_critic(workflow, arguments.phase)))
                        else:
                            _print({"artifact_id": commit_critic(workflow, arguments.phase)})
            return 0

        if arguments.command == "status":
            return _handle_status(arguments)
        if arguments.command == "campaign-wall-budget-amend":
            return _handle_wall_budget_amend(arguments)

        if arguments.command == "skill-backlog":
            return _handle_skill_backlog(arguments)

        if arguments.command == "evidence-register":
            return _handle_evidence_register(arguments)
        if arguments.command == "skill-review":
            return _handle_skill_review(arguments)

        if arguments.command == "resource-register-process":
            return _handle_resource_register_process(arguments)

        if arguments.command == "resource-create-temp":
            return _handle_resource_create_temp(arguments)

        if arguments.command == "resource-cleanup":
            return _handle_resource_cleanup(arguments)

        if arguments.command == "review-queue":
            from .deferred_review import derive_review_queue

            with CampaignManager(arguments.target, arguments.state_dir) as manager:
                _print(derive_review_queue(manager, arguments.campaign_id))
            return 0

        if arguments.command == "recovery-plan":
            from .stage_revisions import stage_recovery_plan

            with CampaignManager(arguments.target, arguments.state_dir) as manager:
                manager.store.get_campaign(arguments.campaign_id)
                _print({
                    "campaign_id": arguments.campaign_id,
                    **stage_recovery_plan(manager.store.list_events(arguments.campaign_id)),
                })
            return 0

        if arguments.command == "inventory":
            return _handle_inventory(arguments)

        if arguments.command == "graph":
            return _handle_graph(arguments)

        if arguments.command == "toolchain-probe":
            return _handle_toolchain_probe(arguments)

        if arguments.command == "compatibility-scan":
            return _handle_compatibility_scan(arguments)

        if arguments.command == "harness-run":
            return _handle_harness_run(arguments)

        if arguments.command == "plan":
            return _handle_plan(arguments)

        if arguments.command == "amend":
            return _handle_amend(arguments)

        if arguments.command in {"r0", "r1", "r2", "r3", "batch-report"}:
            return _handle_batch_stage(arguments)

        if arguments.command in {"handoff-resolve", "handoff-integrate"}:
            return _handle_handoff(arguments)

        if arguments.command.startswith("r35-"):
            return _handle_r35(arguments)

        if arguments.command in {"category-plan", "r4"}:
            return _handle_category_plan_or_r4(arguments)

        if arguments.command in {"r5", "metrics"}:
            return _handle_r5_or_metrics(arguments)

        if arguments.command == "r5-observation-register":
            return _handle_r5_observation_register(arguments)

        if arguments.command in {"finding", "r6"}:
            return _handle_finding_or_r6(arguments)

        if arguments.command == "campaign-close":
            return _handle_campaign_close(arguments)

        if arguments.command == "campaign-abort":
            return _handle_campaign_abort(arguments)

        if arguments.command == "shadow-evaluate":
            return _handle_shadow_evaluate(arguments)

        if arguments.command.startswith("task-"):
            return _handle_task(arguments)

        if arguments.command == "drift-resolve":
            return _handle_drift_resolve(arguments)

        if arguments.command == "batch-add":
            return _handle_batch_add(arguments)
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError, SnapshotError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
