import json
import datetime as dt
from pathlib import Path
import sys

import pytest

from reachable_audit.cli import _default_cli_state_dir, main
from reachable_audit.campaign import CampaignManager
from reachable_audit.compatibility import scan_runtime_compatibility, scan_runtime_deproject
from reachable_audit.execution import (
    DiscoveryCoordinator,
    ManualExecutionBackend,
    TaskResult,
    TaskSpec,
    TaskStatus,
    TaskView,
)
from reachable_audit.models import ModelError
from dataclasses import replace
from test_evaluation import _manifest
from test_batch_workflow import _workflow


def test_cli_initializes_and_reports_campaign(
    tmp_path: Path, capsys: object, monkeypatch: object,
) -> None:
    target = tmp_path / "target"
    target.mkdir()
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state-home"))

    assert main(["init", str(target), "--snapshot-id", "fixture:cli"]) == 0
    init_output = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert init_output["status"] == "PLANNING"
    state_dir = _default_cli_state_dir(target)
    assert state_dir.is_dir()
    assert target not in state_dir.parents
    assert not (target / ".audit_vnext").exists()

    assert main(["status", str(target)]) == 0
    status_output = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert status_output["campaigns"][0]["campaign_id"] == init_output["campaign_id"]


def test_cli_external_default_is_cwd_independent(
    tmp_path: Path, capsys: object, monkeypatch: object,
) -> None:
    target = tmp_path / "project"
    first_cwd = tmp_path / "first-cwd"
    second_cwd = tmp_path / "second-cwd"
    target.mkdir()
    first_cwd.mkdir()
    second_cwd.mkdir()
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state-home"))
    monkeypatch.chdir(first_cwd)

    assert main(["init", str(target), "--snapshot-id", "fixture:cwd"]) == 0
    campaign = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    monkeypatch.chdir(second_cwd)
    assert main(["status", str(target)]) == 0
    result = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]

    assert result["campaigns"][0]["campaign_id"] == campaign["campaign_id"]
    assert _default_cli_state_dir(target).is_dir()
    assert not (target / ".audit_vnext").exists()


@pytest.mark.parametrize("state_home", [".", ""])
def test_cli_falls_back_for_relative_or_empty_xdg_state_home(
    tmp_path: Path, capsys: object, monkeypatch: object, state_home: str,
) -> None:
    target = tmp_path / "project"
    home = tmp_path / "home"
    target.mkdir()
    home.mkdir()
    monkeypatch.setenv("XDG_STATE_HOME", state_home)
    monkeypatch.setenv("HOME", str(home))

    assert main([
        "init", str(target), "--snapshot-id", "fixture:fallback-state-home",
    ]) == 0
    capsys.readouterr()  # type: ignore[attr-defined]
    state_dir = _default_cli_state_dir(target)
    assert state_dir.is_dir()
    assert home / ".local" / "state" in state_dir.parents
    assert target not in state_dir.parents
    assert not (target / ".audit_vnext").exists()


def test_cli_rejects_state_home_inside_target(
    tmp_path: Path, capsys: object, monkeypatch: object,
) -> None:
    target = tmp_path / "project"
    target.mkdir()
    monkeypatch.setenv("XDG_STATE_HOME", str(target / "state"))

    assert main([
        "init", str(target), "--snapshot-id", "fixture:unsafe-state-home",
    ]) == 2
    assert "default state directory would be inside the target" in (
        capsys.readouterr().err  # type: ignore[attr-defined]
    )
    assert not (target / "state" / "reachable-audit").exists()


def test_cli_relative_xdg_fallback_still_rejects_home_inside_target(
    tmp_path: Path, capsys: object, monkeypatch: object,
) -> None:
    target = tmp_path / "project"
    target.mkdir()
    monkeypatch.setenv("XDG_STATE_HOME", "relative-state")
    monkeypatch.setenv("HOME", str(target))

    assert main([
        "init", str(target), "--snapshot-id", "fixture:unsafe-fallback",
    ]) == 2
    assert "default state directory would be inside the target" in (
        capsys.readouterr().err  # type: ignore[attr-defined]
    )
    assert not (target / ".local" / "state" / "reachable-audit").exists()


def test_cli_reuses_unambiguous_legacy_state_and_rejects_ambiguity(
    tmp_path: Path, capsys: object, monkeypatch: object,
) -> None:
    target = tmp_path / "legacy-target"
    target.mkdir()
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state-home"))
    with CampaignManager(target) as manager:
        campaign = manager.create_campaign(
            campaign_id="CMP-legacy-cli", snapshot_id="fixture:legacy"
        )

    assert main(["status", str(target)]) == 0
    result = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert result["campaigns"][0]["campaign_id"] == campaign.campaign_id

    assert main([
        "init", str(target), "--snapshot-id", "fixture:new-store",
        "--campaign-id", "CMP-new-store",
    ]) == 0
    capsys.readouterr()  # type: ignore[attr-defined]
    assert main(["status", str(target)]) == 2
    assert "both legacy and external Campaign state exist" in (
        capsys.readouterr().err  # type: ignore[attr-defined]
    )
    assert main([
        "status", str(target), "--state-dir", str(_default_cli_state_dir(target)),
    ]) == 0
    selected = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert selected["campaigns"][0]["campaign_id"] == "CMP-new-store"


