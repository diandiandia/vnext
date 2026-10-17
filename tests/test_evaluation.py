import pytest
import hashlib
import json

from reachable_audit.evaluation import ShadowRun, evaluate_release, sign_manifest
from reachable_audit.knowledge_catalog import KnowledgeCatalog, default_knowledge_root
from reachable_audit.models import ModelError


_TEST_SIGNING_KEY = b"vnext-unit-test-signing-key"


def _run(project_id: str, engine: str, project_class: str) -> dict[str, object]:
    measurement_ref = f"METRICS-{project_id}-{engine}"
    return {
        "project_id": project_id,
        "engine": engine,
        "project_class": project_class,
        "snapshot_id": f"git:{project_id}",
        "scope_digest": "sha256:" + "a" * 64,
        "execution_config_digest": "sha256:" + "b" * 64,
        "measurement_artifact_ref": measurement_ref,
        "measurements": {"agent_runs": 10, "wall_seconds": 60, "peak_rss_bytes": 1024},
        "budget": {"minutes": 60, "agent_runs": 10},
        "expected_findings": [
            {"finding_id": f"{project_id}-core", "family": "CORE"},
            {"finding_id": f"{project_id}-state", "family": "STATE"},
            {"finding_id": f"{project_id}-auth", "family": "AUTH"},
        ],
        "detected_finding_ids": (
            [f"{project_id}-core"] if engine == "v3"
            else [
                f"{project_id}-core",
                f"{project_id}-state",
                f"{project_id}-auth",
            ]
        ),
        "false_positive_count": 0,
        "needs_review_count": 0,
        "repository_size_bytes": 21_000_000_000 if project_class == "mixed" else 1,
        "campaign_complete": True,
        "interruption_recovered": project_class == "mixed",
        "handoff_count": 2,
        "reconciled_handoff_count": 2,
        "evidence_traceable": True,
        "held_out": True,
        "synthetic": False,
        "evidence_refs": [f"ART-{project_id}-{engine}", measurement_ref],
    }


def _manifest() -> dict[str, object]:
    runs = []
    for project_class in ("native", "managed", "dynamic", "mixed", "jit"):
        project_id = f"project-{project_class}"
        runs.extend([
            _run(project_id, "v3", project_class),
            _run(project_id, "vnext", project_class),
        ])
    catalog = KnowledgeCatalog.load(default_knowledge_root())
    manifest = {
        "runs": runs,
        "languages": [{
            "language": language,
            "certified": True,
            "adapter_contract_passed": True,
            "held_out_sample_passed": True,
            "evidence_refs": [f"ART-{language}-contract"],
        } for language in catalog.languages],
        "language_issue_samples": [{
            "language": language,
            "issue_id": entry["issue_id"],
            "family": entry["family"],
            "sample_count": 3,
            "v3_detected_count": 1,
            "vnext_detected_count": 2,
            "held_out": True,
            "synthetic": False,
            "evidence_refs": [f"ART-{language}-{entry['issue_id']}-heldout"],
        } for language, profile in catalog.profiles.items()
          for entry in profile["entries"]],
        "policy": {"minimum_issue_samples": 3},
        "mixed_language_evidence": [{
            "project_id": "project-mixed",
            "languages": ["c", "cpp"],
            "boundary_cases": 2,
            "reconciled_cases": 2,
            "held_out": True,
            "synthetic": False,
            "evidence_refs": ["ART-mixed-boundaries"],
        }],
        "runtime_deproject_scan": {"passed": True, "evidence_refs": ["ART-scan"]},
        "compatibility_scan": {"passed": True, "evidence_refs": ["ART-compat"]},
    }
    refs = set()

    def collect(node: object) -> None:
        if isinstance(node, dict):
            if isinstance(node.get("evidence_refs"), list):
                refs.update(str(item) for item in node["evidence_refs"])
            for child in node.values():
                collect(child)
        elif isinstance(node, list):
            for child in node:
                collect(child)

    collect(manifest)
    run_by_metric_ref = {
        run["measurement_artifact_ref"]: run for run in manifest["runs"]
    }
    def artifact_content(ref: str) -> dict[str, object]:
        run = run_by_metric_ref.get(ref)
        if run is None:
            return {"artifact_ref": ref, "fixture": "test-only"}
        return {
            "project_id": run["project_id"],
            "engine": run["engine"],
            "repository_size_bytes": run["repository_size_bytes"],
            "scope_digest": run["scope_digest"],
            "execution_config_digest": run["execution_config_digest"],
            "measurements": run["measurements"],
            "campaign_complete": run["campaign_complete"],
            "interruption_recovered": run["interruption_recovered"],
            "handoff_count": run["handoff_count"],
            "reconciled_handoff_count": run["reconciled_handoff_count"],
        }

    manifest["evidence_artifacts"] = {
        ref: {
            "content": artifact_content(ref),
            "sha256": hashlib.sha256(json.dumps(
                artifact_content(ref),
                ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            ).encode("utf-8")).hexdigest(),
        }
        for ref in refs
    }
    return sign_manifest(manifest, _TEST_SIGNING_KEY)


