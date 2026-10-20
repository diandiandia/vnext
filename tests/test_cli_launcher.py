import json
from pathlib import Path
import subprocess
import sys


LAUNCHER = Path(__file__).resolve().parents[1] / "tools" / "vnext.py"


def test_launcher_runs_from_another_directory_and_reopens_state(tmp_path: Path) -> None:
    target = tmp_path / "target with spaces"
    target.mkdir()
    command = [sys.executable, str(LAUNCHER)]
    initialized = subprocess.run(
        [*command, "init", str(target), "--campaign-id", "CMP-launcher",
         "--snapshot-id", "fixture:launcher"],
        cwd=tmp_path, capture_output=True, text=True, check=True,
    )
    assert json.loads(initialized.stdout)["campaign_id"] == "CMP-launcher"
    resumed = subprocess.run(
        [*command, "status", str(target)],
        cwd=tmp_path, capture_output=True, text=True, check=True,
    )
    assert json.loads(resumed.stdout)["campaigns"][0]["campaign_id"] == "CMP-launcher"
    assert resumed.stderr == ""


def test_launcher_propagates_cli_errors(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(LAUNCHER), "unknown-command"],
        cwd=tmp_path, capture_output=True, text=True,
    )
    assert result.returncode == 2
    assert "invalid choice" in result.stderr
    assert result.stdout == ""