def test_cli_adds_batch_from_manifest_file(tmp_path: Path, capsys: object) -> None:
    target = tmp_path / "batch-add-target"
    target.mkdir()
    assert main([
        "init", str(target), "--snapshot-id", "fixture:batch-add",
        "--campaign-id", "CMP-batch-add",
    ]) == 0
    capsys.readouterr()  # type: ignore[attr-defined]
    manifest_path = tmp_path / "batch-manifest.json"
    manifest_path.write_text(json.dumps({
        "work_unit_ids": ["WU-batch-add"],
        "source_file_count": 0,
    }), encoding="utf-8")

    assert main([
        "batch-add", str(target), "CMP-batch-add", "B-batch-add",
        "--manifest", str(manifest_path),
    ]) == 0
    batch = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert batch["batch_id"] == "B-batch-add"
    assert batch["manifest"]["work_unit_ids"] == ["WU-batch-add"]


def test_cli_freezes_max_screening_fraction_at_campaign_init(
    tmp_path: Path, capsys: object
) -> None:
    target = tmp_path / "screening-policy"
    target.mkdir()
    assert main([
        "init", str(target), "--snapshot-id", "fixture:screening-policy",
        "--campaign-id", "CMP-screening-policy",
        "--max-screening-fraction", "0.2",
    ]) == 0
    campaign = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert campaign["budget"]["max_screening_fraction"] == 0.2


def test_cli_freezes_delegated_agent_run_cap_at_campaign_init(
    tmp_path: Path, capsys: object,
) -> None:
    target = tmp_path / "delegated-budget"
    target.mkdir()
    assert main([
        "init", str(target), "--snapshot-id", "fixture:delegated-budget",
        "--campaign-id", "CMP-delegated-budget",
        "--max-delegated-agent-runs", "3",
    ]) == 0
    campaign = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert campaign["budget"]["max_delegated_agent_runs"] == 3

    invalid_target = tmp_path / "negative-delegated-budget"
    invalid_target.mkdir()
    assert main([
        "init", str(invalid_target), "--snapshot-id", "fixture:negative-budget",
        "--max-delegated-agent-runs", "-1",
    ]) == 2
    assert "non-negative" in capsys.readouterr().err  # type: ignore[attr-defined]


def test_cli_can_require_host_worker_attestation_at_campaign_init(
    tmp_path: Path, capsys: object,
) -> None:
    target = tmp_path / "attested-campaign"
    target.mkdir()
    assert main([
        "init", str(target), "--snapshot-id", "fixture:attested-init",
        "--campaign-id", "CMP-attested-init", "--require-host-worker-attestation",
    ]) == 0
    campaign = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert campaign["budget"]["require_host_worker_attestation"] is True


def test_cli_init_accepts_only_positive_max_wall_seconds(
    tmp_path: Path, capsys: object,
) -> None:
    target = tmp_path / "wall-budget"
    target.mkdir()
    assert main([
        "init", str(target), "--snapshot-id", "fixture:wall-budget",
        "--campaign-id", "CMP-wall-budget", "--max-wall-seconds", "120",
    ]) == 0
    campaign = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert campaign["budget"]["max_wall_seconds"] == 120

    assert main([
        "init", str(target), "--snapshot-id", "fixture:invalid-wall-budget",
        "--campaign-id", "CMP-invalid-wall-budget", "--max-wall-seconds", "0",
    ]) == 2
    assert "positive integer" in capsys.readouterr().err  # type: ignore[attr-defined]


def test_execution_claim_enforces_created_at_wall_deadline_and_reports_it(
    tmp_path: Path,
) -> None:
    with CampaignManager(tmp_path) as manager:
        campaign = manager.create_campaign(
            campaign_id="CMP-wall-deadline",
            snapshot_id="fixture:wall-deadline",
            budget={"max_wall_seconds": 60},
        )
        start = dt.datetime.fromisoformat(campaign.created_at)
        manager.add_batch(
            campaign_id=campaign.campaign_id,
            batch_id="B-wall-deadline",
            manifest={"work_unit_ids": ["WU-wall-deadline"]},
        )
        input_ref = manager.artifacts.put_text("{}").artifact_id
        backend = ManualExecutionBackend(
            manager, campaign.campaign_id,
            clock=lambda: start + dt.timedelta(seconds=30),
        )
        for task_id in ("TASK-before-deadline", "TASK-after-deadline"):
            backend.submit(TaskSpec(
                task_id,
                campaign.campaign_id,
                "B-wall-deadline",
                "WU-wall-deadline",
                "discover_surfaces",
                (input_ref,),
                "surface-set/v1",
                {},
            ))
        lease = backend.claim("worker", task_id_filter="TASK-before-deadline")
        assert lease is not None
        wall_report = backend.describe_lease(lease)["campaign_wall_clock"]
        assert wall_report["elapsed_seconds"] >= 30
        assert wall_report["max_wall_seconds"] == 60
        assert wall_report["deadline_at"] == (
            start.astimezone(dt.UTC) + dt.timedelta(seconds=60)
        ).isoformat()

        expired_backend = ManualExecutionBackend(
            manager, campaign.campaign_id,
            clock=lambda: start + dt.timedelta(seconds=60),
        )
        with pytest.raises(
            ModelError, match="elapsed_seconds=60.0.*deadline_at="
        ):
            expired_backend.claim(
                "worker", task_id_filter="TASK-after-deadline"
            )


