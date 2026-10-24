# vNext Test Plan and Requirements

## 1. Purpose

This plan defines how to verify repository behavior and how to qualify the system in a
trusted host and representative projects. Passing local tests demonstrates implementation
behavior only. It does not establish real audit capability, trusted identity, provider
budget enforcement, or release eligibility.

The plan complements [IMPLEMENTATION_COMPLETION_PLAN.md](IMPLEMENTATION_COMPLETION_PLAN.md),
[ACCEPTANCE_PLAN_VNEXT.md](ACCEPTANCE_PLAN_VNEXT.md),
[REAL_CODE_AUDIT_TEST_PLAN_VNEXT.md](REAL_CODE_AUDIT_TEST_PLAN_VNEXT.md), and
[LOCAL_TEST_HANDOFF.md](../LOCAL_TEST_HANDOFF.md).

## 2. Verification Levels

| Level | Scope | Required evidence | May close |
|---|---|---|---|
| Unit | Pure gate, parser, schema, and policy helpers | Named test, assertion output | Local logic requirement |
| Integration | Campaign/Batch lifecycle, artifacts, task/store transactions, CLI | Focused pytest module and durable event/artifact assertions | Repository-owned behavior |
| Fault injection | Failure between artifact, event, transition, and cleanup writes | Injected failure, unchanged/recoverable state, exact retry result | Recovery requirement |
| Synthetic scale | Large deterministic fixtures, concurrency, latency budget | Fixture parameters, wall time, counts, profiler or query budget | Local capacity bound only |
| Development real-target audit | Authorized frozen real source, normal R0-R6 execution, skill/workflow feedback | Scope/permission record, fresh Campaign, isolation, resource limits, task logs and source-backed results | Development workflow findings only; no trusted-host or release claim |
| Host integration | HMAC custody, identity verification, provider reservation, target-read proof | Host logs, policy/config digests, signed attestations | Host mechanics only |
| Release qualification | Held-out labels, paired representative runs, supported languages, large projects | Authority-signed evidence bundle and independent review | Release gates in RG1-RG15 |

## 3. Local Baseline

Run from the checkout under test and record the commit SHA and worktree state first.

```bash
cd /root/vnext
git rev-parse HEAD
git status --short
env -u PYTHONPATH python3 -m pytest tests -o addopts='' -q --tb=short
PYTHONPATH=src python3 -m reachable_audit compatibility-scan
git diff --check
```

A skipped test is recorded as skipped with its prerequisite; do not fabricate protected
held-out data or change labels to remove a skip. Focused tests may be run during development,
but the full suite and compatibility scan are required before changing a phase to locally
complete.

## 4. Test Requirements

### TR-01: Append-Only Stage Revision and Recovery

**Coverage:** R1-R5 deterministic revision IDs, task-output refs, upstream revision pins,
exact retry, conflict non-mutation, invalidation fan-out, stale task rejection, R3/R3.5
subledger replay, and closure stale/ancestry rejection.

**Required tests:** existing `test_batch_workflow.py`, `test_execution.py`,
`test_campaign_closure.py`, and coordinator integration tests. Fault injection must cover
R1 event append and Batch transition, R2 event append, partial R3 adjudications and final
R3 event, R3.5 final event, R4 screening and main events, R5 event, amendment/invalidation
transaction rollback, R6 event append and Batch COMPLETE transition.

**Pass:** exact retry creates no duplicate canonical projection; conflicting retry leaves
events, artifact refs, and status unchanged; a committed amendment atomically appends the
replacement plus invalidation markers; only descendants become stale; stale leased tasks
cannot claim/finalize; closure refuses missing replacements and mismatched ancestry; old
artifacts/events remain readable.

### TR-02: Compact R4 Bundle Contract

**Coverage:** v1 compatibility; v2 shared family, axis-set and task-context references;
per-item CategoryPlan, Work Unit, card allowlist, budget and hypothesis scope; canonical
CategoryRun output.

