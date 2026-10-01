# Reachable Audit vNext Software Design

Status: implementation design aligned with `SYSTEM_DESIGN_VNEXT.md`. Proposed modules
are target boundaries; their presence here does not imply they are implemented.

## 1. Scope and Compatibility

This design extends the existing vNext Python package and its canonical Campaign,
Batch, event, artifact, Work Unit, and Handoff models. It does not introduce v3 runtime
compatibility. Existing vNext schemas remain the starting point; schema changes require
explicit versioning and migrations within vNext only.

The implementation is organized around these separations:

- language != build ecosystem != component;
- issue profile != reusable mechanism card;
- source inventory != security boundary graph;
- discovery evidence != derived verdict/report;
- training knowledge != held-out evaluation answers;
- per-language certification != mixed-language Campaign acceptance.

## 2. Package Layout

```text
src/reachable_audit/
  campaign.py                 existing Campaign orchestration
  campaign_closure.py         existing Campaign gates and closure
  batch_workflow.py           existing staged Batch workflow and gates
  store.py                    existing SQLite event/state store
  artifacts.py                existing content-addressed artifact store
  inventory.py                language/file ownership and source inventory
  graph.py                    build-unit graph plus explicit security boundaries
  planning.py                 Work Unit and Batch planning
  handoffs.py                 existing cross-Batch evidence integration
  drift.py                    existing snapshot drift and impact invalidation
  execution.py                task contracts and task-context assembly
  analysis_models.py          canonical domain models
  knowledge/
    __init__.py
    catalog.py                load/validate immutable runtime knowledge
    issue_profiles.py         per-language prioritized issue profiles
    mechanism_cards.py        reusable root-cause guidance and applicability
    provenance.py             source provenance and trust-state validation
    migration.py              offline one-way extraction tooling only
  adapters/
    languages/
      base.py                  language adapter protocol and capability model
      registry.py              explicit adapter registration and detection
      <language>.py            language-specific semantics and probes
    builds/
      base.py                  existing build adapter protocol
      registry.py              build ecosystem registry
      <ecosystem>.py           build manifest parser
  discovery/
    task_context.py            bounded, auditable analysis prompt assembly
    boundaries.py              boundary candidates and confirmations
    hotspots.py                registered static hotspot providers and coverage reports
  experiments/
    harness_catalog.py         harness metadata, applicability, and fidelity
    environment.py             toolchain/runtime probes
    runner.py                  managed bounded harness execution
  evaluation/
    manifest.py                frozen evaluation manifest and evidence references
    acceptance.py              per-language, per-family, mixed-project gates
  reporting/
    campaign.py                deterministic Campaign report projection
    coverage.py                source, issue, axis, and boundary coverage views
  evaluation.py               existing paired-run evaluator; contract extended below
  resource_cleanup.py         existing Campaign-owned resource cleanup
schemas/
  issue-profile.schema.json
  mechanism-card.schema.json
  language-capability.schema.json
  boundary-edge.schema.json
knowledge/
  portfolio.json               approved 15-language certification portfolio
  profiles/<language>.json     exactly 10 prioritized issue patterns per language
  cards/<family>/<card-id>.json approved training Mechanism Cards
  harnesses/<language>/...     portable harness recipes and applicability
prompts/
  r1-surface.md
  r2-axis.md
  r3-verify.md
  r35-refute.md
  r4-category.md
  r5-experiment.md
tests/
  unit/
  integration/
  fixtures/training/
```

Private held-out cases and expected answers are stored outside the runtime package and
are not installed with the skill. The exact 15-language portfolio is an explicit,
reviewed data file. It is frozen before certification; code must not silently infer or
edit the roster from detected project languages.

## 3. Core Data Contracts

Schemas use strict JSON validation at ingestion. Unknown fields fail validation unless a
schema version explicitly permits extensions. IDs are stable within a schema version;
absolute paths and project-specific identifiers are prohibited in runtime knowledge.

### 3.1 Language Portfolio

`knowledge/portfolio.json` contains exactly 15 canonical language IDs and a portfolio
version. The initially approved IDs are `c`, `cpp`, `csharp`, `go`, `java`, `rust`,
`python`, `javascript`, `typescript`, `kotlin`, `scala`, `php`, `ruby`, `swift`, and
`shell`. Each language entry names its source adapter, optional build adapters, required
capability tests, and status (`planned`, `supported`, `certified`, `retired`).
Certification status is generated from acceptance evidence, not manually asserted in
the source file.

