from pathlib import Path

import hashlib
import shutil
import sys
import pytest

from reachable_audit.discovery.hotspots import scan_work_unit_hotspots
from reachable_audit.discovery import go_provider
from reachable_audit.models import ModelError


def test_hotspot_provider_checks_the_bytes_it_parses(tmp_path: Path) -> None:
    original = b"print('original')\n"
    source = tmp_path / "app.py"
    source.write_bytes(original)
    expected = {"app.py": hashlib.sha256(original).hexdigest()}
    assert scan_work_unit_hotspots(tmp_path, ["app.py"], expected_digests=expected)["candidate_count"] == 0
    source.write_text("import os\nos.system('changed')\n", encoding="utf-8")
    with pytest.raises(ModelError, match="snapshot drift"):
        scan_work_unit_hotspots(tmp_path, ["app.py"], expected_digests=expected)


def test_python_hotspots_are_source_anchored_and_resolve_import_aliases(
    tmp_path: Path,
) -> None:
    (tmp_path / "app.py").write_text(
        "from subprocess import run as launch\n"
        "import pickle as codec\n"
        "launch(command, shell=True)\n"
        "codec.loads(payload)\n",
        encoding="utf-8",
    )

    report = scan_work_unit_hotspots(tmp_path, ["app.py"])

    assert report["provider_status"] == "available"
    assert report["scan_status"] == "completed"
    assert report["supported_path_count"] == 1
    assert report["scanned_path_count"] == 1
    assert report["unsupported_path_count"] == 0
    assert report["scanned_paths"] == ["app.py"]
    assert [item["rule_id"] for item in report["candidates"]] == [
        "PY-CMD-001", "PY-DESER-001",
    ]
    assert [item["evidence_ref"] for item in report["candidates"]] == [
        "LOC-app.py:3", "LOC-app.py:4",
    ]
    assert all(item["candidate_id"].startswith("HOT-") for item in report["candidates"])


def test_python_hotspots_report_coverage_errors_and_candidate_truncation(
    tmp_path: Path,
) -> None:
    (tmp_path / "app.py").write_text(
        "import os\nos.system('x')\nos.popen('y')\n", encoding="utf-8"
    )
    (tmp_path / "broken.py").write_text("def broken(:\n", encoding="utf-8")
    (tmp_path / "Main.java").write_text("class Main {}\n", encoding="utf-8")

    report = scan_work_unit_hotspots(
        tmp_path, ["app.py", "broken.py", "Main.java"], max_candidates=1
    )

    assert report["scanned_paths"] == ["app.py"]
    assert report["unsupported_paths"] == ["Main.java"]
    assert report["scan_status"] == "partial"
    assert report["supported_path_count"] == 2
    assert report["scanned_path_count"] == 1
    assert report["unsupported_path_count"] == 1
    assert report["parse_error_count"] == 1
    assert len(report["parse_errors"]) == 1
    assert report["candidate_count"] == 2
    assert report["included_count"] == 1
    assert report["truncated"] is True
    assert report["limitations"]


def test_python_hotspot_provider_reports_empty_language_coverage(tmp_path: Path) -> None:
    report = scan_work_unit_hotspots(tmp_path, ["Main.java"])

    assert report["provider_status"] == "provider_unavailable"
    assert report["scan_status"] == "not_scanned"
    assert report["supported_path_count"] == 0
    assert report["scanned_path_count"] == 0
    assert report["unsupported_path_count"] == 1
    assert report["parse_error_count"] == 0
    assert report["scanned_paths"] == []
    assert report["unsupported_paths"] == ["Main.java"]
    assert report["candidate_count"] == 0


def test_unimplemented_language_coverage_is_explicit(tmp_path: Path) -> None:
    paths = ["Main.java", "main.go", "main.c", "main.cpp"]

    report = scan_work_unit_hotspots(tmp_path, paths)

    assert report["provider_status"] == "provider_unavailable"
    assert report["scan_status"] == "not_scanned"
    assert report["scanned_paths"] == []
    assert report["unsupported_paths"] == sorted(paths)
    assert report["candidate_count"] == 0
    assert report["included_count"] == 0


def test_malformed_supported_only_hotspot_scan_is_an_error(tmp_path: Path) -> None:
    (tmp_path / "broken.py").write_text("def broken(:\n", encoding="utf-8")

    report = scan_work_unit_hotspots(tmp_path, ["broken.py"])

    assert report["provider_status"] == "provider_unavailable"
    assert report["scan_status"] == "error"
    assert report["supported_path_count"] == 1
    assert report["scanned_path_count"] == 0
    assert report["unsupported_path_count"] == 0
    assert report["parse_error_count"] == 1
    assert report["candidate_count"] == 0


