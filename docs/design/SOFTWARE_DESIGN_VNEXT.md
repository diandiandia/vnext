# Reachable Audit vNext Software Design

Status: as-implemented software baseline, reviewed 2026-10-17 against commit `beaef3b`
plus the working-tree contract repairs.
This supersedes the target package/schema descriptions in the previous revision.
Missing capabilities and known defects below are not supported contracts.

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

### 1.1 Revised Core Contracts

The following target contracts guide repairs; they are not an implementation or
release-certification claim. The as-implemented sections below remain the baseline.

1. Release authorization has one versioned policy and a complete required-gate set.
  Missing, unimplemented, failed, or insufficiently evidenced gates block promotion.
  Passing implemented subset checks is reported separately from release eligibility;
  Campaign completion never authorizes release.
2. A task's reproducible input identity includes source content, plan revision,
  knowledge content/version, analysis contract, and host configuration attestations.
  Results retain those dependencies. Changes invalidate dependent results; a task
  must not silently read new source under an old snapshot identity. Content digests
  establish byte identity, not semantic truth or reviewer independence.
3. New candidates found after R2 require a bounded follow-up through hypothesis,
  verification, refutation, and applicable experiments before becoming Findings.
  Until revision-aware reopening is implemented, use a separately identified,
  explicitly declared follow-up Campaign, record the unresolved candidate in the originating report,
  and do not relabel the original scope as fully verified. Budget exhaustion retains
  an explicit unresolved disposition rather than silently dropping the candidate.
4. Ownership coverage, declared review execution, and evidenced security paths are
  separate metrics. Task-coordinated R1 preserves Agent-declared per-path review claims
  and reports them separately from Plan ownership; neither a file assignment, AxisRun,
  nor claim proves host-observed inspection or safety.
  NOT_APPLICABLE, DEFERRED, unsupported, and unreviewed work remain distinguishable;
  measured resource use is separate from advisory forecasts. Interrupted/released
  attempts without usage make attempt accounting incomplete, not free.
5. Cross-boundary proof needs an identified interface, direction, principal/premises,
  source/target evidence, and relevant data/argument mapping. EDGE_PROVEN Handoff
  resolutions now require a typed BoundaryProof bound to the planned edge and endpoint
  components, with resolvable endpoint evidence and mappings that cite both ends.
  Matching chain join nodes remain a necessary structural check, not a semantic proof;
  proof declarations do not establish that the asserted interface or data flow is true.
  Automatic boundary discovery and independent semantic adjudication remain target work.

The minimum vertical acceptance scenario must exercise a mixed-language boundary,
a late candidate routed to verification, source/input invalidation, interrupted-task
recovery, and blocked promotion with a missing gate. Existing fixtures establish only
the portions they actually execute; held-out quality and scale evidence stay external.
Exact profile counts and six-axis execution are current policy, not proven optima;
changes require measured recall, uncertainty, and cost comparisons at equal budgets.

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
  knowledge.py                mechanism/category helpers
  knowledge_catalog.py        catalog validation and bounded knowledge context
  adapters/
    languages/
      registry.py              explicit adapter registration and detection
    builds/
      base.py                  existing build adapter protocol
      __init__.py              build ecosystem registration
      <ecosystem>.py           build manifest parser
  discovery/
    hotspots.py                registered static hotspot providers and coverage reports
  experiments/
    harness_catalog.py         harness metadata, applicability, and fidelity
    environment.py             toolchain/runtime probes
    runner.py                  managed bounded harness execution
  evaluation.py               signed manifests, metrics, and RG1-RG15 gates
  resource_cleanup.py         existing Campaign-owned resource cleanup
knowledge/
  portfolio.json               approved 15-language certification portfolio
  profiles/<language>.json     exactly 10 prioritized issue patterns per language
  cards/<family>/<card-id>.json approved training Mechanism Cards
tests/
  test_*.py                    unit/integration/contract and optional held-out tests
