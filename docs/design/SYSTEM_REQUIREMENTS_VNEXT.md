# Reachable Audit vNext System Requirements

Status: derived from `SYSTEM_DESIGN_VNEXT.md`. These are system-level obligations, not
claims that the current implementation already satisfies them.

## 1. Requirement Conventions

- IDs `SYSR-###` are stable identifiers for this requirements baseline.
- `Normative requirement` uses **shall** and is testable at system level.
- Software-design coverage means the design defines an implementation contract; it does
  not mean that the code is implemented.
- Values deliberately left to portfolio/policy approval are marked `TBD-before-run`.
- A project need not contain all 15 certified languages. The release portfolio as a
  whole must demonstrate all 15, with separate mixed-language validation.

## 2. System Requirements

| ID | Normative requirement | Derived from system design | Software-design coverage | Coverage check |
|---|---|---|---|---|
| SYSR-001 | The system shall audit whether inputs from declared principals can reach security-sensitive operations and shall retain evidence for each conclusion. | Purpose; §6 | SWDR-012, SWDR-013 | Covered |
| SYSR-002 | The release portfolio shall contain exactly 15 approved canonical programming-language IDs; the roster shall be frozen before certification. | §1; §8 | SWDR-001 | Covered; approved roster is frozen in portfolio-2026-09-v1 |
| SYSR-003 | Each approved language shall have exactly 10 ranked security-issue profile entries linked to applicable mechanisms and verification guidance. | §7; §8 | SWDR-002, SWDR-003 | Covered; shipped profiles are seeded and await held-out validation |
| SYSR-004 | Language capability shall be assessed independently of whether a single project contains that language, and every approved language shall meet its own release gate. | §1; §8 | SWDR-001, SWDR-024 | Covered |
| SYSR-005 | The system shall support one Campaign containing multiple languages, build ecosystems, components, and Batches without losing file-level language ownership. | §5 | SWDR-007, SWDR-011 | Covered |
| SYSR-006 | Every inventoried source file shall have a canonical language assignment or an explicit unknown/unsupported disposition. | §5 | SWDR-007, SWDR-008 | Covered |
| SYSR-007 | Language adapters and build-system adapters shall be independently registered and shall not treat ecosystem support as proof of language certification. | §3.2; §9 | SWDR-008, SWDR-009 | Covered |
| SYSR-008 | Runtime discovery tasks shall receive the applicable language issue profile, approved Mechanism Cards, counterevidence, and verification recipes, with omitted guidance recorded. | §6; §7 | SWDR-004, SWDR-005 | Covered |
| SYSR-009 | Reusable security knowledge shall distinguish mechanism, language applicability, provenance, and evidence state; counts alone shall not establish quality. | §7; §10 | SWDR-002, SWDR-003, SWDR-006 | Covered |
| SYSR-010 | Runtime discovery shall consume approved training knowledge only; held-out answers shall remain inaccessible to runtime agents. | §3.5; §8 | SWDR-004, SWDR-022 | Covered |
| SYSR-011 | The workflow shall represent R0, R1, R2, R3, R3.5, R4, R5, and R6 as distinct, evidence-backed stages with explicit completion conditions. | §6 | SWDR-012, SWDR-013, SWDR-014, SWDR-015 | Covered |
| SYSR-012 | Discovery planning shall select applicable surface, mechanism, state/lifecycle, fix-variant, boundary, and differential axes and record omissions or non-applicability. | §6 | SWDR-011, SWDR-023 | Covered |
| SYSR-013 | A REACHABLE conclusion shall require a source-anchored chain from a declared principal to the affected operation; unresolved proof shall not be reported as confirmed. | §6 | SWDR-013 | Covered |
| SYSR-014 | Independent refutation and adjudication shall be available for material hypotheses, with evidence and disposition recorded. | §6 | SWDR-014 | Covered |
| SYSR-015 | Experiments shall record target fidelity, prerequisites, commands/observations, artifacts, cleanup, and a disposition; unsupported strong claims shall be downgraded or NEEDS_REVIEW. | §6; §7 | SWDR-015, SWDR-029 | Covered |
| SYSR-016 | The system shall model FFI, RPC, IPC, serialization, shared-storage, plugin, and other security boundaries independently of build dependencies. | §5; §9 | SWDR-009, SWDR-010 | Covered |
| SYSR-017 | Every security-relevant boundary shall be confirmed with evidence, rejected with evidence, or retained as unresolved; missing graph data shall not imply safety. | §5 | SWDR-010 | Covered |
| SYSR-018 | Cross-Batch evidence shall be assigned an owner, resolved with edge or blocking evidence, and integrated before dependent findings or Campaign closure. | §5; §9 | SWDR-010, SWDR-011 | Covered |
| SYSR-019 | Planning shall partition large repositories into stable Work Units and resumable Batches while preserving component ownership, dependencies, and evidence identity. | §5; §9 | SWDR-011, SWDR-017 | Covered |
| SYSR-020 | A 20GB+ support claim shall require a real representative Campaign with measured scope, resource use, interruption recovery, and evidence reconciliation. | §9 | SWDR-016, SWDR-022, SWDR-027 | Covered |
| SYSR-021 | Campaign facts and state transitions shall be durably recorded with idempotent submission and reproducible artifact references. | §3.4; §9 | SWDR-017 | Covered |
| SYSR-022 | Source-snapshot drift shall invalidate affected evidence and dependent conclusions; evidence from different snapshots shall not be silently combined. | §9 | SWDR-018 | Covered |
| SYSR-023 | Batch completion shall not imply Campaign completion; reports shall state unreviewed scope, unresolved boundaries, blockers, and residual risk. | §6; §9 | SWDR-012, SWDR-019 | Covered |
| SYSR-024 | Historical v2/v3 runtime schemas, queues, compatibility branches, project-specific examples, and absolute paths shall not enter vNext runtime behavior or prompts. | §3.1; §7; §10 | SWDR-020 | Covered |
| SYSR-025 | Historical knowledge may be extracted only through a one-way offline workflow and shall require portability, provenance, deduplication, consumer, and counterexample review before publication. | §7; §10 | SWDR-028 | Covered |
| SYSR-026 | Evaluation shall use paired, independently adjudicated, held-out runs on comparable snapshots, budgets, scope, and tool permissions; synthetic fixtures shall not count as capability evidence. | §8; §10 | SWDR-021, SWDR-022, SWDR-027 | Covered |
| SYSR-027 | Release evaluation shall certify every approved language and report per-language, per-family, worst-group, noise, uncertainty, budget, and sample-count results. | §8; §10 | SWDR-001, SWDR-021, SWDR-024, SWDR-026, SWDR-027 | Covered; numeric policy is TBD-before-run |
| SYSR-028 | The release portfolio shall include mixed-language Campaign evidence that tests boundary discovery and evidence-chain integration separately from single-language certification. | §5; §8 | SWDR-010, SWDR-022, SWDR-025 | Covered; portfolio cases are TBD-before-run |
| SYSR-029 | Registered language hotspot providers shall return source-anchored candidate locations and explicit coverage/limitations; a missing provider or empty match set shall not imply safety. | §6 | SWDR-031 | Partial; Python AST provider is implemented, other language providers and held-out quality evidence remain outstanding |
| SYSR-030 | Inventory and planning shall distinguish included, explicitly excluded, and deferred paths; exclusions require a reason and remain visible in coverage and final reports. | §5; §9 | SWDR-032 | Partial; closure-level exclusions are recorded, but path-level plan dispositions are not implemented |
| SYSR-031 | Every discovered Surface shall receive a review disposition independent of whether it produces a Hypothesis; zero-result review is valid evidence when scope and axis coverage are recorded. | §6 | SWDR-033 | Partial; Work Unit axes are accounted, but per-Surface dispositions are not stored |
| SYSR-032 | Accepted stage decisions and artifacts shall be correctable only through append-only, evidence-backed amendments; derived views shall use the latest valid revision and preserve prior history. | §3.4; §6 | SWDR-034 | Partial; R6 projections are revisionable, general verdict amendments are not implemented |
| SYSR-033 | Task workers shall be able to claim compatible operations, release/retry eligible work safely, and report delegated effort without falsifying task ownership or exceeding declared budgets. | §3.4; §6 | SWDR-035 | Partial; operation filtering/release/bounded retry exist, delegated budgets and host attestation remain open |
| SYSR-034 | R5 shall represent required experiments that cannot be run and authorized out-of-band observations with explicit reason, provenance, fidelity, and non-confirming status unless evidence is independently verified. | §6 | SWDR-036 | Partial |
| SYSR-035 | Handoffs shall support evidence-backed confirmation that a proposed edge is not a security boundary, distinct from unresolved review. | §5; §6 | SWDR-037 | Implemented |
| SYSR-036 | Campaign closure lessons and skill-regression issues shall be separate, revisionable artifacts; writes shall never overwrite host-authored content without explicit replacement approval. | §3.4; §6 | SWDR-038 | Implemented |
| SYSR-037 | Fresh Campaigns shall not import prior audit findings, scope decisions, lessons, or regression backlogs into discovery; follow-up history shall be explicitly declared and isolated from R1/R2 vulnerability seeds. | §3.6; §6 | SWDR-039 | Partial; managed CLI/state paths isolate history, but host-authored prompt context is outside runtime enforcement |
| SYSR-038 | Campaign coverage shall distinguish screening from substantive inspection, require evidence-backed reasons for NOT_APPLICABLE dispositions, and enforce a predeclared risk-weighted screening ceiling or record a human override that blocks affected release certification. | §5; §6; §8 | SWDR-040 | Partial; coverage and ceiling are reported, but release evaluator enforcement/override attestation is absent |
| SYSR-039 | Evidence validation shall distinguish included-scope call-chain anchors from supporting-evidence anchors, reject blank/out-of-snapshot locations, and reuse snapshot-scoped validation indexes across large task collections. | §3.3; §6 | SWDR-041 | Partial; role-aware validation and an indexed snapshot path registry exist, but cross-task line-count caching and scale certification remain open |
| SYSR-040 | Large Campaign event and Handoff processing shall provide indexed, batchable operations, preserve per-edge evidence/idempotency, and short-circuit zero-target stages without scanning unrelated work. | §3.4; §5; §9 | SWDR-042 | Partial; indexed queries, atomic bulk resolution, and empty-stage fast paths exist, but large-scale acceptance is outstanding |

## 3. Software-Design Coverage Result

All 40 system requirements have a named software-design coverage reference. This is a
design-level traceability result only; it does not assert implementation completeness.
The software design freezes the language roster. Minimum per-cell sample counts are
recorded in the signed evaluation policy; numeric promotion thresholds and representative
mixed-language acceptance cases still require evidence-authority approval before the
held-out release campaign. These are controlled acceptance inputs, not permission to
omit the corresponding system requirement.

The software design shall be updated whenever a requirement is changed. Any requirement
without a software-design reference is a design defect and blocks implementation signoff.