The approved roster is C, C++, C#, Go, Java, Rust, Python, JavaScript, TypeScript,
Kotlin, Scala, PHP, Ruby, Swift, and Shell. The v3 inventory used 16 labels and did not
provide a distinct TypeScript issue profile; vNext excludes Perl and PowerShell from the
certification roster and treats TypeScript as a separate profile seeded from portable
JavaScript mechanisms plus TypeScript runtime-specific pitfalls. Those TypeScript entries
remain `seeded`, not battle-verified, until language-specific held-out evidence exists.

### 3.2 Language Issue Profile

Each profile is one language and contains exactly ten ordered issue entries:

```json
{
  "schema_version": "1.0",
  "profile_id": "LANG-python-v1",
  "language_id": "python",
  "portfolio_version": "portfolio-v1",
  "entries": [{
    "issue_id": "python-issue-01",
    "rank": 1,
    "title": "Untrusted archive path escapes extraction root",
    "weakness_refs": ["CWE-22"],
    "mechanism_card_ids": ["MECH-path-containment"],
    "source_cues": ["archive member name reaches filesystem path construction"],
    "sink_cues": ["open", "extract", "rename"],
    "language_pitfalls": ["normalization differs from filesystem resolution"],
    "counterevidence": ["resolved destination remains under trusted root"],
    "verification_steps": ["trace member name through canonicalization to write"],
    "provenance_refs": ["PROV-..."]
  }]
}
```

The example illustrates the shape only; issue titles and ranks must come from the
approved portfolio work, not from this example. `rank` is a review priority. It is not
severity, exploitability, or permission to ignore non-listed weaknesses.

### 3.3 Mechanism Card

Cards are reusable security reasoning units and may apply to multiple languages when the
semantics genuinely match. Language-specific differences belong in explicit variants or
profile supplements, not vague `any` applicability.

Required fields:

- `mechanism_id`, `family`, `variant`, and concise root-cause title;
- preconditions, dangerous transitions, affected security properties, and sink semantics;
- counterevidence and falsifiable verification recipe;
- `language_applicability` and any required runtime/build conditions;
- provenance references and evidence state;
- `partition`, always `training` for runtime-eligible cards;
- schema and knowledge release versions.

Knowledge evidence states are `seeded`, `battle_observed`, `battle_reproduced`, and
`deprecated`. Only reviewed, non-deprecated training cards may be loaded at runtime.
Evidence state is not inferred from a non-empty provenance string.

### 3.4 Provenance Record

Runtime cards carry opaque provenance IDs. The restricted provenance manifest records
source type, source digest or archival locator, extraction date, reviewer, portability
decision, and evidence status. It must not inject old project paths, private APIs, or
held-out expected answers into prompts.

### 3.6 Event and Artifact Persistence

The existing `AuditStore` remains the sole authority for Campaign/Batch state and event
ordering. State transitions and accepted stage submissions are append-only events with
Campaign/Batch/entity identity, event type, actor, idempotency key, timestamp, and either
a bounded payload or an artifact reference. Replaying an identical idempotency key and
payload returns the prior result; reusing the key with different data is a conflict.

SQLite runs with WAL and foreign-key enforcement. The Coordinator is the only writer of
canonical state. Large source excerpts, task contexts, tool outputs, and experiment
reports are immutable content-addressed artifacts. Every reference is resolved and its
digest checked before a stage event is accepted. Reports and current status are derived
views; they are not alternate writable state stores.

### 3.8 Inventory Footprint and Execution Attestations

Inventory records target worktree bytes by summing regular file sizes without following
symlinks. It excludes `.audit_vnext` so audit artifacts do not inflate the target size;
it includes other regular files, including `.git` and dependency directories. The final
report labels this as worktree footprint, distinct from source-file count and security
scope. `inventory_digest` separately identifies the planned source/component scope.

Every completed Agent task records positive `agent_runs` and `wall_seconds` plus
`model_id`, `runtime_version`, and a SHA-256 `host_tool_policy_digest` when the host
exposes them. Campaign closure preserves task-level records, sums reported measurements
by metric name, and derives a stable execution-configuration digest only when every
completed task supplied the required host attestations. The parity digest covers only
shared host model/runtime/tool policy; the vNext-owned policy digest is recorded
separately and is not compared with v3's engine policy. Missing values are explicit;
they are never inferred from budgets.

