from pathlib import Path
import shutil

import pytest

from reachable_audit.discovery import bounded_process, go_provider, java_provider
from reachable_audit.discovery.hotspots import scan_work_unit_hotspots


@pytest.mark.parametrize("language", ["go", "java"])
def test_parser_caches_stay_outside_target_cwd_and_tmpdir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, language: str,
) -> None:
    tools = ("go",) if language == "go" else ("java", "javac")
    if any(shutil.which(tool) is None for tool in tools):
        pytest.skip("optional trusted parser toolchain unavailable")
    provider = go_provider if language == "go" else java_provider
    provider._cleanup()
    target = tmp_path / "target"
    target.mkdir()
    name, source = (
        ("main.go", 'package x\nimport "io"\nfunc f(){io.ReadAll(r)}\n')
        if language == "go" else
        ("App.java", "class App { void f() { input.readAllBytes(); } }\n")
    )
    (target / name).write_text(source)
    monkeypatch.chdir(target)
    monkeypatch.setenv("TMPDIR", str(target))
    before = {path.name: path.read_bytes() for path in target.iterdir()}
    workspace = None
    try:
        report = scan_work_unit_hotspots(
            target, [name], enable_go=language == "go", enable_java=language == "java",
        )
        assert report["scan_status"] == "completed"
        assert report["candidate_count"] == 1
        workspace = provider._WORKSPACE
        assert workspace is not None and workspace.is_dir()
        assert not workspace.is_relative_to(target)
        assert workspace.stat().st_mode & 0o777 == 0o700
        assert {path.name: path.read_bytes() for path in target.iterdir()} == before
    finally:
        provider._cleanup()
    assert workspace is not None and not workspace.exists()


def test_no_external_parser_scratch_is_an_explicit_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir("/")
    with pytest.raises(OSError, match="outside target"):
        bounded_process.create_workspace("reachable-audit-test-", Path("/"))


def test_parser_child_limits_include_file_and_descriptor_caps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    limits = {}
    resource = bounded_process.resource
    monkeypatch.setattr(resource, "getrlimit", lambda kind: (-1, -1))
    monkeypatch.setattr(resource, "setrlimit", lambda kind, value: limits.update({kind: value}))
    bounded_process.child_limits()
    assert limits[resource.RLIMIT_FSIZE] == (64 * 1024**2,) * 2
    assert limits[resource.RLIMIT_NOFILE] == (128, 128)