def test_cli_runs_registered_language_toolchain_probe(capsys: object) -> None:
    assert main(["toolchain-probe", "python"]) == 0
    result = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert result["language"] == "python"
    assert result["probes"][0]["command"] == ["python3", "--version"]
    assert result["probes"][0]["available"] is True


def test_cli_runs_runtime_compatibility_scan(capsys: object) -> None:
    assert main(["compatibility-scan", "--root", str(Path(__file__).resolve().parents[1])]) == 0
    report = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert report["passed"] is True
    assert report["findings"] == []


def test_runtime_prompt_has_no_historical_target_example() -> None:
    root = Path(__file__).resolve().parents[1]
    report = scan_runtime_compatibility(root, ["HistoricalTarget"])

    assert report["passed"] is True


def test_runtime_deproject_scan_rejects_operator_supplied_token(tmp_path: Path) -> None:
    profile = tmp_path / "knowledge" / "profiles" / "sample.json"
    profile.parent.mkdir(parents=True)
    profile.write_text('{"note":"Acme-Widget"}', encoding="utf-8")

    assert scan_runtime_deproject(tmp_path)["passed"] is True
    report = scan_runtime_deproject(tmp_path, ["acme-widget"])

    assert report["passed"] is False
    assert report["findings"][0]["value"] == "acme-widget"


def test_runtime_deproject_scan_rejects_generic_residue_patterns(tmp_path: Path) -> None:
    profile = tmp_path / "knowledge" / "cards" / "sample.json"
    profile.parent.mkdir(parents=True)
    profile.write_text(
        '{"note":"see CVE-2024-12345 and https://example.org/x/y/commit/abc123"}',
        encoding="utf-8",
    )

    report = scan_runtime_deproject(tmp_path)

    assert {item["value"] for item in report["findings"]} == {
        "cve_identifier", "vcs_reference_url",
    }


def test_runtime_residue_scan_covers_source_and_main_prompt(tmp_path: Path) -> None:
    for relative, text in {
        "src/sample.py": "TARGET = 'Acme-Widget'\n",
        "SKILL.md": "Use the Acme-Widget target configuration.\n",
        "docs/history.md": "Acme-Widget is historical evidence.\n",
        "tests/fixture.py": "PROJECT = 'Acme-Widget'\n",
    }.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    for scanner in (scan_runtime_compatibility, scan_runtime_deproject):
        report = scanner(tmp_path, ["acme-widget"])
        assert report["passed"] is False
        assert {item["path"] for item in report["findings"]} == {"src/sample.py", "SKILL.md"}
        assert report["scanned_python_files"] == 1
        assert report["scanned_prompt_files"] == 1


def test_runtime_residue_scan_rejects_private_host_paths(tmp_path: Path) -> None:
    (tmp_path / "SKILL.md").write_text("Run /home/operator/private-target/tool.\n", encoding="utf-8")
    report = scan_runtime_compatibility(tmp_path)
    assert report["passed"] is False
    assert report["findings"][0]["value"] == "private_host_path"


def test_runtime_residue_scan_does_not_confuse_relative_certificate_names(tmp_path: Path) -> None:
    (tmp_path / "SKILL.md").write_text("Review root.crt/root.key provenance.\n", encoding="utf-8")
    assert scan_runtime_compatibility(tmp_path)["passed"] is True


def test_cli_managed_harness_run_records_output_artifacts(
    tmp_path: Path, capsys: object
) -> None:
    target = tmp_path / "target"
    target.mkdir()
    assert main([
        "init", str(target), "--snapshot-id", "fixture:harness-cli",
        "--campaign-id", "CMP-harness-cli",
    ]) == 0
    capsys.readouterr()  # type: ignore[attr-defined]
    input_path = tmp_path / "harness.json"
    input_path.write_text(json.dumps({
        "command": [sys.executable, "-c", "print('managed')"],
        "timeout_seconds": 5,
        "cpu_limit_seconds": 2,
        "memory_limit_bytes": 256 * 1024 * 1024,
        "hypothesis_id": "HYP-harness-cli",
    }), encoding="utf-8")

    assert main([
        "harness-run", str(target), "CMP-harness-cli", "--input", str(input_path),
    ]) == 0
    result = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert result["exit_code"] == 0
    assert result["empirical_upgrade_eligible"] is True
    assert result["resource_limits"]["cpu_seconds"] == 2
    assert result["resource_limits"]["address_space_bytes"] == 256 * 1024 * 1024
    assert result["stdout_artifact_id"].startswith("sha256:")
    assert result["execution_artifact_id"].startswith("sha256:")


