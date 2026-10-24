import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

import pytest

from reachable_audit.discovery import java_provider
from reachable_audit.discovery.hotspots import (
    enabled_hotspot_provider_ids,
    scan_work_unit_hotspots,
)
from reachable_audit.models import ModelError


@pytest.fixture
def jdk():
    if os.name != "posix" or not shutil.which("javac") or not shutil.which("java"):
        pytest.skip("optional POSIX JDK unavailable")


def test_java_opt_in_and_release_roster(tmp_path):
    (tmp_path / "App.java").write_text("class App { void f() { x.exec(cmd); } }")
    report = scan_work_unit_hotspots(tmp_path, ["App.java"])
    assert report["scan_status"] == "not_scanned"
    assert report["unsupported_paths"] == ["App.java"]
    assert enabled_hotspot_provider_ids() == ("python-ast-hotspots-v1",)


def test_java_real_ast_candidates_are_explicitly_unresolved(tmp_path, jdk):
    (tmp_path / "App.java").write_text("""
import java.io.*;
import static example.Unknown.*;
class App {
  void f(Object stream, Object zip, Object Runtime) {
    // stream.readObject(); Runtime.exec("comment");
    String text = "x.readAllBytes()";
    Runtime.exec(command);
    new ProcessBuilder(command).start();
    stream.readObject();
    stream.readUnshared();
    stream.readAllBytes();
    zip.getNextEntry();
    readObject();
  }
}
""")
    report = scan_work_unit_hotspots(tmp_path, ["App.java"], enable_java=True)
    assert report["scan_status"] == "completed"
    assert report["provider_id"] == java_provider.JAVA_HOTSPOT_PROVIDER_ID
    assert report["candidate_count"] == 7
    assert {c["rule_id"] for c in report["candidates"]} == {
        "JAVA-CMD-001", "JAVA-DESER-001", "JAVA-STREAM-001",
    }
    for candidate in report["candidates"]:
        assert candidate["language"] == "java"
        assert candidate["api"].startswith("unresolved-receiver.")
        assert "unresolved" in candidate["reason"]
        assert candidate["line"] > 1 and candidate["column"] > 0
    assert report == scan_work_unit_hotspots(tmp_path, ["App.java"], enable_java=True)


def test_java_strings_comments_declarations_not_calls(tmp_path, jdk):
    (tmp_path / "App.java").write_text("""
class App {
  String text = "stream.readObject()";
  // exec("no");
  void exec(String s) {}
  void readObject() {}
  void readAllBytes() {}
}
""")
    report = scan_work_unit_hotspots(tmp_path, ["App.java"], enable_java=True)
    assert report["scan_status"] == "completed"
    assert report["candidate_count"] == 0


def test_java_parse_errors_and_mixed_providers(tmp_path, jdk):
    (tmp_path / "Bad.java").write_text("class Bad { void f( { x.exec(a); }")
    (tmp_path / "Good.java").write_text("class Good { void f() { x.readObject(); } }")
    (tmp_path / "app.py").write_text("eval(data)")
    report = scan_work_unit_hotspots(
        tmp_path, ["Bad.java", "Good.java", "app.py"], enable_java=True,
    )
    assert report["scan_status"] == "partial"
    assert report["scanned_paths"] == ["Good.java", "app.py"]
    assert report["parse_error_count"] == 1
    assert report["candidate_count"] == 2


def test_java_missing_toolchain_is_unavailable(tmp_path, monkeypatch):
    (tmp_path / "App.java").write_text("class App {}")
    monkeypatch.setattr(java_provider.shutil, "which", lambda _: None)
    report = scan_work_unit_hotspots(tmp_path, ["App.java"], enable_java=True)
    assert report["scan_status"] == "error"
    assert report["provider_status"] == "provider_unavailable"
    assert report["unavailable_paths"] == ["App.java"]
    assert "unavailable" in report["parse_errors"][0]["error"]