```

This maps relevant modules, not every installed file. Language semantics are registered
in the registry, not one file per language. Task assembly lives in `execution.py`, graph
candidates in `graph.py`, and reporting/coverage in `batch_workflow.py` and
`campaign_closure.py`. Validation uses Python code, not a standalone `schemas/` tree.
Separate knowledge/reporting/evaluation packages and public prompt files are not
required by this baseline.

Harness recipes are generated from family-method and language-prerequisite tables in
`experiments/harness_catalog.py`; there is no `knowledge/harnesses/` asset directory.

Private held-out cases and expected answers are stored outside the runtime package and
are not installed with the skill. The exact 15-language portfolio is an explicit,
reviewed data file. It is frozen before certification; code must not silently infer or
edit the roster from detected project languages.

## 3. Core Data Contracts

Validation is contract-specific. Catalog documents use exact field sets and reject
unknown fields. Many domain `from_dict` parsers read/coerce known fields and ignore
extras; some missing fields still raise raw exceptions. Collection adds selected shape,
identity, coverage, version, and size checks, not universal strict JSON validation.
Ignored fields do not become review evidence. Runtime knowledge has residue checks;
this is not a ban on absolute paths in every Campaign/state field.

### 3.1 Language Portfolio

`knowledge/portfolio.json` contains exactly 15 canonical language IDs and a portfolio
version. The initially approved IDs are `c`, `cpp`, `csharp`, `go`, `java`, `rust`,
`python`, `javascript`, `typescript`, `kotlin`, `scala`, `php`, `ruby`, `swift`, and
`shell`. The loader requires the approved roster/version. Adapters are registered
separately; certification records live in signed evaluation inputs. The portfolio is
not a generated per-language lifecycle/certification registry. Its fixed count is
current evaluation policy, not evidence of capability.

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
  "portfolio_version": "portfolio-2026-09-v1",
  "review_status": "approved",
  "entries": [{
    "issue_id": "python-issue-01",
    "rank": 1,
    "title": "Untrusted archive path escapes extraction root",
    "family": "PATH",
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

This is a syntactically valid, abbreviated shape example, not a loadable profile:
runtime requires ten entries and resolvable card/provenance IDs. Titles/families must
come from approved catalog data, not this example. Rank is review priority, not severity
or permission to ignore other weaknesses.

### 3.3 Mechanism Card

Cards are training guidance records. Shipped cards are language-specific and substantially
templated. Cross-language reuse with explicit variants remains roadmap work.

Required fields:

- `mechanism_id`, `family`, and root-cause title; no card-level `variant` field;
- preconditions, dangerous transitions, and sink semantics;
- counterevidence and falsifiable verification recipe;
- `language_applicability` and any required runtime/build conditions;
- `provenance` references and `evidence_state`;
- `evaluation_partition`, always `training` for runtime-eligible cards;
- `review_status`, schema, and knowledge release versions.

Hypothesis mechanisms and category plans have variant strings; those do not implement
language-specific variants in catalog cards.

Knowledge evidence states are `seeded`, `battle_observed`, `battle_reproduced`, and
`deprecated`. Only reviewed, non-deprecated training cards may be loaded at runtime.
Evidence state is not inferred from a non-empty provenance string.

### 3.4 Provenance Record

Runtime cards carry provenance IDs resolved by the catalog manifest. Loading validates
required structure/references. Durable restricted source archives and independently
evidenced semantic/portability review are not fully implemented. Review flags and opaque
references alone do not establish those properties. Publication/evaluation authorities
remain responsible for isolating private source material and held-out answers.

### 3.6 Event and Artifact Persistence

The existing `AuditStore` remains the sole authority for Campaign/Batch state and event
ordering. State transitions and accepted stage submissions are append-only events with
Campaign/Batch/entity identity, event type, actor, idempotency key, timestamp, and either
a bounded payload or an artifact reference. Replaying an identical idempotency key and
payload returns the prior result; reusing the key with different data is a conflict.

SQLite runs with WAL and foreign-key enforcement. The Coordinator is the only writer of
canonical state through managed APIs. Large source excerpts, task contexts, tool outputs,
and experiment reports are content-addressed artifacts. Artifact reads check their
digests; source/artifact references are checked by the validators that consume them,
not universally at task collection. Reports are derived views; persisted store state
and events remain authoritative.

Hot event queries use composite indexes keyed by Campaign, Batch, entity, and event
type. APIs provide filtered reads, submission-ordered task-ID enumeration, and atomic
batch event append while preserving per-entity idempotency. Empty expected task sets
complete without polling unrelated Campaign tasks. Bulk Handoff resolution preserves an
individual edge/disposition/evidence record for reconciliation but commits a validated
batch in one transaction; homogeneous structural dispositions may share a provenance
artifact only when each edge maps to an explicit entry in that artifact.

R6 reports and skill reviews support append-only revisions. Collected R1, per-axis/compact R2,
R3, individual/bundled R4, R5, and R6 task outputs can be amended before their stage commits;
events retain prior/replacement refs, reason, actor, and resolvable artifact evidence.
Readers select the amended task output. Other post-commit amendments are rejected;
general R1-R5 post-commit amendments and downstream invalidation/recomputation are absent.
Terminal R6 task output may be amended while the Campaign is open; R6 must be recommitted
and Campaign closure rejects a pending amendment until that newer projection exists.
Campaign-complete amendments are rejected.

All six `generate_hypotheses:<axis>` operations support pre-commit correction.
Failed-commit recovery remains limited to implemented operations/stages, not universal.

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

Optional token usage remains non-blocking for audit collection. Hosts may report
`input_tokens` (uncached), `cache_read_tokens`, and `output_tokens`; closure preserves
success-only totals and separately aggregates token usage for every terminal attempt,
including failures and retries. Missing attempt usage is never estimated and makes the
attempt-level cost view incomplete; cost comparisons must not treat it as a full spend
total. The existing `usage` block reports success-task completeness and cache-hit ratio.
Task result artifacts are asked to stay under 1 MiB and are hard-rejected above 4 MiB at
collection. Coverage
takes precedence over size: `output_discipline` states that required items are never
dropped, sampled, or truncated to meet the soft target. Collection of `discover_surfaces`,
`generate_hypotheses`, and compact R2 results verifies, before the task becomes terminal,
that coverage is complete: use the exact scalar `reviewed_scope: "ALL_SOURCE_FILES"` and
omit `reviewed_paths`, or provide `reviewed_paths` equal to the Work Unit `source_files`.
Partial coverage and `excluded_paths` are rejected. R1 `boundary_reviews` must cover
every supplied edge exactly once, with matching Work Unit ID, valid disposition, non-empty
evidence references, and rationale. Surface entry-path anchors are checked for Work Unit
membership, valid line range, and nonblank source at collection; stage commit retains
its own scope and evidence checks. These are structural checks, not observed reading
coverage or proof that an anchor supports its claim.
R2 hypothesis and axis records are parsed at collection so malformed nested objects fail
as `ModelError` while still leased. Hypothesis IDs use the deterministic
`HYP-<work_unit_id>-<origin_axis>-<positive ordinal>` namespace, preventing collisions
between R2 Work Unit/axis tasks. Individual and bundled R4 CategoryRuns are checked at
collection against their plan identity, axis coverage, and verbatim mechanism-variant
coverage; missing fields return actionable `ModelError`s rather than raw `KeyError`s.
R4 inputs supply a Work Unit/family-scoped hypothesis-ID allowlist, enforced at collect.
R5 collection and commit share experiment structure, hypothesis scope, and task-local
reference checks. An absent experiment ID is JSON null; invalid output remains leased
for correction. Legacy successful output can be amended before R5 commit. Empirical
fidelity and registered harness evidence are additionally validated at stage commit.
R6 closure uses canonical stage artifacts rather than a source-discovery inventory.
A rejection reports counts and the first ten missing or extra edge IDs and leaves the
task leased. Agent-facing task inputs are compacted
without changing the canonical Work Unit: files are grouped by directory
(`source_files_by_directory`), the
hotspot report carries counts instead of path lists derivable from the Work Unit, and R1
inputs replace `boundary_edge_ids` with a count because the full edges are already
supplied. `plan` output lists per-batch work-unit, source-file, and source-byte counts,
maximum boundary-review count, and an estimated minimum R1 result size per Work Unit.
`oversize_work_units` identifies estimates above the hard ceiling. The estimate assumes
one minimal evidence reference and rationale per required boundary review; actual Agent
output can be larger, so edge counts are shown alongside it. These are planning signals,
not result-size guarantees or price estimates.

An optional plan cost profile supplies measured per-operation task cost, currency,
low/expected/high hypotheses per Work Unit, expected reachable fraction, and optional R4
bundle width. Forecasts report fixed and hypothesis-dependent task counts, cost scenarios,
and per-Batch ranges; the profile is caller-owned and is not inferred from a repository or
historical Campaign. Forecasts assume compact R2, not six separate axis tasks.
Campaign counts, hypothesis rounding, R4 groups, one R6 per Batch, and rounded costs
sum the per-Batch scenarios; no R4 group crosses a Batch boundary. These are advisory
estimates based on caller assumptions, not enforced budgets or measured savings.
R4 `CategoryAuditPlan` task bundling is opt-in and groups plans only
within the same mechanism family. A bundle retains each original `work_unit_id` and
`category_plan_id`, returns one `CategoryRun` per plan, and validates exact member coverage
before collection succeeds. Its default width is one (the existing task mode); input-size
limits can force a smaller group or individual scheduling. Bundling reduces session
startup/context replay but does not merge WU ownership, findings, or evidence records.

Planning may omit a component only when it owns no source files, build manifests, or
boundary-edge obligations; manifest-only and boundary-only components remain planned.
Omitted component IDs are persisted in the plan. If every component is otherwise empty,
one Work Unit is retained so the Campaign still has a closure path. Forecasts and bundling
are advisory/opt-in controls: their cost and quality effects require measured paired runs.

Each successful task records positive `agent_runs` and `wall_seconds`; failures may
report zero when no worker ran. Hosts define and report whether
`agent_runs` includes delegated sub-agent runs. Workers may claim by operation, Batch,
or task ID and release an unstarted lease. Failed attempts remain visible; after the
configured retry budget is exhausted, an operator may append a reasoned
`TASK_RETRY_AUTHORIZED` event for one bounded additional attempt. Success and cancellation
remain terminal. Worker IDs identify queue actors but are not authenticated human/Agent
identities without host attestation.

Campaign budget may freeze `max_screening_fraction` in the range [0, 1] at init. Closure
reports screened Work Unit IDs, count, fraction, ceiling status, and release eligibility.
Any nonzero screening share without a ceiling is marked not release-eligible in the
Campaign report. Missing/exceeded ceilings do not alone block closure. There is no
authenticated override workflow, and the evaluator does not enforce this report policy.

Release returns a task to PENDING without replenishing its claim budget. Exhausted
released claims, like exhausted failures, require bounded retry authorization. Delegated
budgets are not modeled; worker IDs are labels, not authenticated identities.

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
  "discovery_status": "adapter_proposed",
  "owner_work_unit_id": "WU-..."
}
```

