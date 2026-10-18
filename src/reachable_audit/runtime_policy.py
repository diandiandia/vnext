"""Versioned digest of the vNext task/evidence policy owned by this runtime."""

from __future__ import annotations

import hashlib
import json
from typing import Any


TASK_OUTPUT_MAX_BYTES = 4 * 1024 * 1024
TASK_OUTPUT_TARGET_BYTES = 1024 * 1024
RELEASE_POLICY_VERSION = "vnext-release-policy-6"
REQUIRED_RELEASE_GATES = tuple(f"RG{index}" for index in range(1, 16))
IMPLEMENTED_RELEASE_GATES = tuple(f"RG{index}" for index in range(1, 16))


_POLICY: dict[str, Any] = {
    "policy_version": "vnext-task-policy-32",
    "task_collection": {
        "shell_execution_by_scheduler": False,
        "required_measurements": ["agent_runs", "wall_seconds"],
        "delegated_agent_runs": "optional_measurement_required_when_task_budgeted_and_bounded_by_agent_runs",
        "successful_task_measurements_positive": True,
        "host_worker_attestation": "campaign_opt_in_hmac_sha256_bound_to_task_attempt_lease_worker_and_delegates",
        "source_anchors_required": True,
        "evidence_artifacts_content_addressed": True,
        "held_out_knowledge_runtime_access": False,
        "max_output_bytes": TASK_OUTPUT_MAX_BYTES,
        "soft_output_target_bytes": TASK_OUTPUT_TARGET_BYTES,
        "review_scope_sentinel": "ALL_SOURCE_FILES",
        "reviewed_scope_validation": "exact_scalar_or_exact_paths",
        "r1_boundary_review_coverage": "exactly_once_with_evidence_and_rationale_at_collect",
        "r1_boundary_anchor_validation": "endpoint_component_and_snapshot_loc_line_at_collect",
        "r2_hypothesis_shape_validation": "collect",
        "r4_bundle": "opt-in_same-family_preserve_per_plan_results",
        "r4_bundle_default_work_units": 1,
        "r4_bundle_max_input_bytes": 524288,
        "empty_component_planning": "omit_only_without_source_manifest_or_boundary_obligation",
        "r2_hypothesis_id": "HYP-work_unit_id-origin_axis-positive_ordinal",
        "r4_category_run_validation": "collect_plan_scope_axes_and_verbatim_variants",
        "r4_axis_run_work_unit_id": "optional_on_wire_inherited_from_category_run_explicit_must_match",
        "r4_bundle_mechanism_cards": "serialized_once_at_bundle_scope_seed_card_ids_remain_per_item",
        "released_exhausted_lease_retry": "explicit_bounded_operator_authorization",
        "attempt_usage": "all_claimed_attempts_with_unreported_attempts_incomplete",
        "hotspot_source_identity": "parsed_bytes_match_r0_digest",
        "r5_experiment_reference_validation": "collect_and_commit_null_or_task_local_id",
        "r5_not_feasible": "required_blocker_evidence_null_experiment_id_needs_review_no_attempted_run",
        "r5_external_observation": "host_hmac_campaign_snapshot_batch_hypothesis_observer_method_time_campaign_owned_artifacts_evidence_only_non_confirming",
        "r5_external_observation_refs": "optional_assessment_refs_must_name_registered_same_batch_hypothesis_observation;never_confirms_or_refutes",
        "late_stage_amendment": "r5_r6_precommit_and_terminal_r6_postcommit_before_campaign_close",
        "r5_empirical_contract": "host_registered_harness_for_same_hypothesis_and_snapshot",
        "experiment_recipe_prerequisites": "optional_tooling_scoped_to_memory_safety_and_numeric_families",
        "r6_evidence_context": "canonical_stage_artifacts_not_work_unit_source_inventory",
        "r6_surface_dispositions": "collect_exact_one_per_r1_surface_projection_defaults_missing_to_unreviewed_agent_reported",
        "plan_path_scope": "inventory_exact_path_states_only_included_paths_assigned_exclusions_deferments_visible",
        "r4_hypothesis_references": "task_input_work_unit_and_family_allowlist_at_collect",
        "r1_surface_anchors": "collect_entry_path_and_nonblank_source_line",
        "r1_surface_identity": "collect_unique_id_task_work_unit_and_component_match",
        "r1_oversize_work_unit_guard": "block_scheduling_when_minimum_valid_output_exceeds_hard_limit",
        "planner_boundary_edge_sharding": "r1_minimum_output_floor_v1_per_endpoint_exact_once",
        "r1_path_review_claims": "persist_task_validated_scope_as_agent_declared_not_host_observed",
        "r1_review_altitude": "required_screened_or_inspected_agent_declaration_per_work_unit",
        "r1_path_risk_tiers": "optional_rubric_v1_high_direct_security_boundary_or_sensitive_operation_medium_supporting_logic_low_only_evidenced_no_security_role_unassessed_insufficient_evidence;not_severity_or_safety;omitted_unassessed",
        "r1_low_path_risk_tier": "requires_inspected_work_unit_altitude",
        "r2_review_altitude": "applicable_axis_requires_screened_or_inspected;_non_applicable_not_recorded",
        "r4_review_altitude": "applicable_category_axis_requires_screened_or_inspected;_non_applicable_not_recorded",
            "handoff_edge_proven": "typed_edge_endpoint_direction_principal_premise_and_data_mapping_proof",
    },
    "harness_limits": {
        "max_timeout_seconds": 300,
        "max_output_bytes_per_stream": 1048576,
        "open_files": 64,
        "core_dump_bytes": 0,
    },
}




def execution_policy_digest() -> str:
    payload = json.dumps(
        _POLICY, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()