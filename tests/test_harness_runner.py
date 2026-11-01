from pathlib import Path
import shutil
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
        assert result["empirical_upgrade_eligible"] is False
        assert "hypothesis_id" in result["empirical_upgrade_note"]
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


def test_jvm_profile_uses_bounded_four_gibibyte_address_space(
    tmp_path: Path,
) -> None:
    (tmp_path / "target").mkdir()
    manager = _campaign(tmp_path / "target")
    try:
        default = run_harness(
            manager,
            "CMP-harness",
            command=[sys.executable, "-c", "print('bounded')"],
            profile="jvm-bounded",
        )
        assert default["resource_limits"]["address_space_bytes"] == 4 * 1024**3
        assert default["exit_code"] == 0

        java = shutil.which("java")
        if java is not None:
            jvm = run_harness(
                manager,
                "CMP-harness",
                command=[
                    java,
                    "-Xmx512m",
                    "-XX:MaxMetaspaceSize=256m",
                    "-XX:ReservedCodeCacheSize=128m",
                    "-version",
                ],
                profile="jvm-bounded",
                timeout_seconds=15,
            )
            assert jvm["resource_limits"]["address_space_bytes"] == 4 * 1024**3
            assert jvm["exit_code"] == 0, manager.artifacts.get_bytes(
                str(jvm["stderr_artifact_id"])
            ).decode(errors="replace")

        overridden = run_harness(
            manager,
            "CMP-harness",
            command=[sys.executable, "-c", "print('bounded')"],
            profile="jvm-bounded",
            memory_limit_bytes=512 * 1024**2,
        )
        assert overridden["resource_limits"]["address_space_bytes"] == 512 * 1024**2
        assert overridden["exit_code"] == 0
    finally:
        cleanup_campaign_resources(manager, "CMP-harness")
        manager.close()


def test_runner_validates_execution_provenance_artifact_scope(
    tmp_path: Path,
) -> None:
    (tmp_path / "target").mkdir()
    manager = _campaign(tmp_path / "target")
    try:
        with pytest.raises(ModelError, match="target_tree provenance"):
            run_harness(
                manager,
                "CMP-harness",
                command=[sys.executable, "-c", "pass"],
                execution_provenance={
                    "origin": "target_tree",
                    "artifact_refs": ["sha256:" + "0" * 64],
                },
            )
        build_ref = manager.artifacts.put_bytes(b"build").artifact_id
        with pytest.raises(ModelError, match="same_snapshot_build requires"):
            run_harness(
                manager,
                "CMP-harness",
                command=[sys.executable, "-c", "pass"],
                execution_provenance={
                    "origin": "same_snapshot_build",
                    "source_snapshot_id": "another:snapshot",
                    "artifact_refs": [build_ref],
                },
            )
    finally:
        manager.close()


@pytest.mark.parametrize("provenance", [None, {"origin": "mechanism_only"}])
def test_hypothesis_alone_does_not_establish_empirical_provenance(
    tmp_path: Path, provenance: dict[str, str] | None,
) -> None:
    manager = _campaign(tmp_path / "target")
    try:
        result = run_harness(
            manager,
            "CMP-harness",
            command=[sys.executable, "-c", "print('observed')"],
            hypothesis_id="HYP-capture",
            execution_provenance=provenance,
        )
        assert result["exit_code"] == 0
        assert result["empirical_upgrade_eligible"] is False
        assert "provenance" in str(result["empirical_upgrade_note"])
    finally:
        cleanup_campaign_resources(manager, "CMP-harness")
        manager.close()