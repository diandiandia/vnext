# Reachable Audit vNext System Requirements

Status: as-implemented system requirements baseline, reviewed 2026-10-17 against
commit `beaef3b` plus working-tree repairs and `SYSTEM_DESIGN_VNEXT.md`. This revision replaces target-only
obligations with bounded current contracts. Missing target capabilities and known
defects remain explicit; they have not been implemented or waived by this revision.

## 1. Requirement Conventions

- IDs `SYSR-###` are stable identifiers for this requirements baseline.
- The current contract describes managed runtime behavior, not every earlier target.
- References identify implementation/design coverage, not proof of discovery quality.
- A remaining target is outside the current contract; a known defect is not accepted
  behavior merely because it is documented.
- Held-out selection, policy approval, host isolation, and adjudication require an
  external authority. Catalog membership is not language certification.

## 2. System Requirements

| ID | Current system contract | System design | Software requirements | Implementation boundary / remaining target |
|---|---|---|---|---|
| SYSR-001 | The workflow shall record principal-to-operation reachability submissions and their evidence references. | §1; §6 | SWDR-012, SWDR-013 | Reference validation is implemented; semantic truth remains an adjudication responsibility. |
| SYSR-002 | The release portfolio shall contain exactly 15 approved canonical programming-language IDs; the roster shall be frozen before certification. | §1; §8 | SWDR-001 | Covered; approved roster is frozen in portfolio-2026-09-v1 |
| SYSR-003 | Each approved language shall have exactly 10 ranked security-issue profile entries linked to applicable mechanisms and verification guidance. | §7; §8 | SWDR-002, SWDR-003 | Catalog structure/references are validated; provenance/card evidence states do not establish held-out discovery quality. |
| SYSR-004 | Evaluation shall compare supplied certification records against the full approved roster independently of target composition. | §1; §8 | SWDR-001, SWDR-024 | RG6 exists; no real complete portfolio has been certified. |
| SYSR-005 | The system shall support one Campaign containing multiple languages, build ecosystems, components, and Batches without losing file-level language ownership. | §5 | SWDR-007, SWDR-011 | Covered |
| SYSR-006 | Every inventoried source file shall have a canonical language assignment or an explicit unknown/unsupported disposition. | §5 | SWDR-007, SWDR-008 | Covered |
| SYSR-007 | Language adapters and build-system adapters shall be independently registered and shall not treat ecosystem support as proof of language certification. | §3.2; §9 | SWDR-008, SWDR-009 | Covered |
| SYSR-008 | R2/R4 task artifacts shall contain catalog guidance selected by Work Unit languages/families and an entry-count limit, with omissions recorded. | §6; §7 | SWDR-004, SWDR-005, SWDR-006 | No token-budget or semantic boundary-based selector; host delivery/Agent use is not independently verified. |
| SYSR-009 | Catalog records shall distinguish mechanism, language applicability, provenance references, and evidence state. | §7; §10 | SWDR-002, SWDR-003, SWDR-006 | Cross-language variants and mechanically evidenced semantic review remain targets; counts do not establish quality. |
| SYSR-010 | The managed catalog shall reject unreviewed, held-out, or deprecated runtime cards. | §3.5; §8 | SWDR-004, SWDR-022 | External host files/prompts are not sandboxed; answer isolation is an authority/host obligation. |
| SYSR-011 | The workflow shall enforce distinct R0-R6 stage records and completion conditions. | §6 | SWDR-012, SWDR-013, SWDR-014, SWDR-015 | R0 emits a digest receipt, not a signed baseline. R5 states are limited to implemented assessments. |
| SYSR-012 | The supported R2 workflow shall schedule all six axes per Work Unit, separately or compactly, and require evidenced applicability records. | §6 | SWDR-011, SWDR-023 | Planner rejects unsupported subsets; risk-selected subsets remain target work. |
| SYSR-013 | REACHABLE records shall require principal, source-anchored chain, and edge-evidence references under the evidence-grade rules. | §6 | SWDR-013 | Validators check structure/references, not semantic correctness of the asserted path. |
| SYSR-014 | Refutation/adjudication shall record separate reviewer identities, evidence, and dispositions. | §6 | SWDR-014 | Identities are submitted actors/task labels, not independently authenticated workers. |
| SYSR-015 | Experiments shall record target fidelity, prerequisites, commands/observations, artifacts, cleanup, and a disposition; unsupported strong claims shall be downgraded or NEEDS_REVIEW. | §6; §7 | SWDR-015, SWDR-029 | Covered |
| SYSR-016 | The graph shall retain typed supplied boundaries separately from build/import dependency candidates. | §5; §9 | SWDR-009, SWDR-010 | Complete automatic FFI/RPC/IPC/serialization discovery is not implemented. |
| SYSR-017 | R1 shall require an evidenced confirm/reject/unresolved review from each owning Work Unit for each supplied boundary. | §5 | SWDR-010 | Missing graph edges cannot be reconciled as supplied edges; graph completeness is not proven. |
| SYSR-018 | Cross-Batch evidence shall be assigned an owner, resolved with edge or blocking evidence, and integrated before dependent findings or Campaign closure. | §5; §9 | SWDR-010, SWDR-011 | Covered |
| SYSR-019 | Planning shall partition large repositories into stable Work Units and resumable Batches while preserving component ownership, dependencies, and evidence identity. | §5; §9 | SWDR-011, SWDR-017 | Covered |
| SYSR-020 | Evaluation shall check signed large-run size/recovery/measurement records against digest-verified artifacts. | §9 | SWDR-016, SWDR-022, SWDR-027, SWDR-043 | Size excludes symlinks/runtime state and is not inspected-source volume. Forecast counts/costs reconcile per Batch but remain advisory. Missing claim usage is reported incomplete; real large-run evidence is absent. |
| SYSR-021 | Campaign facts and state transitions shall be durably recorded with idempotent submission and reproducible artifact references. | §3.4; §9 | SWDR-017 | Covered |
| SYSR-022 | Recorded source-snapshot drift shall invalidate affected Work Units, Handoffs, and Findings until resolved with evidence. | §9 | SWDR-018 | Implemented for recorded/detected drift, not continuous monitoring of every host source read. |
| SYSR-023 | Batch completion shall not imply Campaign completion; reports shall state unreviewed scope, unresolved boundaries, blockers, and residual risk. | §6; §9 | SWDR-012, SWDR-019 | Covered |
| SYSR-024 | Runtime shall use canonical vNext state without v2/v3 queue imports; compatibility/deproject scans shall check generic and caller-supplied residue patterns. | §3.1; §7; §10 | SWDR-020 | Scan scope includes runtime Python, the main prompt, and runtime-eligible knowledge, not history/development documents or tests. A clean scan is bounded by patterns, not proof of semantic neutrality. Caller-owned Campaign paths are not forbidden runtime-knowledge examples. |
| SYSR-025 | Offline extraction shall produce reviewable knowledge/provenance without importing legacy modules into runtime. | §7; §10 | SWDR-028 | Publication review is operator-asserted; semantic deduplication and consumer/counterexample review are not fully enforced. |
| SYSR-026 | Evaluation shall validate HMAC-signed paired-run records, parity digests, budgets, evidence digests, and held-out/non-synthetic attestations. | §8; §10 | SWDR-021, SWDR-022, SWDR-027 | Independent adjudication and actual host isolation are trusted-signer responsibilities, not independently checked facts. |
| SYSR-027 | Evaluation shall apply implemented release gates and report per-language/family/cell recall, worst-group deltas, noise, sample counts, and intervals from signed inputs. | §8; §10 | SWDR-001, SWDR-021, SWDR-024, SWDR-026, SWDR-027 | RG1-RG15 have evaluator checks; signed assertions and gate success still require independent real evidence and never alone certify capability. |
| SYSR-028 | RG11 shall require signed mixed-language boundary evidence separately from the language/issue-cell sample matrix. | §5; §8 | SWDR-010, SWDR-022, SWDR-025 | Reconciled case counts and references are checked; real discovery/integration acceptance evidence remains external. |
| SYSR-029 | Registered language hotspot providers shall return source-anchored candidate locations and explicit coverage/limitations; a missing provider or empty match set shall not imply safety. | §6 | SWDR-031 | Partial; Python AST provider is implemented, other language providers and held-out quality evidence remain outstanding |
| SYSR-030 | Plans shall retain exact inventoried source ownership; closure shall require structured decisions for declared unreviewed scope. | §5; §9 | SWDR-032 | Path-level roles and included/excluded/deferred plan dispositions remain unimplemented targets. |
| SYSR-031 | CG3 shall reconcile Surface identity/ownership, Work Unit axis review, references, and hypothesis/verdict IDs without requiring a hypothesis per Surface. | §6 | SWDR-033 | Per-Surface clean/deferred/unreviewed dispositions remain unimplemented; axis review is not equivalent evidence. |
| SYSR-032 | Supported pre-commit task corrections and R6/skill-review revisions shall append history rather than overwrite artifacts. | §3.4; §6 | SWDR-034 | R1, per-axis/compact R2, R3, R4, R5, and R6 support pre-commit corrections; post-commit verdict amendment and downstream recomputation remain absent. |
| SYSR-033 | Workers shall claim filtered tasks, release leases, and use bounded retry authorization; collection shall validate supplied measurements against task budgets. | §3.4; §6 | SWDR-035 | Delegated effort/budgets and authenticated worker identity are not modeled; reported usage is host-attested. |
| SYSR-034 | R5 shall use the implemented assessment states, retain infeasible required experiments as unresolved, and bind empirical upgrades to eligible managed-run artifacts. | §6 | SWDR-036 | NOT_FEASIBLE is recorded only for a required unattempted experiment with blocker evidence; it does not confirm or refute. Authorized external-observation registration and its independent provenance validation remain unimplemented. |
| SYSR-035 | Handoffs shall support evidence-backed confirmation that a proposed edge is not a security boundary, distinct from unresolved review. | §5; §6 | SWDR-037 | Implemented |
| SYSR-036 | Campaign closure lessons and skill-regression issues shall be separate, revisionable artifacts; writes shall never overwrite host-authored content without explicit replacement approval. | §3.4; §6 | SWDR-038 | Implemented |
| SYSR-037 | Managed Campaign/state paths shall default to fresh history isolation and require explicit same-target follow-up sources. | §3.6; §6 | SWDR-039 | Managed history mode is enforced and RG13 checks signed provenance against task-input refs; actual host prompt/session isolation and independent verification of signer truth remain external. |
| SYSR-038 | Closure shall derive screening/substantive Work Unit counts from axes/hypotheses and report an optional init-frozen screening ceiling. | §5; §6; §8 | SWDR-040 | RG14 validates digest-backed counts/fraction against the frozen ceiling and rejects overrides at release evaluation; Campaign closure does not block on a missing/exceeded ceiling. Path/risk-weighted altitude and authenticated override remain absent; host-observed inspection is not proven. |
| SYSR-039 | R1/R3 stage validators shall distinguish call-chain/supporting anchors, check non-blank valid locations, and use indexed path lookup with stage-local line caches. | §3.3; §6 | SWDR-041 | R1 Surface and R3 location checks also run at collect. Not all stage-level semantic/reference checks run there; cross-task line caching and scale certification remain absent. |
| SYSR-040 | Large Campaign event and Handoff processing shall provide indexed, batchable operations, preserve per-edge evidence/idempotency, and short-circuit zero-target stages without scanning unrelated work. | §3.4; §5; §9 | SWDR-042 | Partial; indexed queries, atomic bulk resolution, and empty-stage fast paths exist, but large-scale acceptance is outstanding |

## 3. Software-Design Coverage Result

Working-tree repairs on 2026-10-17 add fail-closed release policy, Campaign knowledge
content binding, hotspot byte checks, latest-state cancellation, safe note revisions,
and claim-complete usage accounting. The revised target contracts in software design
section 1.1 still require full dependency invalidation, revision-aware late-candidate
reopening, separated review/evidence coverage, and richer interface proofs. These are
not waived by the narrower current contracts or the synthetic follow-up fixture.

All 40 IDs are retained and map to software requirements, which name software-design
sections and code/tests. This is document traceability, not complete verification or
certification. Unchanged "Covered" entries indicate a mapped local mechanism, not a
claim of real-project acceptance. The software requirements give implementation bounds.

External release policy still requires real paired held-out, mixed-language, scale,
clean-room, and screening evidence. Missing capabilities listed above remain roadmap
work; in particular, the evaluator's current eligibility result does not satisfy all
RG1-RG15. No status-count percentage is a measure of audit capability.