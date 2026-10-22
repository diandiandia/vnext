from pathlib import Path

import hashlib
import pytest

from reachable_audit.discovery.hotspots import scan_work_unit_hotspots
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
    assert len(report["parse_errors"]) == 1
    assert report["candidate_count"] == 2
    assert report["included_count"] == 1
    assert report["truncated"] is True
    assert report["limitations"]


def test_python_hotspot_provider_reports_empty_language_coverage(tmp_path: Path) -> None:
    report = scan_work_unit_hotspots(tmp_path, ["Main.java"])

    assert report["provider_status"] == "provider_unavailable"
    assert report["scanned_paths"] == []
    assert report["unsupported_paths"] == ["Main.java"]
    assert report["candidate_count"] == 0


def test_unimplemented_language_coverage_is_explicit(tmp_path: Path) -> None:
    paths = ["Main.java", "main.go", "main.c", "main.cpp"]

    report = scan_work_unit_hotspots(tmp_path, paths)

    assert report["provider_status"] == "provider_unavailable"
    assert report["scanned_paths"] == []
    assert report["unsupported_paths"] == sorted(paths)
    assert report["candidate_count"] == 0
    assert report["included_count"] == 0


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
