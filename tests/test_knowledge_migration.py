import json
from pathlib import Path
import subprocess
import sys

import pytest

from reachable_audit.knowledge_catalog import KnowledgeCatalog, default_knowledge_root
from reachable_audit.models import ModelError


LANGUAGES = (
    "c", "cpp", "csharp", "go", "java", "rust", "python", "javascript",
    "kotlin", "scala", "php", "ruby", "swift", "shell",
)


def _legacy_inventory() -> dict[str, object]:
    entries = []
    generic_issues = [
        ("CWE-78", "INJECTION"), ("CWE-94", "INJECTION"),
        ("CWE-787", "MEMORY-SAFETY"), ("CWE-416", "MEMORY-SAFETY"),
        ("CWE-125", "MEMORY-SAFETY"), ("CWE-362", "RACE"),
        ("CWE-770", "RESOURCE-DOS"), ("CWE-862", "AUTHN"),
        ("CWE-22", "WEB"), ("CWE-20", "DATA-INTEGRITY"),
    ]
    for language in LANGUAGES:
        count = 11 if language == "c" else 12 if language == "go" else 10
        for index in range(count):
            javascript_issues = [
                ("CWE-78", "INJECTION"), ("CWE-94", "INJECTION"),
                ("CWE-400", "RESOURCE-DOS"), ("CWE-862", "AUTHN"),
                ("CWE-770", "RESOURCE-DOS"), ("CWE-639", "AUTHN"),
                ("CWE-327", "CRYPTO"), ("CWE-79", "WEB"),
                ("CWE-352", "WEB"), ("CWE-22", "WEB"),
            ]
            cwe, family = (
                javascript_issues[index % len(javascript_issues)]
                if language == "javascript"
                else generic_issues[index % len(generic_issues)]
            )
            entries.append({
                "id": f"SRC-{language}-{index:02d}",
                "lang": language,
                "title": (
                    "ExampleTarget project-specific sample"
                    if language == "c" and index == 10
                    else f"{language} issue pattern {index:02d}"
                ),
                "family": family,
                "cwe": [cwe],
                "pattern": f"source-controlled pattern {language}-{index}",
                "sink_hint": "sensitive operation",
                "pitfall": "check the guard and counterevidence",
                "source": {"tier": "source_seeded", "origin": "reviewed source"},
                "verify": {"status": "unverified"},
            })
    by_id = {entry["id"]: entry for entry in entries}

    def revise(language: str, index: int, record_id: str, cwe: str, family: str) -> dict[str, object]:
        entry = by_id[f"SRC-{language}-{index:02d}"]
        entry.update({"id": record_id, "cwe": [cwe], "family": family})
        return entry

    revise("go", 0, "INV-go-003", "CWE-78", "INJECTION")
    revise("go", 1, "INV-go-011", "CWE-94", "INJECTION")
    revise("go", 2, "INV-go-007", "CWE-918", "WEB")
    revise("go", 3, "INV-go-006", "CWE-862", "AUTHN")
    revise("go", 4, "INV-go-010", "CWE-639", "AUTHN")
    revise("go", 5, "INV-go-014", "CWE-697", "NUMERIC")
    revise("go", 6, "INV-go-012", "CWE-770", "RESOURCE-DOS")
    go_buffering = revise("go", 7, "INV-go-013", "CWE-770", "RESOURCE-DOS")
    go_buffering["cwe"] = ["CWE-770", "CWE-789"]
    revise("go", 8, "INV-go-015", "CWE-416", "MEMORY-SAFETY")
    revise("go", 9, "INV-go-016", "CWE-59", "DATA-INTEGRITY")
    revise("go", 10, "INV-go-017", "CWE-20", "DATA-INTEGRITY")
    revise("go", 11, "INV-go-018", "CWE-125", "MEMORY-SAFETY")
    revise("c", 0, "INV-c-003", "CWE-787", "MEMORY-SAFETY")
    revise("c", 1, "INV-c-006", "CWE-789", "RESOURCE-DOS")
    revise("c", 2, "INV-c-007", "CWE-696", "STATE")
    revise("c", 3, "INV-c-016", "CWE-306", "AUTHN")
    revise("c", 4, "INV-c-017", "CWE-770", "RESOURCE-DOS")
    revise("c", 6, "SRC-c-extra", "CWE-400", "RESOURCE-DOS")
    revise("shell", 7, "INV-shell-009", "CWE-862", "AUTHN")
    revise("shell", 8, "INV-shell-010", "CWE-863", "AUTHN")
    revise("shell", 9, "INV-shell-011", "CWE-639", "AUTHN")
    revise("shell", 2, "INV-shell-003", "CWE-77", "INJECTION")
    for index, cwe, family in (
        (0, "CWE-78", "INJECTION"), (1, "CWE-787", "MEMORY-SAFETY"),
        (2, "CWE-416", "MEMORY-SAFETY"), (3, "CWE-125", "MEMORY-SAFETY"),
        (4, "CWE-770", "RESOURCE-DOS"), (5, "CWE-362", "RACE"),
        (6, "CWE-862", "AUTHN"), (7, "CWE-22", "WEB"),
        (8, "CWE-20", "DATA-INTEGRITY"), (9, "CWE-918", "WEB"),
    ):
        revise("swift", index, f"INV-swift-{index + 1:03d}", cwe, family)
    return {"entries": entries}