### 3.7 Snapshot Drift and Evidence Invalidation

R0 hashes the scoped source files against the Campaign's frozen baseline before a Batch
starts. Any mismatch writes a drift event and blocks the detecting Batch. The impact
resolver follows source ownership, plan edges, and evidence dependencies to identify
affected Work Units, Handoffs, and Findings. It appends invalidation events rather than
deleting earlier evidence. Unaffected records remain usable only when their source
dependencies are outside the changed impact set.

Drift resolution requires fresh source digests and explicit resolution evidence. A
finding or chain that depends on changed source stays blocked until revalidated. Reports
retain both the original and replacement evidence lineage and never merge different
snapshots without marking the transition.

### 3.5 Boundary Edge

Extend the existing `BoundaryEdge` with typed evidence and language/build context:

```json
{
  "edge_id": "EDGE-...",
  "source_component_id": "COMP-client",
  "target_component_id": "COMP-native-lib",
  "kind": "ffi",
  "source_language": "rust",
  "target_language": "c",
  "source_path": "src/bridge.rs",
  "target_path": "native/parser.c",
  "evidence_refs": ["ART-..."],
  "discovery_status": "adapter_proposed|agent_proposed|confirmed|rejected|unresolved",
  "owner_work_unit_id": "WU-..."
}
```

Build dependency edges and security call/dataflow edges are distinct edge kinds. A build
edge cannot be silently promoted to a proven call edge. Confirmed security edges require
source anchors or a reproducible interface contract.

## 4. Knowledge Loading and Task Assembly

`knowledge.catalog` loads a pinned knowledge release, validates the portfolio and all
referenced schemas, rejects held-out/deprecated cards, and returns immutable objects.
It does not mutate or learn during an audit.

For each R2/R4 task, `discovery.task_context`:

1. Reads Work Unit file-level languages, target categories, surfaces, and confirmed or
   unresolved boundaries.
2. Loads the matching language profiles and only the relevant top-ranked entries within
   the declared task budget.
3. Resolves referenced Mechanism Cards and language-specific supplements.
4. Includes falsification/counterevidence steps and provenance IDs, not private source
   details or unrelated lessons.
5. Writes the exact assembled task context as an immutable artifact and records its
   digest, knowledge release, included profile entries, omitted entries, and omission
   reason.

An empty knowledge match is an explicit task limitation. It must not silently be treated
as a successful knowledge-guided run. The Agent may still use general reasoning, but the
report distinguishes that from a task supplied with profile guidance.

Prompt size is budgeted by mechanism coverage and applicable issue rank, not by dumping
the whole corpus. The task records which applicable knowledge was omitted due to budget
so evaluation can detect language/family bias caused by truncation.

## 5. Source and Build Adapter Contracts

### 5.1 Language Adapter

`LanguageAdapter` provides:

- file/language detection and confidence;
- symbol and module resolution where supported;
- language-specific source-to-sink and boundary cues;
- generated-code classification;
- toolchain/runtime probes and harness capabilities;
- normalization of source locations and evidence anchors.

Adapters return evidence and diagnostics. They do not decide whether a vulnerability is
confirmed.

Every source-like file is represented in inventory even when its language is unknown
or no adapter is registered. Such records carry `language_id: unknown`, the detected
extension, and a diagnostic; they are not silently dropped. The Planner marks their
analysis capability as unsupported/deferred and reports the resulting scope limitation.

### 5.2 Build Adapter

`BuildAdapter` parses manifests into build units and dependency candidates. It reports
unsupported constructs and unresolved local dependencies explicitly. Build adapters are
registered independently of languages; a language may have multiple build systems and
one repository may have multiple languages/build systems.

Unsupported manifests do not invalidate source inventory or prevent unrelated static
analysis. They do lower graph completeness and block claims whose reachability depends
on missing dependency evidence.

### 5.3 Boundary Discovery

Boundary candidates come from adapters, inventory metadata, interface definitions, and
Agent analysis. Candidate sources include FFI declarations, RPC schemas, IPC endpoints,
serialization entry points, plugin APIs, shared memory, and build dependencies.

Each candidate is either confirmed with evidence, rejected with evidence, or retained as
unresolved. R1 task contracts must require review of boundary candidates and a scoped
search for unrepresented cross-language interfaces. Handoffs transport confirmed or
explicitly unresolved work; they do not discover edges on their own.