def test_python_hotspots_ignore_unrelated_api_lookalikes(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text(
        "import logging\n"
        "logger = logging.getLogger(__name__)\n"
        "logger.error('system execution failed')\n"
        "class ProcessNotes:\n"
        "    def start_process(self):\n"
        "        return None\n",
        encoding="utf-8",
    )

    report = scan_work_unit_hotspots(tmp_path, ["app.py"])

    assert report["scanned_paths"] == ["app.py"]
    assert report["scan_status"] == "completed"
    assert report["scanned_path_count"] == 1
    assert report["candidate_count"] == 0
    assert any("no match is not evidence of safety" in item for item in report["limitations"])

def test_compact_hotspot_report_replaces_path_lists_with_counts(tmp_path) -> None:
    from reachable_audit.discovery.hotspots import (
        compact_hotspot_report, scan_work_unit_hotspots,
    )

    (tmp_path / "app.py").write_text("import os\nos.system('x')\n", encoding="utf-8")
    (tmp_path / "Main.java").write_text("class Main {}\n", encoding="utf-8")
    (tmp_path / "Other.java").write_text("class Other {}\n", encoding="utf-8")
    report = compact_hotspot_report(
        scan_work_unit_hotspots(tmp_path, ["app.py", "Main.java", "Other.java"])
    )

    assert "scanned_paths" not in report and "unsupported_paths" not in report
    assert report["scanned_path_count"] == 1
    assert report["unsupported_path_count"] == 2
    assert report["unsupported_extension_counts"] == {".java": 2}
    assert report["candidate_count"] == 1


@pytest.fixture
def go_toolchain() -> None:
    if shutil.which("go") is None:
        pytest.skip("optional host Go toolchain is unavailable")


def test_go_ast_hotspots_are_opt_in_alias_resolved_and_deterministic(
    tmp_path: Path, go_toolchain,
) -> None:
    source = (
        'package sample\n'
        'import ( launch "os/exec"; stream "io"; old "io/ioutil"; paths "path/filepath" )\n'
        'func f() {\n'
        ' launch.Command("echo", "hello")\n'
        ' launch.CommandContext(ctx, "echo")\n'
        ' stream.ReadAll(reader)\n'
        ' old.ReadAll(reader)\n'
        ' paths.Join(root, userPath)\n'
        '}\n'
    )
    (tmp_path / "main.go").write_text(source, encoding="utf-8")
    expected = {"main.go": hashlib.sha256(source.encode()).hexdigest()}
    default = scan_work_unit_hotspots(tmp_path, ["main.go"])
    assert default["scan_status"] == "not_scanned"
    assert default["unsupported_paths"] == ["main.go"]
    report = scan_work_unit_hotspots(
        tmp_path, ["main.go"], enable_go=True, expected_digests=expected,
    )
    assert report["provider_id"] == "go-ast-hotspots-v1"
    assert report["scan_status"] == "completed"
    assert report["scanned_paths"] == ["main.go"]
    assert report["candidate_count"] == 5
    assert [item["api"] for item in report["candidates"]] == [
        "os/exec.Command", "os/exec.CommandContext", "io.ReadAll",
        "io/ioutil.ReadAll", "path/filepath.Join",
    ]
    assert [item["evidence_ref"] for item in report["candidates"]] == [
        f"LOC-main.go:{line}" for line in range(4, 9)
    ]
    assert all(item["language"] == "go" for item in report["candidates"])
    repeated = scan_work_unit_hotspots(tmp_path, ["main.go"], enable_go=True)
    assert repeated["candidates"] == report["candidates"]
    from reachable_audit.discovery.hotspots import enabled_hotspot_provider_ids
    assert enabled_hotspot_provider_ids() == ("python-ast-hotspots-v1",)


def test_go_parser_ignores_comments_strings_lookalikes_and_lexical_shadows(
    tmp_path: Path, go_toolchain,
) -> None:
    (tmp_path / "main.go").write_text(
        'package sample\n'
        'import ("os/exec"; "io"; p "path"; . "io/ioutil"; custom "example.invalid/exec")\n'
        'func param(exec interface{Command(string)}) {exec.Command("not imported")}\n'
        'func f() {\n'
        ' // exec.Command("comment")\n'
        ' _ = `io.ReadAll(reader)`\n'
        ' custom.Command("lookalike")\n'
        ' ReadAll(reader)\n'
        ' {exec := local; exec.Command("local")}\n'
        ' for io := range things {io.ReadAll(reader)}\n'
        ' if p := local; yes {p.Clean("local")}\n'
        ' func(io interface{ReadAll(any)}) {io.ReadAll(reader)}(local)\n'
        ' switch io := local; io {case true: io.ReadAll(reader)}\n'
        ' switch io := local.(type) {case Thing: io.ReadAll(reader)}\n'
        ' {var exec = local; exec.Command("local")}\n'
        ' {type exec struct{}; exec.Command("local")}\n'
        ' exec.Command("real")\n'
        ' io.ReadAll(reader)\n'
        ' p.Clean("real")\n'
        '}\n',
        encoding="utf-8",
    )
    report = scan_work_unit_hotspots(tmp_path, ["main.go"], enable_go=True)
    assert report["scan_status"] == "completed"
    assert [item["line"] for item in report["candidates"]] == [17, 18, 19]


def test_go_parser_uses_physical_positions_not_line_directives(
    tmp_path: Path, go_toolchain,
) -> None:
    (tmp_path / "main.go").write_text(
        'package sample\nimport "os/exec"\n'
        '//line forged.go:999\nfunc f(){exec.Command("echo")}\n',
        encoding="utf-8",
    )
    candidate = scan_work_unit_hotspots(
        tmp_path, ["main.go"], enable_go=True,
    )["candidates"][0]
    assert candidate["path"] == "main.go"
    assert candidate["line"] == 4
    assert candidate["evidence_ref"] == "LOC-main.go:4"


def test_go_mixed_scan_errors_and_truncation(tmp_path: Path, go_toolchain) -> None:
    (tmp_path / "a.go").write_text(
        'package a\nimport "io"\nfunc f(){io.ReadAll(r); io.ReadAll(s)}\n',
        encoding="utf-8",
    )
    (tmp_path / "b.go").write_text("package b\nfunc broken( {\n", encoding="utf-8")
    (tmp_path / "c.py").write_text("import os\nos.system('echo')\n", encoding="utf-8")
    (tmp_path / "d.java").write_text("class D {}", encoding="utf-8")
    report = scan_work_unit_hotspots(
        tmp_path, ["d.java", "c.py", "b.go", "a.go"], enable_go=True, max_candidates=1,
    )
    assert report["scan_status"] == "partial"
    assert report["supported_path_count"] == 3
    assert report["scanned_paths"] == ["a.go", "c.py"]
    assert report["unsupported_paths"] == ["d.java"]
    assert report["parse_error_count"] == 1
    assert report["parse_errors"][0]["path"] == "b.go"
    assert report["candidate_count"] == 3
    assert report["included_count"] == 1
    assert report["candidates"][0]["path"] == "a.go"
    assert report["truncated"] is True
    assert report["unavailable_path_count"] == 0


@pytest.mark.parametrize("source", [b"package x\nfunc broken( {", b"package x\n\xff"])
def test_go_malformed_source_is_not_scanned(
    tmp_path: Path, go_toolchain, source: bytes,
) -> None:
    (tmp_path / "main.go").write_bytes(source)
    report = scan_work_unit_hotspots(tmp_path, ["main.go"], enable_go=True)
    assert report["scan_status"] == "error"
    assert report["scanned_paths"] == []
    assert report["parse_error_count"] == 1
    assert report["candidate_count"] == 0


def test_go_drift_is_checked_before_helper_receives_bytes(tmp_path, monkeypatch) -> None:
    (tmp_path / "main.go").write_bytes(b'package x\nimport "io"\n')
    monkeypatch.setattr(
        "reachable_audit.discovery.hotspots.scan_go_bytes",
        lambda *args, **kwargs: pytest.fail("drifted bytes reached Go parser"),
    )
    with pytest.raises(ModelError, match="snapshot drift"):
        scan_work_unit_hotspots(
            tmp_path, ["main.go"], enable_go=True, expected_digests={"main.go": "wrong"},
        )


def test_go_parses_verified_buffer_not_reread_target_file(tmp_path, monkeypatch) -> None:
    path = tmp_path / "main.go"
    original = b'package x\nimport "io"\nfunc f(){io.ReadAll(r)}\n'
    path.write_bytes(original)
    real_scan = go_provider.scan_go_bytes

    def change_after_verification(sources, **kwargs):
        assert sources == {"main.go": original}
        path.write_bytes(b"package changed\n")
        return real_scan(sources, **kwargs)

    if shutil.which("go") is None:
        pytest.skip("optional host Go toolchain is unavailable")
    monkeypatch.setattr(
        "reachable_audit.discovery.hotspots.scan_go_bytes", change_after_verification,
    )
    report = scan_work_unit_hotspots(
        tmp_path, ["main.go"], enable_go=True,
        expected_digests={"main.go": hashlib.sha256(original).hexdigest()},
    )
    assert report["candidate_count"] == 1


def test_missing_go_toolchain_is_explicit_and_preserves_python(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(go_provider.shutil, "which", lambda _: None)
    (tmp_path / "main.go").write_text("package x\n", encoding="utf-8")
    (tmp_path / "app.py").write_text("print('x')\n", encoding="utf-8")
    report = scan_work_unit_hotspots(tmp_path, ["main.go", "app.py"], enable_go=True)
    assert report["scan_status"] == "partial"
    assert report["scanned_paths"] == ["app.py"]
    assert report["supported_path_count"] == 2
    assert report["unsupported_path_count"] == 0
    assert report["unavailable_paths"] == ["main.go"]
    assert "unavailable" in report["parse_errors"][0]["error"]
    report = scan_work_unit_hotspots(tmp_path, ["main.go"], enable_go=True)
    assert report["scan_status"] == "error"
    assert report["provider_status"] == "provider_unavailable"


@pytest.mark.parametrize("message", ["timed out", "output limit exceeded", "exited with status 2"])
def test_go_subprocess_errors_are_not_clean_scans(tmp_path, monkeypatch, message) -> None:
    (tmp_path / "main.go").write_text("package x\n", encoding="utf-8")

    def fail(*args, **kwargs):
        raise go_provider.GoProviderError(message)

    monkeypatch.setattr(go_provider, "_helper", fail)
    report = scan_work_unit_hotspots(tmp_path, ["main.go"], enable_go=True)
    assert report["scan_status"] == "error"
    assert report["scanned_path_count"] == 0
    assert report["parse_errors"] == [{"path": "main.go", "error": message}]


def test_go_file_budget_is_explicit(tmp_path, monkeypatch) -> None:
    (tmp_path / "main.go").write_bytes(b"x" * (go_provider.MAX_GO_FILE_BYTES + 1))
    monkeypatch.setattr(
        "reachable_audit.discovery.hotspots.scan_go_bytes",
        lambda *args, **kwargs: pytest.fail("oversized bytes reached Go parser"),
    )
    report = scan_work_unit_hotspots(tmp_path, ["main.go"], enable_go=True)
    assert report["scan_status"] == "error"
    assert "byte limit" in report["parse_errors"][0]["error"]


def test_go_helper_runs_once_per_work_unit_not_per_file(tmp_path, go_toolchain, monkeypatch) -> None:
    calls = []
    real_run = go_provider._run_bounded

    def record(command, *args):
        calls.append(command)
        return real_run(command, *args)

    # Warm helper so only parse subprocesses are counted below.
    go_provider._helper()
    monkeypatch.setattr(go_provider, "_run_bounded", record)
    for name in ("a.go", "b.go"):
        (tmp_path / name).write_text("package x\n", encoding="utf-8")
    for _ in range(2):
        report = scan_work_unit_hotspots(tmp_path, ["b.go", "a.go"], enable_go=True)
        assert report["scanned_path_count"] == 2
    assert len(calls) == 2
    assert all(len(command) == 1 for command in calls)


def test_go_subprocess_pipe_and_timeout_bounds_cleanup(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(go_provider, "_OUTPUT_LIMIT", 1024)
    with pytest.raises(go_provider.GoProviderError, match="output limit"):
        go_provider._run_bounded(
            [sys.executable, "-c", "import os; os.write(2, b'x'*4096)"],
            tmp_path, b"", 5,
        )
    with pytest.raises(go_provider.GoProviderError, match="timed out"):
        go_provider._run_bounded(
            [sys.executable, "-c", "import time; time.sleep(2)"],
            tmp_path, b"", 0,
        )
    with pytest.raises(go_provider.GoProviderError, match="status 3"):
        go_provider._run_bounded(
            [sys.executable, "-c", "raise SystemExit(3)"], tmp_path, b"", 5,
        )
    assert list(tmp_path.glob("request-*.json")) == []


def test_go_environment_disables_target_configuration(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GOFLAGS", "-toolexec=untrusted")
    monkeypatch.setenv("GOTOOLCHAIN", "go9.9")
    environment = go_provider._environment(tmp_path)
    assert environment["GOFLAGS"] == ""
    assert environment["GOTOOLCHAIN"] == "local"
    assert environment["GOENV"] == "off"
    assert environment["GO111MODULE"] == "off"
    assert environment["GOWORK"] == "off"
    assert environment["GOPROXY"] == environment["GOSUMDB"] == "off"
    assert environment["CGO_ENABLED"] == "0"
    assert "LD_PRELOAD" not in environment


def test_go_provider_does_not_load_target_modules(tmp_path, go_toolchain) -> None:
    (tmp_path / "go.mod").write_text(
        "not a valid Go module; must never be read by go build\n", encoding="utf-8",
    )
    (tmp_path / "main.go").write_text(
        'package sample\nimport ("io"; _ "missing.invalid/does-not-exist")\n'
        'func f(){io.ReadAll(unknown)}\n',
        encoding="utf-8",
    )
    report = scan_work_unit_hotspots(tmp_path, ["main.go"], enable_go=True)
    assert report["scan_status"] == "completed"
    assert report["candidate_count"] == 1


def test_go_file_count_and_work_unit_byte_budgets(tmp_path, monkeypatch) -> None:
    captured = []

    def scan(sources, **kwargs):
        captured.append(sources)
        return [
            {"path": path, "count": 0, "candidates": []} for path in sorted(sources)
        ]

    monkeypatch.setattr("reachable_audit.discovery.hotspots.scan_go_bytes", scan)
    monkeypatch.setattr("reachable_audit.discovery.hotspots.MAX_GO_FILES", 1)
    for name in ("a.go", "b.go"):
        (tmp_path / name).write_bytes(b"package x\n")
    report = scan_work_unit_hotspots(tmp_path, ["b.go", "a.go"], enable_go=True)
    assert report["scan_status"] == "partial"
    assert report["scanned_paths"] == ["a.go"]
    assert "file count" in report["parse_errors"][0]["error"]
    assert set(captured[-1]) == {"a.go"}
    monkeypatch.setattr("reachable_audit.discovery.hotspots.MAX_GO_FILES", 128)
    monkeypatch.setattr("reachable_audit.discovery.hotspots.MAX_GO_TOTAL_BYTES", 10)
    report = scan_work_unit_hotspots(tmp_path, ["a.go", "b.go"], enable_go=True)
    assert report["scan_status"] == "partial"
    assert "Work Unit byte" in report["parse_errors"][0]["error"]
    assert set(captured[-1]) == {"a.go"}


def test_go_hard_candidate_retention_limit_preserves_total(tmp_path, go_toolchain) -> None:
    (tmp_path / "main.go").write_text(
        'package x\nimport "io"\nfunc f(){\n'
        + "io.ReadAll(r)\n" * 205 + "}\n", encoding="utf-8",
    )
    report = scan_work_unit_hotspots(
        tmp_path, ["main.go"], enable_go=True, max_candidates=1000,
    )
    assert report["candidate_count"] == 205
    assert report["included_count"] == 200
    assert len(report["candidates"]) == 200
    assert report["truncated"] is True
    assert report["scan_status"] == "completed"


@pytest.mark.parametrize("output", [b"{}", b"[{}]", b"not json"])
def test_go_invalid_helper_responses_are_errors(tmp_path, monkeypatch, output) -> None:
    (tmp_path / "main.go").write_bytes(b"package x\n")
    monkeypatch.setattr(go_provider, "_helper", lambda *_: (tmp_path / "helper", tmp_path))
    monkeypatch.setattr(go_provider, "_run_bounded", lambda *args: output)
    report = scan_work_unit_hotspots(tmp_path, ["main.go"], enable_go=True)
    assert report["scan_status"] == "error"
    assert report["unavailable_paths"] == ["main.go"]


def test_go_helper_build_failure_cleans_private_workspace(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(go_provider, "_WORKSPACE", None)
    monkeypatch.setattr(go_provider, "_BINARY", None)
    monkeypatch.setattr(go_provider.shutil, "which", lambda _: sys.executable)

    def fail(*args):
        raise go_provider.GoProviderError("build failed")

    monkeypatch.setattr(go_provider, "_run_bounded", fail)
    with pytest.raises(go_provider.GoProviderError, match="build failed"):
        go_provider._helper()
    assert list(tmp_path.glob(".reachable-audit-go-*")) == []
