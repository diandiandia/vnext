"""Versioned digest of the vNext task/evidence policy owned by this runtime."""

from __future__ import annotations

import hashlib
import json
from typing import Any


_POLICY: dict[str, Any] = {
    "policy_version": "vnext-task-policy-1",
    "task_collection": {
        "shell_execution_by_scheduler": False,
        "required_measurements": ["agent_runs", "wall_seconds"],
        "source_anchors_required": True,
        "evidence_artifacts_content_addressed": True,
        "held_out_knowledge_runtime_access": False,
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