def test_cli_task_list_filters_batch_and_hints_exhausted_retry(
    tmp_path: Path, capsys: object
) -> None:
    target = tmp_path / "task-target"
    target.mkdir()
    with CampaignManager(target) as manager:
        campaign = manager.create_campaign(
            campaign_id="CMP-task-list", snapshot_id="fixture:task-list"
        )
        manager.add_batch(
            campaign_id=campaign.campaign_id,
            batch_id="B-failed",
            manifest={"work_unit_ids": ["WU-failed"]},
        )
        manager.add_batch(
            campaign_id=campaign.campaign_id,
            batch_id="B-pending",
            manifest={"work_unit_ids": ["WU-pending"]},
        )
        input_ref = manager.artifacts.put_text("{}").artifact_id
        failed_task = TaskSpec(
            "TASK-failed", campaign.campaign_id, "B-failed", "WU-failed",
            "discover_surfaces", (input_ref,), "surface-set/v1", {}, max_attempts=1,
        )
        pending_task = replace(
            failed_task,
            task_id="TASK-pending",
            batch_id="B-pending",
            work_unit_id="WU-pending",
        )
        backend = ManualExecutionBackend(manager, campaign.campaign_id)
        backend.submit(failed_task)
        backend.submit(pending_task)
        lease = backend.claim(
            "worker", batch_id="B-failed", task_id_filter=failed_task.task_id
        )
        assert lease is not None
        assert backend.collect(lease, TaskResult(
            False, None, "worker failed", {"agent_runs": 1, "wall_seconds": 1},
        )).status is TaskStatus.FAILED

    assert main([
        "task-list", str(target), "CMP-task-list", "--batch-id", "B-failed",
    ]) == 0
    result = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert [item["task"]["task_id"] for item in result["tasks"]] == ["TASK-failed"]
    assert "task-retry" in result["tasks"][0]["operator_hint"]

    assert main([
        "task-list", str(target), "CMP-task-list", "--batch-id", "B-pending",
    ]) == 0
    result = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert [item["task"]["task_id"] for item in result["tasks"]] == ["TASK-pending"]


def test_r6_scheduler_exposes_tasks_and_legacy_task_alias(
    tmp_path: Path, capsys: object, monkeypatch: object,
) -> None:
    target = tmp_path / "r6-cli-target"
    target.mkdir()
    with CampaignManager(target) as manager:
        campaign = manager.create_campaign(
            campaign_id="CMP-r6-cli", snapshot_id="fixture:r6-cli"
        )
        manager.add_batch(
            campaign_id=campaign.campaign_id,
            batch_id="B-r6-cli",
            manifest={"work_unit_ids": ["WU-r6-cli"]},
        )
    task_view = TaskView(
        TaskSpec(
            "TASK-r6-cli", "CMP-r6-cli", "B-r6-cli", "WU-r6-cli",
            "collect_batch_closure_evidence", (), "batch-closure-evidence/v1", {},
        ),
        TaskStatus.PENDING,
        None,
        0,
        None,
        None,
    )
    monkeypatch.setattr(DiscoveryCoordinator, "schedule_r6", lambda _self: task_view)

    assert main([
        "task-schedule-r6", str(target), "CMP-r6-cli", "B-r6-cli",
    ]) == 0
    result = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]

    assert result["tasks"] == [result["task"]]
    assert result["task"]["task"]["task_id"] == "TASK-r6-cli"


def test_task_list_help_exposes_filters() -> None:
    from reachable_audit.cli import _parser

    help_text = _parser().format_help()
    subparser_action = next(
        action for action in _parser()._actions if action.dest == "command"
    )
    task_list_parser = subparser_action.choices["task-list"]
    task_list_help = task_list_parser.format_help()
    assert "--batch-id" in task_list_help
    assert "--operation" in task_list_help
    assert "relative paths are target-relative" in task_list_help


