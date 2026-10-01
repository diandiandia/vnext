"""Runtime-safe Mechanism Card filtering and Category plan generation."""

from __future__ import annotations

import hashlib
import json
from pathlib import PurePath
from typing import Mapping, Sequence

from .analysis_models import CategoryAuditPlan, EvaluationPartition, MechanismCard
from .models import ModelError
from .plan_models import WorkUnit


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\x00".join(parts).encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def _validate_runtime_card(card: MechanismCard) -> None:
    if card.evaluation_partition is not EvaluationPartition.TRAINING:
        raise ModelError(
            f"held-out Mechanism Card cannot enter a runtime plan: {card.mechanism_id}"
        )
    portable_values = (
        card.mechanism_id,
        card.title,
        *card.preconditions,
        *card.dangerous_transitions,
        *card.sink_semantics,
        *card.counterevidence,
        *card.verification_recipe,
    )
    if any(PurePath(value).is_absolute() for value in portable_values):
        raise ModelError(
            f"Mechanism Card contains an absolute path: {card.mechanism_id}"
        )


def create_category_audit_plans(
    work_units: Sequence[WorkUnit],
    cards: Sequence[MechanismCard],
    *,
    budget: Mapping[str, int],
) -> tuple[CategoryAuditPlan, ...]:
    if any(value < 0 for value in budget.values()):
        raise ModelError("Category plan budget values cannot be negative")
    for card in cards:
        _validate_runtime_card(card)
    plans = []
    for work_unit in sorted(work_units, key=lambda item: item.work_unit_id):
        languages = set(work_unit.languages)
        for family in sorted(work_unit.category_families):
            applicable_cards = [
                card
                for card in cards
                if card.family == family
                and (
                    "any" in card.language_applicability
                    or bool(languages.intersection(card.language_applicability))
                )
            ]
            variants = tuple(sorted({
                transition
                for card in applicable_cards
                for transition in card.dangerous_transitions
            }))
            card_ids = tuple(sorted(card.mechanism_id for card in applicable_cards))
            seed = json.dumps({
                "work_unit_id": work_unit.work_unit_id,
                "family": family,
                "variants": variants,
                "cards": card_ids,
                "axes": work_unit.discovery_axes,
                "budget": dict(sorted(budget.items())),
            }, sort_keys=True, separators=(",", ":"))
            plans.append(CategoryAuditPlan(
                category_plan_id=_stable_id("CAP", seed),
                work_unit_id=work_unit.work_unit_id,
                family=family,
                mechanism_variants=variants,
                seed_card_ids=card_ids,
                discovery_axes=work_unit.discovery_axes,
                budget=dict(sorted(budget.items())),
            ))
    return tuple(plans)