`rejected` requires evidence that the proposed interface is not a security-relevant
edge for the declared scope. It is not interchangeable with `unresolved`, which means
the edge's existence or security relevance could not be established.

### 5.4 Work Unit and Handoff Integration

The Planner assigns each inventoried source file to exactly one Work Unit and each Work
Unit to exactly one Batch. Stable Work Unit identity is derived from the frozen snapshot,
component identity, shard identity, and owned paths. Any split, merge, or ownership change
is a Plan Amendment and preserves references to completed evidence.

For every cross-Batch boundary edge, the planner creates one Handoff with a source Batch,
an owner Batch, and the relevant edge ID. The owner records one of `EDGE_PROVEN`,
`BLOCKED`, `NEEDS_REVIEW`, or `CANCELLED` with rationale and evidence references.
`EDGE_PROVEN` must include a chain suffix whose first node joins the submitted chain
prefix; the integrator deduplicates the join node and records the combined chain as an
artifact. A dependent finding cannot use an unresolved or cancelled edge as proof.

Generated build-dependency edges and security call/dataflow edges remain distinct.
The Planner can route only edges present in its input graph; boundary completeness is
therefore a separate R1/R6 obligation, not an assumption of this planning algorithm.

## 6. Discovery Axis and Verification Contracts

The existing `_AXIS_INSTRUCTIONS` remain short safety invariants, not the full task prompt.
Prompt templates add task-specific source scope, applicable issue profile entries,
Mechanism Cards, counterevidence, and required output fields.

### 6.0 Static Hotspot Providers

The discovery layer may run registered, language-specific hotspot providers over the
frozen Work Unit source files before constructing R1/R2 task context. A provider returns
candidate API/source locations with stable rule IDs, language, family hints, and concise
reason text, plus scanned/unsupported file coverage and explicit limitations. Results
are stored as an immutable artifact and supplied to Agents as leads only; they do not
create Surfaces, Hypotheses, Verdicts, or Findings and cannot satisfy evidence gates.

The first implementation slice is Python using the standard-library AST. It recognizes
a deliberately small set of high-signal call families, reports exact file/line/column,
and labels unresolved aliases, dynamic dispatch, generated code, and interprocedural
flow as limitations. Other languages remain explicitly `provider_unavailable` until
their own conformance fixtures exist. Providers must include positive, negative, alias,
and malformed-source tests before being enabled by default.

For each Work Unit, R2 schedules all six axes, either as six independently claimable
tasks or as one compact task containing all axes. Compact mode reduces host CLI/lease
round trips; per-axis mode remains available when context isolation or parallel workers
are useful. The Agent returns an `AxisRun` disposition for every `(Work Unit, axis)`:
`APPLICABLE`, `NOT_APPLICABLE`, or `DEFERRED`. `NOT_APPLICABLE` requires a
scoped reason and evidence; `DEFERRED` requires a reason and reportable follow-up. An
applicable axis must have a task result or an explicit execution failure. The collector
requires exactly one disposition per Work Unit and axis and rejects hypotheses from axes
marked not applicable or deferred. This makes omitted analysis visible without requiring
six redundant full-repository passes.

Each axis task returns:

- exact `reviewed_paths` and an explicit omitted-path explanation;
- knowledge/profile references actually considered;
- hypotheses or an evidenced zero-result disposition;
- source anchors and relevant boundary IDs;
- time/Agent/tool measurements.

R3, R3.5, and R5 retain the current strict evidence models. R5 adds a versioned harness
catalog entry containing supported languages, prerequisites, isolation requirements,
setup/cleanup, input classes, expected observations, and fidelity. Harness execution is
an experiment artifact, not a card-authored claim of confirmation.

The managed R5 runner requires an argv array, rejects working directories outside the
target, and disables shell execution. It bounds wall time and output size; POSIX children
also receive CPU-time, address-space, open-file, and core-dump limits. It registers its
process group and temporary directory with the Campaign and stores stdout/stderr as
artifacts. These controls are not a security sandbox; hostile native code requires an
external container or VM.

### 6.1 Stage Completion and Evidence Contracts

- **R0:** every Work Unit path must be present in the frozen baseline and match its
  current digest. Drift blocks the Batch and creates an impact record.