**Required tests:** `test_category_runs.py` validates v1/v2 decoding, multi-item byte size,
invalid axis/context references, task repairability, task commit, and unchanged canonical
R4 stage output.

**Pass:** serialized v2 input is smaller than the equivalent v1 input for a multi-item
bundle; invalid/missing references fail before terminalizing the lease; valid replay stores
exactly one canonical CategoryRun per CategoryAuditPlan. Old v1 task inputs continue to
parse.

**External gate:** measure v1/v2 bytes, provider token usage, and latency on representative
large projects before adopting broader compaction. Record per-bundle item count and input
artifact size; synthetic byte reduction is not real-project qualification.

### TR-03: Delegated Budget Reservation

**Coverage:** Campaign `max_delegated_agent_runs`, per-task reservation binding, concurrent
claims, reservation release on lease release/expiry, terminal usage accounting, failure
accounting, stale task exclusion, and CLI initialization.

**Required tests:** `test_execution.py`, `test_campaign_store.py`, and `test_cli.py` cover
concurrent SQLite connections, expiry/release, failed use, over-reservation, unreserved
positive usage, integer-only values, and backwards-compatible Campaigns without a cap.

**Pass:** under `BEGIN IMMEDIATE`, active reservations plus terminal delegated usage never
exceed the Campaign cap; a competing claim is denied; release/expiry returns only unused
reservation; completed/failed delegated usage remains charged; malformed or unreserved
usage cannot finalize.

**External gate:** verify provider-side hard limits and reservation/settlement with actual
provider calls. Local SQLite caps are not provider enforcement.

### TR-04: Host Worker Attestation

**Coverage:** HMAC envelope binds Campaign, Batch, Task, attempt, lease expiry, worker,
delegated workers, and delegated usage; invalid signature, schema, worker, attempt, expiry,
and replay behavior.

**Required tests:** `test_execution.py` exercises missing/forged/mismatched signatures,
expired leases, cross-attempt replay, and valid attestation.

**Pass:** invalid attestations fail before finalization; lease expiry/replay cannot
terminalize a task; accepted payload exactly matches the active lease and result.

**External gate:** trusted host key generation, storage, rotation, worker/reviewer identity
verification, and incident recovery must be proven by a host integration run. An HMAC
signed by an untrusted local worker does not authenticate that worker.

### TR-05: R5 External Observation Provenance

**Coverage:** authority signature; Campaign/target/snapshot/Batch/hypothesis binding;
observer, method, timestamp, artifact ownership and digest validation; evidence-only
semantics; citation through R5, closure, and release evaluation.

**Required tests:** `test_batch_closure.py` covers registration, the negative
scope/ownership/digest/signature matrix, non-promotion of NEEDS_REVIEW, post-close
retention, and campaign-report citation; `test_campaign_closure.py` covers campaign
closure gates/reporting; `test_evaluation.py` covers release-evidence citation and
digest/manifest-signature rejection.

**Pass:** unsigned, wrong-scope, changed-digest or unauthorized references fail; valid
observations retain signature and artifact references while never upgrading an R5
assessment on their own.

**External gate:** authority-held signing key, independently verified observer identity,
and the authority's real accept-path retest. Repository tests cannot establish custody or
independence.

### TR-06: CLI and Campaign Closure Behavior

**Coverage:** each CLI command family, canonical JSON and errors, Campaign close/abort,
all CG1-CG10 decisions, stage stale/ancestry gates, and durable artifacts.

**Required tests:** `test_cli.py`, `test_campaign_closure.py`, `test_batch_closure.py`, and
`test_snapshot_drift.py` pin output, exit codes, cleanup, report idempotence, gate details,
and correction/retry paths.

