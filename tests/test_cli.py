import json
from pathlib import Path
import sys

from reachable_audit.cli import main
from reachable_audit.campaign import CampaignManager
from reachable_audit.compatibility import scan_runtime_compatibility, scan_runtime_deproject
from reachable_audit.execution import ManualExecutionBackend, TaskResult, TaskSpec, TaskStatus
from dataclasses import replace
from test_evaluation import _manifest
from test_batch_workflow import _workflow


def test_cli_initializes_and_reports_campaign(tmp_path: Path, capsys: object) -> None:
    target = tmp_path / "target"
    target.mkdir()

    assert main(["init", str(target), "--snapshot-id", "fixture:cli"]) == 0
    init_output = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert init_output["status"] == "PLANNING"
    assert (target / ".audit_vnext" / "campaign.json").exists()

    assert main(["status", str(target)]) == 0
    status_output = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert status_output["campaigns"][0]["campaign_id"] == init_output["campaign_id"]


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
    with CampaignManager(target) as manager:
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
    with CampaignManager(target) as manager:
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
        (target / ".audit_vnext" / "campaigns" / "CMP-path-scope" / "plans").glob(
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
    capsys.readouterr()  # type: ignore[attr-defined]
    assert main(["inventory", str(target), "CMP-tasks"]) == 0
    capsys.readouterr()  # type: ignore[attr-defined]
    assert main(["graph", str(target), "CMP-tasks"]) == 0
    capsys.readouterr()  # type: ignore[attr-defined]
    assert main(["plan", str(target), "CMP-tasks", "--categories", "STATE"]) == 0
    plan = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    plan_file = next(
        (target / ".audit_vnext" / "campaigns" / "CMP-tasks" / "plans").glob(
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
    capsys.readouterr()  # type: ignore[attr-defined]
    assert main(["task-commit-r1", str(target), "CMP-tasks", batch_id]) == 0
    assert "artifact_id" in json.loads(
        capsys.readouterr().out  # type: ignore[attr-defined]
    )


def test_default_r2_cli_schedules_one_compact_task_per_work_unit(
    tmp_path: Path, capsys: object
) -> None:
    manager, workflow, plan = _workflow(tmp_path, "CMP-r2-cli-compact")
    workflow.run_r0()
    workflow.record_r1([])
    manager.close()

    assert main([
        "task-schedule-r2", str(tmp_path), "CMP-r2-cli-compact",
        plan.batches[0].batch_id,
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
    assert (target / ".audit_vnext" / "campaigns" / "CMP-abort" / "lessons.md").exists()
