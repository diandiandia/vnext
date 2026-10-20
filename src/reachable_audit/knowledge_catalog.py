"""Validated, versioned runtime knowledge for language-aware audit tasks."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .analysis_models import EvaluationPartition, MechanismCard
from .models import ModelError


_PROFILE_FIELDS = frozenset({
    "issue_id", "rank", "title", "family", "weakness_refs",
    "mechanism_card_ids", "source_cues", "sink_cues", "language_pitfalls",
    "counterevidence", "verification_steps", "provenance_refs",
})
_PROFILE_DOCUMENT_FIELDS = frozenset({
    "schema_version", "profile_id", "language_id", "portfolio_version",
    "review_status", "entries",
})
_CARD_FIELDS = frozenset({
    "schema_version", "knowledge_version", "review_status", "mechanism_id",
    "family", "title", "preconditions", "dangerous_transitions",
    "sink_semantics", "counterevidence", "language_applicability",
    "verification_recipe", "provenance", "evaluation_partition", "evidence_state",
})
_EVIDENCE_STATES = frozenset({
    "seeded", "battle_observed", "battle_reproduced", "deprecated",
})


def default_knowledge_root() -> Path:
    return Path(__file__).resolve().parents[2] / "knowledge"


@dataclass(frozen=True)
class KnowledgeTaskContext:
    knowledge_version: str
    languages: tuple[str, ...]
    issue_entries: tuple[Mapping[str, Any], ...]
    mechanism_cards: tuple[Mapping[str, Any], ...]
    omitted_issue_ids: tuple[str, ...]
    unsupported_languages: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        limitations = []
        if self.omitted_issue_ids:
            limitations.append("issue guidance omitted due to task entry budget")
        if self.unsupported_languages:
            limitations.append("no approved language profile for one or more languages")
        return {
            "schema_version": "1.0",
            "knowledge_version": self.knowledge_version,
            "guidance": (
                "These ranked patterns are review leads, not expected findings or "
                "an exhaustive security checklist. Establish applicability from target evidence "
                "before assuming a framework, platform, privilege, API, or deployment mode. "
                "Historical evidence states describe training provenance, not this target. "
                "Test counterevidence; absent preconditions may justify NOT_APPLICABLE. "
                "Do not force a finding or discard source-evidenced mechanisms outside these entries."
            ),
            "languages": list(self.languages),
            "issue_entries": [dict(item) for item in self.issue_entries],
            "mechanism_cards": [dict(item) for item in self.mechanism_cards],
            "omitted_issue_ids": list(self.omitted_issue_ids),
            "unsupported_languages": list(self.unsupported_languages),
            "limitations": limitations,
        }


class KnowledgeCatalog:
    """Read-only catalog; held-out and deprecated knowledge never enters task context."""

    def __init__(
        self,
        *,
        version: str,
        languages: Sequence[str],
        profiles: Mapping[str, Mapping[str, Any]],
        cards: Mapping[str, Mapping[str, Any]],
        provenance: Mapping[str, Mapping[str, Any]],
    ) -> None:
        self.version = version
        self.languages = tuple(languages)
        self.profiles = dict(profiles)
        self.cards = dict(cards)
        self.provenance = dict(provenance)

    @classmethod
    def load(cls, root: str | Path) -> "KnowledgeCatalog":
        directory = Path(root)
        portfolio = _read_json(directory / "portfolio.json")
        if set(portfolio) != {
            "schema_version", "portfolio_version", "approval_state", "languages",
        }:
            raise ModelError("knowledge portfolio has unknown or missing fields")
        if portfolio.get("schema_version") != "1.0":
            raise ModelError("unsupported knowledge portfolio schema_version")
        if portfolio.get("approval_state") != "approved":
            raise ModelError("runtime knowledge portfolio is not approved")
        version = str(portfolio.get("portfolio_version", ""))
        languages = tuple(str(item) for item in portfolio.get("languages", []))
        if not version or len(languages) != 15 or len(set(languages)) != 15:
            raise ModelError("knowledge portfolio requires a version and 15 unique languages")

        profile_root = directory / "profiles"
        profiles: dict[str, Mapping[str, Any]] = {}
        for language in languages:
            profile = _read_json(profile_root / f"{language}.json")
            _validate_profile(profile, language, version)
            profiles[language] = profile
        unexpected_profiles = {
            path.stem for path in profile_root.glob("*.json")
        } - set(languages)
        if unexpected_profiles:
            raise ModelError(
                f"profiles outside approved portfolio: {sorted(unexpected_profiles)}"
            )

        provenance_value = _read_json(directory / "provenance.json")
        if set(provenance_value) != {"schema_version", "records"}:
            raise ModelError("provenance manifest has unknown or missing fields")
        if provenance_value.get("schema_version") != "1.0":
            raise ModelError("unsupported provenance schema_version")
        provenance = provenance_value.get("records")
        if not isinstance(provenance, dict):
            raise ModelError("provenance records must be an object")
        if any(
            not isinstance(item, dict) or item.get("review_status") != "approved"
            or item.get("evidence_state") not in _EVIDENCE_STATES - {"deprecated"}
            for item in provenance.values()
        ):
            raise ModelError("runtime provenance contains an unreviewed or invalid record")
        for provenance_id, item in provenance.items():
            digest_basis = item.get("source_digest_basis")
            if not isinstance(digest_basis, dict):
                raise ModelError(f"provenance digest basis is missing: {provenance_id}")
            encoded_basis = json.dumps(
                digest_basis, sort_keys=True, separators=(",", ":")
            ).encode()
            expected_digest = "sha256:" + hashlib.sha256(encoded_basis).hexdigest()
            if item.get("source_digest") != expected_digest:
                raise ModelError(f"provenance source digest mismatch: {provenance_id}")

        cards_root = directory / "cards"
        cards: dict[str, Mapping[str, Any]] = {}
        for path in sorted(cards_root.rglob("*.json")):
            raw = _read_json(path)
            if set(raw) != _CARD_FIELDS:
                raise ModelError(f"Mechanism Card has unknown or missing fields: {path.name}")
            card = MechanismCard.from_dict(raw)
            if card.evaluation_partition is not EvaluationPartition.TRAINING:
                raise ModelError(f"runtime catalog cannot contain held-out card: {card.mechanism_id}")
            if raw.get("evidence_state") not in _EVIDENCE_STATES - {"deprecated"}:
                raise ModelError(f"invalid runtime card evidence state: {card.mechanism_id}")
            if raw.get("schema_version") != "1.0" or raw.get("knowledge_version") != version:
                raise ModelError(f"card release mismatch: {card.mechanism_id}")
            if raw.get("review_status") != "approved":
                raise ModelError(f"runtime card is not approved: {card.mechanism_id}")
            if card.mechanism_id in cards:
                raise ModelError(f"duplicate mechanism card: {card.mechanism_id}")
            for provenance_id in card.provenance:
                if provenance_id not in provenance:
                    raise ModelError(
                        f"unknown card provenance {provenance_id}: {card.mechanism_id}"
                    )
            cards[card.mechanism_id] = raw

        if not cards:
            raise ModelError("runtime knowledge catalog contains no Mechanism Cards")
        _validate_profile_references(profiles, cards, provenance)
        return cls(
            version=version,
            languages=languages,
            profiles=profiles,
            cards=cards,
            provenance=provenance,
        )

    def task_context(
        self,
        languages: Sequence[str],
        *,
        families: Sequence[str] = (),
        max_entries: int = 20,
    ) -> KnowledgeTaskContext:
        if max_entries < 0:
            raise ModelError("knowledge task entry budget cannot be negative")
        requested = tuple(sorted(set(str(language) for language in languages)))
        family_filter = {str(family).upper() for family in families}
        unsupported = tuple(language for language in requested if language not in self.profiles)
        per_language: dict[str, list[Mapping[str, Any]]] = {}
        for language in requested:
            profile = self.profiles.get(language)
            if profile is None:
                continue
            entries = [
                item for item in profile["entries"]
                if not family_filter or str(item["family"]).upper() in family_filter
            ]
            per_language[language] = sorted(entries, key=lambda item: int(item["rank"]))

        selected: list[Mapping[str, Any]] = []
        remaining = {language: list(items) for language, items in per_language.items()}
        while len(selected) < max_entries and any(remaining.values()):
            for language in requested:
                if len(selected) >= max_entries:
                    break
                if remaining.get(language):
                    selected.append({
                        **remaining[language].pop(0),
                        "language_id": language,
                    })
        omitted = tuple(sorted(
            str(item["issue_id"])
            for items in remaining.values()
            for item in items
        ))
        card_ids = {
            str(card_id)
            for item in selected
            for card_id in item["mechanism_card_ids"]
        }
        cards = tuple(
            self.cards[card_id]
            for card_id in sorted(card_ids)
        )
        return KnowledgeTaskContext(
            knowledge_version=self.version,
            languages=requested,
            issue_entries=tuple(selected),
            mechanism_cards=cards,
            omitted_issue_ids=omitted,
            unsupported_languages=unsupported,
        )


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ModelError(f"required knowledge file is missing: {path.name}") from error
    except (OSError, json.JSONDecodeError) as error:
        raise ModelError(f"cannot read knowledge file {path.name}: {error}") from error
    if not isinstance(value, dict):
        raise ModelError(f"knowledge file must contain a JSON object: {path.name}")
    return value


def _validate_profile(profile: Mapping[str, Any], language: str, version: str) -> None:
    if set(profile) != _PROFILE_DOCUMENT_FIELDS:
        raise ModelError(f"profile has unknown or missing document fields: {language}")
    if profile.get("schema_version") != "1.0":
        raise ModelError(f"unsupported profile schema_version: {language}")
    if profile.get("review_status") != "approved":
        raise ModelError(f"runtime profile is not approved: {language}")
    if profile.get("language_id") != language:
        raise ModelError(f"profile language mismatch: {language}")
    if profile.get("portfolio_version") != version:
        raise ModelError(f"profile portfolio version mismatch: {language}")
    entries = profile.get("entries")
    if not isinstance(entries, list) or len(entries) != 10:
        raise ModelError(f"language profile must contain exactly 10 entries: {language}")
    ranks = [item.get("rank") for item in entries if isinstance(item, dict)]
    issue_ids = [item.get("issue_id") for item in entries if isinstance(item, dict)]
    if ranks != list(range(1, 11)):
        raise ModelError(f"profile ranks must be ordered integers 1-10: {language}")
    if len(issue_ids) != 10 or len(set(issue_ids)) != 10:
        raise ModelError(f"profile issue IDs must be unique: {language}")
    for entry in entries:
        if (
            not isinstance(entry, dict)
            or _PROFILE_FIELDS - set(entry)
            or set(entry) - _PROFILE_FIELDS
        ):
            raise ModelError(f"profile entry has unknown or missing fields: {language}")
        if any(not entry[field] for field in (
            "issue_id", "title", "family", "mechanism_card_ids", "verification_steps",
            "provenance_refs",
        )):
            raise ModelError(f"profile entry has empty required values: {language}")
        if not isinstance(entry["rank"], int) or isinstance(entry["rank"], bool):
            raise ModelError(f"profile rank must be an integer: {language}")
        for field in (
            "weakness_refs", "mechanism_card_ids", "source_cues", "sink_cues",
            "language_pitfalls", "counterevidence", "verification_steps", "provenance_refs",
        ):
            if not isinstance(entry[field], list):
                raise ModelError(f"profile field {field} must be an array: {language}")


def _validate_profile_references(
    profiles: Mapping[str, Mapping[str, Any]],
    cards: Mapping[str, Mapping[str, Any]],
    provenance: Mapping[str, Mapping[str, Any]],
) -> None:
    for language, profile in profiles.items():
        for entry in profile["entries"]:
            for provenance_id in entry["provenance_refs"]:
                if provenance_id not in provenance:
                    raise ModelError(
                        f"unknown profile provenance {provenance_id}: {entry['issue_id']}"
                    )
            for card_id in entry["mechanism_card_ids"]:
                card = cards.get(str(card_id))
                if card is None:
                    raise ModelError(
                        f"unknown Mechanism Card {card_id}: {entry['issue_id']}"
                    )
                applicability = set(card["language_applicability"])
                if language not in applicability and "any" not in applicability:
                    raise ModelError(
                        f"card {card_id} is not applicable to profile language {language}"
                    )