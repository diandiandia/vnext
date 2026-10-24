import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile


def test_wheel_includes_runtime_knowledge_without_development_history(
    tmp_path: Path,
) -> None:
    repository = Path(__file__).resolve().parents[1]
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    for name in ("pyproject.toml", "README.md"):
        shutil.copy2(repository / name, checkout / name)
    for name in ("src", "knowledge"):
        shutil.copytree(
            repository / name, checkout / name,
            ignore=shutil.ignore_patterns("__pycache__", "*.egg-info"),
        )
    wheel_dir = tmp_path / "wheels"
    wheel_dir.mkdir()
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    subprocess.run(
        [
            sys.executable, "-c",
            "from setuptools.build_meta import build_wheel; "
            "import sys; build_wheel(sys.argv[1])",
            str(wheel_dir),
        ],
        cwd=checkout, env=env, capture_output=True, text=True, check=True, timeout=60,
    )
    wheels = list(wheel_dir.glob("*.whl"))
    assert len(wheels) == 1
    installed = tmp_path / "installed"
    with zipfile.ZipFile(wheels[0]) as archive:
        names = archive.namelist()
        assert {
            path.relative_to(repository / "src").as_posix()
            for path in (repository / "src").rglob("*.py")
        } <= set(names)
        assert "reachable_audit/knowledge_assets/portfolio.json" in names
        assert len([
            name for name in names
            if name.startswith("reachable_audit/knowledge_assets/") and name.endswith(".json")
        ]) == 167
        assert not any(
            name.startswith(("docs/", "tests/"))
            or name.endswith(("migration-report.json", "SKILL.md"))
            for name in names
        )
        archive.extractall(installed)
    result = subprocess.run(
        [
            sys.executable, "-I", "-c",
            "import json, sys; from importlib.resources import files; "
            "sys.path.insert(0, sys.argv[1]); "
            "from reachable_audit.cli import main; "
            "from reachable_audit.execution import DiscoveryCoordinator; "
            "from reachable_audit.knowledge_catalog import KnowledgeCatalog, default_knowledge_root; "
            "catalog = KnowledgeCatalog.load(default_knowledge_root()); "
            "assert files('reachable_audit.discovery').joinpath('JavaHotspots.java').is_file(); "
            "assert files('reachable_audit.discovery').joinpath('go_hotspots.go').is_file(); "
            "print(json.dumps({'languages': len(catalog.languages), "
            "'cards': len(catalog.cards), "
            "'entries': len(catalog.task_context(['java']).issue_entries)}))",
            str(installed),
        ],
        cwd=tmp_path, env=env, capture_output=True, text=True, check=True, timeout=30,
    )
    assert json.loads(result.stdout) == {"languages": 15, "cards": 150, "entries": 10}