Build dependency edges and security call/dataflow edges are distinct edge kinds. A build
edge cannot be silently promoted to a proven call edge. Confirmed security edges require
source anchors or a reproducible interface contract.

## 4. Knowledge Loading and Task Assembly

`knowledge_catalog.py` loads the approved release, validates catalog fields/references,
and rejects held-out/deprecated cards. It does not learn or modify the catalog during
an audit. The first coordinator stores a full content-addressed catalog snapshot and
KNOWLEDGE_BOUND event; later coordinators reject different content/version. Coordinator
inputs are deep-copied from the supplied catalog; their exposed nested mappings are not
guaranteed deeply immutable. This is not complete input-dependency invalidation.

For R2/R4, `execution.py` supplies Work Unit languages, families, and an entry-count
bound to `KnowledgeCatalog.task_context`. The selector filters entries, orders by rank,
selects round-robin across languages, and resolves full referenced cards. Version,
selected entries/cards, omitted IDs, unsupported languages, and limitations are retained
in the content-addressed task input. Surface/plan context is assembled separately;
the selector does not prioritize semantically from confirmed boundaries.

An empty knowledge match is an explicit task limitation. It must not silently be treated
as a successful knowledge-guided run. The Agent may still use general reasoning, but the
report distinguishes that from a task supplied with profile guidance.

