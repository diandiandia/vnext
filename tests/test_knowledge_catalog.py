import json
import hashlib
from pathlib import Path

import pytest

from reachable_audit.knowledge_catalog import KnowledgeCatalog, default_knowledge_root
from reachable_audit.models import ModelError


LANGUAGES = tuple(f"lang-{index:02d}" for index in range(15))


def _write_catalog(root: Path) -> None:
    (root / "profiles").mkdir(parents=True)
    (root / "cards").mkdir()
    languages = list(LANGUAGES)
    (root / "portfolio.json").write_text(json.dumps({
        "schema_version": "1.0",
        "portfolio_version": "test-v1",
        "approval_state": "approved",
        "languages": languages,
    }), encoding="utf-8")
    records = {}
    for language in languages:
        entries = []
        for rank in range(1, 11):
            card_id = f"MECH-{language}-{rank}"
            provenance_id = f"PROV-{language}-{rank}"
            family = "STATE" if rank % 2 else "INJECTION"
            entries.append({
                "issue_id": f"ISSUE-{language}-{rank}",
                "rank": rank,
                "title": f"Issue {rank}",
                "family": family,
                "weakness_refs": ["CWE-362"],
                "mechanism_card_ids": [card_id],
                "source_cues": ["untrusted input"],
                "sink_cues": ["sensitive operation"],
                "language_pitfalls": ["language-specific semantics"],
                "counterevidence": ["guard precedes operation"],
                "verification_steps": ["trace the condition"],
                "provenance_refs": [provenance_id],
            })
            digest_basis = {
                "id": provenance_id,
                "lang": language,
                "title": f"Issue {rank}",
                "family": family,
                "cwe": ["CWE-362"],
            }
            digest = hashlib.sha256(json.dumps(
                digest_basis, sort_keys=True, separators=(",", ":")
            ).encode()).hexdigest()
            records[provenance_id] = {
                "source_type": "test_fixture",
                "source_record_id": provenance_id,
                "source_digest_basis": digest_basis,
                "source_digest": f"sha256:{digest}",
                "evidence_state": "seeded",
                "review_status": "approved",
            }
            (root / "cards" / f"{card_id}.json").write_text(json.dumps({
                "schema_version": "1.0",
                "knowledge_version": "test-v1",
                "review_status": "approved",
                "mechanism_id": card_id,
                "family": family,
                "title": f"Mechanism {rank}",
                "preconditions": ["condition"],
                "dangerous_transitions": ["transition"],
                "sink_semantics": ["effect"],
                "counterevidence": ["guard"],
                "language_applicability": [language],
                "verification_recipe": ["check"],
                "provenance": [provenance_id],
                "evaluation_partition": "training",
                "evidence_state": "seeded",
            }), encoding="utf-8")
        (root / "profiles" / f"{language}.json").write_text(json.dumps({
            "schema_version": "1.0",
            "profile_id": f"PROFILE-{language}",
            "language_id": language,
            "portfolio_version": "test-v1",
            "review_status": "approved",
            "entries": entries,
        }), encoding="utf-8")
    (root / "provenance.json").write_text(json.dumps({
        "schema_version": "1.0",
        "records": records,
    }), encoding="utf-8")


def test_catalog_requires_fifteen_profiles_with_ten_issues_each(tmp_path: Path) -> None:
    _write_catalog(tmp_path)

    catalog = KnowledgeCatalog.load(tmp_path)

    assert catalog.languages == LANGUAGES
    assert len(catalog.profiles) == 15
    assert all(len(profile["entries"]) == 10 for profile in catalog.profiles.values())


def test_task_context_balances_languages_and_resolves_cards(tmp_path: Path) -> None:
    _write_catalog(tmp_path)
    catalog = KnowledgeCatalog.load(tmp_path)

    context = catalog.task_context(
        ["lang-00", "lang-01"], families=["STATE"], max_entries=4
    ).to_dict()

    assert [entry["rank"] for entry in context["issue_entries"]] == [1, 1, 3, 3]
    assert {entry["language_id"] for entry in context["issue_entries"]} == {
        "lang-00", "lang-01",
    }
    assert len(context["mechanism_cards"]) == 4
    assert context["omitted_issue_ids"] == [
        "ISSUE-lang-00-5", "ISSUE-lang-00-7", "ISSUE-lang-00-9",
        "ISSUE-lang-01-5", "ISSUE-lang-01-7", "ISSUE-lang-01-9",
    ]
    assert context["unsupported_languages"] == []


def test_shipped_catalog_preserves_portfolio_without_deployment_assumptions() -> None:
    catalog = KnowledgeCatalog.load(default_knowledge_root())
    context = catalog.task_context(["go"], families=["DATA-INTEGRITY"]).to_dict()
    card = next(
        card for card in context["mechanism_cards"]
        if card["mechanism_id"] == "MECH-go-09"
    )

    assert len(catalog.languages) == 15
    assert sum(len(profile["entries"]) for profile in catalog.profiles.values()) == 150
    assert "neither root execution, Linux" in " ".join(card["counterevidence"])
    guidance = json.dumps(context["issue_entries"]) + json.dumps(card)
    assert "root.crt" not in guidance
    assert "truststore.Install" not in guidance
    assert "target evidence" in context["guidance"]
    assert "not expected findings" in context["guidance"]
    assert "provenance" not in context


def test_java_tasks_receive_java_top_ten_not_all_fifteen_languages() -> None:
    catalog = KnowledgeCatalog.load(default_knowledge_root())
    context = catalog.task_context(["java"]).to_dict()

    assert context["languages"] == ["java"]
    assert len(context["issue_entries"]) == 10
    assert {entry["language_id"] for entry in context["issue_entries"]} == {"java"}
    assert context["omitted_issue_ids"] == []
    assert all(
        "java" in card["language_applicability"] or "any" in card["language_applicability"]
        for card in context["mechanism_cards"]
    )


def test_catalog_rejects_a_missing_language_profile(tmp_path: Path) -> None:
    _write_catalog(tmp_path)
    (tmp_path / "profiles" / f"{LANGUAGES[-1]}.json").unlink()

    with pytest.raises(ModelError, match="required knowledge file is missing"):
        KnowledgeCatalog.load(tmp_path)


def test_catalog_rejects_held_out_runtime_cards(tmp_path: Path) -> None:
    _write_catalog(tmp_path)
    card_path = tmp_path / "cards" / f"MECH-{LANGUAGES[0]}-1.json"
    card = json.loads(card_path.read_text(encoding="utf-8"))
    card["evaluation_partition"] = "held_out"
    card_path.write_text(json.dumps(card), encoding="utf-8")

    with pytest.raises(ModelError, match="held-out card"):
        KnowledgeCatalog.load(tmp_path)


def test_catalog_rejects_tampered_provenance_digest(tmp_path: Path) -> None:
    _write_catalog(tmp_path)
    provenance_path = tmp_path / "provenance.json"
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    first_record = next(iter(provenance["records"].values()))
    first_record["source_digest"] = "sha256:" + "0" * 64
    provenance_path.write_text(json.dumps(provenance), encoding="utf-8")

    with pytest.raises(ModelError, match="source digest mismatch"):
        KnowledgeCatalog.load(tmp_path)