`test_cli_launcher.py` verifies the checkout CLI entry from another working directory,
target paths containing spaces, durable state reopening and propagated errors.
`test_execution.py` and `test_batch_workflow.py` verify HIGH/LOW inspection-altitude
checks and repair behavior; prompt and full-revival selection tests establish contracts,
not real recall or physical worker-context isolation.

**Pass:** extracted helpers preserve existing report fields, ordering, exit behavior, and
failure semantics; no broad exception handling hides state or cleanup failures.

### TR-07: Synthetic Scale and Ordering

**Coverage:** 30k Handoffs with large evidence artifacts, bulk transaction rollback,
30k task ordering, 1k-file R1/R3 review and evidence validation, and zero-target R3.5
short-circuit latency with 30k unrelated Campaign events.

**Required tests:** `test_handoffs.py`, `test_campaign_store.py`,
`test_batch_workflow.py`, and `test_execution.py`.

**Pass:** exact counts reconcile; failure leaves no partial batch write; oldest submitted
task remains first; all 1k paths are represented and R3 anchors validate; zero-target
schedule/commit completes under the declared 2-second local budget without task listing or
Campaign-wide scans.

**Interpretation:** synthetic results establish bounded implementation behavior only.
They do not certify real storage, provider, host, or large-repository capacity.

### TR-08: Language and Held-Out Release Gates

**Coverage:** all supported language strata, every language/issue cell, held-out mixed
language boundaries, paired v3/vNext runs, signed evidence and release gates RG1-RG15.

**Local tests:** `test_evaluation.py` verifies missing/duplicate/extra languages, missing
issue strata, invalid signatures/digests, and gate fail-closed behavior using synthetic
fixtures.

**Pass:** local evaluator behavior fails closed and preserves evidence references. This is
not a release pass.

**External gate:** independent held-out labels, evaluator-authority signature, paired real
runs, target-read proof, 20GB+ repository evidence and host-reviewed findings must be
supplied and independently reviewed. Never mark synthetic fixtures as real or held-out.

### TR-09: Finding Classification and Large-Source Preflight

**Coverage:** finding classification is explicit; security-vulnerability reports carry
structured, resolvable impact references; reports separate Agent-classified confirmed
security-vulnerability claims from ordinary defects and hardening; planning flags
individual included sources at or above the 1 MiB advisory threshold.

**Required tests:** `test_batch_closure.py`, `test_campaign_closure.py`, `test_cli.py`,
and `test_execution.py` cover recording/rejection, report totals, the large-file
preflight field, and R2 task guidance.

**Pass:** incomplete/non-security findings cannot be counted as Agent-classified
confirmed security vulnerabilities; planner measurement failures are surfaced rather
than converted to zero; the warning names the affected path and Work Unit. This is a
structural classification gate, not a semantic classifier: it does not establish that
the evidence is relevant, that the threat model is correct, or that a finding is
exploitable. Real-target reporting must separately record independent review of each
security-impact declaration before calling it independently validated or release-ready.
The warning is advisory and does not prove R2 completion or physical inspection.

**External gate:** on representative large-source targets, verify full-scope R2
completion under recorded context/time limits or obtain an approved deferred-scope
decision and reconcile it in Campaign closure. Predeclare important helper-level
entrypoints and require source-backed call/guard/sink evidence before making recall
claims. The engine does not observe reads or enforce line-range completeness.

### TR-10: Evidence-First Qualification Before Capability Development

TR-10 is a development-entry gate for capabilities whose correct behavior depends on
target language/framework conventions or actual model/context limits. It is not a
release gate and must not be satisfied by synthetic tests alone.

**Hotspot-provider test-first matrix:** before implementing or enabling each additional
language provider, freeze a representative, legally usable sample corpus and label
expected candidate sites independently. Add positive, negative (including comments,
strings, and lookalikes), alias/import, malformed-source, encoding, and snapshot-drift
cases. Measure candidate coverage and precision against reviewed labels; retain each
sample's language, framework, rule, expected sites, observed candidates, and evidence
reference. Synthetic fixtures must pass first; held-out results are reported separately
and cannot be inferred from the fixtures. Go and Java currently have experimental
opt-in providers; that does not imply default enablement. Keep provider availability,
real-target workflow coverage, and language qualification as separate assertions.
Update unsupported-provider expectations only when that provider's implementation and
the corresponding tests actually change.