The entry-count bound is not a knowledge token/byte bound. Omitted IDs expose selection
limits, not proof of unbiased guidance. R4 bundles have a separate input-byte limit.

### 4.1 Campaign History Isolation and Scope Decisions

Campaign creation records `audit_mode` (`fresh`, `follow-up`, or migrated `legacy`) and
explicit history-source Campaign IDs. Fresh mode rejects history sources and records an
empty skill-regression baseline. Follow-up mode requires same-target source IDs and
limits its regression baseline to those sources. The `skill-backlog` CLI requires a
Campaign ID, returns no prior issues for fresh/legacy mode, and labels results as
`tool_regression_only`.

Campaign closure requires an explicit `scope_dispositions` array and must use the
latest durable Plan artifact for the Campaign; stale Plan IDs and caller-mutated Plan
objects are rejected before gates run. Every
`unreviewed_scope` string maps to exactly one `EXCLUDED` or `DEFERRED` record with the
current snapshot ID, approver, rationale, and evidence. Source evidence must resolve to
a current inventory LOC anchor; artifact evidence must be recorded by the current
Campaign, or by an explicitly declared history source in follow-up mode. The derived
report includes `audit_mode`, declared history sources, and `scope_completeness`.

Plans retain one path-scope record for every inventory source path. Omitted CLI records
default to INCLUDED; EXCLUDED and DEFERRED paths require rationale, an approver
declaration, and evidence refs. Only INCLUDED paths are assigned to Work Units. CG2
checks exact inventory classification, included-path ownership, and resolvable evidence;
the final report and Markdown export retain every path decision. The approver string is
not authenticated identity, and this ledger is not host-observed review evidence.
Closure-level `scope_dispositions` remain separate decisions for broader unreviewed
scope statements.

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

