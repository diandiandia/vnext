import json
import os
from pathlib import Path
import subprocess
import sys


REPOSITORY = Path(__file__).resolve().parents[1]
LAUNCHER = REPOSITORY / "tools" / "vnext.py"


def test_launcher_runs_from_another_directory_and_reopens_state(tmp_path: Path) -> None:
    target = tmp_path / "target with spaces"
    target.mkdir()
    env = os.environ.copy()
    env["XDG_STATE_HOME"] = str(tmp_path / "state-home")
    command = [sys.executable, str(LAUNCHER)]
    initialized = subprocess.run(
        [*command, "init", str(target), "--campaign-id", "CMP-launcher",
         "--snapshot-id", "fixture:launcher"],
        cwd=tmp_path, env=env, capture_output=True, text=True, check=True,
    )
    assert json.loads(initialized.stdout)["campaign_id"] == "CMP-launcher"
    resumed = subprocess.run(
        [*command, "status", str(target)],
        cwd=tmp_path, env=env, capture_output=True, text=True, check=True,
    )
    assert json.loads(resumed.stdout)["campaigns"][0]["campaign_id"] == "CMP-launcher"
    assert resumed.stderr == ""
    assert not (target / ".audit_vnext").exists()


def test_launcher_propagates_cli_errors(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(LAUNCHER), "unknown-command"],
        cwd=tmp_path, capture_output=True, text=True,
    )
    assert result.returncode == 2
    assert "invalid choice" in result.stderr
    assert result.stdout == ""


def test_readme_demo_plans_and_reopens_external_state(tmp_path: Path) -> None:
    readme = (REPOSITORY / "README.md").read_text(encoding="utf-8")
    demo_section = readme.split("## Runnable Demo\n", 1)[1].split("\n## ", 1)[0]
    demo_script = demo_section.split("```bash\n", 1)[1].split("\n```", 1)[0]
    quick_start = readme.split("## Quick Start\n", 1)[1].split("\n## ", 1)[0]
    launcher_function = next(
        line for line in quick_start.splitlines() if line.startswith("vnext()")
    )
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env["VNEXT_ROOT"] = str(REPOSITORY)
    result = subprocess.run(
        ["bash", "-e", "-c", f"{launcher_function}\n{demo_script}"],
        cwd=tmp_path, env=env, capture_output=True, text=True, check=True, timeout=60,
    )
    decoder = json.JSONDecoder()
    outputs = []
    remaining = result.stdout.strip()
    while remaining:
        output, end = decoder.raw_decode(remaining)
        outputs.append(output)
        remaining = remaining[end:].lstrip()

    assert len(outputs) == 5
    assert outputs[0]["campaign_id"] == "demo-001"
    assert outputs[3]["batches"]
    assert outputs[4]["campaigns"][0]["campaign_id"] == "demo-001"
    demo_root = tmp_path / "vnext-demo"
    assert (demo_root / "target" / "app.py").is_file()
    assert any((demo_root / "state").iterdir())
    assert not (demo_root / "target" / ".audit_vnext").exists()
    assert not (demo_root / "target" / ".audit_results").exists()
    assert result.stderr == ""