### TR-16: Remaining Top-15 Language Development Pilots

The operator reports real-project tests for C, C++, Go and Java. Record their Campaign
and evidence references in the run ledger; do not infer provider certification from
those workflow pilots. The remaining development-pilot set is **C#, Rust, Python,
JavaScript, TypeScript, Kotlin, Scala, PHP, Ruby, Swift and Shell**. The detailed
sequence, project markers and run protocol are in
[REAL_CODE_AUDIT_TEST_PLAN_VNEXT.md](REAL_CODE_AUDIT_TEST_PLAN_VNEXT.md).

For each language, use a distinct fresh Campaign on a legally authorized, frozen
representative repository/component, run R0-R6, and select the language's ten issue
profiles from the versioned catalog. Review each profile as applicable, not applicable
or deferred with a current-snapshot rationale; do not target a finding count. Record
source/build inventory, component/path coverage, unsupported or unparsed files, R1/R2
evidence, R3/R3.5/R4 decisions, R5/R6 results, handoffs, resource use, and independently
reviewed source-backed candidate/false-positive dispositions. A project with no
vulnerability candidates may still pass workflow checks; it cannot establish recall
without independent expected labels. A candidate count or successful Campaign alone
does not establish language capability.

**Pilot pass:** scope is fully accounted for or explicitly deferred; required stages
complete without bypassing contracts; build/component boundaries and language paths
are not silently lost; all ten issue profiles have recorded dispositions; evidence and
resource records are reviewable; every surfaced candidate has a source anchor and
independent disposition or is clearly unresolved; limitations and unsupported paths
are explicit. **Fail:** a reproducible contract/data-integrity defect, silent scope
loss, unsafe execution, or unsupported claim occurs. **Blocked:** authorization,
representative source, evidence, or required toolchain is unavailable. None of these
pilot outcomes is a release qualification.

After the 11 pilots, run a separate mixed-language Campaign with at least one
source-to-destination boundary in scope, and separately measure large-project
capacity. Release qualification still requires the per-language/per-issue held-out
sample floors in [ACCEPTANCE_PLAN_VNEXT.md](ACCEPTANCE_PLAN_VNEXT.md), independent
adjudication, and signed evidence; do not pool these exploratory pilots as held-out
samples.

### TR-17: Discovery-quality paired evaluation

Use [DISCOVERY_QUALITY_EVALUATION_PROTOCOL.md](DISCOVERY_QUALITY_EVALUATION_PROTOCOL.md)
before treating a proposed discovery aid as a recall improvement. The protocol is a
design, not evidence that a benchmark exists or has passed. The first implementation
slice adds a non-gating report metric linking explicitly HIGH-risk R1 Surface
declarations to R2 hypothesis `surface_ids`; it does not score vulnerability recall,
validate Agent-declared reading, or interpret unmapped Surfaces as safe or missed.

For an actual paired evaluation, the trusted evaluator must supply frozen vulnerable
snapshots, separately protected expected labels, independent candidate adjudication,
and equal baseline/treatment execution budgets. Test one treatment at a time (such as
an optional sink census); keep issue labels, patches, and expected locations outside
Campaign/task context. Report per-language and per-mechanism paired recall, reviewed
false-positive burden, scope coverage, completion, and costs. Record underpowered
strata and unresolved evaluator disagreements. Do not enable a treatment by default or
set universal thresholds from the development pilots. Mutation fixtures are secondary
mechanism tests and cannot substitute for the vulnerable-snapshot benchmark.

