"""Phase 6 shadow-run comparison and release acceptance gates."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping, Sequence

from .models import ModelError
from .knowledge_catalog import KnowledgeCatalog, default_knowledge_root
from .compatibility import scan_runtime_compatibility, scan_runtime_deproject
from .discovery.hotspots import enabled_hotspot_provider_ids
from .runtime_policy import (
    IMPLEMENTED_RELEASE_GATES,
    RELEASE_POLICY_VERSION,
    REQUIRED_RELEASE_GATES,
)


_PROJECT_CLASSES = {"native", "managed", "dynamic", "mixed", "jit"}


@dataclass(frozen=True)
class ExpectedFinding:
    finding_id: str
    family: str

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ExpectedFinding":
        finding = cls(str(value["finding_id"]), str(value["family"]))
        if not finding.finding_id or not finding.family:
            raise ModelError("expected finding identity and family are required")
        return finding


@dataclass(frozen=True)
class ShadowRun:
    project_id: str
    engine: str
    project_class: str
    snapshot_id: str
    scope_digest: str
    execution_config_digest: str
    measurement_artifact_ref: str
    measurements: Mapping[str, int]
    budget: Mapping[str, int]
    expected_findings: tuple[ExpectedFinding, ...]
    detected_finding_ids: tuple[str, ...]
    false_positive_count: int
    needs_review_count: int
    repository_size_bytes: int
    campaign_complete: bool
    interruption_recovered: bool
    handoff_count: int
    reconciled_handoff_count: int
    evidence_traceable: bool
    held_out: bool
    synthetic: bool
    evidence_refs: tuple[str, ...]

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ShadowRun":
        run = cls(
            project_id=str(value["project_id"]),
            engine=str(value["engine"]),
            project_class=str(value["project_class"]).lower(),
            snapshot_id=str(value["snapshot_id"]),
            scope_digest=str(value["scope_digest"]),
            execution_config_digest=str(value["execution_config_digest"]),
            measurement_artifact_ref=str(value["measurement_artifact_ref"]),
            measurements={
                str(key): int(amount)
                for key, amount in value.get("measurements", {}).items()
            },
            budget={str(key): int(amount) for key, amount in value["budget"].items()},
            expected_findings=tuple(
                ExpectedFinding.from_dict(item)
                for item in value.get("expected_findings", [])
            ),
            detected_finding_ids=tuple(
                str(item) for item in value.get("detected_finding_ids", [])
            ),
            false_positive_count=int(value.get("false_positive_count", 0)),
            needs_review_count=int(value.get("needs_review_count", 0)),
            repository_size_bytes=int(value.get("repository_size_bytes", 0)),
            campaign_complete=bool(value.get("campaign_complete", False)),
            interruption_recovered=bool(value.get("interruption_recovered", False)),
            handoff_count=int(value.get("handoff_count", 0)),
            reconciled_handoff_count=int(value.get("reconciled_handoff_count", 0)),
            evidence_traceable=bool(value.get("evidence_traceable", False)),
            held_out=bool(value.get("held_out", False)),
            synthetic=bool(value.get("synthetic", True)),
            evidence_refs=tuple(str(item) for item in value.get("evidence_refs", [])),
        )
        if run.engine not in {"v3", "vnext"}:
            raise ModelError(f"unknown shadow engine: {run.engine}")
        if run.project_class not in _PROJECT_CLASSES:
            raise ModelError(f"unknown project class: {run.project_class}")
        if not run.project_id or not run.snapshot_id or not run.budget:
            raise ModelError("shadow run requires project, snapshot, and budget")
        if not _is_sha256(run.scope_digest) or not _is_sha256(run.execution_config_digest):
            raise ModelError("shadow run requires SHA-256 scope and execution-config digests")
        if not run.measurement_artifact_ref or not {"agent_runs", "wall_seconds"}.issubset(run.measurements):
            raise ModelError("shadow run requires an artifact-backed agent_runs and wall_seconds measurement")
        if any(amount < 0 for amount in run.measurements.values()):
            raise ModelError("shadow run measurements cannot be negative")
        if any(amount < 0 for amount in run.budget.values()):
            raise ModelError("shadow run budget values cannot be negative")
        if min(
            run.false_positive_count,
            run.needs_review_count,
            run.repository_size_bytes,
            run.handoff_count,
            run.reconciled_handoff_count,
        ) < 0:
            raise ModelError("shadow run counters cannot be negative")
        if not run.evidence_refs:
            raise ModelError("shadow run requires evidence references")
        expected_ids = {item.finding_id for item in run.expected_findings}
        unknown = set(run.detected_finding_ids) - expected_ids
        if unknown:
            raise ModelError(
                f"detected finding IDs are absent from expected set: {sorted(unknown)}"
            )
        return run


@dataclass(frozen=True)
class LanguageAcceptance:
    language: str
    certified: bool
    adapter_contract_passed: bool
    held_out_sample_passed: bool
    evidence_refs: tuple[str, ...]

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LanguageAcceptance":
        item = cls(
            language=str(value["language"]),
            certified=bool(value.get("certified", False)),
            adapter_contract_passed=bool(value.get("adapter_contract_passed", False)),
            held_out_sample_passed=bool(value.get("held_out_sample_passed", False)),
            evidence_refs=tuple(str(ref) for ref in value.get("evidence_refs", [])),
        )
        if not item.language:
            raise ModelError("language acceptance requires a language")
        if item.certified and not item.evidence_refs:
            raise ModelError("certified language acceptance requires evidence")
        return item


@dataclass(frozen=True)
class LanguageIssueSample:
    language: str
    issue_id: str
    family: str
    sample_count: int
    v3_detected_count: int
    vnext_detected_count: int
    held_out: bool
    synthetic: bool
    evidence_refs: tuple[str, ...]

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LanguageIssueSample":
        sample = cls(
            language=str(value["language"]),
            issue_id=str(value["issue_id"]),
            family=str(value["family"]).upper(),
            sample_count=int(value.get("sample_count", 0)),
            v3_detected_count=int(value.get("v3_detected_count", 0)),
            vnext_detected_count=int(value.get("vnext_detected_count", 0)),
            held_out=bool(value.get("held_out", False)),
            synthetic=bool(value.get("synthetic", True)),
            evidence_refs=tuple(str(item) for item in value.get("evidence_refs", [])),
        )
        if not sample.language or not sample.issue_id or not sample.family:
            raise ModelError("language-issue sample requires language, issue, and family")
        if sample.sample_count < 0 or min(
            sample.v3_detected_count, sample.vnext_detected_count
        ) < 0:
            raise ModelError("language-issue sample counts cannot be negative")
        if max(sample.v3_detected_count, sample.vnext_detected_count) > sample.sample_count:
            raise ModelError("detected language-issue count exceeds sample count")
        if not sample.evidence_refs:
            raise ModelError("language-issue sample requires evidence references")
        return sample


@dataclass(frozen=True)
class AcceptancePolicy:
    minimum_improved_families: int = 2
    maximum_noise_ratio_increase: float = 0.05
    maximum_worst_group_recall_drop: float = 0.0
    large_repository_bytes: int = 20_000_000_000
    minimum_issue_samples: int = 3

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AcceptancePolicy":
        policy = cls(
            minimum_improved_families=int(value.get("minimum_improved_families", 2)),
            maximum_noise_ratio_increase=float(
                value.get("maximum_noise_ratio_increase", 0.05)
            ),
            maximum_worst_group_recall_drop=float(
                value.get("maximum_worst_group_recall_drop", 0.0)
            ),
            large_repository_bytes=int(
                value.get("large_repository_bytes", 20_000_000_000)
            ),
            minimum_issue_samples=int(value.get("minimum_issue_samples", 3)),
        )
        if (
            policy.minimum_improved_families < 0
            or policy.maximum_noise_ratio_increase < 0
            or policy.maximum_worst_group_recall_drop < 0
            or policy.large_repository_bytes <= 0
            or policy.minimum_issue_samples <= 0
        ):
            raise ModelError("acceptance policy thresholds must be non-negative")
        if policy.minimum_issue_samples < 3:
            raise ModelError("acceptance policy requires at least three samples per issue cell")
        return policy


def sign_manifest(value: Mapping[str, Any], key: bytes) -> dict[str, Any]:
    if not key:
        raise ModelError("evaluation signing key cannot be empty")
    manifest = {str(name): item for name, item in value.items() if name != "signature"}
    signature = hmac.new(key, _canonical_json(manifest), hashlib.sha256).hexdigest()
    return {**manifest, "signature": {"algorithm": "hmac-sha256", "value": signature}}


def evaluate_release(
    value: Mapping[str, Any], *, signing_key: bytes | None = None
) -> dict[str, Any]:
    signing_key = signing_key or os.environ.get("VNA_EVALUATION_HMAC_KEY", "").encode()
    if not signing_key:
        raise ModelError("VNA_EVALUATION_HMAC_KEY is required to verify release evidence")
    signature = value.get("signature")
    if not isinstance(signature, Mapping) or signature.get("algorithm") != "hmac-sha256":
        raise ModelError("release manifest requires an HMAC-SHA256 signature")
    unsigned = {str(name): item for name, item in value.items() if name != "signature"}
    expected_signature = hmac.new(
        signing_key, _canonical_json(unsigned), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(str(signature.get("value", "")), expected_signature):
        raise ModelError("release manifest signature is invalid")
    verified_evidence_refs = _validate_evidence_artifacts(value)

    runs = [ShadowRun.from_dict(item) for item in value.get("runs", [])]
    invalid_measurements = _validate_run_measurement_artifacts(
        runs, value["evidence_artifacts"]
    )
    languages = [
        LanguageAcceptance.from_dict(item)
        for item in value.get("languages", [])
    ]
    issue_samples = [
        LanguageIssueSample.from_dict(item)
        for item in value.get("language_issue_samples", [])
    ]
    policy = AcceptancePolicy.from_dict(value.get("policy", {}))
    catalog = KnowledgeCatalog.load(default_knowledge_root())
    required_languages = set(catalog.languages)
    required_issues = {
        (language, str(entry["issue_id"]), str(entry["family"]).upper())
        for language, profile in catalog.profiles.items()
        for entry in profile["entries"]
    }
    sample_by_cell: dict[tuple[str, str, str], LanguageIssueSample] = {}
    duplicate_cells = []
    for sample in issue_samples:
        cell = (sample.language, sample.issue_id, sample.family)
        if cell in sample_by_cell:
            duplicate_cells.append(cell)
        sample_by_cell[cell] = sample
    supplied_cells = set(sample_by_cell)
    missing_cells = sorted(required_issues - supplied_cells)
    unexpected_cells = sorted(supplied_cells - required_issues)
    invalid_samples = sorted(
        f"{item.language}:{item.issue_id}"
        for item in issue_samples
        if not item.held_out or item.synthetic
        or item.sample_count < policy.minimum_issue_samples
    )
    language_recall: dict[str, dict[str, float | int]] = {}
    issue_deltas: dict[str, float] = {}
    issue_cell_metrics: dict[str, dict[str, Any]] = {}
    for language in catalog.languages:
        rows = [item for item in issue_samples if item.language == language]
        expected_count = sum(item.sample_count for item in rows)
        v3_count = sum(item.v3_detected_count for item in rows)
        vnext_count = sum(item.vnext_detected_count for item in rows)
        language_recall[language] = {
            "sample_count": expected_count,
            "v3_recall": v3_count / expected_count if expected_count else 0.0,
            "vnext_recall": vnext_count / expected_count if expected_count else 0.0,
            "delta": (vnext_count - v3_count) / expected_count if expected_count else 0.0,
            "v3_recall_95ci": _wilson_interval(v3_count, expected_count),
            "vnext_recall_95ci": _wilson_interval(vnext_count, expected_count),
        }
        for item in rows:
            cell_id = f"{language}:{item.issue_id}"
            issue_deltas[cell_id] = (
                item.vnext_detected_count - item.v3_detected_count
            ) / item.sample_count if item.sample_count else 0.0
            issue_cell_metrics[cell_id] = {
                "family": item.family,
                "sample_count": item.sample_count,
                "v3_recall": item.v3_detected_count / item.sample_count if item.sample_count else 0.0,
                "vnext_recall": item.vnext_detected_count / item.sample_count if item.sample_count else 0.0,
                "delta": issue_deltas[cell_id],
                "v3_recall_95ci": _wilson_interval(item.v3_detected_count, item.sample_count),
                "vnext_recall_95ci": _wilson_interval(item.vnext_detected_count, item.sample_count),
            }
    pairs = _pair_runs(runs)
    paired_run_ids = {
        (project_id, engine)
        for project_id in pairs
        for engine in ("v3", "vnext")
    }
    incomplete_pairs = sorted({
        run.project_id for run in runs
        if (run.project_id, run.engine) not in paired_run_ids
    })
    pair_mismatches = [
        project_id
        for project_id, (v3_run, vnext_run) in pairs.items()
        if v3_run.snapshot_id != vnext_run.snapshot_id
        or v3_run.scope_digest != vnext_run.scope_digest
        or v3_run.execution_config_digest != vnext_run.execution_config_digest
        or dict(v3_run.budget) != dict(vnext_run.budget)
        or v3_run.held_out != vnext_run.held_out
        or v3_run.synthetic != vnext_run.synthetic
        or {
            (item.finding_id, item.family) for item in v3_run.expected_findings
        } != {
            (item.finding_id, item.family) for item in vnext_run.expected_findings
        }
    ]
    comparable_pairs = {
        project_id: pair
        for project_id, pair in pairs.items()
        if project_id not in pair_mismatches
    }

    v3_detected = {
        f"{project_id}:{finding_id}"
        for project_id, (v3_run, _) in comparable_pairs.items()
        for finding_id in v3_run.detected_finding_ids
    }
    vnext_detected = {
        f"{project_id}:{finding_id}"
        for project_id, (_, vnext_run) in comparable_pairs.items()
        for finding_id in vnext_run.detected_finding_ids
    }
    lost_core_findings = sorted(v3_detected - vnext_detected)
    gates: dict[str, dict[str, Any]] = {
        "RG1": {
            "pass": bool(comparable_pairs)
            and not incomplete_pairs
            and not pair_mismatches
            and not lost_core_findings,
            "detail": {
                "paired_projects": sorted(comparable_pairs),
                "incomplete_pairs": incomplete_pairs,
                "comparison_mismatches": pair_mismatches,
                "lost_v3_findings": lost_core_findings,
            },
        }
    }

    held_out_pairs = {
        project_id: pair
        for project_id, pair in comparable_pairs.items()
        if pair[0].held_out and pair[1].held_out and not pair[0].synthetic
        and not pair[1].synthetic
    }
    v3_held_out_recall = _aggregate_recall(pair[0] for pair in held_out_pairs.values())
    vnext_held_out_recall = _aggregate_recall(
        pair[1] for pair in held_out_pairs.values()
    )
    family_deltas = _family_recall_deltas(held_out_pairs.values())
    improved_families = sorted(
        family for family, delta in family_deltas.items() if delta > 0
    )
    gates["RG2"] = {
        "pass": bool(held_out_pairs)
        and vnext_held_out_recall >= v3_held_out_recall
        and len(improved_families) >= policy.minimum_improved_families,
        "detail": {
            "v3_recall_at_budget": v3_held_out_recall,
            "vnext_recall_at_budget": vnext_held_out_recall,
            "improved_families": improved_families,
            "family_deltas": family_deltas,
        },
    }

    real_pairs = [
        pair for pair in comparable_pairs.values()
        if not pair[0].synthetic and not pair[1].synthetic
    ]
    v3_noise = _noise_ratio(pair[0] for pair in real_pairs)
    vnext_noise = _noise_ratio(pair[1] for pair in real_pairs)
    gates["RG3"] = {
        "pass": bool(real_pairs)
        and vnext_noise <= v3_noise + policy.maximum_noise_ratio_increase,
        "detail": {"v3_noise_ratio": v3_noise, "vnext_noise_ratio": vnext_noise},
    }

    real_vnext_runs = [
        run for run in runs if run.engine == "vnext" and not run.synthetic
    ]
    covered_classes = {run.project_class for run in real_vnext_runs}
    large_runs = [
        run for run in real_vnext_runs
        if run.repository_size_bytes >= policy.large_repository_bytes
        and run.campaign_complete
        and run.interruption_recovered
    ]
    gates["RG4"] = {
        "pass": covered_classes == _PROJECT_CLASSES and bool(large_runs)
        and not invalid_measurements,
        "detail": {
            "missing_project_classes": sorted(_PROJECT_CLASSES - covered_classes),
            "qualifying_large_projects": sorted(run.project_id for run in large_runs),
            "invalid_measurement_runs": invalid_measurements,
        },
    }
    unreconciled_handoffs = sorted(
        run.project_id for run in real_vnext_runs
        if run.handoff_count != run.reconciled_handoff_count
    )
    gates["RG5"] = {
        "pass": bool(real_vnext_runs) and not unreconciled_handoffs,
        "detail": {"unreconciled_projects": unreconciled_handoffs},
    }
    certified_languages = [item for item in languages if item.certified]
    certified_language_ids = [item.language for item in certified_languages]
    failed_languages = sorted(
        item.language for item in certified_languages
        if not item.adapter_contract_passed or not item.held_out_sample_passed
    )
    gates["RG6"] = {
        "pass": len(certified_language_ids) == len(required_languages)
        and set(certified_language_ids) == required_languages
        and len(languages) == len(required_languages)
        and {item.language for item in languages} == required_languages
        and not failed_languages,
        "detail": {
            "required_languages": sorted(required_languages),
            "missing_languages": sorted(required_languages - {item.language for item in certified_languages}),
            "unexpected_languages": sorted({item.language for item in languages} - required_languages),
            "duplicate_languages": sorted({
                item.language for item in languages
                if sum(other.language == item.language for other in languages) > 1
            }),
            "failed_certified_languages": failed_languages,
        },
    }

    worst_family_delta = min(family_deltas.values(), default=float("-inf"))
    worst_language_delta = min(
        (float(item["delta"]) for item in language_recall.values()),
        default=float("-inf"),
    )
    worst_issue_delta = min(issue_deltas.values(), default=float("-inf"))
    worst_group_delta = min(worst_family_delta, worst_language_delta, worst_issue_delta)
    gates["RG7"] = {
        "pass": bool(family_deltas) and bool(issue_deltas)
        and worst_group_delta >= -policy.maximum_worst_group_recall_drop,
        "detail": {
            "worst_family_recall_delta": worst_family_delta,
            "worst_language_recall_delta": worst_language_delta,
            "worst_issue_recall_delta": worst_issue_delta,
            "worst_group_recall_delta": worst_group_delta,
            "per_language_recall": language_recall,
        },
    }
    deproject = value.get("runtime_deproject_scan", {})
    runtime_root = Path(__file__).resolve().parents[2]
    forbidden_tokens = [str(item) for item in value.get("forbidden_residue_tokens", [])]
    actual_deproject = scan_runtime_deproject(runtime_root, forbidden_tokens)
    gates["RG8"] = {
        "pass": deproject.get("passed") is True
        and bool(deproject.get("evidence_refs"))
        and actual_deproject["passed"],
        "detail": {
            "evidence_refs": list(deproject.get("evidence_refs", [])),
            "runtime_scan": actual_deproject,
        },
    }
    compatibility = value.get("compatibility_scan", {})
    actual_compatibility = scan_runtime_compatibility(runtime_root, forbidden_tokens)
    gates["RG9"] = {
        "pass": bool(compatibility.get("passed"))
        and bool(compatibility.get("evidence_refs"))
        and actual_compatibility["passed"],
        "detail": {
            "evidence_refs": list(compatibility.get("evidence_refs", [])),
            "runtime_scan": actual_compatibility,
        },
    }
    untraceable_projects = sorted(
        run.project_id for run in real_vnext_runs if not run.evidence_traceable
    )
    gates["RG10"] = {
        "pass": bool(real_vnext_runs) and not untraceable_projects,
        "detail": {"untraceable_projects": untraceable_projects},
    }
    mixed_evidence = value.get("mixed_language_evidence", [])
    valid_mixed = [
        item for item in mixed_evidence
        if isinstance(item, dict)
        and item.get("held_out") is True
        and item.get("synthetic") is False
        and len(set(item.get("languages", []))) >= 2
        and set(item.get("languages", [])).issubset(required_languages)
        and int(item.get("boundary_cases", 0)) > 0
        and int(item.get("reconciled_cases", -1)) == int(item.get("boundary_cases", 0))
        and bool(item.get("evidence_refs"))
        and item.get("project_id") in {run.project_id for run in real_vnext_runs}
    ]
    gates["RG11"] = {
        "pass": bool(valid_mixed)
        and not missing_cells
        and not unexpected_cells
        and not duplicate_cells
        and not invalid_samples,
        "detail": {
            "valid_mixed_projects": sorted(item["project_id"] for item in valid_mixed),
            "required_language_issue_cells": len(required_issues),
            "missing_cells": [list(item) for item in missing_cells],
            "unexpected_cells": [list(item) for item in unexpected_cells],
            "duplicate_cells": [list(item) for item in sorted(set(duplicate_cells))],
            "invalid_samples": invalid_samples,
            "verified_evidence_artifacts": len(verified_evidence_refs),
            "issue_cell_metrics": issue_cell_metrics,
        },
    }
    enabled_provider_ids = set(enabled_hotspot_provider_ids())
    provider_records = value.get("hotspot_provider_acceptance")
    if not isinstance(provider_records, list):
        provider_records = []
    provider_by_id: dict[str, Mapping[str, Any]] = {}
    duplicate_providers: set[str] = set()
    invalid_providers: set[str] = set()
    unexpected_providers: set[str] = set()
    provider_metrics: dict[str, dict[str, Any]] = {}
    required_record_fields = {
        "provider_id", "enabled", "fixture_results", "held_out", "evidence_refs",
    }
    required_fixtures = {"positive", "negative", "alias", "malformed_source"}
    required_heldout_fields = {
        "sample_count", "expected_candidate_sites", "candidate_covered_sites",
        "candidate_count", "reviewed_candidate_count", "true_positive_candidates",
        "held_out", "synthetic",
    }
    for record in provider_records:
        if not isinstance(record, Mapping):
            invalid_providers.add("<invalid-provider-record>")
            continue
        provider_id = str(record.get("provider_id", ""))
        if not provider_id:
            invalid_providers.add("<missing-provider-id>")
            continue
        if provider_id in provider_by_id:
            duplicate_providers.add(provider_id)
            continue
        provider_by_id[provider_id] = record
        if provider_id not in enabled_provider_ids:
            unexpected_providers.add(provider_id)
    missing_providers = enabled_provider_ids - set(provider_by_id)
    for provider_id in enabled_provider_ids & set(provider_by_id):
        record = provider_by_id[provider_id]
        fixture_results = record.get("fixture_results")
        held_out = record.get("held_out")
        evidence_refs = record.get("evidence_refs")
        if (
            set(record) != required_record_fields
            or record.get("enabled") is not True
            or not isinstance(fixture_results, Mapping)
            or set(fixture_results) != required_fixtures
            or any(fixture_results.get(name) is not True for name in required_fixtures)
            or not isinstance(held_out, Mapping)
            or set(held_out) != required_heldout_fields
            or held_out.get("held_out") is not True
            or held_out.get("synthetic") is not False
            or not isinstance(evidence_refs, list)
            or not evidence_refs
            or any(reference not in verified_evidence_refs for reference in evidence_refs)
        ):
            invalid_providers.add(provider_id)
            continue
        sample_count = held_out["sample_count"]
        expected_sites = held_out["expected_candidate_sites"]
        covered_sites = held_out["candidate_covered_sites"]
        candidate_count = held_out["candidate_count"]
        reviewed_count = held_out["reviewed_candidate_count"]
        true_positive_count = held_out["true_positive_candidates"]
        counts = (sample_count, expected_sites, covered_sites, candidate_count,
                  reviewed_count, true_positive_count)
        if (
            any(type(amount) is not int or amount < 0 for amount in counts)
            or sample_count < 1
            or expected_sites < 1
            or covered_sites > expected_sites
            or reviewed_count > candidate_count
            or true_positive_count > reviewed_count
        ):
            invalid_providers.add(provider_id)
            continue
        provider_metrics[provider_id] = {
            "sample_count": sample_count,
            "candidate_coverage": covered_sites / expected_sites,
            "candidate_precision": (
                true_positive_count / reviewed_count if reviewed_count else None
            ),
            "candidate_count": candidate_count,
            "reviewed_candidate_count": reviewed_count,
            "true_positive_candidates": true_positive_count,
            "evidence_refs": list(evidence_refs),
        }
    gates["RG12"] = {
        "pass": bool(enabled_provider_ids)
        and not missing_providers
        and not duplicate_providers
        and not unexpected_providers
        and not invalid_providers,
        "detail": {
            "enabled_provider_ids": sorted(enabled_provider_ids),
            "missing_providers": sorted(missing_providers),
            "duplicate_providers": sorted(duplicate_providers),
            "unexpected_providers": sorted(unexpected_providers),
            "invalid_providers": sorted(invalid_providers),
            "provider_metrics": provider_metrics,
        },
    }
    clean_room_detail = _clean_room_provenance_detail(
        real_vnext_runs,
        value.get("clean_room_provenance"),
        value["evidence_artifacts"],
    )
    gates["RG13"] = {
        "pass": bool(real_vnext_runs)
        and not any(clean_room_detail[key] for key in (
            "missing_projects", "duplicate_projects",
            "unexpected_projects", "invalid_projects",
        )),
        "detail": clean_room_detail,
    }
    missing_screening_evidence = []
    invalid_screening_projects = []
    over_ceiling_projects = []
    overridden_projects = []
    for run in real_vnext_runs:
        record = value["evidence_artifacts"].get(run.measurement_artifact_ref)
        content = record.get("content") if isinstance(record, dict) else None
        coverage = content.get("screening_coverage") if isinstance(content, dict) else None
        if not isinstance(coverage, dict):
            missing_screening_evidence.append(run.project_id)
            continue
        required_screening_fields = {
            "screened_work_unit_ids", "screened_work_unit_count",
            "total_work_unit_count", "screened_fraction",
            "max_screening_fraction", "ceiling_status", "release_eligible",
        }
        if (
            not required_screening_fields.issubset(coverage)
            or set(coverage) - required_screening_fields - {"human_override"}
        ):
            invalid_screening_projects.append(run.project_id)
            continue
        screened_ids = coverage["screened_work_unit_ids"]
        screened_count = coverage["screened_work_unit_count"]
        total_count = coverage["total_work_unit_count"]
        reported_fraction = coverage["screened_fraction"]
        ceiling = coverage["max_screening_fraction"]
        override = coverage.get("human_override", False)
        if (
            not isinstance(screened_ids, list)
            or any(not isinstance(item, str) or not item for item in screened_ids)
            or len(screened_ids) != len(set(screened_ids))
            or type(screened_count) is not int
            or type(total_count) is not int
            or total_count <= 0
            or screened_count < 0
            or screened_count > total_count
            or len(screened_ids) != screened_count
            or isinstance(reported_fraction, bool)
            or not isinstance(reported_fraction, (int, float))
            or not math.isfinite(reported_fraction)
            or isinstance(ceiling, bool)
            or not isinstance(ceiling, (int, float))
            or not math.isfinite(ceiling)
            or not 0 <= ceiling <= 1
            or type(override) is not bool
        ):
            invalid_screening_projects.append(run.project_id)
            continue
        measured_fraction = screened_count / total_count
        within_ceiling = measured_fraction <= ceiling
        expected_status = "WITHIN_CEILING" if within_ceiling else "EXCEEDED"
        if (
            not math.isclose(reported_fraction, measured_fraction, rel_tol=1e-9, abs_tol=1e-9)
            or coverage["ceiling_status"] != expected_status
            or coverage["release_eligible"] is not within_ceiling
        ):
            invalid_screening_projects.append(run.project_id)
        if not within_ceiling:
            over_ceiling_projects.append(run.project_id)
        if override:
            overridden_projects.append(run.project_id)
    gates["RG14"] = {
        "pass": bool(real_vnext_runs)
        and not missing_screening_evidence
        and not invalid_screening_projects
        and not over_ceiling_projects
        and not overridden_projects,
        "detail": {
            "missing_screening_evidence": missing_screening_evidence,
            "invalid_screening_projects": invalid_screening_projects,
            "over_ceiling_projects": over_ceiling_projects,
            "overridden_projects": overridden_projects,
        },
    }
    scale_acceptance = value.get("scale_acceptance")
    fixture = scale_acceptance.get("fixture") if isinstance(scale_acceptance, dict) else None
    missing_fixture = not isinstance(fixture, dict)
    invalid_fixture = False
    if isinstance(fixture, dict):
        fixture_flags = (
            "indexed_queries", "bulk_resolution", "per_edge_reconciliation",
            "atomic_failure_behavior", "oldest_first_task_order",
            "bounded_zero_target_cost",
        )
        handoff_count = fixture.get("handoff_count")
        event_count = fixture.get("event_count")
        fixture_refs = fixture.get("evidence_refs")
        invalid_fixture = (
            set(fixture) != {*fixture_flags, "handoff_count", "event_count", "evidence_refs"}
            or type(handoff_count) is not int
            or handoff_count < 30_000
            or type(event_count) is not int
            or event_count < 10_000
            or any(fixture.get(flag) is not True for flag in fixture_flags)
            or not isinstance(fixture_refs, list)
            or not fixture_refs
            or any(reference not in verified_evidence_refs for reference in fixture_refs)
        )
    large_campaign_records = (
        scale_acceptance.get("large_campaigns", [])
        if isinstance(scale_acceptance, dict) else []
    )
    real_runs_by_project = {run.project_id: run for run in real_vnext_runs}
    qualifying_large_projects = []
    invalid_large_campaigns = []
    seen_large_projects = set()
    if not isinstance(large_campaign_records, list):
        large_campaign_records = []
        invalid_large_campaigns.append("<invalid-large-campaign-list>")
    for item in large_campaign_records:
        if not isinstance(item, dict):
            invalid_large_campaigns.append("<invalid-large-campaign-record>")
            continue
        project_id = str(item.get("project_id", ""))
        refs = item.get("evidence_refs")
        if not project_id or project_id in seen_large_projects:
            invalid_large_campaigns.append(project_id or "<missing-project-id>")
            continue
        seen_large_projects.add(project_id)
        run = real_runs_by_project.get(project_id)
        if (
            run is None
            or run.repository_size_bytes < policy.large_repository_bytes
            or not run.campaign_complete
            or not run.interruption_recovered
            or run.handoff_count != run.reconciled_handoff_count
            or not isinstance(refs, list)
            or not refs
            or any(reference not in verified_evidence_refs for reference in refs)
            or run.measurement_artifact_ref not in refs
            or not set(refs).issubset(run.evidence_refs)
        ):
            invalid_large_campaigns.append(project_id)
        else:
            qualifying_large_projects.append(project_id)
    gates["RG15"] = {
        "pass": not missing_fixture
        and not invalid_fixture
        and bool(qualifying_large_projects)
        and not invalid_large_campaigns,
        "detail": {
            "missing_fixture": missing_fixture,
            "invalid_fixture": invalid_fixture,
            "missing_large_campaign": not bool(qualifying_large_projects),
            "qualifying_large_projects": sorted(qualifying_large_projects),
            "invalid_large_campaigns": sorted(invalid_large_campaigns),
        },
    }
    subset_passed = all(gates[gate_id]["pass"] for gate_id in IMPLEMENTED_RELEASE_GATES)
    unimplemented_gates = [gate_id for gate_id in REQUIRED_RELEASE_GATES if gate_id not in gates]
    for gate_id in unimplemented_gates:
        gates[gate_id] = {
            "pass": False,
            "detail": {"status": "NOT_IMPLEMENTED", "reason": "required release check is unavailable"},
        }
    failed_gates = [gate_id for gate_id in REQUIRED_RELEASE_GATES if not gates[gate_id]["pass"]]
    return {
        "schema_version": "1.0",
        "status": "ACCEPTED" if not failed_gates else "BLOCKED",
        "eligible_for_promotion": not failed_gates,
        "implemented_subset_status": "PASS" if subset_passed else "BLOCKED",
        "unimplemented_gates": unimplemented_gates,
        "failed_gates": failed_gates,
        "gates": gates,
        "policy": {
            "release_policy_version": RELEASE_POLICY_VERSION,
            "required_gates": list(REQUIRED_RELEASE_GATES),
            "minimum_improved_families": policy.minimum_improved_families,
            "maximum_noise_ratio_increase": policy.maximum_noise_ratio_increase,
            "maximum_worst_group_recall_drop": policy.maximum_worst_group_recall_drop,
            "large_repository_bytes": policy.large_repository_bytes,
            "minimum_issue_samples": policy.minimum_issue_samples,
        },
    }


def write_evaluation_report(path: str | Path, report: Mapping[str, Any]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{destination.name}.", dir=destination.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _pair_runs(runs: Sequence[ShadowRun]) -> dict[str, tuple[ShadowRun, ShadowRun]]:
    grouped: dict[str, dict[str, ShadowRun]] = {}
    duplicates = []
    for run in runs:
        engines = grouped.setdefault(run.project_id, {})
        if run.engine in engines:
            duplicates.append(f"{run.project_id}:{run.engine}")
        engines[run.engine] = run
    if duplicates:
        raise ModelError(f"duplicate shadow runs: {sorted(duplicates)}")
    return {
        project_id: (engines["v3"], engines["vnext"])
        for project_id, engines in grouped.items()
        if set(engines) == {"v3", "vnext"}
    }


def _canonical_json(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _is_sha256(value: str) -> bool:
    algorithm, separator, digest = value.partition(":")
    return (
        algorithm == "sha256"
        and separator == ":"
        and len(digest) == 64
        and all(character in "0123456789abcdef" for character in digest)
    )


def _validate_evidence_artifacts(value: Mapping[str, Any]) -> set[str]:
    registry = value.get("evidence_artifacts")
    if not isinstance(registry, dict):
        raise ModelError("release manifest requires an evidence_artifacts registry")
    required_refs: set[str] = set()

    def collect(node: Any) -> None:
        if isinstance(node, Mapping):
            refs = node.get("evidence_refs")
            if isinstance(refs, list):
                required_refs.update(str(item) for item in refs)
            for child in node.values():
                collect(child)
        elif isinstance(node, list):
            for child in node:
                collect(child)

    collect({key: item for key, item in value.items() if key != "evidence_artifacts"})
    missing = required_refs - set(registry)
    if missing:
        raise ModelError(f"evidence artifact references are unresolved: {sorted(missing)}")
    for artifact_ref in sorted(required_refs):
        record = registry[artifact_ref]
        if not isinstance(record, dict) or "content" not in record:
            raise ModelError(f"invalid evidence artifact record: {artifact_ref}")
        digest = hashlib.sha256(_canonical_json(record["content"])).hexdigest()
        if not hmac.compare_digest(str(record.get("sha256", "")), digest):
            raise ModelError(f"evidence artifact digest mismatch: {artifact_ref}")
    return required_refs


def _validate_run_measurement_artifacts(
    runs: Sequence[ShadowRun], registry: Mapping[str, Any]
) -> list[str]:
    invalid = []
    for run in runs:
        record = registry.get(run.measurement_artifact_ref)
        content = record.get("content") if isinstance(record, dict) else None
        if not isinstance(content, dict):
            invalid.append(f"{run.project_id}:{run.engine}:missing-measurement-artifact")
            continue
        expected = {
            "repository_size_bytes": run.repository_size_bytes,
            "scope_digest": run.scope_digest,
            "execution_config_digest": run.execution_config_digest,
            "measurements": dict(run.measurements),
            "campaign_complete": run.campaign_complete,
            "interruption_recovered": run.interruption_recovered,
            "handoff_count": run.handoff_count,
            "reconciled_handoff_count": run.reconciled_handoff_count,
        }
        if any(content.get(key) != value for key, value in expected.items()):
            invalid.append(f"{run.project_id}:{run.engine}:measurement-mismatch")
    return sorted(invalid)


def _clean_room_provenance_detail(
    runs: Sequence[ShadowRun],
    attestations: Any,
    registry: Mapping[str, Any],
) -> dict[str, Any]:
    expected_projects = {run.project_id for run in runs}
    if not isinstance(attestations, list):
        attestations = []
    by_project: dict[str, Mapping[str, Any]] = {}
    duplicate_projects: set[str] = set()
    invalid_projects: set[str] = set()
    for item in attestations:
        if not isinstance(item, Mapping):
            invalid_projects.add("<invalid-attestation>")
            continue
        project_id = str(item.get("project_id", ""))
        if not project_id:
            invalid_projects.add("<missing-project-id>")
        elif project_id in by_project:
            duplicate_projects.add(project_id)
        else:
            by_project[project_id] = item
    missing_projects = expected_projects - set(by_project)
    unexpected_projects = set(by_project) - expected_projects
    verified_input_artifacts: set[str] = set()
    for run in runs:
        attestation = by_project.get(run.project_id)
        if attestation is None:
            continue
        report_record = registry.get(run.measurement_artifact_ref)
        report = report_record.get("content") if isinstance(report_record, dict) else None
        if not isinstance(report, dict):
            invalid_projects.add(run.project_id)
            continue
        report_campaign_id = report.get("campaign_id")
        measurement = report.get("execution_measurements")
        tasks = measurement.get("tasks") if isinstance(measurement, dict) else None
        if (
            not isinstance(report_campaign_id, str)
            or not report_campaign_id
            or report.get("snapshot_id") != run.snapshot_id
            or report.get("audit_mode") != "fresh"
            or report.get("history_source_campaign_ids") != []
            or not isinstance(tasks, list)
        ):
            invalid_projects.add(run.project_id)
            continue
        task_input_refs: set[str] = set()
        primary_input_operations: dict[str, set[str]] = {}
        saw_r1 = False
        saw_r2 = False
        for task in tasks:
            if not isinstance(task, dict):
                continue
            operation = str(task.get("operation", ""))
            is_r1 = operation == "discover_surfaces"
            is_r2 = (
                operation == "generate_hypotheses"
                or operation.startswith("generate_hypotheses:")
            )
            if not is_r1 and not is_r2:
                continue
            saw_r1 = saw_r1 or is_r1
            saw_r2 = saw_r2 or is_r2
            refs = task.get("input_artifact_refs")
            if not isinstance(refs, list) or not refs or any(
                not isinstance(reference, str) or not reference for reference in refs
            ):
                invalid_projects.add(run.project_id)
                continue
            task_input_refs.update(refs)
            primary_input_operations.setdefault(refs[0], set()).add(operation)
        supplied_refs_value = attestation.get("r1_r2_input_refs")
        supplied_refs = (
            set(supplied_refs_value)
            if isinstance(supplied_refs_value, list)
            and all(isinstance(item, str) and item for item in supplied_refs_value)
            else set()
        )
        attestation_evidence_value = attestation.get("evidence_refs")
        attestation_evidence = (
            set(attestation_evidence_value)
            if isinstance(attestation_evidence_value, list)
            and all(isinstance(item, str) and item for item in attestation_evidence_value)
            else set()
        )
        if (
            not saw_r1
            or not saw_r2
            or supplied_refs != task_input_refs
            or not isinstance(supplied_refs_value, list)
            or len(supplied_refs_value) != len(supplied_refs)
            or report_campaign_id != attestation.get("campaign_id")
            or attestation.get("audit_mode") != "fresh"
            or attestation.get("history_source_campaign_ids") != []
            or attestation.get("prior_target_artifacts_excluded") is not True
            or attestation.get("regression_backlog_excluded") is not True
            or not isinstance(attestation.get("verified_by"), str)
            or not attestation.get("verified_by", "").strip()
            or run.measurement_artifact_ref not in attestation_evidence
            or not task_input_refs.issubset(attestation_evidence)
        ):
            invalid_projects.add(run.project_id)
        for reference, operations in primary_input_operations.items():
            artifact_record = registry.get(reference)
            content = artifact_record.get("content") if isinstance(artifact_record, dict) else None
            if (
                not isinstance(content, dict)
                or content.get("operation") not in operations
                or content.get("snapshot_id") != run.snapshot_id
                or content.get("audit_mode", "fresh") != "fresh"
                or content.get("history_source_campaign_ids", []) != []
            ):
                invalid_projects.add(run.project_id)
            else:
                verified_input_artifacts.add(reference)
    return {
        "missing_projects": sorted(missing_projects),
        "duplicate_projects": sorted(duplicate_projects),
        "unexpected_projects": sorted(unexpected_projects),
        "invalid_projects": sorted(invalid_projects),
        "verified_primary_input_artifacts": len(verified_input_artifacts),
    }


def _wilson_interval(successes: int, trials: int, z: float = 1.96) -> tuple[float, float] | None:
    if trials <= 0:
        return None
    rate = successes / trials
    denominator = 1 + z * z / trials
    center = (rate + z * z / (2 * trials)) / denominator
    margin = z * (
        rate * (1 - rate) / trials + z * z / (4 * trials * trials)
    ) ** 0.5 / denominator
    return max(0.0, center - margin), min(1.0, center + margin)


def _aggregate_recall(runs: Any) -> float:
    expected = 0
    detected = 0
    for run in runs:
        expected_ids = {item.finding_id for item in run.expected_findings}
        expected += len(expected_ids)
        detected += len(set(run.detected_finding_ids) & expected_ids)
    return detected / expected if expected else 0.0


def _noise_ratio(runs: Any) -> float:
    noise = 0
    results = 0
    for run in runs:
        run_noise = run.false_positive_count + run.needs_review_count
        noise += run_noise
        results += len(run.detected_finding_ids) + run_noise
    return noise / results if results else 0.0


def _family_recall_deltas(
    pairs: Any,
) -> dict[str, float]:
    expected: dict[str, set[str]] = {}
    v3_detected: dict[str, set[str]] = {}
    vnext_detected: dict[str, set[str]] = {}
    for v3_run, vnext_run in pairs:
        for finding in v3_run.expected_findings:
            expected.setdefault(finding.family, set()).add(
                f"{v3_run.project_id}:{finding.finding_id}"
            )
        for finding in v3_run.expected_findings:
            key = f"{v3_run.project_id}:{finding.finding_id}"
            if finding.finding_id in v3_run.detected_finding_ids:
                v3_detected.setdefault(finding.family, set()).add(key)
            if finding.finding_id in vnext_run.detected_finding_ids:
                vnext_detected.setdefault(finding.family, set()).add(key)
    return {
        family: (
            len(vnext_detected.get(family, set()))
            - len(v3_detected.get(family, set()))
        ) / len(expected_ids)
        for family, expected_ids in sorted(expected.items())
    }