Inventory recognizes registered/known-unsupported extensions and heuristic source-like
files. SourceFile uses `language` and `language_status`, not a universal language_id/
diagnostic contract. Arbitrary unknown syntax can be missed. Inventoried unsupported
files are INCLUDED by default. A Plan may explicitly mark a path EXCLUDED or DEFERRED
while retaining it in the path-scope ledger and final report.

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

The Planner retains every inventoried source path in exactly one Plan disposition.
INCLUDED paths are assigned to exactly one Work Unit and Batch; EXCLUDED and DEFERRED
paths remain visible but are not assigned to source-review Work Units. Closure scope
decisions do not change these Plan dispositions. Stable Work Unit identity is derived
from the frozen snapshot, component identity, shard identity, and included owned paths.
Any split, merge, or ownership change is a Plan Amendment and preserves references to
completed evidence. Campaign closure is bound to the latest recorded Plan and compares
the supplied Plan object with its durable artifact before evaluating coverage.

Stable build-dependency edge IDs include the source manifest/build-unit identity, target,
dependency class, local target/path, and evidence identity. The graph builder rejects
duplicate IDs with collision details before persistence; downstream plans never repair
collisions by renaming edges.

For every cross-Batch boundary edge, the planner creates one Handoff with a source Batch,
an owner Batch, and the relevant edge ID. The owner records one of `EDGE_PROVEN`,
`BLOCKED`, `NEEDS_REVIEW`, `NOT_SECURITY_BOUNDARY`, or `CANCELLED` with rationale and
evidence references. `NOT_SECURITY_BOUNDARY` requires evidence that the edge is
development/build-only or otherwise outside runtime trust flow; it is not an unresolved
review.
`EDGE_PROVEN` must include a chain suffix whose first node joins the submitted chain
prefix; it also requires a typed `boundary_proof` with planned edge identity, source and
target components, interface kind, direction, principal, premises, source/target
evidence refs, and at least one source-to-target data mapping. Every mapping cites at
least one ref from each endpoint evidence set. The resolver binds these fields to the
planned edge, checks LOC ownership and current source anchors, and accepts only artifacts
owned by the Campaign. The integrator retains the proof and deduplicates the join node
when recording the combined chain. These checks validate structure and reference
identity, not semantic truth. A dependent finding cannot use an unresolved or cancelled
edge as proof.

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

