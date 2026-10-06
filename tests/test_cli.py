import json
from pathlib import Path
import sys

from reachable_audit.cli import main
from reachable_audit.campaign import CampaignManager
from reachable_audit.compatibility import scan_runtime_deproject
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


def test_runtime_deproject_scan_rejects_known_project_token(tmp_path: Path) -> None:
    profile = tmp_path / "knowledge" / "profiles" / "sample.json"
    profile.parent.mkdir(parents=True)
    profile.write_text('{"note":"SWR-V3.11-004"}', encoding="utf-8")

    report = scan_runtime_deproject(tmp_path)

    assert report["passed"] is False
    assert report["findings"][0]["value"] == "swr-v3.11-004"


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
    assert main([
        "plan", str(target), "CMP-pipeline", "--categories", "STATE",
    ]) == 0
    plan_output = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert plan_output["work_units"] == 1
    assert plan_output["batches"] == 1


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