def _resign(manifest: dict[str, object]) -> dict[str, object]:
    return sign_manifest(
        {key: value for key, value in manifest.items() if key != "signature"},
        _TEST_SIGNING_KEY,
    )


def test_release_blocks_when_required_gates_are_unimplemented() -> None:
    report = evaluate_release(_manifest(), signing_key=_TEST_SIGNING_KEY)
    assert report["status"] == "BLOCKED"
    assert report["eligible_for_promotion"] is False
    assert report["implemented_subset_status"] == "PASS"
    assert report["unimplemented_gates"] == ["RG12", "RG13", "RG14", "RG15"]
    assert report["failed_gates"] == report["unimplemented_gates"]
    assert set(report["gates"]) == {f"RG{index}" for index in range(1, 16)}
    assert report["policy"]["release_policy_version"] == "vnext-release-policy-1"
    assert report["gates"]["RG6"]["pass"] is True
    assert report["gates"]["RG11"]["detail"]["required_language_issue_cells"] == 150

def test_rg8_rejects_manifest_claim_when_runtime_scan_finds_residue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "reachable_audit.evaluation.scan_runtime_deproject",
        lambda _root, _tokens=(): {
            "schema_version": "1.0",
            "passed": False,
            "findings": [{"path": "knowledge/profiles/sample.json", "value": "acme-widget"}],
            "scanned_knowledge_files": 1,
        },
    )

    report = evaluate_release(_manifest(), signing_key=_TEST_SIGNING_KEY)

    assert report["gates"]["RG8"]["pass"] is False
    assert report["status"] == "BLOCKED"
    assert report["gates"]["RG8"]["detail"]["runtime_scan"]["findings"]


def test_synthetic_runs_cannot_satisfy_real_project_acceptance() -> None:
    manifest = _manifest()
    for run in manifest["runs"]:  # type: ignore[index, union-attr]
        run["synthetic"] = True
    manifest = _resign(manifest)
    report = evaluate_release(manifest, signing_key=_TEST_SIGNING_KEY)
    assert report["status"] == "BLOCKED"
    assert {"RG2", "RG4", "RG5", "RG7", "RG10"}.issubset(report["failed_gates"])


def test_shadow_run_rejects_unbudgeted_or_unexpected_results() -> None:
    value = _run("project", "vnext", "dynamic")
    value["detected_finding_ids"] = ["unknown"]
    with pytest.raises(ModelError, match="expected set"):
        ShadowRun.from_dict(value)


def test_release_rejects_an_unpaired_shadow_run() -> None:
    manifest = _manifest()
    manifest["runs"].pop()  # type: ignore[index, union-attr]
    manifest = _resign(manifest)
    report = evaluate_release(manifest, signing_key=_TEST_SIGNING_KEY)
    assert report["gates"]["RG1"]["pass"] is False
    assert report["gates"]["RG1"]["detail"]["incomplete_pairs"] == ["project-jit"]


