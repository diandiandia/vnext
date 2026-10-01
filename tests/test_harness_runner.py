from pathlib import Path
import sys

import pytest

from reachable_audit.campaign import CampaignManager
from reachable_audit.experiments.runner import run_harness
from reachable_audit.models import ModelError
from reachable_audit.resource_cleanup import cleanup_campaign_resources


def _campaign(root: Path) -> CampaignManager:
    root.mkdir(parents=True, exist_ok=True)
    manager = CampaignManager(root)
    manager.create_campaign(campaign_id="CMP-harness", snapshot_id="fixture:harness")
    return manager


def test_runner_captures_bounded_output_as_artifacts_and_cleans_group(tmp_path: Path) -> None:
    (tmp_path / "target").mkdir()
    manager = _campaign(tmp_path / "target")
    try:
        result = run_harness(
            manager,
            "CMP-harness",
            command=[sys.executable, "-c", "print('x' * 100)"],
            output_limit_bytes=12,
        )

        stdout = manager.artifacts.get_bytes(result["stdout_artifact_id"])
        assert result["exit_code"] != 0
        assert result["timed_out"] is False
        assert result["output_limit_exceeded"] is True
        assert len(stdout) == 12
        assert "runtime" in result["runtime_directory_ref"]
        assert cleanup_campaign_resources(manager, "CMP-harness")["failures"] == []
    finally:
        manager.close()


def test_runner_terminates_timed_out_process_group(tmp_path: Path) -> None:
    (tmp_path / "target").mkdir()
    manager = _campaign(tmp_path / "target")
    try:
        result = run_harness(
            manager,
            "CMP-harness",
            command=[sys.executable, "-c", "import time; time.sleep(30)"],
            timeout_seconds=1,
        )
        assert result["timed_out"] is True
        assert result["exit_code"] is not None
        resources = cleanup_campaign_resources(manager, "CMP-harness")
        assert resources["failures"] == []
    finally:
        manager.close()


def test_runner_rejects_working_directory_escape(tmp_path: Path) -> None:
    (tmp_path / "target").mkdir()
    manager = _campaign(tmp_path / "target")
    try:
        with pytest.raises(ModelError, match="escapes the target root"):
            run_harness(
                manager,
                "CMP-harness",
                command=[sys.executable, "--version"],
                cwd="..",
            )
    finally:
        manager.close()