**Large-source R2 test-first matrix:** on an authorized representative file, record the
frozen digest, byte/line counts, task-input bytes, model/context limit, token and wall
time, inspected line ranges (if available), evidence anchors, and completion/defer
decision. Predeclare helper/entrypoint and sink anchors. A qualifying result requires
all source ranges accounted for without overlap or gaps, or an explicit approved
deferred disposition; `reviewed_scope: ALL_SOURCE_FILES` alone is not measured line
coverage. Use the observed failure mode to define slice boundaries and reconciliation
before writing implementation tests. The current planner test is only an advisory-
warning test.

**Cross-language boundary test-first matrix:** in a representative mixed-language
target, inventory actual FFI, RPC, IPC, serialization, generated-code, and shared-data
mechanisms. For each sampled edge, retain source and destination anchors, language pair,
protocol/framework, direction, trust boundary, expected owner and route, and whether
current discovery found it. Include negative/unrelated dependency cases. Only then
specify detector behavior and add synthetic regression fixtures; measure misses and
false positives on a separate reviewed sample.

**Pass before implementation:** the target/sample, labels, metrics, known limitations,
and acceptance thresholds are predeclared and retained as an evidence bundle. If an
authorized representative sample is unavailable, mark the capability **BLOCKED on
target evidence**; do not implement a speculative detector or report a synthetic pass
as capability evidence.

### TR-11: Cross-Stage Coverage and Finding Reconciliation

**Coverage:** R2 requires an explicit predeclared entrypoint checklist and exactly one
source-backed disposition per checklist ID on its specified axis; R4 requires exactly
one evidence-linked disposition per scoped hypothesis and exact reconciliation of
previously recorded Findings in applicable CategoryRuns; R6 requires exactly one review
per recorded Finding and reports R3.5/R4 disposition disagreements.

**Required tests:** `test_execution.py` covers checklist parsing, per-axis and compact
task collection, exact ID coverage, evidence anchors, and explicit empty checklists.
`test_category_runs.py` covers R4 hypothesis and Finding coverage for individual and
bundled CategoryRuns. `test_batch_closure.py` covers R6 review coverage, evidence
references, disagreement reporting, and the distinction between Agent assertions and
independent human review. `test_cli.py` covers the required checklist argument.

**Pass:** missing, duplicate, extra, or unsupported references fail without silently
accepting a task; valid outputs preserve canonical R2/R4/R6 artifacts and reports.
These structural checks establish identity and traceability only; they do not prove
that evidence semantically supports a disposition or that the Agent's analysis is
correct.

### TR-12: Caller-Supplied Residue Policy for Offline Migration

**Coverage:** The developer-only knowledge migration tool must not embed a blacklist of
historical target/project names. It requires a reviewer/evaluator-supplied token file,
uses those tokens to exclude matching source entries, and rejects any matching residue
in generated runtime assets.

**Required tests:** `test_knowledge_migration.py` verifies that the CLI refuses to run
without the token-file argument, excludes a synthetic caller-supplied project token,
reports the excluded source record, and does not publish the token in generated assets.

**Pass:** no repository-owned target-name list is used by migration; an explicitly empty
file is accepted as an explicit no-additional-token decision. This scan is only a
pattern-based safeguard; it cannot prove that a concept is semantically portable.

### TR-13: Pilot-Driven Closure and Execution Reliability

**Coverage and required tests:**

- `test_campaign_closure.py`: reproduce a Batch with unresolved scope and an empty
  Campaign declaration; preserve the item, Batch provenance, Markdown, lessons and
  exact retry. A Finding recorded after R4 must join by hypothesis ID; unrecorded
  candidates without consistent rejection remain unresolved, not silently dropped.
  Missing execution attempts/usage/configuration/limits must not produce resource
  PASS; elapsed deadline breaches produce FAIL independently of workflow PASS.
