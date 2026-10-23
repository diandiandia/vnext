from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

import pytest

from reachable_audit.analysis_models import Experiment
from reachable_audit.batch_workflow import BatchWorkflow
from reachable_audit.campaign import CampaignManager
from reachable_audit.experiments.runner import run_harness
from reachable_audit.inventory import build_inventory
from reachable_audit.models import ModelError
from reachable_audit.planning import create_audit_plan
from reachable_audit.resource_cleanup import (
    cleanup_campaign_resources,
    create_campaign_temp_directory,
)


_GO_SOURCE = """package main

import (
    "encoding/json"
    "os"
)

func main() {
    offline := os.Getenv("GOTOOLCHAIN") == "local" &&
        os.Getenv("GOPROXY") == "off" && os.Getenv("GOSUMDB") == "off" &&
        os.Getenv("GOENV") == "off" && os.Getenv("GOTELEMETRY") == "off" &&
        os.Getenv("HARNESS_TEST_SECRET") == ""
    if len(os.Args) != 2 || os.Args[1] != "observe" || !offline {
        json.NewEncoder(os.Stdout).Encode(map[string]any{
            "result": "inconclusive", "reason": "fixture precondition absent",
        })
        os.Exit(3)
    }
    state := 0
    transition := func(allowed bool) {
        if allowed { state++ }
    }
    transition(false)
    negativeControl := state == 0
    transition(true)
    json.NewEncoder(os.Stdout).Encode(map[string]any{
        "result": "confirmed", "observed": state,
        "negative_control": negativeControl, "offline": offline,
    })
}
"""


def test_real_go_build_and_r5_artifacts_are_offline_bounded_and_disposable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    go = shutil.which("go")
    if go is None:
        pytest.skip("requires a real host Go toolchain; no simulated success")
    if os.name != "posix":
        pytest.skip("managed harness requires POSIX resource limits")
    target = tmp_path / "synthetic-target"
    target.mkdir()
    source = target / "main.go"
    source.write_text(_GO_SOURCE, encoding="utf-8")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    manager = CampaignManager(target)
    campaign_id = "CMP-go-offline"
    snapshot_id = "fixture:synthetic-go-only"
    manager.create_campaign(campaign_id=campaign_id, snapshot_id=snapshot_id)
    inventory = build_inventory(target, snapshot_id)
    plan = create_audit_plan(
        campaign_id=campaign_id, inventory=inventory, category_families=["STATE"],
    )
    manager.record_inventory(campaign_id=campaign_id, inventory=inventory)
    manager.record_plan(campaign_id=campaign_id, plan=plan, inventory=inventory)
    workflow = BatchWorkflow(manager, campaign_id, plan.batches[0].batch_id)
    monkeypatch.setenv("HARNESS_TEST_SECRET", "must-not-be-inherited")
    monkeypatch.setenv("GOFLAGS", "-this-host-setting-must-not-be-inherited")
    runtime_paths: list[Path] = []
    try:
        workspace = create_campaign_temp_directory(
            manager, campaign_id, label="synthetic Go executable",
        )
        runtime_paths.append(workspace)
        binary = workspace / "probe"
        build = run_harness(
            manager, campaign_id,
            command=[go, "build", "-p=1", "-trimpath", "-o", str(binary), "main.go"],
            profile="go-offline", timeout_seconds=120,
        )
        runtime_paths.append(manager.state_dir / str(build["runtime_directory_ref"]))
        assert build["exit_code"] == 0, manager.artifacts.get_bytes(
            str(build["stderr_artifact_id"])
        ).decode(errors="replace")
        assert binary.is_file()
        assert build["empirical_upgrade_eligible"] is False
        assert build["resource_limits"]["address_space_bytes"] == 8 * 1024**3
        assert build["resource_limits"]["file_size_bytes_per_stream"] == 64 * 1024**2
        for mode, expected_exit, expected_result in (
            ("observe", 0, "confirmed"), ("missing-precondition", 3, "inconclusive"),
        ):
            result = run_harness(
                manager, campaign_id, command=[str(binary), mode],
                profile="go-offline", hypothesis_id="HYP-synthetic-go",
                output_limit_bytes=4096, timeout_seconds=5,
            )
            runtime_paths.append(manager.state_dir / str(result["runtime_directory_ref"]))
            assert result["exit_code"] == expected_exit
            assert result["timed_out"] is False
            assert result["output_limit_exceeded"] is False
            assert result["empirical_upgrade_eligible"] is True
            observation = json.loads(manager.artifacts.get_bytes(
                str(result["stdout_artifact_id"])
            ))
            assert observation["result"] == expected_result
            if expected_exit == 0:
                assert observation == {
                    "result": "confirmed", "observed": 1,
                    "negative_control": True, "offline": True,
                }
            experiment = Experiment.from_dict({
                "experiment_id": f"EXP-go-{mode}",
                "hypothesis_id": "HYP-synthetic-go",
                "fidelity": "real_target",
                "result": expected_result,
                "target_ref": "fixture:synthetic-go-only/main.go",
                "command_refs": [result["execution_artifact_id"]],
                "observation_refs": [
                    result["stdout_artifact_id"], result["stderr_artifact_id"],
                ],
                "rationale": "Only synthetic fixture behavior; not production target evidence.",
            })
            if expected_exit == 0:
                workflow._validate_empirical_harness_evidence(experiment)
            assert experiment.supports_empirical_upgrade is (expected_exit == 0)
            event = manager.store.list_events(
                campaign_id, event_type="HARNESS_EXECUTION_COMPLETED",
            )[-1]
            assert event.payload_ref == result["execution_artifact_id"]
            assert event.payload["hypothesis_id"] == "HYP-synthetic-go"
            stored = json.loads(manager.artifacts.get_bytes(event.payload_ref))
            assert stored["snapshot_id"] == snapshot_id
            if expected_exit == 0:
                mismatched = replace(experiment, hypothesis_id="HYP-other")
                with pytest.raises(ModelError, match="registered harness execution"):
                    workflow._validate_empirical_harness_evidence(mismatched)
        assert hashlib.sha256(source.read_bytes()).hexdigest() == digest
        assert manager.load_snapshot_baseline(campaign_id)["files"]["main.go"] == digest
    finally:
        try:
            report = cleanup_campaign_resources(manager, campaign_id)
            assert report["failures"] == []
            assert all(not path.exists() for path in runtime_paths)
            events = manager.store.list_events(campaign_id)
            registrations = {
                event.entity_id for event in events
                if event.event_type == "RESOURCE_REGISTERED"
            }
            releases = {
                event.entity_id for event in events
                if event.event_type == "RESOURCE_RELEASED"
            }
            assert registrations == releases
            for event in events:
                if event.event_type == "RESOURCE_REGISTERED" and event.payload["kind"] == "process_group":
                    with pytest.raises(ProcessLookupError):
                        os.killpg(event.payload["process_group_id"], 0)
            assert hashlib.sha256(source.read_bytes()).hexdigest() == digest
        finally:
            manager.close()


