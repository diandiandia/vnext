import pytest
import hashlib
import hmac
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
        "hotspot_provider_acceptance": [{
            "provider_id": "python-ast-hotspots-v1",
            "enabled": True,
            "fixture_results": {
                "positive": True,
                "negative": True,
                "alias": True,
                "malformed_source": True,
            },
            "held_out": {
                "sample_count": 10,
                "expected_candidate_sites": 10,
                "candidate_covered_sites": 8,
                "candidate_count": 12,
                "reviewed_candidate_count": 10,
                "true_positive_candidates": 7,
                "held_out": True,
                "synthetic": False,
            },
            "evidence_refs": ["ART-hotspot-python"],
        }],
        "scale_acceptance": {
            "fixture": {
                "handoff_count": 30_000,
                "event_count": 10_000,
                "indexed_queries": True,
                "bulk_resolution": True,
                "per_edge_reconciliation": True,
                "atomic_failure_behavior": True,
                "oldest_first_task_order": True,
                "bounded_zero_target_cost": True,
                "evidence_refs": ["ART-scale-fixture"],
            },
            "large_campaigns": [{
                "project_id": "project-mixed",
                "evidence_refs": ["METRICS-project-mixed-vnext"],
            }],
        },
    }
    input_artifact_contents: dict[str, dict[str, object]] = {}
    clean_room_provenance = []
    for run in runs:
        if run["engine"] != "vnext":
            continue
        project_id = str(run["project_id"])
        campaign_id = f"campaign-{project_id}"
        r1_input_ref = f"INPUT-{project_id}-R1"
        r2_input_ref = f"INPUT-{project_id}-R2"
        input_artifact_contents[r1_input_ref] = {
            "operation": "discover_surfaces",
            "snapshot_id": run["snapshot_id"],
        }
        input_artifact_contents[r2_input_ref] = {
            "operation": "generate_hypotheses",
            "snapshot_id": run["snapshot_id"],
        }
        clean_room_provenance.append({
            "project_id": project_id,
            "campaign_id": campaign_id,
            "audit_mode": "fresh",
            "history_source_campaign_ids": [],
            "r1_r2_input_refs": [r1_input_ref, r2_input_ref],
            "prior_target_artifacts_excluded": True,
            "regression_backlog_excluded": True,
            "verified_by": "trusted-evaluator",
            "evidence_refs": [
                run["measurement_artifact_ref"], r1_input_ref, r2_input_ref,
            ],
        })
    manifest["clean_room_provenance"] = clean_room_provenance
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
        if ref in input_artifact_contents:
            return input_artifact_contents[ref]
        run = run_by_metric_ref.get(ref)
        if run is None:
            return {"artifact_ref": ref, "fixture": "test-only"}
        return {
            "campaign_id": f"campaign-{run['project_id']}",
            "snapshot_id": run["snapshot_id"],
            "audit_mode": "fresh",
            "history_source_campaign_ids": [],
            "engine": run["engine"],
            "repository_size_bytes": run["repository_size_bytes"],
            "scope_digest": run["scope_digest"],
            "execution_config_digest": run["execution_config_digest"],
            "measurements": run["measurements"],
            "campaign_complete": run["campaign_complete"],
            "interruption_recovered": run["interruption_recovered"],
            "handoff_count": run["handoff_count"],
            "reconciled_handoff_count": run["reconciled_handoff_count"],
            "screening_coverage": {
                "screened_work_unit_ids": [],
                "screened_work_unit_count": 0,
                "total_work_unit_count": 4,
                "screened_fraction": 0.0,
                "max_screening_fraction": 0.25,
                "ceiling_status": "WITHIN_CEILING",
                "release_eligible": True,
            },
            "campaign_id": f"campaign-{run['project_id']}",
            "audit_mode": "fresh",
            "history_source_campaign_ids": [],
            "execution_measurements": {
                "tasks": [
                    {
                        "operation": "discover_surfaces",
                        "input_artifact_refs": [f"INPUT-{run['project_id']}-R1"],
                    },
                    {
                        "operation": "generate_hypotheses",
                        "input_artifact_refs": [f"INPUT-{run['project_id']}-R2"],
                    },
                ] if run["engine"] == "vnext" else [],
            },
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


def _rewrite_measurement_artifact(
    manifest: dict[str, object], project_id: str, **changes: object,
) -> None:
    run = next(
        item for item in manifest["runs"]
        if item["project_id"] == project_id and item["engine"] == "vnext"
    )
    record = manifest["evidence_artifacts"][run["measurement_artifact_ref"]]
    record["content"].update(changes)
    record["sha256"] = hashlib.sha256(json.dumps(
        record["content"], ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def test_release_accepts_when_all_implemented_gate_evidence_is_valid() -> None:
    manifest = _manifest()
    report = evaluate_release(manifest, signing_key=_TEST_SIGNING_KEY)
    assert report["status"] == "ACCEPTED"
    assert report["eligible_for_promotion"] is True
    assert report["implemented_subset_status"] == "PASS"
    assert report["unimplemented_gates"] == []
    assert report["failed_gates"] == []
    assert report["verified_evidence_refs"] == sorted(manifest["evidence_artifacts"])
    assert set(report["gates"]) == {f"RG{index}" for index in range(1, 16)}
    assert report["policy"]["release_policy_version"] == "vnext-release-policy-6"
    assert report["gates"]["RG6"]["pass"] is True
    assert report["gates"]["RG12"]["pass"] is True
    provider_metric = report["gates"]["RG12"]["detail"]["provider_metrics"]["python-ast-hotspots-v1"]
    assert provider_metric["candidate_coverage"] == 0.8
    assert provider_metric["candidate_precision"] == 0.7
    assert report["gates"]["RG14"]["pass"] is True
    assert report["gates"]["RG15"]["pass"] is True
    assert report["gates"]["RG13"]["pass"] is True
    assert report["gates"]["RG11"]["detail"]["required_language_issue_cells"] == 150


@pytest.mark.parametrize(
    "mutation",
    ("missing", "positive", "negative", "alias", "malformed", "not-held-out", "bad-counts"),
)
def test_rg12_requires_provider_conformance_and_heldout_metrics(mutation: str) -> None:
    manifest = _manifest()
    provider = manifest["hotspot_provider_acceptance"][0]
    if mutation == "missing":
        manifest["hotspot_provider_acceptance"] = []
    elif mutation in {"positive", "negative", "alias", "malformed"}:
        key = "malformed_source" if mutation == "malformed" else mutation
        provider["fixture_results"][key] = False
    elif mutation == "not-held-out":
        provider["held_out"]["synthetic"] = True
    else:
        provider["held_out"]["true_positive_candidates"] = 11
    report = evaluate_release(_resign(manifest), signing_key=_TEST_SIGNING_KEY)
    assert report["gates"]["RG12"]["pass"] is False
    detail = report["gates"]["RG12"]["detail"]
    assert detail["missing_providers"] or detail["invalid_providers"]


@pytest.mark.parametrize(
    ("coverage", "detail_key"),
    (
        (None, "missing_screening_evidence"),
        ({
            "screened_work_unit_ids": ["WU-1", "WU-2"],
            "screened_work_unit_count": 2,
            "total_work_unit_count": 4,
            "screened_fraction": 0.5,
            "max_screening_fraction": 0.25,
            "ceiling_status": "EXCEEDED",
            "release_eligible": False,
        }, "over_ceiling_projects"),
        ({
            "screened_work_unit_ids": ["WU-1"],
            "screened_work_unit_count": 1,
            "total_work_unit_count": 4,
            "screened_fraction": 0.1,
            "max_screening_fraction": 0.25,
            "ceiling_status": "WITHIN_CEILING",
            "release_eligible": True,
        }, "invalid_screening_projects"),
        ({
            "screened_work_unit_ids": [],
            "screened_work_unit_count": 0,
            "total_work_unit_count": 4,
            "screened_fraction": 0.0,
            "max_screening_fraction": 0.25,
            "ceiling_status": "WITHIN_CEILING",
            "release_eligible": True,
            "human_override": True,
        }, "overridden_projects"),
    ),
)
def test_rg14_requires_consistent_digest_backed_screening_evidence(
    coverage: dict[str, object] | None, detail_key: str,
) -> None:
    manifest = _manifest()
    if coverage is None:
        _rewrite_measurement_artifact(
            manifest, "project-native", screening_coverage=None,
        )
    else:
        _rewrite_measurement_artifact(
            manifest, "project-native", screening_coverage=coverage,
        )
    report = evaluate_release(_resign(manifest), signing_key=_TEST_SIGNING_KEY)
    assert report["gates"]["RG14"]["pass"] is False
    assert "project-native" in report["gates"]["RG14"]["detail"][detail_key]


@pytest.mark.parametrize(
    "mutation",
    ("missing", "follow-up", "history", "prior-data", "backlog", "input-refs"),
)
def test_rg13_requires_consistent_signed_fresh_campaign_provenance(
    mutation: str,
) -> None:
    manifest = _manifest()
    provenance = next(
        item for item in manifest["clean_room_provenance"]
        if item["project_id"] == "project-native"
    )
    if mutation == "missing":
        manifest["clean_room_provenance"].remove(provenance)
    elif mutation == "follow-up":
        provenance["audit_mode"] = "follow-up"
    elif mutation == "history":
        provenance["history_source_campaign_ids"] = ["prior-campaign"]
    elif mutation == "prior-data":
        provenance["prior_target_artifacts_excluded"] = False
    elif mutation == "backlog":
        provenance["regression_backlog_excluded"] = False
    else:
        provenance["r1_r2_input_refs"] = provenance["r1_r2_input_refs"][:1]
    report = evaluate_release(_resign(manifest), signing_key=_TEST_SIGNING_KEY)
    assert report["gates"]["RG13"]["pass"] is False
    issue_key = "missing_projects" if mutation == "missing" else "invalid_projects"
    assert "project-native" in report["gates"]["RG13"]["detail"][issue_key]


@pytest.mark.parametrize(
    ("mutation", "detail_key"),
    (
        ("missing", "missing_fixture"),
        ("handoffs", "invalid_fixture"),
        ("atomicity", "invalid_fixture"),
        ("large-campaign", "missing_large_campaign"),
    ),
)
def test_rg15_requires_scale_fixture_and_recovered_large_campaign(
    mutation: str, detail_key: str,
) -> None:
    manifest = _manifest()
    if mutation == "missing":
        manifest.pop("scale_acceptance")
    elif mutation == "handoffs":
        manifest["scale_acceptance"]["fixture"]["handoff_count"] = 29_999
    elif mutation == "atomicity":
        manifest["scale_acceptance"]["fixture"]["atomic_failure_behavior"] = False
    else:
        manifest["scale_acceptance"]["large_campaigns"] = []
    report = evaluate_release(_resign(manifest), signing_key=_TEST_SIGNING_KEY)
    assert report["gates"]["RG15"]["pass"] is False
    assert report["gates"]["RG15"]["detail"][detail_key]

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


def _signed_observation_artifact() -> dict[str, object]:
    payload = {
        "schema_version": "1.0",
        "observation_id": "OBS-release-001",
        "campaign_id": "campaign-project-native",
        "batch_id": "B-release-0001",
        "snapshot_id": "git:project-native",
        "hypothesis_id": "HYP-release",
        "target_ref": "/authorized/target",
        "observer_id": "independent-observer-001",
        "method": "manual runtime observation",
        "observed_at": "2026-10-20T12:00:00Z",
        "evidence_refs": ["sha256:" + "c" * 64],
    }
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return {
        **payload,
        "signature": hmac.new(
            b"observation-authority-test-key", canonical, hashlib.sha256,
        ).hexdigest(),
    }


def test_release_cites_signed_observation_evidence_and_rejects_tampering() -> None:
    manifest = _manifest()
    observation_ref = "ART-external-observation"
    run = next(
        item for item in manifest["runs"]  # type: ignore[union-attr]
        if item["engine"] == "vnext" and item["project_class"] == "native"
    )
    run["evidence_refs"].append(observation_ref)  # type: ignore[union-attr]
    observation = _signed_observation_artifact()
    manifest["evidence_artifacts"][observation_ref] = {  # type: ignore[index]
        "content": observation,
        "sha256": hashlib.sha256(json.dumps(
            observation, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")).hexdigest(),
    }
    report = evaluate_release(_resign(manifest), signing_key=_TEST_SIGNING_KEY)
    assert report["status"] == "ACCEPTED"
    assert observation_ref in report["verified_evidence_refs"]
    assert manifest["evidence_artifacts"][observation_ref]["content"]["signature"] == (  # type: ignore[index]
        observation["signature"]
    )

    tampered = json.loads(json.dumps(manifest))
    tampered["evidence_artifacts"][observation_ref]["content"]["signature"] = "0" * 64
    with pytest.raises(ModelError, match="evidence artifact digest mismatch"):
        evaluate_release(_resign(tampered), signing_key=_TEST_SIGNING_KEY)

    missing = json.loads(json.dumps(manifest))
    del missing["evidence_artifacts"][observation_ref]
    with pytest.raises(ModelError, match="unresolved"):
        evaluate_release(_resign(missing), signing_key=_TEST_SIGNING_KEY)

    forged = json.loads(json.dumps(manifest))
    forged["evidence_artifacts"][observation_ref]["content"]["method"] = "altered method"
    forged["evidence_artifacts"][observation_ref]["sha256"] = hashlib.sha256(json.dumps(
        forged["evidence_artifacts"][observation_ref]["content"],
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    with pytest.raises(ModelError, match="release manifest signature is invalid"):
        evaluate_release(forged, signing_key=_TEST_SIGNING_KEY)


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