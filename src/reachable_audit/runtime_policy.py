"""Versioned digest of the vNext task/evidence policy owned by this runtime."""

from __future__ import annotations

import hashlib
import json
from typing import Any


TASK_OUTPUT_MAX_BYTES = 4 * 1024 * 1024
TASK_OUTPUT_TARGET_BYTES = 1024 * 1024


_POLICY: dict[str, Any] = {
    "policy_version": "vnext-task-policy-5",
    "task_collection": {
        "shell_execution_by_scheduler": False,
        "required_measurements": ["agent_runs", "wall_seconds"],
        "successful_task_measurements_positive": True,
        "source_anchors_required": True,
        "evidence_artifacts_content_addressed": True,
        "held_out_knowledge_runtime_access": False,
        "max_output_bytes": TASK_OUTPUT_MAX_BYTES,
        "soft_output_target_bytes": TASK_OUTPUT_TARGET_BYTES,
        "review_scope_sentinel": "ALL_SOURCE_FILES",
        "reviewed_scope_validation": "exact_scalar_or_exact_paths",
        "r1_boundary_review_coverage": "exactly_once_with_evidence_and_rationale_at_collect",
        "r2_hypothesis_shape_validation": "collect",
        "r4_bundle": "opt-in_same-family_preserve_per_plan_results",
        "r4_bundle_default_work_units": 1,
        "r4_bundle_max_input_bytes": 524288,
        "empty_component_planning": "omit_only_without_source_manifest_or_boundary_obligation",
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