def test_cli_amends_successful_uncommitted_task_output(
    tmp_path: Path, capsys: object
) -> None:
    target = tmp_path / "amend-target"
    target.mkdir()
    assert main([
        "init", str(target), "--snapshot-id", "fixture:task-amend",
        "--campaign-id", "CMP-task-amend",
    ]) == 0
    capsys.readouterr()  # type: ignore[attr-defined]
    state_dir = _default_cli_state_dir(target)
    with CampaignManager(target, state_dir) as manager:
        manager.add_batch(
            campaign_id="CMP-task-amend", batch_id="B-amend",
            manifest={"work_unit_ids": ["WU-amend"]},
        )
        input_ref = manager.artifacts.put_text(json.dumps({
            "work_unit": {"work_unit_id": "WU-amend", "source_files": []},
            "boundary_edges": [],
        })).artifact_id
        task = TaskSpec(
            "TASK-amend", "CMP-task-amend", "B-amend", "WU-amend",
            "discover_surfaces", (input_ref,), "surface-set/v1", {},
        )
        backend = ManualExecutionBackend(manager, "CMP-task-amend")
        backend.submit(task)
        lease = backend.claim("worker")
        assert lease is not None
        prior_ref = manager.artifacts.put_text(json.dumps({
            "schema_version": "1.0", "review_altitude": "INSPECTED",
            "reviewed_paths": [],
            "surfaces": [], "boundary_reviews": [],
        })).artifact_id
        backend.collect(lease, TaskResult(
            True, prior_ref, "collected before failed stage commit",
            {"agent_runs": 1, "wall_seconds": 1},
        ))

    amend_path = tmp_path / "amendment.json"
    amend_path.write_text(json.dumps({
        "output": {
                "schema_version": "1.0", "review_altitude": "INSPECTED",
            "reviewed_scope": "ALL_SOURCE_FILES",
            "surfaces": [], "boundary_reviews": [],
        },
            "reason": "replace legacy path echo with the full-scope sentinel",
        "evidence_refs": [prior_ref],
    }), encoding="utf-8")
    assert main([
        "task-amend", str(target), "CMP-task-amend", "TASK-amend",
        "--input", str(amend_path),
    ]) == 0
    amended = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert amended["status"] == "SUCCEEDED"
    assert amended["output_ref"] != prior_ref
    with CampaignManager(target, state_dir) as manager:
        event = next(
            event for event in manager.store.list_events("CMP-task-amend")
            if event.event_type == "TASK_OUTPUT_AMENDED"
        )
        assert event.payload["prior_output_ref"] == prior_ref


def test_harness_help_documents_hypothesis_and_cwd_constraints() -> None:
    from reachable_audit.cli import _parser

    parser = _parser()
    subparser_action = next(
        action for action in parser._actions if action.dest == "command"
    )
    harness_help = subparser_action.choices["harness-run"].format_help()
    assert "input.hypothesis_id" in harness_help
    assert "input.cwd" in harness_help
    assert "not an OS sandbox" in harness_help


def test_cli_runs_inventory_graph_plan_in_order(tmp_path: Path, capsys: object) -> None:
    target = tmp_path / "target"
    target.mkdir()
    (target / "pyproject.toml").write_text(
        "[project]\nname='target'\n", encoding="utf-8"
    )
    (target / "main.py").write_text("print('ok')\n", encoding="utf-8")

    assert main([
        "init", str(target), "--snapshot-id", "fixture:pipeline",
        "--campaign-id", "CMP-pipeline",
    ]) == 0
    capsys.readouterr()  # type: ignore[attr-defined]
    assert main(["inventory", str(target), "CMP-pipeline"]) == 0
    capsys.readouterr()  # type: ignore[attr-defined]
    assert main(["graph", str(target), "CMP-pipeline"]) == 0
    graph_output = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert graph_output["build_units"] == 1
    cost_profile = tmp_path / "cost-profile.json"
    cost_profile.write_text(json.dumps({
        "profile_id": "fixture-profile",
        "currency": "TEST",
        "assumptions": {
            "hypotheses_per_work_unit": {"low": 1, "expected": 2, "high": 3},
            "reachable_fraction": 0.5,
        },
        "cost_per_task": {
            operation: 1.0 for operation in (
                "discover_surfaces", "generate_hypotheses_compact",
                "run_category_audit", "verify_reachability",
                "refute_reachability", "adjudicate_refutations",
                "assess_experiment", "collect_batch_closure_evidence",
            )
        },
    }), encoding="utf-8")
    assert main([
        "plan", str(target), "CMP-pipeline", "--categories", "STATE",
        "--cost-profile", str(cost_profile),
    ]) == 0
    plan_output = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert plan_output["work_units"] == 1
    assert plan_output["batches"] == 1
    assert plan_output["batch_summaries"][0]["source_files"] == 1
    assert plan_output["batch_summaries"][0]["source_bytes"] == len("print('ok')\n")
    assert plan_output["oversize_work_units"] == []
    assert plan_output["batch_summaries"][0]["max_estimated_r1_output_floor_bytes"] > 0
    assert plan_output["batch_summaries"][0]["max_boundary_review_count"] == 0
    assert plan_output["cost_forecast"]["scenarios"]["expected"]["estimated_total_tasks"] == 11
    assert main([
        "amend", str(target), "CMP-pipeline", plan_output["plan_id"],
        "--reason", "repack before execution",
        "--max-batch-files", "1", "--max-batch-work-units", "1",
    ]) == 0
    amendment = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert amendment["base_plan_id"] == plan_output["plan_id"]
    assert amendment["amended_plan_id"] != amendment["base_plan_id"]
    assert amendment["batches"] == 1