- `test_refutation.py`: UPHOLD counts as reviewed, not overturned; test all revival
  outcomes, retain the legacy reviewed-list alias and exact retries.
- `test_execution.py`: the R3 contract states ordered pure source anchors and external
  runtime-assumption evidence requirements; poll timing distinguishes expired leases
  without inventing worker liveness; claim deadlines reject invalid/expired budgets
  and preserve result collection/recovery.
- `test_cli.py` and `test_hotspots.py`: external state selection and legacy recovery,
  cwd-independent explicit paths, R6 list output with compatibility, positive init
  deadline, and unsupported-only/mixed/zero-result/parse-error provider reporting.

**Pass:** the named regression tests and full suite pass; there are no target-specific
runtime branches, known-target blacklists or expected-finding quotas. Workflow PASS
must not be interpreted as resource PASS or independently confirmed security impact.
Host dispatch confirmation, actual worker stopping, complete provider metering and
independent reviewer identity still require real host evidence.

### TR-14: Experimental Go Leads and Managed Runtime Evidence

**Development entry:** the real Go pilot established missing automatic leads and an
unconnected empirical path. These justify a bounded candidate provider and reuse of
the existing harness, not broad language certification or a new experiment system.

**Provider requirements:** parse Go with its standard parser, use generic imported
standard-library call sites and source anchors, and remain an explicit frozen opt-in
for new development Campaigns. Test positive/negative/aliased/shadowed calls, comments
and strings, malformed input, unavailable toolchain, snapshot drift, mixed-language
coverage and truncation. The helper must not execute target packages or resolve their
dependencies, and its process, input, output and temporary resources must be bounded.

**Integration requirements:** CLI opt-in persists in the Campaign; R1, compact R2 and
per-axis R2 use that same selection and R0 digests. Default Python-only behavior and
the release-qualified provider roster remain unchanged. Installed package data must
include the trusted Go helper; a checkout-only success is insufficient.
Run `tests/test_hotspots.py` and `tests/test_go_provider_integration.py` together.
Keep Go optional: environments without the toolchain must exercise explicit
unavailable-provider behavior; Go-enabled validation must record the actual toolchain
and must not count toolchain-dependent skips as passing parser execution.

**Empirical requirements:** execute a synthetic, authorized offline Go probe through
`run_harness`, bind to a hypothesis and verify execution/stdout/stderr references,
actual exit/output, cleanup and unchanged source. Use explicit Go-compatible address
space and offline environment (`profile="go-offline"` in the API or harness JSON),
not a silent default memory increase. Verify CLI forwarding as well as the library
path; ordinary default limits and explicit overrides must remain intact. Where an R5
upgrade is exercised, show both eligible confirming evidence and a nonconfirming or
failed path that cannot upgrade. A successful process exit alone is not proof of a
security vulnerability. Timeout and truncated-output reports explicitly marked
ineligible must fail the actual R5 evidence validator. Complete nonzero-exit
observations can remain reviewable crash evidence, without automatic confirmation.
Run `tests/test_go_harness_runner.py`, `tests/test_harness_runner.py`,
`tests/test_refutation.py` and `tests/test_go_provider_integration.py` together.

**Real-target exit:** independently adjudicate candidate sites and false positives
on predeclared frozen scopes before enabling Go by default or claiming measured
precision/recall. Retest the actual host's harness registration, isolation and resource
policy. Synthetic Go probes establish execution mechanics, not target exploitability.

### TR-15: Scope, Evidence and Interrupted Java-Pilot Work

**Scope projection:** synthetic mixed-scope fixtures must prune wholly outside edges
and otherwise empty obligations, retain both directions of cross-scope dependencies,
respect concrete endpoints, and round-trip/amend plans without losing exclusions.
Keep truly empty roots and manifest-only behavior; explicitly excluded/deferred-only
inventories may produce zero Batches. Read-only replay of a prior probe is planning
evidence only, not a newly executed full audit.

