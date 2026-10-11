"""Canonical models for the R0-R3 analysis slice."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping

from .models import ModelError


class HypothesisStatus(StrEnum):
    NEW = "NEW"
    SCREENED = "SCREENED"
    VERIFYING = "VERIFYING"
    WAITING_HANDOFF = "WAITING_HANDOFF"
    TERMINAL = "TERMINAL"


class VerdictKind(StrEnum):
    REACHABLE = "REACHABLE"
    UNREACHABLE = "UNREACHABLE"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class EvidenceGrade(StrEnum):
    STATIC_ONLY = "static_only"
    EDGE_PROVEN = "edge_proven"
    EMPIRICALLY_CONFIRMED = "empirically_confirmed"


class HandoffOutcome(StrEnum):
    EDGE_PROVEN = "EDGE_PROVEN"
    BLOCKED = "BLOCKED"
    NOT_SECURITY_BOUNDARY = "NOT_SECURITY_BOUNDARY"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    CANCELLED = "CANCELLED"


class BoundaryDisposition(StrEnum):
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    UNRESOLVED = "unresolved"


class DiscoveryAxis(StrEnum):
    SURFACE = "surface"
    MECHANISM = "mechanism"
    STATE = "state"
    FIX_VARIANT = "fix_variant"
    BOUNDARY = "boundary"
    DIFFERENTIAL = "differential"


class AttackAngle(StrEnum):
    CALL_CHAIN = "call_chain"
    PRINCIPAL = "principal"
    CONFIGURATION = "configuration"
    DEPLOYMENT = "deployment"
    IMPACT = "impact"


class AdjudicationActor(StrEnum):
    AUTO = "auto"
    HUMAN = "human"


class RevivalOutcome(StrEnum):
    UPHOLD = "UPHOLD"
    REVIVE_TO_NEEDS_REVIEW = "REVIVE_TO_NEEDS_REVIEW"
    REVIVE_TO_REACHABLE = "REVIVE_TO_REACHABLE"


class EvaluationPartition(StrEnum):
    TRAINING = "training"
    HELD_OUT = "held_out"


class Applicability(StrEnum):
    APPLICABLE = "APPLICABLE"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    DEFERRED = "DEFERRED"


class CategoryRunStatus(StrEnum):
    COMPLETE = "COMPLETE"
    DEFERRED = "DEFERRED"


class ExperimentFidelity(StrEnum):
    REAL_TARGET = "real_target"
    EQUIVALENT = "equivalent"
    MECHANISM = "mechanism"


class ExperimentResult(StrEnum):
    CONFIRMED = "confirmed"
    REFUTED = "refuted"
    INCONCLUSIVE = "inconclusive"


class R5Disposition(StrEnum):
    STATIC_VERDICT_RETAINED = "STATIC_VERDICT_RETAINED"
    EMPIRICALLY_CONFIRMED = "EMPIRICALLY_CONFIRMED"
    REFUTED = "REFUTED"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class SkillIssueKind(StrEnum):
    ERROR = "ERROR"
    DEFECT = "DEFECT"


class SkillIssueStatus(StrEnum):
    REGRESSION_PENDING = "REGRESSION_PENDING"
    RESOLVED = "RESOLVED"


class ScopeDispositionKind(StrEnum):
    EXCLUDED = "EXCLUDED"
    DEFERRED = "DEFERRED"


class FindingSeverity(StrEnum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class FindingStatus(StrEnum):
    CONFIRMED = "CONFIRMED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    SUPERSEDED = "SUPERSEDED"


@dataclass(frozen=True)
class Surface:
    surface_id: str
    work_unit_id: str
    component_id: str
    kind: str
    entry_path: str
    entry_symbol: str | None
    principal: str
    evidence_refs: tuple[str, ...]

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Surface":
        surface = cls(
            surface_id=str(value["surface_id"]),
            work_unit_id=str(value["work_unit_id"]),
            component_id=str(value["component_id"]),
            kind=str(value["kind"]),
            entry_path=str(value["entry_path"]),
            entry_symbol=(
                str(value["entry_symbol"])
                if value.get("entry_symbol") is not None
                else None
            ),
            principal=str(value["principal"]),
            evidence_refs=tuple(str(item) for item in value["evidence_refs"]),
        )
        if not surface.surface_id or not surface.kind or not surface.principal:
            raise ModelError("surface identity, kind, and principal are required")
        if not surface.evidence_refs:
            raise ModelError(f"surface requires evidence refs: {surface.surface_id}")
        return surface


@dataclass(frozen=True)
class BoundaryReview:
    edge_id: str
    work_unit_id: str
    disposition: BoundaryDisposition
    evidence_refs: tuple[str, ...]
    rationale: str

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "BoundaryReview":
        if not isinstance(value, Mapping):
            raise ModelError("boundary review must be an object")
        required = {"edge_id", "work_unit_id", "disposition", "rationale"}
        missing = required - set(value)
        if missing:
            raise ModelError(f"boundary review is missing fields: {sorted(missing)}")
        evidence_refs = value.get("evidence_refs", [])
        rationale = value.get("rationale")
        if (
            not isinstance(evidence_refs, list)
            or any(not isinstance(ref, str) or not ref.strip() for ref in evidence_refs)
            or not isinstance(rationale, str)
            or not rationale.strip()
        ):
            raise ModelError("boundary review requires evidence references and rationale")
        review = cls(
            edge_id=str(value["edge_id"]),
            work_unit_id=str(value["work_unit_id"]),
            disposition=BoundaryDisposition(str(value["disposition"])),
            evidence_refs=tuple(str(item) for item in value.get("evidence_refs", [])),
            rationale=str(value.get("rationale", "")),
        )
        if not review.edge_id or not review.work_unit_id:
            raise ModelError("boundary review requires edge and Work Unit IDs")
        if not review.evidence_refs or not review.rationale:
            raise ModelError("boundary review requires evidence references and rationale")
        return review


@dataclass(frozen=True)
class Mechanism:
    family: str
    variant: str
    freeform: str | None = None

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Mechanism":
        if not isinstance(value, Mapping):
            raise ModelError("mechanism must be an object")
        missing = {"family", "variant"} - set(value)
        if missing:
            raise ModelError(
                "mechanism requires family and variant fields; "
                f"missing {sorted(missing)}"
            )
        if any(
            not isinstance(value[field_name], str) or not value[field_name].strip()
            for field_name in ("family", "variant")
        ):
            raise ModelError("mechanism family and variant must be non-empty strings")
        mechanism = cls(
            family=str(value["family"]).upper(),
            variant=str(value["variant"]),
            freeform=str(value["freeform"]) if value.get("freeform") else None,
        )
        if not mechanism.family or not mechanism.variant:
            raise ModelError("mechanism family and variant are required")
        return mechanism


@dataclass(frozen=True)
class Hypothesis:
    hypothesis_id: str
    work_unit_id: str
    origin_axis: str
    seed_refs: tuple[str, ...]
    surface_ids: tuple[str, ...]
    mechanism: Mechanism
    claim: str
    status: HypothesisStatus

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Hypothesis":
        if not isinstance(value, Mapping):
            raise ModelError("hypothesis must be an object")
        required = {
            "hypothesis_id", "work_unit_id", "origin_axis", "seed_refs",
            "surface_ids", "mechanism", "claim",
        }
        missing = required - set(value)
        if missing:
            raise ModelError(f"hypothesis is missing fields: {sorted(missing)}")
        if not isinstance(value["mechanism"], Mapping):
            raise ModelError("hypothesis mechanism must be an object")
        for field_name in ("seed_refs", "surface_ids"):
            if not isinstance(value[field_name], list):
                raise ModelError(f"hypothesis {field_name} must be an array")
        hypothesis = cls(
            hypothesis_id=str(value["hypothesis_id"]),
            work_unit_id=str(value["work_unit_id"]),
            origin_axis=str(value["origin_axis"]),
            seed_refs=tuple(str(item) for item in value["seed_refs"]),
            surface_ids=tuple(str(item) for item in value["surface_ids"]),
            mechanism=Mechanism.from_dict(value["mechanism"]),
            claim=str(value["claim"]),
            status=HypothesisStatus(str(value.get("status", "NEW"))),
        )
        if not hypothesis.hypothesis_id or not hypothesis.claim:
            raise ModelError("hypothesis identity and claim are required")
        try:
            DiscoveryAxis(hypothesis.origin_axis)
        except ValueError as error:
            raise ModelError(f"unknown discovery axis: {hypothesis.origin_axis}") from error
        if not hypothesis.seed_refs:
            raise ModelError(f"hypothesis requires seed refs: {hypothesis.hypothesis_id}")
        return hypothesis


@dataclass(frozen=True)
class VerdictSubmission:
    hypothesis_id: str
    verdict: VerdictKind
    evidence_grade: EvidenceGrade
    principal: str
    preconditions: tuple[str, ...]
    call_chain: tuple[str, ...]
    edge_evidence_ids: tuple[str, ...]
    blocking_evidence_ids: tuple[str, ...]
    experiment_ids: tuple[str, ...]
    rationale: str

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "VerdictSubmission":
        submission = cls(
            hypothesis_id=str(value["hypothesis_id"]),
            verdict=VerdictKind(str(value["verdict"])),
            evidence_grade=EvidenceGrade(str(value["evidence_grade"])),
            principal=str(value["principal"]),
            preconditions=tuple(str(item) for item in value.get("preconditions", [])),
            call_chain=tuple(str(item) for item in value.get("call_chain", [])),
            edge_evidence_ids=tuple(
                str(item) for item in value.get("edge_evidence_ids", [])
            ),
            blocking_evidence_ids=tuple(
                str(item) for item in value.get("blocking_evidence_ids", [])
            ),
            experiment_ids=tuple(str(item) for item in value.get("experiment_ids", [])),
            rationale=str(value["rationale"]),
        )
        if not submission.principal or not submission.rationale:
            raise ModelError("verdict principal and rationale are required")
        if submission.evidence_grade is EvidenceGrade.EMPIRICALLY_CONFIRMED:
            raise ModelError("empirically_confirmed requires the Phase 4 R5 workflow")
        if submission.verdict is VerdictKind.REACHABLE:
            if not submission.call_chain or not submission.edge_evidence_ids:
                raise ModelError("REACHABLE requires call-chain and edge evidence")
        if (
            submission.verdict is VerdictKind.UNREACHABLE
            and not submission.blocking_evidence_ids
        ):
            raise ModelError("UNREACHABLE requires blocking evidence")
        return submission


@dataclass(frozen=True)
class CanonicalVerdict:
    hypothesis_id: str
    verdict: VerdictKind
    evidence_grade: EvidenceGrade
    principal: str
    preconditions: tuple[str, ...]
    call_chain: tuple[str, ...]
    edge_evidence_ids: tuple[str, ...]
    blocking_evidence_ids: tuple[str, ...]
    experiment_ids: tuple[str, ...]
    refutation_ids: tuple[str, ...]
    rationale: str
    adjudication_event_id: str


@dataclass(frozen=True)
class HandoffResolution:
    handoff_id: str
    owner_batch_id: str
    outcome: HandoffOutcome
    chain_suffix: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    rationale: str
    adjudication_event_id: str | None = None

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "HandoffResolution":
        resolution = cls(
            handoff_id=str(value["handoff_id"]),
            owner_batch_id=str(value["owner_batch_id"]),
            outcome=HandoffOutcome(str(value["outcome"])),
            chain_suffix=tuple(str(item) for item in value.get("chain_suffix", [])),
            evidence_refs=tuple(str(item) for item in value.get("evidence_refs", [])),
            rationale=str(value["rationale"]),
            adjudication_event_id=(
                str(value["adjudication_event_id"])
                if value.get("adjudication_event_id") is not None
                else None
            ),
        )
        if not resolution.rationale or not resolution.evidence_refs:
            raise ModelError("Handoff resolution requires rationale and evidence refs")
        if resolution.outcome is HandoffOutcome.EDGE_PROVEN and not resolution.chain_suffix:
            raise ModelError("EDGE_PROVEN Handoff requires a chain suffix")
        if (
            resolution.outcome is HandoffOutcome.CANCELLED
            and not resolution.adjudication_event_id
        ):
            raise ModelError("CANCELLED Handoff requires an adjudication event")
        return resolution


@dataclass(frozen=True)
class Refutation:
    refutation_id: str
    hypothesis_id: str
    refuter_id: str
    verdict: VerdictKind
    attack_angle: AttackAngle
    evidence_refs: tuple[str, ...]
    rationale: str

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Refutation":
        refutation = cls(
            refutation_id=str(value["refutation_id"]),
            hypothesis_id=str(value["hypothesis_id"]),
            refuter_id=str(value["refuter_id"]),
            verdict=VerdictKind(str(value["verdict"])),
            attack_angle=AttackAngle(str(value["attack_angle"])),
            evidence_refs=tuple(str(item) for item in value.get("evidence_refs", [])),
            rationale=str(value["rationale"]),
        )
        if not refutation.refutation_id or not refutation.refuter_id:
            raise ModelError("refutation and refuter IDs are required")
        if not refutation.evidence_refs or not refutation.rationale:
            raise ModelError("refutation requires evidence refs and rationale")
        return refutation


@dataclass(frozen=True)
class SourceVerification:
    claim: str
    evidence_ref: str
    source_anchor: str

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SourceVerification":
        verification = cls(
            claim=str(value["claim"]),
            evidence_ref=str(value["evidence_ref"]),
            source_anchor=str(value["source_anchor"]),
        )
        if not all((verification.claim, verification.evidence_ref, verification.source_anchor)):
            raise ModelError("source verification fields are required")
        if ":" not in verification.source_anchor:
            raise ModelError("source verification anchor must include a line reference")
        return verification


@dataclass(frozen=True)
class Adjudication:
    adjudication_id: str
    hypothesis_id: str
    refutation_ids: tuple[str, ...]
    final_verdict: VerdictKind
    actor: AdjudicationActor
    source_verifications: tuple[SourceVerification, ...]
    rationale: str

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Adjudication":
        adjudication = cls(
            adjudication_id=str(value["adjudication_id"]),
            hypothesis_id=str(value["hypothesis_id"]),
            refutation_ids=tuple(str(item) for item in value["refutation_ids"]),
            final_verdict=VerdictKind(str(value["final_verdict"])),
            actor=AdjudicationActor(str(value["actor"])),
            source_verifications=tuple(
                SourceVerification.from_dict(item)
                for item in value.get("source_verifications", [])
            ),
            rationale=str(value["rationale"]),
        )
        if not adjudication.adjudication_id or not adjudication.rationale:
            raise ModelError("adjudication identity and rationale are required")
        return adjudication


@dataclass(frozen=True)
class RevivalReview:
    revival_id: str
    hypothesis_id: str
    reviewer_id: str
    outcome: RevivalOutcome
    evidence_refs: tuple[str, ...]
    rationale: str

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RevivalReview":
        review = cls(
            revival_id=str(value["revival_id"]),
            hypothesis_id=str(value["hypothesis_id"]),
            reviewer_id=str(value["reviewer_id"]),
            outcome=RevivalOutcome(str(value["outcome"])),
            evidence_refs=tuple(str(item) for item in value.get("evidence_refs", [])),
            rationale=str(value["rationale"]),
        )
        if not review.revival_id or not review.reviewer_id:
            raise ModelError("revival and reviewer IDs are required")
        if not review.evidence_refs or not review.rationale:
            raise ModelError("revival review requires evidence refs and rationale")
        return review


@dataclass(frozen=True)
class MechanismCard:
    mechanism_id: str
    family: str
    title: str
    preconditions: tuple[str, ...]
    dangerous_transitions: tuple[str, ...]
    sink_semantics: tuple[str, ...]
    counterevidence: tuple[str, ...]
    language_applicability: tuple[str, ...]
    verification_recipe: tuple[str, ...]
    provenance: tuple[str, ...]
    evaluation_partition: EvaluationPartition

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "MechanismCard":
        card = cls(
            mechanism_id=str(value["mechanism_id"]),
            family=str(value["family"]).upper(),
            title=str(value["title"]),
            preconditions=tuple(str(item) for item in value["preconditions"]),
            dangerous_transitions=tuple(
                str(item) for item in value["dangerous_transitions"]
            ),
            sink_semantics=tuple(str(item) for item in value["sink_semantics"]),
            counterevidence=tuple(str(item) for item in value["counterevidence"]),
            language_applicability=tuple(
                str(item) for item in value["language_applicability"]
            ),
            verification_recipe=tuple(
                str(item) for item in value["verification_recipe"]
            ),
            provenance=tuple(str(item) for item in value["provenance"]),
            evaluation_partition=EvaluationPartition(str(value["evaluation_partition"])),
        )
        required_sequences = (
            card.preconditions,
            card.dangerous_transitions,
            card.sink_semantics,
            card.counterevidence,
            card.language_applicability,
            card.verification_recipe,
            card.provenance,
        )
        if not card.mechanism_id or not card.family or not card.title:
            raise ModelError("Mechanism Card identity, family, and title are required")
        if any(not values for values in required_sequences):
            raise ModelError(f"Mechanism Card has an empty required field: {card.mechanism_id}")
        return card


@dataclass(frozen=True)
class CategoryAuditPlan:
    category_plan_id: str
    work_unit_id: str
    family: str
    mechanism_variants: tuple[str, ...]
    seed_card_ids: tuple[str, ...]
    discovery_axes: tuple[str, ...]
    budget: Mapping[str, int]


@dataclass(frozen=True)
class AxisRun:
    axis: DiscoveryAxis
    applicability: Applicability
    evidence_refs: tuple[str, ...]
    rationale: str
    work_unit_id: str | None = None

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AxisRun":
        run = cls(
            axis=DiscoveryAxis(str(value["axis"])),
            applicability=Applicability(str(value["applicability"])),
            evidence_refs=tuple(str(item) for item in value.get("evidence_refs", [])),
            rationale=str(value["rationale"]),
            work_unit_id=(
                str(value["work_unit_id"])
                if value.get("work_unit_id") is not None else None
            ),
        )
        if not run.evidence_refs or not run.rationale:
            raise ModelError("axis run requires evidence refs and rationale")
        return run


@dataclass(frozen=True)
class CategoryRun:
    category_run_id: str
    category_plan_id: str
    work_unit_id: str
    family: str
    mechanism_variants_examined: tuple[str, ...]
    axis_runs: tuple[AxisRun, ...]
    applicability: Applicability
    status: CategoryRunStatus
    evidence_refs: tuple[str, ...]
    rationale: str
    hypothesis_ids: tuple[str, ...]
    finding_ids: tuple[str, ...]

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CategoryRun":
        run = cls(
            category_run_id=str(value["category_run_id"]),
            category_plan_id=str(value["category_plan_id"]),
            work_unit_id=str(value["work_unit_id"]),
            family=str(value["family"]).upper(),
            mechanism_variants_examined=tuple(
                str(item) for item in value.get("mechanism_variants_examined", [])
            ),
            axis_runs=tuple(AxisRun.from_dict(item) for item in value["axis_runs"]),
            applicability=Applicability(str(value["applicability"])),
            status=CategoryRunStatus(str(value["status"])),
            evidence_refs=tuple(str(item) for item in value.get("evidence_refs", [])),
            rationale=str(value["rationale"]),
            hypothesis_ids=tuple(str(item) for item in value.get("hypothesis_ids", [])),
            finding_ids=tuple(str(item) for item in value.get("finding_ids", [])),
        )
        if not run.category_run_id or not run.rationale or not run.evidence_refs:
            raise ModelError("CategoryRun identity, rationale, and evidence refs are required")
        if run.applicability is Applicability.DEFERRED:
            if run.status is not CategoryRunStatus.DEFERRED:
                raise ModelError("DEFERRED CategoryRun must have DEFERRED status")
        elif run.status is not CategoryRunStatus.COMPLETE:
            raise ModelError("non-deferred CategoryRun must be COMPLETE")
        return run


@dataclass(frozen=True)
class Experiment:
    experiment_id: str
    hypothesis_id: str
    fidelity: ExperimentFidelity
    result: ExperimentResult
    target_ref: str
    command_refs: tuple[str, ...]
    observation_refs: tuple[str, ...]
    equivalence_evidence_refs: tuple[str, ...]
    preconditions_tested: tuple[str, ...]
    rationale: str

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Experiment":
        experiment = cls(
            experiment_id=str(value["experiment_id"]),
            hypothesis_id=str(value["hypothesis_id"]),
            fidelity=ExperimentFidelity(str(value["fidelity"])),
            result=ExperimentResult(str(value["result"])),
            target_ref=str(value["target_ref"]),
            command_refs=tuple(str(item) for item in value.get("command_refs", [])),
            observation_refs=tuple(
                str(item) for item in value.get("observation_refs", [])
            ),
            equivalence_evidence_refs=tuple(
                str(item) for item in value.get("equivalence_evidence_refs", [])
            ),
            preconditions_tested=tuple(
                str(item) for item in value.get("preconditions_tested", [])
            ),
            rationale=str(value["rationale"]),
        )
        if not all((
            experiment.experiment_id,
            experiment.hypothesis_id,
            experiment.target_ref,
            experiment.command_refs,
            experiment.observation_refs,
            experiment.rationale,
        )):
            raise ModelError("experiment identity, target, evidence, and rationale are required")
        if (
            experiment.fidelity is ExperimentFidelity.EQUIVALENT
            and not experiment.equivalence_evidence_refs
        ):
            raise ModelError("equivalent experiment requires equivalence evidence")
        return experiment

    @property
    def supports_empirical_upgrade(self) -> bool:
        return (
            self.result is ExperimentResult.CONFIRMED
            and self.fidelity
            in {ExperimentFidelity.REAL_TARGET, ExperimentFidelity.EQUIVALENT}
        )


@dataclass(frozen=True)
class R5Assessment:
    hypothesis_id: str
    experiment_required: bool
    experiment_id: str | None
    disposition: R5Disposition
    evidence_refs: tuple[str, ...]
    rationale: str

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "R5Assessment":
        assessment = cls(
            hypothesis_id=str(value["hypothesis_id"]),
            experiment_required=bool(value["experiment_required"]),
            experiment_id=(
                str(value["experiment_id"])
                if value.get("experiment_id") is not None
                else None
            ),
            disposition=R5Disposition(str(value["disposition"])),
            evidence_refs=tuple(str(item) for item in value.get("evidence_refs", [])),
            rationale=str(value["rationale"]),
        )
        if not assessment.evidence_refs or not assessment.rationale:
            raise ModelError("R5 assessment requires evidence refs and rationale")
        if assessment.experiment_required and assessment.experiment_id is None:
            raise ModelError("required R5 experiment is missing")
        return assessment


@dataclass(frozen=True)
class Finding:
    finding_id: str
    root_cause_key: str
    mechanism: Mechanism
    hypothesis_ids: tuple[str, ...]
    affected_component_ids: tuple[str, ...]
    severity: FindingSeverity
    evidence_grade: EvidenceGrade
    status: FindingStatus
    evidence_refs: tuple[str, ...]
    title: str

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Finding":
        finding = cls(
            finding_id=str(value["finding_id"]),
            root_cause_key=str(value["root_cause_key"]),
            mechanism=Mechanism.from_dict(value["mechanism"]),
            hypothesis_ids=tuple(str(item) for item in value["hypothesis_ids"]),
            affected_component_ids=tuple(
                str(item) for item in value["affected_component_ids"]
            ),
            severity=FindingSeverity(str(value["severity"])),
            evidence_grade=EvidenceGrade(str(value["evidence_grade"])),
            status=FindingStatus(str(value["status"])),
            evidence_refs=tuple(str(item) for item in value["evidence_refs"]),
            title=str(value["title"]),
        )
        if not all((
            finding.finding_id,
            finding.root_cause_key,
            finding.hypothesis_ids,
            finding.affected_component_ids,
            finding.evidence_refs,
            finding.title,
        )):
            raise ModelError("Finding identity, scope, evidence, and title are required")
        if (
            finding.status is FindingStatus.CONFIRMED
            and finding.evidence_grade is EvidenceGrade.STATIC_ONLY
        ):
            raise ModelError("confirmed Finding must be at least edge_proven")
        return finding


@dataclass(frozen=True)
class BatchClosure:
    budget_used: Mapping[str, int]
    constraints_observed: tuple[str, ...]
    unreviewed_scope: tuple[str, ...]
    residual_risks: tuple[str, ...]
    lessons: tuple[str, ...]

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "BatchClosure":
        closure = cls(
            budget_used={
                str(key): int(amount)
                for key, amount in value.get("budget_used", {}).items()
            },
            constraints_observed=tuple(
                str(item) for item in value.get("constraints_observed", [])
            ),
            unreviewed_scope=tuple(
                str(item) for item in value.get("unreviewed_scope", [])
            ),
            residual_risks=tuple(
                str(item) for item in value.get("residual_risks", [])
            ),
            lessons=tuple(str(item) for item in value.get("lessons", [])),
        )
        if any(amount < 0 for amount in closure.budget_used.values()):
            raise ModelError("Batch budget usage cannot be negative")
        if not closure.budget_used:
            raise ModelError("Batch closure requires measured budget usage")
        return closure


@dataclass(frozen=True)
class CampaignClosure:
    architecture_overview: str
    unreviewed_scope: tuple[str, ...]
    residual_risks: tuple[str, ...]
    limitations: tuple[str, ...]
    lessons: tuple[str, ...]
    knowledge_nominations: tuple[str, ...]
    skill_issues: tuple["SkillIssue", ...]
    scope_dispositions: tuple["ScopeDisposition", ...] = ()

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CampaignClosure":
        required_lists = (
            "unreviewed_scope",
            "residual_risks",
            "limitations",
            "lessons",
            "knowledge_nominations",
            "skill_issues",
            "scope_dispositions",
        )
        missing = [name for name in required_lists if name not in value]
        if missing:
            raise ModelError(
                f"Campaign closure requires explicit list fields: {', '.join(missing)}"
            )
        closure = cls(
            architecture_overview=str(value["architecture_overview"]),
            unreviewed_scope=tuple(str(item) for item in value["unreviewed_scope"]),
            residual_risks=tuple(str(item) for item in value["residual_risks"]),
            limitations=tuple(str(item) for item in value["limitations"]),
            lessons=tuple(str(item) for item in value["lessons"]),
            knowledge_nominations=tuple(
                str(item) for item in value["knowledge_nominations"]
            ),
            skill_issues=tuple(
                SkillIssue.from_dict(item) for item in value["skill_issues"]
            ),
            scope_dispositions=tuple(
                ScopeDisposition.from_dict(item)
                for item in value["scope_dispositions"]
            ),
        )
        if not closure.architecture_overview.strip():
            raise ModelError("Campaign closure requires an architecture overview")
        return closure


@dataclass(frozen=True)
class ScopeDisposition:
    scope_ref: str
    disposition: ScopeDispositionKind
    snapshot_id: str
    rationale: str
    approved_by: str
    evidence_refs: tuple[str, ...]
    history_source_campaign_id: str | None = None

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ScopeDisposition":
        decision = cls(
            scope_ref=str(value["scope_ref"]),
            disposition=ScopeDispositionKind(str(value["disposition"])),
            snapshot_id=str(value["snapshot_id"]),
            rationale=str(value["rationale"]),
            approved_by=str(value["approved_by"]),
            evidence_refs=tuple(str(item) for item in value.get("evidence_refs", [])),
            history_source_campaign_id=(
                str(value["history_source_campaign_id"])
                if value.get("history_source_campaign_id") is not None
                else None
            ),
        )
        if not all((
            decision.scope_ref.strip(),
            decision.snapshot_id.strip(),
            decision.rationale.strip(),
            decision.approved_by.strip(),
            decision.evidence_refs,
        )):
            raise ModelError(
                "scope disposition requires identity, current review, rationale, and evidence"
            )
        return decision


@dataclass(frozen=True)
class SkillIssue:
    issue_id: str
    kind: SkillIssueKind
    stage: str
    summary: str
    evidence_refs: tuple[str, ...]
    regression_expectation: str
    status: SkillIssueStatus

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SkillIssue":
        issue = cls(
            issue_id=str(value["issue_id"]),
            kind=SkillIssueKind(str(value["kind"])),
            stage=str(value["stage"]),
            summary=str(value["summary"]),
            evidence_refs=tuple(str(item) for item in value.get("evidence_refs", [])),
            regression_expectation=str(value["regression_expectation"]),
            status=SkillIssueStatus(str(value["status"])),
        )
        if not all((
            issue.issue_id,
            issue.stage,
            issue.summary,
            issue.evidence_refs,
            issue.regression_expectation,
        )):
            raise ModelError("skill issue identity, evidence, and regression expectation are required")
        return issue