def test_java_verified_bytes_not_reopened(tmp_path, monkeypatch, jdk):
    source = b"class App { void f() { x.exec(cmd); } }"
    path = tmp_path / "App.java"
    path.write_bytes(source)
    real_scan = java_provider.scan_java_bytes

    def mutate(sources, **kwargs):
        path.write_text("class App {}")
        assert sources == {"App.java": source}
        return real_scan(sources, **kwargs)

    monkeypatch.setattr("reachable_audit.discovery.hotspots.scan_java_bytes", mutate)
    report = scan_work_unit_hotspots(
        tmp_path, ["App.java"], enable_java=True,
        expected_digests={"App.java": hashlib.sha256(source).hexdigest()},
    )
    assert report["candidate_count"] == 1
    with pytest.raises(ModelError, match="snapshot drift"):
        scan_work_unit_hotspots(
            tmp_path, ["App.java"], enable_java=True,
            expected_digests={"App.java": hashlib.sha256(source).hexdigest()},
        )


def test_java_candidate_budget_preserves_count(tmp_path, jdk):
    (tmp_path / "App.java").write_text(
        "class App { void f() {" + "x.exec(cmd);" * 240 + "} }"
    )
    report = scan_work_unit_hotspots(
        tmp_path, ["App.java"], enable_java=True, max_candidates=3,
    )
    assert report["candidate_count"] == 240
    assert report["included_count"] == 3
    assert report["truncated"]


def test_java_input_limits_and_escape(tmp_path, monkeypatch):
    (tmp_path / "App.java").write_bytes(b"x" * (java_provider.MAX_JAVA_FILE_BYTES + 1))
    monkeypatch.setattr(
        "reachable_audit.discovery.hotspots.scan_java_bytes",
        lambda *args, **kwargs: pytest.fail("oversized bytes reached parser"),
    )
    report = scan_work_unit_hotspots(tmp_path, ["App.java", "../Escape.java"], enable_java=True)
    assert report["scan_status"] == "error"
    assert report["parse_error_count"] == 2
    for sources in (
        {"a.java": b"x" * (java_provider.MAX_JAVA_FILE_BYTES + 1)},
        {f"{i}.java": b"" for i in range(java_provider.MAX_JAVA_FILES + 1)},
        {"x" * 4097: b""},
        {f"{i}.java": b"x" * java_provider.MAX_JAVA_FILE_BYTES for i in range(5)},
    ):
        with pytest.raises(java_provider.JavaProviderError, match="input limit"):
            java_provider.scan_java_bytes(sources, max_candidates=1)


def test_java_file_count_limit_reported(tmp_path, monkeypatch):
    monkeypatch.setattr("reachable_audit.discovery.hotspots.MAX_JAVA_FILES", 1)
    for name in ("A.java", "B.java"):
        (tmp_path / name).write_text("class A {}")
    monkeypatch.setattr(
        "reachable_audit.discovery.hotspots.scan_java_bytes",
        lambda sources, **kwargs: [
            {"path": path, "count": 0, "candidates": []} for path in sources
        ],
    )
    report = scan_work_unit_hotspots(tmp_path, ["A.java", "B.java"], enable_java=True)
    assert report["scanned_paths"] == ["A.java"]
    assert report["scan_status"] == "partial"
    assert "count" in report["parse_errors"][0]["error"]


def test_java_invalid_utf8_is_file_error(tmp_path, jdk):
    (tmp_path / "A.java").write_bytes(b"class A {}\xff")
    report = scan_work_unit_hotspots(tmp_path, ["A.java"], enable_java=True)
    assert report["scan_status"] == "error"
    assert report["scanned_paths"] == []
    assert "UTF-8" in report["parse_errors"][0]["error"]