**Evidence:** register supporting files before first R0 with safe paths and bounded
sizes; reject replacement, post-R0 registration, source/resource digest drift, invalid
LOC lines, blank lines and missing artifacts. Test concrete references nested inside
axis and hypothesis reviews, on direct, individual, bundle and screening paths.
Legacy symbolic IDs are not verified source proof. R3 must expose the true nested
contract and an example parseable as a VerdictSubmission, without preselecting a
positive verdict. Test the resource CLI as well as manager APIs.

**Recovery and budget:** ordinary expired collection stays rejected. Explicit recovery
must bind original claim/worker/attempt/output, preserve attestation and normal
schema/measurement/budget checks, reject stale/superseded/terminal/closed work, and
consume authorization transactionally with rollback on failure. A deadline must not
block collecting existing results. Monotone approved extensions retain original start
time/budget and breach history; test actual resumed claims and final report FAIL
against the original limit separately from the approved limit.

**Static challenge:** default behavior remains edge-proven only. Frozen opt-in must
schedule both perspectives for static-only REACHABLE, require normal adjudication
coverage and preserve the static grade. Disabled static challenges must be visible.

**Java provider:** use trusted JDK parse-only synthetic fixtures for generic command,
deserialization and stream/archive call sites; comments/string lookalikes must not
match. Explicitly retain unresolved-receiver/same-name limitations. Test default-off,
all R1/R2 paths, unavailable tools, UTF-8/parser failures, snapshot drift, caps and
installed wheel resources outside the checkout. Run `tests/test_provider_workspace.py`
with both target root and `TMPDIR` set to the audit tree; assert Go/Java helper caches
and temporary workspaces stay outside it, target paths/content do not change, private
permissions and cleanup hold, and filesystem/file-descriptor limits are applied.
Unsafe scratch-root availability must fail explicitly. Never compile/load target
classes or run processors. Go behavior must survive shared process-runner extraction.

Run `tests/test_planning.py`, `tests/test_plan_amendment.py`,
`tests/test_resource_evidence.py`, `tests/test_category_runs.py`,
`tests/test_task_recovery.py`, `tests/test_budget_amendment.py`,
`tests/test_refutation.py`, `tests/test_execution.py`, `tests/test_campaign_closure.py`,
`tests/test_java_hotspots.py`, `tests/test_hotspots.py`,
`tests/test_go_provider_integration.py`, `tests/test_provider_workspace.py` and
`tests/test_helper_residue.py`.
Full suite and compatibility scan remain required. Runtime residue scanning includes
packaged Go/Java helpers as well as Python, main Skill and eligible knowledge.

**Qualification still external:** real-host interruption/termination, authentic approval,
usage truth, Java lead precision/recall, mixed-language misses and representative large
source/20GB+ behavior. This local contract is not Google approval or ISO conformity.

## 5. Evidence Record

Every test report records:

- Engine commit SHA, worktree state, Python/runtime versions and exact command.
- Test IDs, exit code, passed/failed/skipped counts, failure output and injected boundary.
- For scale tests: fixture size, event/file/task counts, wall time, and resource limits.
- For host runs: target snapshot, Campaign/Batch IDs, model/tool versions, permissions,
  worker identity evidence, budget policy and signed artifact refs.
- For release runs: signed manifest, evidence digests, held-out policy, reviewer identity
  and explicit failed/blocked gates.

Never record HMAC keys, provider credentials, or protected held-out labels in the
repository. Mark unavailable external prerequisites `BLOCKED` with the owner and evidence
needed; do not convert them to `PASS` through mocks.

## 6. Stop/Exit Rules

A local implementation phase closes only when its required tests pass on the same commit
and the full suite/compatibility scan pass. A host/release phase closes only with its
external evidence and independent review. If any stage changes output, event ordering,
report fields, or budget semantics, rerun all tests in the affected requirement and the
full suite before updating the completion plan.