Planning rejects axis subsets; only all-six plans are currently supported end to end.
R1/R2 scheduling rechecks R0, and the hotspot provider verifies the bytes it parses
against R0 digests. This does not sandbox arbitrary host reads or freeze external tools.

Each axis output has full Work Unit coverage (`reviewed_paths` or ALL_SOURCE_FILES),
an evidenced AxisRun, and possibly empty hypotheses. Compact output has one run per
axis. Review altitude, examined knowledge IDs, and per-path omission dispositions are
not enforced fields. Partial coverage and `excluded_paths` are rejected. Measurements
and configuration belong to the task-result envelope.

Coverage uses axis-derived Work Unit counts: all planned axes NOT_APPLICABLE with no
hypotheses means screening-only; any APPLICABLE axis contributes to substantive Work
Units. There is no path/risk-tier inspection ledger. An optional init-frozen screening
ceiling is reported, not enforced as a closure or evaluator gate; signed overrides are
not implemented.

R3, R3.5, and R5 validate their implemented evidence models, not universal strict schemas.
R5's HarnessCatalog generates recipes with recipe ID, language, family, method,
prerequisites, isolation, fidelity guidance, and cleanup guidance. Optional sanitizer
tooling is suggested only for memory-safety/numeric families in languages with supported
tools; it is not a prerequisite for unrelated experiment classes. Recipes have no
separate release-version, setup, input-class, or expected-observation fields. Managed
execution produces an experiment artifact, not a card-authored claim of confirmation.

The managed R5 runner requires an argv array, rejects working directories outside the
target, and disables shell execution. It bounds wall time and output size; POSIX children
also receive CPU-time, address-space, open-file, and core-dump limits. It registers its
process group and temporary directory with the Campaign and stores stdout/stderr as
artifacts. These controls are not a security sandbox; hostile native code requires an
external container or VM.

### 6.1 Stage Completion and Evidence Contracts

- **R0:** Work Unit source paths must match the frozen baseline digests. Drift blocks
  the Batch and records impact. The receipt is content-addressed, not signed.
- **R1:** Surfaces have principal, owner, source path, and valid evidence anchors.
  Supplied boundaries require confirmed/rejected/unresolved reviews. Independent
  dispositions are not part of R1; durable R6 output requires exactly one
  agent-reported disposition per R1 Surface and rejects missing, extra, or duplicate
  IDs. In-process `BatchClosure` projection defaults absent records to UNREVIEWED.
  Neither representation proves host-observed reading. Path roles are not stored.
- **R2:** every hypothesis names a valid Work Unit, origin axis, seed evidence, applicable
  mechanism family, and known Surface references. It does not require every Surface to be
  copied into a Hypothesis. CG3 uses Work Unit/axis coverage, not Surface dispositions;
  the R6 ledger is an explicit Agent declaration, not observed reading evidence.
  Zero-hypothesis results retain axis evidence; the runtime does not verify which
  individual knowledge entries the Agent examined.