def _run_migration(
    source: Path,
    output: Path,
    *,
    publish: bool,
    forbidden_tokens: tuple[str, ...],
    replace: bool = False,
) -> None:
    script = Path(__file__).resolve().parents[1] / "tools" / "migrate_legacy_knowledge.py"
    tokens = output.parent / "forbidden-residue-tokens.txt"
    tokens.write_text("\n".join(forbidden_tokens) + "\n", encoding="utf-8")
    command = [
        sys.executable, str(script), "--inventory", str(source),
        "--output", str(output), "--version", "migration-test-v1",
        "--forbidden-tokens-file", str(tokens),
    ]
    if publish:
        command.append("--publish-reviewed")
    if replace:
        command.append("--replace-existing-catalog")
    subprocess.run(command, check=True, capture_output=True, text=True)


def test_migration_requires_reviewer_supplied_residue_tokens(tmp_path: Path) -> None:
    script = Path(__file__).resolve().parents[1] / "tools" / "migrate_legacy_knowledge.py"
    result = subprocess.run(
        [
            sys.executable, str(script),
            "--inventory", str(tmp_path / "inventory.json"),
            "--output", str(tmp_path / "output"),
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "--forbidden-tokens-file" in result.stderr


def test_migration_builds_complete_reviewed_catalog_without_project_tokens(
    tmp_path: Path,
) -> None:
    source = tmp_path / "legacy.json"
    source.write_text(json.dumps(_legacy_inventory()), encoding="utf-8")
    output = tmp_path / "published"

    _run_migration(
        source, output, publish=True, forbidden_tokens=("ExampleTarget",)
    )
    catalog = KnowledgeCatalog.load(output)
    report = json.loads((output / "migration-report.json").read_text(encoding="utf-8"))
    published_runtime = json.dumps({
        "profiles": catalog.profiles,
        "cards": catalog.cards,
        "provenance": catalog.provenance,
    })

    assert len(catalog.languages) == 15
    assert sum(len(profile["entries"]) for profile in catalog.profiles.values()) == 150
    assert len(catalog.cards) == 150
    assert report["languages"]["c"]["excluded_for_project_tokens"] == ["SRC-c-10"]
    assert "ExampleTarget project-specific sample" not in published_runtime
    assert all(
        len({cwe for issue in profile["entries"] for cwe in issue["weakness_refs"]}) == 10
        for profile in catalog.profiles.values()
    )
    go_profile = catalog.profiles["go"]
    go_provenance = catalog.provenance
    go_lifecycle = next(
        issue for issue in go_profile["entries"]
        if go_provenance[issue["provenance_refs"][0]]["source_record_id"] == "INV-go-015"
    )
    assert go_lifecycle["weakness_refs"] == ["CWE-404"]
    assert go_lifecycle["family"] == "ERROR-HANDLING"
    assert all(
        go_provenance[issue["provenance_refs"][0]]["source_record_id"] != "INV-go-018"
        for issue in go_profile["entries"]
    )
    assert "INV-go-018" in report["languages"]["go"]["excluded_false_positive_lessons"]
    assert any(
        issue["weakness_refs"] == ["CWE-362"] and "goroutines" in issue["title"]
        for issue in go_profile["entries"]
    )
    go_source_ids = {
        go_provenance[issue["provenance_refs"][0]]["source_record_id"]
        for issue in go_profile["entries"]
    }
    assert {
        "INV-go-007", "INV-go-012", "INV-go-013", "INV-go-014", "INV-go-015",
        "INV-go-016", "INV-go-017",
    } <= go_source_ids
    assert any(issue["weakness_refs"] == ["CWE-918"] for issue in go_profile["entries"])
    trust_issue = next(
        issue for issue in go_profile["entries"]
        if go_provenance[issue["provenance_refs"][0]]["source_record_id"] == "INV-go-017"
    )
    assert trust_issue["title"] == "Untrusted trust material installed across a privilege boundary"
    assert "neither root execution, Linux" in " ".join(trust_issue["counterevidence"])
    c_source_ids = {
        catalog.provenance[issue["provenance_refs"][0]]["source_record_id"]
        for issue in catalog.profiles["c"]["entries"]
    }
    assert {"INV-c-003", "INV-c-006", "INV-c-007", "INV-c-016", "INV-c-017"} <= c_source_ids
    shell_profile = catalog.profiles["shell"]
    assert any("temporary path" in issue["title"] for issue in shell_profile["entries"])
    assert report["languages"]["shell"]["excluded_for_semantic_scope"]
    assert any(issue["weakness_refs"] == ["CWE-88"] for issue in shell_profile["entries"])
    assert "INV-shell-003" in report["languages"]["shell"]["excluded_for_semantic_scope"]
    swift_profile = catalog.profiles["swift"]
    swift_write = next(issue for issue in swift_profile["entries"] if issue["weakness_refs"] == ["CWE-787"])
    assert "UnsafeMutablePointer" in " ".join(swift_write["sink_cues"])
    assert all(
        card["evidence_state"] == "seeded"
        for card in catalog.cards.values()
        if card["mechanism_id"].startswith("MECH-typescript-")
    )
    node_command_card = catalog.cards["MECH-typescript-01"]
    assert "node:child_process exec/execSync command string" in node_command_card["sink_semantics"]
    assert "system/popen/exec 族调用点" not in node_command_card["sink_semantics"]
    assert node_command_card["preconditions"] != node_command_card["dangerous_transitions"]

    stale_card = output / "cards" / "obsolete-family" / "MECH-csharp-05.json"
    stale_card.parent.mkdir(parents=True)
    stale_card.write_text(json.dumps(catalog.cards["MECH-csharp-05"]), encoding="utf-8")
    _run_migration(
        source, output, publish=True, forbidden_tokens=("ExampleTarget",), replace=True
    )
    assert not stale_card.exists()
    KnowledgeCatalog.load(output)


def test_runtime_task_context_omits_legacy_template_directives() -> None:
    catalog = KnowledgeCatalog.load(default_knowledge_root())
    context = catalog.task_context(("c",), families=("MEMORY-SAFETY",))
    serialized = json.dumps(context.to_dict(), ensure_ascii=False)
    assert "parser_fuzz" not in serialized
    assert "stub 复刻" not in serialized


def test_draft_migration_is_rejected_by_runtime_catalog(tmp_path: Path) -> None:
    source = tmp_path / "legacy.json"
    source.write_text(json.dumps(_legacy_inventory()), encoding="utf-8")
    output = tmp_path / "draft"

    _run_migration(source, output, publish=False, forbidden_tokens=())

    with pytest.raises(ModelError, match="portfolio is not approved"):
        KnowledgeCatalog.load(output)