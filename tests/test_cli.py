import json
from pathlib import Path
import sys

from reachable_audit.cli import main
from reachable_audit.compatibility import scan_runtime_deproject
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
    }), encoding="utf-8")

    assert main([
        "harness-run", str(target), "CMP-harness-cli", "--input", str(input_path),
    ]) == 0
    result = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert result["exit_code"] == 0
    assert result["stdout_artifact_id"].startswith("sha256:")
    assert result["execution_artifact_id"].startswith("sha256:")


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
    assert main(["task-claim", str(target), "CMP-tasks", "worker-a"]) == 0
    claim = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    task_id = claim["lease"]["task"]["task_id"]
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
        },
    }), encoding="utf-8")
    assert main([
        "task-collect", str(target), "CMP-tasks", task_id, "worker-a",
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

    assert main(["skill-backlog", str(target)]) == 0
    backlog = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert backlog == {"pending_issues": []}

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
    assert main(["skill-backlog", str(target)]) == 0
    backlog = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert backlog["pending_issues"][0]["issue_id"] == "SKILL-cli-1"


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