- **R3:** REACHABLE requires a non-empty, ordered call/dataflow chain with source evidence
  for every asserted edge, plus principal and preconditions. UNREACHABLE requires
  evidence of the blocking condition. Missing proof remains NEEDS_REVIEW. Empirical
  confirmation is only assigned through R5. Call-chain anchors must be in included
  source/build scope; supporting-evidence anchors may reference any frozen in-repository
  file. Both must point to non-blank lines. A snapshot path registry and stage-local
  line caches exist; cross-task line-count caching is absent. Collection does not
  preflight every anchor, so collected output can still fail commit. General post-commit
  verdict amendment and dependent recomputation are absent.
- **R3.5:** required refuters are distinct task identities and do not receive one another's
  conclusions. Adjudication records the disputed claim, evidence for and against, actor,
  and final disposition. Revival reopens the hypothesis and invalidates dependent terminal
  conclusions until rechecked.
- **R4:** each planned Work Unit/category pair has a COMPLETE, evidenced run or a
  structured, evidenced NOT_APPLICABLE/DEFERRED disposition. Finding count may be zero.
- `CategoryRun.finding_ids` optionally attributes canonical Findings already recorded
  for the Batch; R4 tasks do not create Findings. R4 metrics report distinct linked
  Findings separately, while canonical finding count/yield come from
  `FINDING_RECORDED` events, including Findings recorded after R5.
- **R5:** the experiment artifact records target reference, fidelity, prerequisites,
  exact commands or actions, observations, relevant artifacts, cleanup result, and final
  assessment. Dispositions are STATIC_VERDICT_RETAINED, EMPIRICALLY_CONFIRMED, REFUTED,
  NEEDS_REVIEW, and NOT_FEASIBLE. NOT_FEASIBLE requires a required experiment, no
  attempted run, a null experiment ID, and blocker evidence/rationale. It remains
  unresolved and never establishes confirmation/refutation; an inconclusive attempted
  run uses NEEDS_REVIEW with its experiment artifact. Out-of-band evidence registration
  remains unimplemented.
  A harness run without `hypothesis_id` is standalone and is ineligible for an R5
  empirical upgrade. No authorized external-observation registration contract exists.
  Failed setup is not a negative security result. Strong unsupported claims
  remain NEEDS_REVIEW.
- **R6:** all stage outputs reconcile to the Batch manifest; every open dependent Handoff,
  drift event, omitted path, and residual risk is listed. R6 closes a Batch only.

R3.5 schedulers derive refutation/adjudication targets from the committed R3 artifact.
When there are no eligible targets, schedule/commit records explicit empty-stage results
without enumerating unrelated Campaign tasks or reloading unrelated plan state. The same
short-circuit applies to zero-target revival stages.

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
Cancellation uses the latest task state, including failed/released tasks and retries;
a historical failure does not protect a later active lease from cancellation.

Every completed skill review writes `.audit_vnext/campaigns/<campaign-id>/lessons.md`
with closure `unreviewed_scope`, residual risks, limitations, and lessons. Writes append
an idempotent digest-marked section and preserve host-authored content. Skill defects are
stored separately in digest-marked, append-only sections in `skill-issues.md`, preserving
host-authored content; the global `skill-regression.json` and its
derived Markdown export are the canonical regression backlog. Repeated skill reviews
append revisions; they do not overwrite closure lessons or reject a corrected review.

Schema validation checks required fields and reference identities. Where a referenced
artifact is required, the collector resolves the artifact and verifies its digest before
accepting the stage event. Textual references that cannot be resolved are not treated as
verified evidence.

### 6.2 Reporting Projection

`CampaignCloser` derives reports from stored stage events/artifacts, not manually
assembled report updates. Coverage includes source ownership, axes, categories, Handoffs,
and declared scope decisions. It is not a complete path/Surface review ledger or a record
of every knowledge entry actually examined by an Agent.