@pytest.mark.parametrize(
    ("script", "flag"),
    [
        ("import time; time.sleep(30)", "timed_out"),
        ("import os; os.write(1, b'x' * 10000)", "output_limit_exceeded"),
        (
            "import os, time; os.write(2, b'x' * 10000); time.sleep(30)",
            "output_limit_exceeded",
        ),
    ],
)
def test_go_profile_failures_do_not_claim_empirical_success(
    tmp_path: Path, script: str, flag: str,
) -> None:
    (tmp_path / "fixture.go").write_text("package fixture\n", encoding="utf-8")
    manager = CampaignManager(tmp_path)
    manager.create_campaign(campaign_id="CMP-go-failure", snapshot_id="fixture:failure")
    try:
        result = run_harness(
            manager, "CMP-go-failure", command=[sys.executable, "-c", script],
            profile="go-offline", timeout_seconds=1, output_limit_bytes=128,
            hypothesis_id="HYP-failure",
        )
        assert result["empirical_upgrade_eligible"] is False
        assert result["empirical_upgrade_note"]
        assert result[flag] is True
        assert len(manager.artifacts.get_bytes(str(result["stdout_artifact_id"]))) <= 128
        assert len(manager.artifacts.get_bytes(str(result["stderr_artifact_id"]))) <= 128
        inventory = build_inventory(tmp_path, "fixture:failure")
        plan = create_audit_plan(
            campaign_id="CMP-go-failure", inventory=inventory, category_families=["STATE"],
        )
        manager.record_inventory(campaign_id="CMP-go-failure", inventory=inventory)
        manager.record_plan(
            campaign_id="CMP-go-failure", plan=plan, inventory=inventory,
        )
        workflow = BatchWorkflow(manager, "CMP-go-failure", plan.batches[0].batch_id)
        claimed_confirmation = Experiment.from_dict({
            "experiment_id": "EXP-invalid-upgrade",
            "hypothesis_id": "HYP-failure",
            "fidelity": "real_target",
            "result": "confirmed",
            "target_ref": "fixture:failure",
            "command_refs": [result["execution_artifact_id"]],
            "observation_refs": [
                result["stdout_artifact_id"], result["stderr_artifact_id"],
            ],
            "rationale": "Invalid attempted upgrade from incomplete bounded observation.",
        })
        with pytest.raises(ModelError, match="registered harness execution"):
            workflow._validate_empirical_harness_evidence(claimed_confirmation)
    finally:
        cleanup_campaign_resources(manager, "CMP-go-failure")
        manager.close()


