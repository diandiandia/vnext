# Lifecycle Conformance Self-Assessment

Status: preliminary engineering self-assessment, not certification. ISO/IEC/IEEE 12207:2017 was withdrawn and replaced by ISO/IEC/IEEE 12207:2026, published 2026-04. This repository has not baselined organizational tailoring rules or performed clause-by-clause verification against the 2026 text. This document maps vNext evidence to selected lifecycle process concepts at a high level; it does not reproduce normative standard text or claim conformity.

## Assessment Basis

The assessment covers the vNext repository at commit `9a97cba`, the working-tree contract repairs, and the documentation revision of 2026-10-17. It does not assess the user's organization, independent evaluation authority, acquisition/supplier contracts, deployment operations, or proprietary Google engineering policies. Those require external evidence and authorized assessors. Rebaselining documents does not waive missing capabilities or resolve implementation defects.

Statuses mean:

- **Implemented in tool:** a tested software mechanism exists.
- **Partially supported:** some process artifacts/mechanisms exist, but governance or acceptance evidence is incomplete.
- **Not evidenced:** the repository does not establish the process outcome.
- **Not applicable to this tool:** the process belongs to the adopting organization; applicability must be confirmed during project tailoring.

## Process-Group Mapping

| 12207 process area (paraphrased) | vNext evidence | Self-assessment and gap |
|---|---|---|
| Agreement processes: acquisition and supply | No acquisition or supplier contract workflow is part of the skill. | **Not applicable to the standalone tool; adopter responsibility.** If deployed as a contracted service, define supplier, acceptance, data-handling, and evidence-retention agreements outside this repository. |
| Organizational project-enabling: life-cycle model, infrastructure, quality, knowledge, human resources | Requirements/design baseline, roadmap, versioned knowledge catalog, provenance, compatibility scan, test suite. | **Partial.** No organizational quality system, competency authorization, tool qualification, records-retention policy, or independent process audit is supplied. |
| Technical management: planning, assessment/control, decision, risk, configuration, information, measurement, quality assurance | Frozen snapshot/plan, catalog content binding, append-only records, budgets/measurements, drift handling, and selected pre-commit amendments. | **Partial.** Per-axis amendment, forecast aggregation, and claim accounting repairs are regression-tested. Post-commit correction, complete dependency invalidation, delegated budgets, authenticated workers, screening enforcement, and scale evidence remain absent. R0 is a digest receipt, not a signed baseline. |
| Technical processes: stakeholder needs and system/software requirements | SYSR/SWDR baselines with cross-references and explicit implementation statuses. | **Partial.** Requirements are traceable, but approved-user needs, project-specific tailoring, acceptance owners, and complete requirement verification evidence are external inputs. |
| Technical processes: architecture/design and implementation | System/software design, language/build adapters, Campaign/Batch workflow, runtime code and schema. | **Partial.** The engine is implemented, while path-level exclusion, first-class Surface disposition, general amendment invalidation, and some evidence-role contracts remain incomplete. |
| Technical processes: integration and verification | Unit/integration/adapter tests, task contracts, evidence validation, Handoffs, regression suite. | **Partial.** Tests pass, but real cross-language boundary completeness, 30k-Handoff/10k-event performance, 1k-file validation cost, and supported-platform integrations lack acceptance evidence. |
| Technical processes: validation and transition | Paired-run contracts, signed manifest mechanism, RG1-RG11 evaluator, fail-closed RG1-RG15 release policy, CLI. | **Not release-validated.** RG12-RG15 are explicitly failed as NOT_IMPLEMENTED; subset success cannot authorize promotion. Held-out provenance is signer-attested, not independently verified. No complete real portfolio/mixed-language/20GB+ acceptance bundle has been supplied. |
| Technical processes: operation, maintenance, and disposal | Campaign status, cleanup/abort, task retry, snapshots, artifact store, regression backlog. | **Partial.** Routine recovery exists, but accepted-stage correction after downstream commit, operational ownership, retention/deletion, and restore drills need policy and tests. |

## Decision

The current evidence supports **partial alignment of the tool's engineering workflow** with selected lifecycle process concepts. It does not establish conformity to ISO/IEC/IEEE 12207:2017 or 12207:2026, organizational compliance, or certification. A formal assessment needs the controlled 2026 text, a tailored process set, accountable process owners, objective work-product evidence, independent audit, and closure of the gaps above.

Google internal engineering/security requirements are not publicly available to this assessment and were not supplied as controlled criteria. No claim of meeting them is made. A comparison requires the authorized requirement set and evidence mapping.