def test_java_build_failure_cleans_private_cache(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(java_provider, "_WORKSPACE", None)
    monkeypatch.setattr(java_provider, "_HELPER", None)
    monkeypatch.setattr(java_provider.shutil, "which", lambda _: sys.executable)

    def fail(*args):
        raise java_provider.JavaProviderError("build failed")

    monkeypatch.setattr(java_provider, "_run_bounded", fail)
    with pytest.raises(java_provider.JavaProviderError, match="build failed"):
        java_provider._helper()
    assert not list(tmp_path.glob(".reachable-audit-java-*"))


def test_java_helper_cache_is_bounded_and_reused(jdk):
    first = java_provider._helper()
    assert java_provider._helper() == first
    assert sum(
        path.stat().st_size for path in first[1].rglob("*") if path.is_file()
    ) <= java_provider.MAX_JAVA_CACHE_BYTES


def test_java_only_helper_is_compiled_no_target_processors(tmp_path, monkeypatch, jdk):
    java_provider._helper()
    real_run = java_provider._run_bounded
    commands = []

    def record(command, workspace, payload, timeout):
        commands.append(command)
        return real_run(command, workspace, payload, timeout)

    monkeypatch.setattr(java_provider, "_run_bounded", record)
    (tmp_path / "App.java").write_text("""
import missing.Target;
@missing.Annotation class App {
  static { throw new RuntimeException("must not run"); }
  void f() { unknown.exec(data); }
}
""")
    report = scan_work_unit_hotspots(tmp_path, ["App.java"], enable_java=True)
    assert report["candidate_count"] == 1
    assert len(commands) == 1
    assert Path(commands[0][0]).name == "java"
    assert str(tmp_path) not in " ".join(commands[0])
    environment = java_provider._environment(tmp_path)
    assert not {"CLASSPATH", "JAVA_TOOL_OPTIONS", "_JAVA_OPTIONS", "JDK_JAVA_OPTIONS"} & environment.keys()


def test_java_runner_output_timeout_and_status(tmp_path, monkeypatch):
    monkeypatch.setattr(java_provider, "_OUTPUT_LIMIT", 1024)
    for code, timeout, message in (
        ("print('x' * 2000)", 5, "output limit"),
        ("import time; time.sleep(10)", 1, "timed out"),
        ("raise SystemExit(3)", 5, "status 3"),
    ):
        with pytest.raises(java_provider.JavaProviderError, match=message):
            java_provider._run_bounded([sys.executable, "-c", code], tmp_path, b"", timeout)
    assert not list(tmp_path.glob("request-*"))


@pytest.mark.parametrize("output", [
    b"", b"not a response\n", b"F\tYS5qYXZh\t-1\t\n",
    b"F\tYS5qYXZh\t0\t\nC\tYS5qYXZh\t1\t1\tunresolved-receiver.exec\n",
    b"F\tYS5qYXZh\t1\t\nC\tYS5qYXZh\t0\t1\tunresolved-receiver.exec\n",
    b"F\tYS5qYXZh\t1\t\nC\tYS5qYXZh\t1\t1\tjava.lang.Runtime.exec\n",
])
def test_java_invalid_helper_response(tmp_path, monkeypatch, output):
    monkeypatch.setattr(java_provider, "_helper", lambda: (tmp_path, tmp_path))
    monkeypatch.setattr(java_provider, "_run_bounded", lambda *args: output)
    with pytest.raises(java_provider.JavaProviderError, match="response"):
        java_provider.scan_java_bytes({"a.java": b"class A {}"}, max_candidates=1)


def test_java_wheel_resource_parses_outside_source_checkout(tmp_path, jdk):
    pytest.importorskip("setuptools")
    root = Path(__file__).resolve().parents[1]
    project = tmp_path / "project"
    project.mkdir()
    for name in ("pyproject.toml", "README.md"):
        shutil.copyfile(root / name, project / name)
    shutil.copytree(root / "src", project / "src", ignore=shutil.ignore_patterns("__pycache__", "*.egg-info"))
    wheels = tmp_path / "wheels"
    wheels.mkdir()
    environment = dict(os.environ, TMPDIR=str(tmp_path))
    build = subprocess.run(
        [sys.executable, "-c",
         "from setuptools.build_meta import build_wheel; "
         f"build_wheel({str(wheels)!r})"],
        cwd=project, env=environment, capture_output=True, timeout=30,
    )
    assert build.returncode == 0, build.stderr.decode()
    installed = tmp_path / "installed"
    with zipfile.ZipFile(next(wheels.glob("*.whl"))) as wheel:
        assert "reachable_audit/discovery/JavaHotspots.java" in wheel.namelist()
        wheel.extractall(installed)
    environment["PYTHONPATH"] = str(installed)
    run = subprocess.run(
        [sys.executable, "-c", """
from pathlib import Path
import reachable_audit
from reachable_audit.discovery.java_provider import scan_java_bytes
assert Path(reachable_audit.__file__).is_relative_to(Path("installed").resolve())
result = scan_java_bytes({"A.java": b"class A { void f() { x.exec(cmd); } }"}, max_candidates=1)
assert result[0]["count"] == 1, result
"""],
        cwd=tmp_path, env=environment, capture_output=True, timeout=45,
    )
    assert run.returncode == 0, run.stderr.decode()
    assert not list(tmp_path.glob(".reachable-audit-java-*"))