@pytest.mark.parametrize("profile", [None, "go-offline"])
def test_nonzero_exit_is_complete_evidence_not_automatic_confirmation(
    tmp_path: Path, profile: str | None,
) -> None:
    (tmp_path / "fixture.go").write_text("package fixture\n", encoding="utf-8")
    manager = CampaignManager(tmp_path)
    manager.create_campaign(campaign_id="CMP-crash", snapshot_id="fixture:crash")
    try:
        result = run_harness(
            manager, "CMP-crash",
            command=[sys.executable, "-c", "print('synthetic crash observation'); raise SystemExit(3)"],
            profile=profile, hypothesis_id="HYP-crash",
        )
        assert result["exit_code"] == 3
        assert result["empirical_upgrade_eligible"] is True
        assert result["empirical_upgrade_note"] is None
        assert manager.artifacts.get_bytes(str(result["stdout_artifact_id"])) == (
            b"synthetic crash observation\n"
        )
        inventory = build_inventory(tmp_path, "fixture:crash")
        plan = create_audit_plan(
            campaign_id="CMP-crash", inventory=inventory, category_families=["STATE"],
        )
        manager.record_inventory(campaign_id="CMP-crash", inventory=inventory)
        manager.record_plan(campaign_id="CMP-crash", plan=plan, inventory=inventory)
        workflow = BatchWorkflow(manager, "CMP-crash", plan.batches[0].batch_id)
        experiment = Experiment.from_dict({
            "experiment_id": "EXP-crash-observation",
            "hypothesis_id": "HYP-crash",
            "fidelity": "real_target",
            "result": "confirmed",
            "target_ref": "fixture:crash",
            "command_refs": [result["execution_artifact_id"]],
            "observation_refs": [
                result["stdout_artifact_id"], result["stderr_artifact_id"],
            ],
            "rationale": "The synthetic expected nonzero-exit observation was captured completely.",
        })
        workflow._validate_empirical_harness_evidence(experiment)
    finally:
        cleanup_campaign_resources(manager, "CMP-crash")
        manager.close()


def test_go_profile_controls_environment_without_inheriting_host_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HARNESS_TEST_SECRET", "must-not-be-inherited")
    manager = CampaignManager(tmp_path)
    manager.create_campaign(campaign_id="CMP-go-env", snapshot_id="fixture:environment")
    try:
        result = run_harness(
            manager, "CMP-go-env",
            command=[sys.executable, "-c", "import json, os; print(json.dumps(dict(os.environ)))"],
            profile="go-offline",
            environment={"GOPROXY": "https://invalid.invalid", "GOFLAGS": "-unsafe", "HOME": "/"},
        )
        assert result["exit_code"] == 0
        environment = json.loads(manager.artifacts.get_bytes(str(result["stdout_artifact_id"])))
        assert "HARNESS_TEST_SECRET" not in environment
        assert environment["GOPROXY"] == "off"
        assert environment["GOTOOLCHAIN"] == "local"
        assert environment["GOSUMDB"] == "off"
        assert environment["GOENV"] == "off"
        assert environment["GOFLAGS"] == ""
        assert environment["CGO_ENABLED"] == "0"
        runtime = manager.state_dir / str(result["runtime_directory_ref"])
        for key in ("HOME", "GOCACHE", "GOPATH", "TMPDIR", "GOTMPDIR"):
            assert Path(environment[key]).is_relative_to(runtime)
            assert Path(environment[key]).is_dir()
    finally:
        cleanup_campaign_resources(manager, "CMP-go-env")
        manager.close()


def test_go_profile_does_not_change_default_limits_or_accept_unknown_profile(tmp_path: Path) -> None:
    manager = CampaignManager(tmp_path)
    manager.create_campaign(campaign_id="CMP-default", snapshot_id="fixture:default")
    try:
        with pytest.raises(ModelError, match="unknown harness profile"):
            run_harness(manager, "CMP-default", command=[sys.executable], profile="go")
        result = run_harness(manager, "CMP-default", command=[sys.executable, "-c", "pass"])
        assert result["profile"] is None
        assert result["resource_limits"]["address_space_bytes"] == 2 * 1024**3
        assert result["resource_limits"]["file_size_bytes_per_stream"] == 1024**2
        explicit = run_harness(
            manager, "CMP-default", command=[sys.executable, "-c", "pass"],
            profile="go-offline", memory_limit_bytes=512 * 1024**2,
        )
        assert explicit["resource_limits"]["address_space_bytes"] == 512 * 1024**2
    finally:
        cleanup_campaign_resources(manager, "CMP-default")
        manager.close()