def test_cli_plan_accepts_path_dispositions_and_reports_them(
    tmp_path: Path, capsys: object,
) -> None:
    target = tmp_path / "target"
    target.mkdir()
    (target / "included.py").write_text("print('in')\n", encoding="utf-8")
    (target / "excluded.py").write_text("print('out')\n", encoding="utf-8")
    scope_file = tmp_path / "path-dispositions.json"
    scope_file.write_text(json.dumps([{
        "path": "excluded.py",
        "state": "EXCLUDED",
        "rationale": "outside approved scope",
        "approved_by": "scope-owner",
        "evidence_refs": ["LOC-excluded.py:1"],
    }]), encoding="utf-8")

    assert main([
        "init", str(target), "--snapshot-id", "fixture:path-scope",
        "--campaign-id", "CMP-path-scope",
    ]) == 0
    state_dir = _default_cli_state_dir(target)
    capsys.readouterr()  # type: ignore[attr-defined]
    assert main(["inventory", str(target), "CMP-path-scope"]) == 0
    capsys.readouterr()  # type: ignore[attr-defined]
    assert main(["graph", str(target), "CMP-path-scope"]) == 0
    capsys.readouterr()  # type: ignore[attr-defined]

    assert main([
        "plan", str(target), "CMP-path-scope", "--categories", "STATE",
        "--path-dispositions", str(scope_file),
    ]) == 0
    output = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert output["path_scope_counts"] == {
        "INCLUDED": 1, "EXCLUDED": 1, "DEFERRED": 0,
    }
    assert output["batch_summaries"][0]["source_files"] == 1
    plan_file = next(
        (state_dir / "campaigns" / "CMP-path-scope" / "plans").glob(
            "*.json"
        )
    )
    plan = json.loads(plan_file.read_text(encoding="utf-8"))
    assert {item["path"]: item["state"] for item in plan["path_dispositions"]} == {
        "excluded.py": "EXCLUDED",
        "included.py": "INCLUDED",
    }
    assert [
        path for unit in plan["work_units"] for path in unit["source_files"]
    ] == ["included.py"]