- **R1:** every Surface has a declared principal, Work Unit/component owner, source file,
  valid line anchor, and review disposition. Candidate boundaries are confirmed,
  rejected, or unresolved with evidence; every scoped path has an explicit review state.
- **R2:** every hypothesis names a valid Work Unit, origin axis, seed evidence, applicable
  mechanism family, and known Surface references. A zero-hypothesis result still records
  which applicable axes and knowledge entries were examined.
- **R3:** REACHABLE requires a non-empty, ordered call/dataflow chain with source evidence
  for every asserted edge, plus principal and preconditions. UNREACHABLE requires
  evidence of the blocking condition. Missing proof remains NEEDS_REVIEW. Empirical
  confirmation is only assigned through R5.
- **R3.5:** required refuters are distinct task identities and do not receive one another's
  conclusions. Adjudication records the disputed claim, evidence for and against, actor,
  and final disposition. Revival reopens the hypothesis and invalidates dependent terminal
  conclusions until rechecked.
- **R4:** each planned Work Unit/category pair has a COMPLETE, evidenced run or a
  structured, evidenced NOT_APPLICABLE/DEFERRED disposition. Finding count may be zero.
- **R5:** the experiment artifact records target reference, fidelity, prerequisites,
  exact commands or actions, observations, relevant artifacts, cleanup result, and final
  assessment. Failed setup is not a negative security result. Strong unsupported claims
  remain NEEDS_REVIEW.
- **R6:** all stage outputs reconcile to the Batch manifest; every open dependent Handoff,
  drift event, omitted path, and residual risk is listed. R6 closes a Batch only.

### 6.3 Campaign Abort, Cleanup, and Lessons

Successful Campaign closure calls `cleanup_campaign_resources` after every gate passes.
It cancels unfinished tasks and releases registered process groups and temporary
directories, recording each release. Cleanup is deliberately registration-based; it
does not scan the host for arbitrary processes.

Retryable gate failures leave the Campaign resumable and do not implicitly kill its
resources. An operator who abandons the audit runs `campaign-abort` with a reason and an
explicit `skill_issues` array, including an empty array when no skill defect was found.
Abort records a lifecycle event, moves the Campaign to BLOCKED, runs resource cleanup,
and writes an abort report. Cleanup failures are surfaced and preserved in that report.

Every completed skill review writes `.audit_vnext/campaigns/<campaign-id>/lessons.md`
with all reported issues or an explicit no-issues record. The separate
`.audit_vnext/lessons.md` remains an aggregate pending-regression ledger, not the only
record of a Campaign's lessons.

Schema validation checks required fields and reference identities. Where a referenced
artifact is required, the collector resolves the artifact and verifies its digest before
accepting the stage event. Textual references that cannot be resolved are not treated as
verified evidence.

### 6.2 Reporting Projection

`reporting.campaign` derives the final report only from validated events and artifacts;
it does not accept a manually assembled report as a state update. `reporting.coverage`
computes file/scope coverage, issue-profile and mechanism coverage, axis dispositions,
language coverage, boundary dispositions, and unresolved evidence counts.

The Campaign report includes snapshot and knowledge versions, component/language
inventory, all findings with evidence grades, NEEDS_REVIEW items, resolved and unresolved
Handoffs, unsupported adapters/toolchains, unreviewed scope, residual risks, gate results,
and budget measurements. Batch reports remain identifiable and are linked from the
Campaign view. Exported Markdown/JSON is a reproducible view; the event/artifact store
remains authoritative.

## 7. Runtime and Offline Migration Boundaries

The runtime package includes only approved profiles, training cards, public prompts,
adapters, and harness recipes. It excludes:

- v3 queue files, old schema aliases, version-specific test artifacts, and install-time
  compatibility code;
- raw project lessons, absolute paths, private project/API names, and target-specific
  expected findings;
- held-out tests, answer keys, and scoring metadata.

`knowledge.migration` is a developer-only, one-way tool. It reads selected v3 assets,
normalizes candidate concepts into draft records, and emits a migration report with
source references, rejected items, duplicates, missing fields, and provenance state. It
does not write into the runtime catalog. A human review step approves each draft before
it is copied into a new vNext knowledge release. No v3 module is imported at runtime.

Migration gates require:

