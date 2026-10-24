from pathlib import Path

from reachable_audit.compatibility import scan_runtime_compatibility


def test_packaged_helper_sources_are_included_in_residue_scan(tmp_path: Path) -> None:
    source = tmp_path / "src" / "provider"
    source.mkdir(parents=True)
    (source / "Parser.java").write_text('// private path "/srv/fixture/private"\n')
    (source / "parser.go").write_text("// synthetic-target-token\n")
    report = scan_runtime_compatibility(tmp_path, ["synthetic-target-token"])
    assert report["passed"] is False
    assert report["scanned_helper_files"] == 2
    assert {item["value"] for item in report["findings"]} == {
        "private_host_path", "synthetic-target-token",
    }
