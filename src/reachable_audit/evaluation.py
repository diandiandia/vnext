"""Phase 6 shadow-run comparison and release acceptance gates."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping, Sequence

from .models import ModelError
from .knowledge_catalog import KnowledgeCatalog, default_knowledge_root
from .compatibility import scan_runtime_compatibility, scan_runtime_deproject


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
        and not failed_languages,
        "detail": {
            "required_languages": sorted(required_languages),
            "missing_languages": sorted(required_languages - {item.language for item in certified_languages}),
            "unexpected_languages": sorted({item.language for item in certified_languages} - required_languages),
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
    failed_gates = [gate_id for gate_id, gate in gates.items() if not gate["pass"]]
    return {
        "schema_version": "1.0",
        "status": "ACCEPTED" if not failed_gates else "BLOCKED",
        "eligible_for_promotion": not failed_gates,
        "failed_gates": failed_gates,
        "gates": gates,
        "policy": {
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