1. A portability scan for project names, paths, private APIs, and target-specific values.
2. Deduplication by mechanism, not by matching CWE label alone.
3. Separate knowledge for distinct language semantics; no unsafe language merging.
4. A consumer task and positive/counterexample test for every published card.
5. Explicit provenance/evidence state; missing evidence is marked seeded or rejected,
   never upgraded by conversion.

## 8. Capability Evaluation Implementation

The evaluator consumes a signed/versioned manifest that references immutable run
artifacts. Boolean fields such as `held_out`, `synthetic`, and `evidence_traceable` are
not trusted as proof by themselves. Before scoring, validation checks:

- artifact existence, digest, producer, snapshot, and evaluation-manifest membership;
- independently recorded held-out partition and expected-finding adjudication;
- paired v3/vNext snapshot, budget, model/tool configuration, and scope;
- no missing or duplicate runs for a required language/project stratum;
- certified language roster equals the approved 15-language portfolio;
- every required language-issue evaluation cell has its predeclared minimum evidence;
- mixed-language runs include declared language pairs/boundaries and boundary outcomes.

The evaluation manifest is private to the evaluator. Runtime tasks cannot read expected
finding IDs or held-out labels. Reports include per-language and per-family metrics,
sample counts, uncertainty intervals where statistically meaningful, worst-group results,
and explicit `INSUFFICIENT_EVIDENCE`/`BLOCKED` states.

The top-10 language issue profiles define the coverage matrix, but not every single
project must exercise all ten issues. Held-out cases are pooled across representative
projects while preserving the 150 language-issue strata. Minimum sample counts and
promotion thresholds are frozen in policy before running the benchmark; they are not
chosen after observing results.

## 9. Acceptance and Test Design

### 9.1 Unit Tests

- Strict schema validation, unknown versions, duplicate ranks, and exactly ten entries.
- Portfolio validation for exactly 15 unique canonical language IDs.
- Card provenance, applicability, partition, deprecated-state, and prompt-leak rejection.
- Task-context selection, token budget, omitted-entry accounting, and stable digest.
- Adapter language detection and unsupported-build diagnostics.
- Boundary edge provenance, language pair, ownership, and confirmed/unresolved states.
- Evaluation manifest signatures/digests, duplicate strata, incomplete language roster,
  leaked held-out data, and insufficient sample counts.

### 9.2 Integration Tests

- One Campaign containing at least two languages and multiple build ecosystems.
- A cross-language FFI or RPC path represented by source evidence, split across Batches,
  resolved by Handoff, and integrated into one evidence-backed chain.
- A boundary that is intentionally not found/confirmed remains unresolved and prevents a
  dependent reachable claim from being finalized.
- A language with no build adapter is inventoried, explicitly downgraded, and still
  receives the supported static analysis rather than silently disappearing.
- R2 task artifact proves applicable profile/card content reached the Agent task.
- R5 harness success, failure, missing toolchain, cleanup, and fidelity transitions.

### 9.3 Held-Out Release Tests

- Every approved language has representative held-out evidence; no language can be
  silently omitted from the release manifest.
- The 150 language-issue strata meet frozen minimum sample requirements across the
  portfolio, not necessarily in one repository.
- Mixed-language test campaigns measure boundary discovery and chain integration
  separately from individual-language results.
- v3 and vNext receive equivalent snapshots, budgets, tool permissions, and expected-set
  adjudication.
- Promotion checks overall recall, per-language/per-family regressions, noise,
  unresolved boundaries, evidence grades, and operating cost.

Synthetic tests validate mechanics only. A passing unit suite or fabricated run manifest
cannot certify audit capability.

## 10. Implementation Sequence

1. Freeze and approve the 15-language portfolio and the ten issue entries per language.
2. Implement schemas, catalog loading, provenance model, and task-context artifact.
3. Migrate selected v3 knowledge offline into reviewed draft profiles/cards; run leak and
   semantic deduplication checks.
4. Implement language adapter contract tests and prioritize missing build adapters by
   the approved portfolio and target prevalence.
5. Add boundary-candidate discovery and evidence-backed cross-language Handoffs.
6. Add reviewed harness recipes and toolchain/environment probes per certified language.
7. Upgrade the evaluator to validate artifact evidence, all language strata, and mixed
   boundary runs before it can authorize promotion.
8. Run held-out shadow campaigns, inspect per-language weak groups, and iterate only on
   evidenced gaps.

Each step has its own tests and data release. No phase is considered complete because
files or card counts exist; completion is based on consumers, evidence, and acceptance
results.