The Campaign report includes snapshot and knowledge versions, component/language
inventory, all findings with evidence grades, NEEDS_REVIEW items, resolved and unresolved
Handoffs, unsupported adapters/toolchains, unreviewed scope, residual risks, gate results,
and budget measurements. Batch reports remain identifiable and are linked from the
Campaign view. Exported Markdown/JSON is a reproducible view; the event/artifact store
remains authoritative.

## 7. Runtime and Offline Migration Boundaries

Managed discovery task context includes approved profile entries/cards,
scheduler-authored contracts, adapter context, and generated harness recipes. The
catalog also loads source-digest provenance metadata for validation, but that metadata
is not serialized into Agent task context. Repository-controlled files and tool output
are untrusted evidence; SKILL instructs Agents not to obey embedded directions that
change audit scope, evidence rules, or host permissions. This is prompt-level guidance,
not a runtime-enforced sandbox; the host remains responsible for tool permissions and
resource limits. Offline migration is a separate tool. Task context does not include:

- v3 queue files, old schema aliases, version-specific test artifacts, and install-time
  compatibility code;
- raw project lessons, absolute paths, private project/API names, and target-specific
  expected findings;
- private held-out cases or answer manifests. Evaluation code remains in the package;
  keeping private evaluation material outside Agent access is a host obligation.

`tools/migrate_legacy_knowledge.py` is a developer-only, one-way tool. It reads selected v3 assets,
normalizes candidate concepts into draft records, and emits a migration report with
source references, rejected items, duplicates, missing fields, and provenance state. It
does not update the active catalog as part of audit execution. Reviewed publication
is selected by an operator flag, not an independently verified human-review record.
No v3 module is imported at runtime.

Publication review objectives (not universally enforced gates) include:

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
- signed held-out/synthetic labels and expected-finding adjudication attestations;
- paired v3/vNext snapshot, budget, model/tool configuration, and scope;
- no missing or duplicate runs for a required language/project stratum;
- certified language roster equals the approved 15-language portfolio;
- every required language-issue evaluation cell has its predeclared minimum evidence;
- mixed-language runs include declared language pairs/boundaries and boundary outcomes.

Authorities must keep manifests/keys outside Agent-readable scope; runtime does not
sandbox host file/prompt access. Labels and answers are trusted-signer attestations,
not independently queried protected-answer records. Reports include per-language and per-family metrics,
sample counts, uncertainty intervals where statistically meaningful, worst-group results,
and explicit `INSUFFICIENT_EVIDENCE`/`BLOCKED` states.

The top-10 language issue profiles define the coverage matrix, but not every single
project must exercise all ten issues. Held-out cases are pooled across representative
projects while preserving the 150 language-issue strata. Minimum sample counts and
promotion thresholds are frozen in policy before running the benchmark; they are not
chosen after observing results.

Implemented evaluator checks are RG1-RG15. RG12 checks provider conformance evidence,
but the runtime currently has one provider and no independent real candidate-quality
acceptance. RG13 checks signed provenance and task-input artifact links, not actual host
prompt/session isolation; RG14 cannot prove host-observed reading activity; RG15 checks
signed fixture/run evidence, not actual scale performance.
The versioned policy in runtime_policy.py owns the full required set. Passing the
implemented subset sets implemented_subset_status=PASS, not release eligibility;
status remains BLOCKED. Extra signed fields cannot enable or waive missing checks.

## 9. Acceptance and Test Design

The lists below are test objectives, not a claim of complete implementation. Synthetic
fixtures cover selected mechanics; domain parsing is not universally strict and real
capability evidence is absent. RG1-RG15 have evaluator checks but still lack independent
provider-quality, host-observation, and scale qualification.

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

This sequence is roadmap work, not a completion record. Current contracts and defects
are the baseline above and the software requirements table.

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