def test_release_rejects_scope_or_execution_config_mismatch() -> None:
    manifest = _manifest()
    vnext_run = next(
        item for item in manifest["runs"]
        if item["project_id"] == "project-native" and item["engine"] == "vnext"
    )
    vnext_run["scope_digest"] = "sha256:" + "c" * 64
    report = evaluate_release(_resign(manifest), signing_key=_TEST_SIGNING_KEY)
    assert report["gates"]["RG1"]["pass"] is False
    assert "project-native" in report["gates"]["RG1"]["detail"]["comparison_mismatches"]


def test_shadow_run_requires_scope_and_execution_config_digests() -> None:
    value = _run("project", "vnext", "dynamic")
    value.pop("scope_digest")

    with pytest.raises(KeyError):
        ShadowRun.from_dict(value)


def test_release_rejects_tampered_manifest() -> None:
    manifest = _manifest()
    manifest["runs"][0]["evidence_traceable"] = False  # type: ignore[index, union-attr]

    with pytest.raises(ModelError, match="signature is invalid"):
        evaluate_release(manifest, signing_key=_TEST_SIGNING_KEY)


def test_release_rejects_tampered_evidence_digest() -> None:
    manifest = _manifest()
    artifact = next(iter(manifest["evidence_artifacts"].values()))  # type: ignore[index, union-attr]
    artifact["content"]["fixture"] = "modified"  # type: ignore[index]
    manifest = _resign(manifest)

    with pytest.raises(ModelError, match="digest mismatch"):
        evaluate_release(manifest, signing_key=_TEST_SIGNING_KEY)


def test_release_requires_all_fifteen_languages() -> None:
    manifest = _manifest()
    manifest["languages"].pop()  # type: ignore[index, union-attr]

    report = evaluate_release(_resign(manifest), signing_key=_TEST_SIGNING_KEY)

    assert report["gates"]["RG6"]["pass"] is False
    assert report["gates"]["RG6"]["detail"]["missing_languages"] == ["shell"]


def test_release_requires_every_language_issue_stratum() -> None:
    manifest = _manifest()
    manifest["language_issue_samples"].pop()  # type: ignore[index, union-attr]

    report = evaluate_release(_resign(manifest), signing_key=_TEST_SIGNING_KEY)

    assert report["gates"]["RG11"]["pass"] is False
    assert len(report["gates"]["RG11"]["detail"]["missing_cells"]) == 1


@pytest.mark.parametrize("duplicate", [False, True])
def test_release_rejects_extra_uncertified_language_records(duplicate: bool) -> None:
    manifest = _manifest()
    extra = dict(manifest["languages"][0])
    extra["certified"] = False
    if not duplicate:
        extra["language"] = "not-in-approved-roster"
    manifest["languages"].append(extra)
    report = evaluate_release(_resign(manifest), signing_key=_TEST_SIGNING_KEY)
    assert report["gates"]["RG6"]["pass"] is False


def test_release_policy_cannot_lower_the_issue_sample_floor() -> None:
    manifest = _manifest()
    manifest["policy"]["minimum_issue_samples"] = 1
    with pytest.raises(ModelError, match="at least three"):
        evaluate_release(_resign(manifest), signing_key=_TEST_SIGNING_KEY)


def test_release_blocks_issue_strata_below_frozen_sample_floor() -> None:
    manifest = _manifest()
    sample = manifest["language_issue_samples"][0]  # type: ignore[index, union-attr]
    sample["sample_count"] = 1
    sample["v3_detected_count"] = 0
    sample["vnext_detected_count"] = 1

    report = evaluate_release(_resign(manifest), signing_key=_TEST_SIGNING_KEY)

    assert report["gates"]["RG11"]["pass"] is False
    assert report["gates"]["RG11"]["detail"]["invalid_samples"]