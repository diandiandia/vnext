"""Versioned digest of the vNext task/evidence policy owned by this runtime."""

from __future__ import annotations

import hashlib
import json
from typing import Any


TASK_OUTPUT_MAX_BYTES = 4 * 1024 * 1024
TASK_OUTPUT_TARGET_BYTES = 1024 * 1024
R2_LARGE_SOURCE_FILE_WARNING_BYTES = 1024 * 1024
RELEASE_POLICY_VERSION = "vnext-release-policy-6"
REQUIRED_RELEASE_GATES = tuple(f"RG{index}" for index in range(1, 16))
IMPLEMENTED_RELEASE_GATES = tuple(f"RG{index}" for index in range(1, 16))


_POLICY: dict[str, Any] = {
    "policy_version": "vnext-task-policy-45",
    "task_collection": {
        "go_hotspots": "campaign_frozen_opt_in_trusted_offline_ast_helper_candidates_only_not_release_qualified",
        "java_hotspots": "campaign_frozen_opt_in_jdk_parse_only_unresolved_method_candidates_not_release_qualified",
        "supporting_resources": "explicit_pre_r0_digest_registration;concrete_loc_refs_match_frozen_bytes;not_call_chain_or_review_coverage",
        "r3_wire_contract": "nested_verdict_with_complete_example",
        "r35_static_challenges": "campaign_frozen_opt_in_same_two_perspective_protocol_no_evidence_grade_upgrade",
        "late_collection": "explicit_operator_authorization_original_attempt_and_output_normal_validation_no_new_dispatch",
        "wall_amendment": "append_only_monotone_limit_extension_original_clock_and_breach_retained",
        "go_harness_profile": "explicit_go_offline_environment_and_bounded_build_file_size;captured_output_limits_independent;ineligible_runs_cannot_upgrade",
        "shell_execution_by_scheduler": False,
        "task_execution_policy": "static_analysis_by_worker;dynamic_execution_requires_explicit_host_authorization_and_registered_r5_harness;not_os_enforced",
        "required_measurements": ["agent_runs", "wall_seconds"],
        "delegated_agent_runs": "optional_measurement_required_when_task_budgeted_and_bounded_by_agent_runs",
        "successful_task_measurements_positive": True,
        "host_worker_attestation": "campaign_opt_in_hmac_sha256_bound_to_task_attempt_lease_worker_and_delegates",
        "source_anchors_required": True,
        "evidence_artifacts_content_addressed": True,
        "held_out_knowledge_runtime_access": False,
        "knowledge_guidance": "conditional_target_evidence_not_expected_findings_or_exhaustive_checklist",
        "r2_axis_heuristics": "source_evidenced_six_axis_triggers_conditional_history_no_candidate_does_not_imply_inapplicable",
        "r35_revival_guidance": "independent_guard_bypass_and_boundary_contract_review_preserve_valid_counterevidence",
        "r35_human_review": "explicit_operator_approval_bound_to_current_output_digest_not_worker_label_or_verified_identity",
        "max_output_bytes": TASK_OUTPUT_MAX_BYTES,
        "soft_output_target_bytes": TASK_OUTPUT_TARGET_BYTES,
        "review_scope_sentinel": "ALL_SOURCE_FILES",
        "reviewed_scope_validation": "exact_scalar_or_exact_paths",
        "r1_boundary_review_coverage": "exactly_once_with_evidence_and_rationale_at_collect",
        "r1_boundary_anchor_validation": "endpoint_component_and_snapshot_loc_line_at_collect",
        "r2_hypothesis_shape_validation": "collect",
        "r2_large_source_guidance": "bounded_line_range_and_symbol_reads_fail_without_complete_file_scope",
        "r2_large_source_warning_bytes": R2_LARGE_SOURCE_FILE_WARNING_BYTES,
        "r4_bundle": "opt-in_same-family_preserve_per_plan_results",
        "r4_bundle_default_work_units": 1,
        "r4_bundle_max_input_bytes": 524288,
        "empty_component_planning": "scope_project_edges_prune_wholly_excluded_obligations_preserve_cross_scope_boundaries_and_truly_empty_root",
        "r2_hypothesis_id": "HYP-work_unit_id-origin_axis-positive_ordinal",
        "r4_category_run_validation": "collect_direct_bundle_shared_concrete_loc_and_artifact_validation_plan_scope_axes_verbatim_variants",
        "r4_axis_run_work_unit_id": "optional_on_wire_inherited_from_category_run_explicit_must_match",
        "r4_bundle_mechanism_cards": "serialized_once_at_bundle_scope_seed_card_ids_remain_per_item",
        "released_exhausted_lease_retry": "explicit_bounded_operator_authorization",
        "attempt_usage": "all_claimed_attempts_with_unreported_attempts_incomplete",
        "hotspot_source_identity": "parsed_bytes_match_r0_digest",
        "r5_experiment_reference_validation": "collect_and_commit_null_or_task_local_id",
        "r5_not_feasible": "required_blocker_evidence_null_experiment_id_needs_review_no_attempted_run",
        "r5_external_observation": "host_hmac_campaign_snapshot_batch_hypothesis_observer_method_time_campaign_owned_artifacts_evidence_only_non_confirming",
        "r5_external_observation_refs": "optional_assessment_refs_must_name_registered_same_batch_hypothesis_observation;never_confirms_or_refutes",
        "late_stage_amendment": "r1_r6_precommit_r1_r5_postcommit_atomic_dependent_invalidation_and_terminal_r6_recommit_before_campaign_close",
        "r5_empirical_contract": "host_registered_harness_for_same_hypothesis_and_snapshot",
        "experiment_recipe_prerequisites": "optional_tooling_scoped_to_memory_safety_and_numeric_families",
        "r6_evidence_context": "canonical_stage_artifacts_not_work_unit_source_inventory",
        "r6_surface_dispositions": "collect_exact_one_per_r1_surface_projection_defaults_missing_to_unreviewed_agent_reported",
        "plan_path_scope": "inventory_exact_path_states_only_included_paths_assigned_exclusions_deferments_visible",
        "r4_hypothesis_references": "exactly_once_reconciliation_of_task_input_work_unit_family_allowlist_at_collect",
        "r4_hypothesis_reviews": "one_evidence_linked_review_per_hypothesis; existing_scoped_findings_injected_and_exactly_reconciled; semantic_validity_remains_agent_asserted",
        "r4_current_r3_verdicts": "inject_exact_work_unit_family_verdicts_and_require_agent_rationale_reconciliation",
        "r2_predeclared_entrypoints": "explicit_checklist_per_axis_requires_source_anchored_agent_disposition; checklist_empty_is_explicit",
        "r6_finding_reconciliation": "all_recorded_findings_supplied_and_agent_reviewed_exactly_once; conflicts_reported; no_independent_human_review_claim",
        "r5_proposed_experiment": "unexecuted_inconclusive_empty_observations_needs_review_no_empirical_upgrade",
        "finding_classification": "security_vulnerability_requires_structured_impact_and_resolvable_evidence;nonsecurity_classifications_excluded_from_vulnerability_counts",
        "r1_surface_anchors": "collect_entry_path_and_nonblank_source_line",
        "r1_surface_identity": "collect_unique_id_task_work_unit_and_component_match",
        "r1_boundary_evidence": "registered_source_or_component_build_manifest_LOC_anchor_with_frozen_digest_validation",
        "r6_surface_template": "per_r1_surface_default_unreviewed_editable_template_not_a_review_claim",
        "cancelled_unclaimed_task_retry": "explicit_reason_authorization_only_when_no_worker_attempt_exists",
        "high_risk_surface_hypothesis_mapping": "derived_from_r1_agent_risk_tier_and_r2_surface_ids_exploratory_non_gating_not_review_or_safety_proof",
        "cg2_component_ownership": "all_paths_explicitly_excluded_or_deferred_can_account_for_component_without_work_unit_only_with_valid_scope_evidence_and_no_boundary_obligation_not_audit_approval",
        "r1_oversize_work_unit_guard": "block_scheduling_when_minimum_valid_output_exceeds_hard_limit",
        "planner_boundary_edge_sharding": "r1_minimum_output_floor_v1_per_endpoint_exact_once",
        "r1_path_review_claims": "persist_task_validated_scope_as_agent_declared_not_host_observed",
        "r1_review_altitude": "required_screened_or_inspected_agent_declaration_per_work_unit",
        "r1_path_risk_tiers": "optional_rubric_v1_high_direct_security_boundary_or_sensitive_operation_medium_supporting_logic_low_only_evidenced_no_security_role_unassessed_insufficient_evidence;not_severity_or_safety;omitted_unassessed",
        "r1_low_path_risk_tier": "requires_inspected_work_unit_altitude",
        "r1_high_path_risk_tier": "requires_inspected_work_unit_altitude_agent_declaration_not_observed_reads",
        "r2_review_altitude": "applicable_axis_requires_screened_or_inspected;_non_applicable_not_recorded",
        "r4_review_altitude": "applicable_category_axis_requires_screened_or_inspected;_non_applicable_not_recorded",
        "r3_call_chain": "ordered_pure_LOC_path_line_anchors;descriptions_separate_in_rationale",
        "r3_runtime_assumptions": "actual_exact_target_version_evidence_or_NEEDS_REVIEW;never_infer_from_worker_runtime",
        "task_poll_lease": "claim_created_at_elapsed_seconds_expired_flag;worker_liveness_always_UNKNOWN",
        "campaign_wall_deadline": "positive_integer_seconds_from_campaign_created_at_includes_pauses_without_subtraction;blocks_claims_only",
        "closure_unreviewed_scope": "inherited_batch_unreviewed_scope_union_cannot_be_removed_by_coordinator",
        "closure_hypothesis_outcomes": "findings_joined_by_hypothesis_ids_even_late;rejection_only_when_consistent_across_stages",
        "closure_resource_assessment": "separate_from_workflow_status;NOT_ASSESSED_without_attempts_usage_configuration_or_wall_limit;FAIL_when_elapsed_completion_exceeds_configured_limit",
        "r35_revival_counts": "reviewed_upheld_actual_revived;legacy_revived_equals_all_reviewed",
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