def test_cli_plan_flags_large_r2_source_files_without_silent_size_fallback(
    tmp_path: Path, capsys: object,
) -> None:
    target = tmp_path / "large-source-target"
    target.mkdir()
    large_source = target / "large.c"
    large_source.write_bytes(b"int value;\n" * ((1024 * 1024 // 11) + 2))

    assert main([
        "init", str(target), "--snapshot-id", "fixture:large-source",
        "--campaign-id", "CMP-large-source",
    ]) == 0
    capsys.readouterr()  # type: ignore[attr-defined]
    assert main(["inventory", str(target), "CMP-large-source"]) == 0
    capsys.readouterr()  # type: ignore[attr-defined]
    assert main(["graph", str(target), "CMP-large-source"]) == 0
    capsys.readouterr()  # type: ignore[attr-defined]
    assert main([
        "plan", str(target), "CMP-large-source", "--categories", "MEMORY-SAFETY",
    ]) == 0
    result = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]

    assert len(result["r2_large_source_files"]) == 1
    warning = result["r2_large_source_files"][0]
    assert warning["path"] == "large.c"
    assert warning["size_bytes"] == large_source.stat().st_size
    assert warning["work_unit_id"]
    assert warning["warning_threshold_bytes"] == 1024 * 1024
    assert "approved scope decision" in warning["action"]
    assert result["batch_summaries"][0]["source_bytes"] == large_source.stat().st_size


def test_cli_plan_surfaces_source_size_lookup_errors(
    tmp_path: Path, capsys: object, monkeypatch: object,
) -> None:
    target = tmp_path / "unreadable-size-target"
    target.mkdir()
    source = target / "main.py"
    source.write_text("print('ok')\n", encoding="utf-8")
    assert main([
        "init", str(target), "--snapshot-id", "fixture:size-error",
        "--campaign-id", "CMP-size-error",
    ]) == 0
    capsys.readouterr()  # type: ignore[attr-defined]
    assert main(["inventory", str(target), "CMP-size-error"]) == 0
    capsys.readouterr()  # type: ignore[attr-defined]
    assert main(["graph", str(target), "CMP-size-error"]) == 0
    capsys.readouterr()  # type: ignore[attr-defined]

    original_stat = Path.stat

    def fail_source_stat(path: Path, *args: object, **kwargs: object):
        if path == source:
            raise OSError("injected stat failure")
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", fail_source_stat)
    assert main([
        "plan", str(target), "CMP-size-error", "--categories", "STATE",
    ]) == 2
    assert "cannot measure planned source file size: main.py" in (
        capsys.readouterr().err  # type: ignore[attr-defined]
    )


def test_cli_writes_shadow_evaluation_report(
    tmp_path: Path, capsys: object, monkeypatch: object
) -> None:
    monkeypatch.setenv("VNA_EVALUATION_HMAC_KEY", "vnext-unit-test-signing-key")
    input_path = tmp_path / "shadow.json"
    output_path = tmp_path / "acceptance.json"
    input_path.write_text(json.dumps(_manifest()), encoding="utf-8")

    assert main([
        "shadow-evaluate", "--input", str(input_path), "--output", str(output_path),
    ]) == 0
    report = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert report["status"] == "ACCEPTED"
    assert report["implemented_subset_status"] == "PASS"
    assert report["eligible_for_promotion"] is True
    assert json.loads(output_path.read_text(encoding="utf-8")) == report


def test_cli_drives_a_durable_surface_task(tmp_path: Path, capsys: object) -> None:
    target = tmp_path / "target"
    target.mkdir()
    (target / "main.py").write_text("def handle():\n    pass\n", encoding="utf-8")
    assert main([
        "init", str(target), "--snapshot-id", "fixture:tasks",
        "--campaign-id", "CMP-tasks",
    ]) == 0
    state_dir = _default_cli_state_dir(target)
    capsys.readouterr()  # type: ignore[attr-defined]
    assert main(["inventory", str(target), "CMP-tasks"]) == 0
    capsys.readouterr()  # type: ignore[attr-defined]
    assert main(["graph", str(target), "CMP-tasks"]) == 0
    capsys.readouterr()  # type: ignore[attr-defined]
    assert main(["plan", str(target), "CMP-tasks", "--categories", "STATE"]) == 0
    plan = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    plan_file = next(
        (state_dir / "campaigns" / "CMP-tasks" / "plans").glob(
            "*.json"
        )
    )
    batch_id = json.loads(plan_file.read_text(encoding="utf-8"))["batches"][0][
        "batch_id"
    ]
    assert plan["batches"] == 1
    assert main(["r0", str(target), "CMP-tasks", batch_id]) == 0
    capsys.readouterr()  # type: ignore[attr-defined]
    assert main(["task-schedule-r1", str(target), "CMP-tasks", batch_id]) == 0
    capsys.readouterr()  # type: ignore[attr-defined]
    assert main([
        "task-claim", str(target), "CMP-tasks", "worker-a",
        "--operation", "discover_surfaces",
    ]) == 0
    first_claim = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    task_id = first_claim["lease"]["task"]["task_id"]
    assert main([
        "task-release", str(target), "CMP-tasks", task_id, "worker-a",
        "--reason", "worker pool routing correction",
    ]) == 0
    capsys.readouterr()  # type: ignore[attr-defined]
    assert main([
        "task-claim", str(target), "CMP-tasks", "worker-b",
        "--operation", "discover_surfaces",
    ]) == 0
    second_claim = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert second_claim["lease"]["task"]["task_id"] == task_id
    assert second_claim["lease"]["attempt"] == 2
    result_path = tmp_path / "result.json"
    result_path.write_text(json.dumps({
        "succeeded": True,
        "summary": "no exposed surface",
        "measurements": {"agent_runs": 1, "wall_seconds": 1},
        "configuration": {
            "model_id": "test-model",
            "runtime_version": "test-runtime/1",
            "tool_policy_digest": "sha256:" + "a" * 64,
        },
        "output": {
            "schema_version": "1.0",
            "review_altitude": "INSPECTED",
            "reviewed_paths": ["main.py"],
            "surfaces": [],
                "boundary_reviews": [],
        },
    }), encoding="utf-8")
    assert main([
        "task-collect", str(target), "CMP-tasks", task_id, "worker-b",
        "--input", str(result_path),
    ]) == 0
    collected = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert main(["task-commit-r1", str(target), "CMP-tasks", batch_id]) == 0
    assert "artifact_id" in json.loads(
        capsys.readouterr().out  # type: ignore[attr-defined]
    )
    with CampaignManager(target, state_dir) as manager:
        r0_event = next(
            event for event in manager.store.list_batch_events(
                "CMP-tasks", batch_id, event_type="R0_COMPLETED",
            )
        )
        r1_event = next(
            event for event in manager.store.list_batch_events(
                "CMP-tasks", batch_id, event_type="R1_COMPLETED",
            )
        )
        assert r1_event.payload["source_task_output_refs"] == {
            task_id: collected["output_ref"],
        }
        assert r1_event.payload["upstream_revision_ids"] == {
            "R0_COMPLETED": r0_event.event_id,
        }
        assert r1_event.payload["revision_id"].startswith("REV-")


def test_default_r2_cli_schedules_one_compact_task_per_work_unit(
    tmp_path: Path, capsys: object
) -> None:
    manager, workflow, plan = _workflow(tmp_path, "CMP-r2-cli-compact")
    workflow.run_r0()
    workflow.record_r1([])
    manager.close()
    checklist = tmp_path / "entrypoint-checklist.json"
    checklist.write_text("[]", encoding="utf-8")

    assert main([
        "task-schedule-r2", str(tmp_path), "CMP-r2-cli-compact",
        plan.batches[0].batch_id, "--entrypoint-checklist", str(checklist),
    ]) == 0
    task_output = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]

    assert len(task_output["tasks"]) == len(plan.work_units)
    assert all(
        item["task"]["operation"] == "generate_hypotheses_compact"
        for item in task_output["tasks"]
    )


def test_cli_cleans_campaign_resources_and_reads_skill_backlog(
    tmp_path: Path, capsys: object
) -> None:
    target = tmp_path / "target"
    target.mkdir()
    assert main([
        "init", str(target), "--snapshot-id", "fixture:lifecycle",
        "--campaign-id", "CMP-lifecycle",
    ]) == 0
    capsys.readouterr()  # type: ignore[attr-defined]

    assert main([
        "resource-create-temp", str(target), "CMP-lifecycle",
        "--label", "runtime fixture",
    ]) == 0
    resource = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    resource_path = Path(resource["path"])
    assert resource_path.is_dir()

    assert main(["resource-cleanup", str(target), "CMP-lifecycle"]) == 0
    cleanup = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert cleanup["failures"] == []
    assert not resource_path.exists()

    assert main(["skill-backlog", str(target), "CMP-lifecycle"]) == 0
    backlog = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert backlog == {
        "purpose": "tool_regression_only",
        "campaign_id": "CMP-lifecycle",
        "pending_issues": [],
    }

    review_path = tmp_path / "skill-review.json"
    review_path.write_text(json.dumps({
        "skill_issues": [{
            "issue_id": "SKILL-cli-1",
            "kind": "ERROR",
            "stage": "R5",
            "summary": "runtime probe left no observation artifact",
            "evidence_refs": ["TASK-probe-failed"],
            "regression_expectation": "failed probes retain stderr evidence",
            "status": "REGRESSION_PENDING",
        }],
    }), encoding="utf-8")
    assert main([
        "skill-review", str(target), "CMP-lifecycle",
        "--input", str(review_path),
    ]) == 0
    capsys.readouterr()  # type: ignore[attr-defined]
    assert main(["skill-backlog", str(target), "CMP-lifecycle"]) == 0
    backlog = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert backlog["pending_issues"] == []

    assert main([
        "init", str(target), "--snapshot-id", "fixture:follow-up",
        "--campaign-id", "CMP-follow-up", "--audit-mode", "follow-up",
        "--history-source", "CMP-lifecycle",
    ]) == 0
    capsys.readouterr()  # type: ignore[attr-defined]
    assert main(["skill-backlog", str(target), "CMP-follow-up"]) == 0
    backlog = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert backlog["pending_issues"][0]["issue_id"] == "SKILL-cli-1"

    revised_review = json.loads(review_path.read_text(encoding="utf-8"))
    revised_review["skill_issues"][0]["summary"] = "runtime probe lacked a registered observation artifact"
    review_path.write_text(json.dumps(revised_review), encoding="utf-8")
    assert main([
        "skill-review", str(target), "CMP-lifecycle",
        "--input", str(review_path),
    ]) == 0
    capsys.readouterr()  # type: ignore[attr-defined]
    assert main(["skill-backlog", str(target), "CMP-follow-up"]) == 0
    backlog = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert backlog["pending_issues"][0]["summary"] == (
        "runtime probe lacked a registered observation artifact"
    )


def test_cli_aborts_campaign_writes_lesson_and_cleans_resources(
    tmp_path: Path, capsys: object
) -> None:
    target = tmp_path / "target"
    target.mkdir()
    assert main([
        "init", str(target), "--snapshot-id", "fixture:abort",
        "--campaign-id", "CMP-abort",
    ]) == 0
    state_dir = _default_cli_state_dir(target)
    capsys.readouterr()  # type: ignore[attr-defined]
    assert main([
        "resource-create-temp", str(target), "CMP-abort", "--label", "harness",
    ]) == 0
    temp_path = Path(json.loads(capsys.readouterr().out)["path"])  # type: ignore[attr-defined]
    issues_path = tmp_path / "abort-issues.json"
    issues_path.write_text(json.dumps({"skill_issues": []}), encoding="utf-8")

    assert main([
        "campaign-abort", str(target), "CMP-abort", "--reason", "operator stopped run",
        "--input", str(issues_path),
    ]) == 0
    report = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]

    assert report["status"] == "ABORTED"
    assert report["resource_cleanup"]["failures"] == []
    assert not temp_path.exists()
    assert (state_dir / "campaigns" / "CMP-abort" / "lessons.md").exists()
