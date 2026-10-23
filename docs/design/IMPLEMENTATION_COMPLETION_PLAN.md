# vNext Implementation Completion Plan

## Purpose

Finish repository-owned design requirements before treating representative-project
audits as the only remaining work. Synthetic tests establish implementation behavior;
they do not substitute for host attestation, held-out campaigns, or release qualification.
The executable test requirements and evidence rules are in
[TEST_PLAN_VNEXT.md](TEST_PLAN_VNEXT.md).
The real-target pilot and release qualification procedure is in
[REAL_CODE_AUDIT_TEST_PLAN_VNEXT.md](REAL_CODE_AUDIT_TEST_PLAN_VNEXT.md).

## Ordered Work

### 0. Repository-Owned Gaps and Evidence-First Work

The following work is deliberately separated by what evidence can establish:

| Work item | Current state | Next action |
|---|---|---|
| Offline migration residue policy | **Fixed in this iteration.** The migration tool no longer embeds a blacklist of historical project names; it requires a reviewer/evaluator-supplied token file and uses it for candidate exclusion and output validation. | Retain the explicit token input and pattern-based limitation; do not reintroduce project-specific defaults. Verify with TR-12. |
| Finding classification gate and large-source preflight | **Locally implemented and covered by synthetic regression tests (TR-09).** The planner warns at the configured threshold; it does not measure R2 read coverage. A 2026-10-22 development audit completed one >1 MiB source-file R2 task, but also recorded helper-level recall gaps and Agent classifications that were not independently reviewed. | Do not treat structural Finding validation as semantic classification. In the next authorized pilot, predeclare helper entries under the current policy, reconcile actual R2/R6 dispositions, and independently review each security-impact declaration. Keep uncovered source explicitly unreviewed/deferred; do not infer line coverage from a completed task. |
| Additional language hotspot providers (SWDR-031) | Python AST provider is active. The Go pilot established an automatic-lead gap, permitting a bounded experimental Go AST slice, not portfolio-wide enablement. | Use explicit Campaign-frozen opt-in for development only; verify positive/negative/alias/shadow/malformed-source and snapshot identity fixtures before trial. Independently reviewed candidate coverage and precision remain required before qualification. |
| Large-source R2 slicing and completeness claims (N-6) | Preflight warning and bounded-read guidance exist; no line-range coverage ledger or automatic slicing contract exists. | First measure an authorized representative large file's task input size, runtime, context use, candidate/evidence distribution, and full-scope result. Then specify slices and reconciliation rules from observed failure modes; add regression tests before implementing them. |
| Automatic cross-language boundary discovery (SWDR-010) | Typed boundary records, build/import proposals, owner review, and Handoff proof exist; automatic FFI/RPC/IPC/serialization discovery is incomplete. | First inventory real boundary mechanisms and observed misses in an authorized mixed-language target. Define framework-specific evidence and false-positive expectations before adding detectors. |
| Host identity/key custody, provider-enforced hard limits, authority keys, and independent held-out release evidence | Repository mechanisms are partial or intentionally rely on external authorities. | Remain blocked on the named host, provider, or evaluation authority; repository-only code and mocks cannot close these items. |

This table is the implementation decision: TR-09 is the locally implementable
repository-owned work completed in this iteration; the remaining capability gaps either
need target-specific evidence before their behavior can be specified safely or require
external authority. Development-only pilots may proceed under
[REAL_CODE_AUDIT_TEST_PLAN_VNEXT.md](REAL_CODE_AUDIT_TEST_PLAN_VNEXT.md) without claiming
release qualification.

#### Evidence-ready development after the Go pilot

The supplied pilot on engine `f1ec0bc` exercised one Batch, 369 source files and
182 completed tasks, predominantly Go, with no automatic Go hotspot leads and no
executed R5 experiments. This unlocks two bounded items:

1. An explicit experimental Go AST provider for generic standard-library call sites,
   supplied through normal R1/R2 task context. It must parse supplied snapshot bytes,
   never build/import/execute target packages, never use target function names, and
   emit review candidates rather than vulnerability verdicts. Default production
   provider and release-acceptance scope must not silently expand.
2. A real offline Go probe through the existing registered harness and R5 evidence
   path, with explicit memory/CPU/time/output policy and unchanged source. Reuse the
   existing runner rather than create a second experiment engine. A probe that cannot
   start or yields inconclusive output cannot count as a confirmed experiment.

The earlier TR-13 workflow repairs are already locally implemented. No new generic
FFI detector or automatic large-file slicing is unlocked by this single-Batch trial:
it had no qualifying large-source flags or measured mixed-language boundary misses.
Collect those specific observations rather than require another undirected full audit.
The executable local acceptance for this increment is TR-14.

#### Latest real-target evidence and version boundary

The 2026-10-22 development audit evidence bundle is digest-verified and records
engine `5d7dd33` plus the TR-09 worktree, policy `vnext-task-policy-37`, and one
completed Batch from a larger mixed-language source snapshot. R2 completed in 532
seconds on a source file larger than 1 MiB and emitted nine hypotheses. This is useful
evidence that the advisory preflight can be followed by a successful task in one case;
it does not establish complete file coverage, general large-file capacity, full-project
coverage, or a 20GB+ recovery result.

The same run recorded 61 R1 Surfaces across a 39-file Batch, but only 17 files had an
R1 Surface; R2 evidence was concentrated in seven files, and R6 left 23 Surfaces
UNREVIEWED. Predeclared helper checks found missed iterator-helper, JSON, evaluation,
and examples boundary paths. R4 included a semantically off-target category rationale.
The Finding structure accepted security-impact declarations whose classification was
subsequently questioned; independent human review was not performed, and no dynamic
experiment ran. The second Batch was not started. Treat these as explicit limitations,
not full-audit success or proof that any finding is exploitable.

This evidence predates the current `vnext-task-policy-38` R2/R4/R6 cross-stage
traceability contract. Therefore it neither validates nor invalidates that newer
contract. The next development pilot should execute `RTA-38-LARGE-01` from
[REAL_CODE_AUDIT_TEST_PLAN_VNEXT.md](REAL_CODE_AUDIT_TEST_PLAN_VNEXT.md) against the
current engine, with predeclared helper IDs, exact task outputs, reconciled unreviewed
scope, measured per-Batch capacity, and separately recorded human review of
security-impact claims.

### 1. Stage Revision, Invalidation, and Recovery

Status: **LOCAL IMPLEMENTATION AND SYNTHETIC ACCEPTANCE COMPLETE**. R1-R5 projection
events carry deterministic revision IDs,
exact source task-output refs, and upstream revision pins. R1/R2/R4 main/R5 preflight
exact retries before artifact writes; R3 adjudication and R4 screening retain partial-
write/exact-retry protection. Post-commit R1-R5 task-output amendments append the
replacement and dependent-projection invalidation markers in one SQLite batch transaction.
Downstream TaskSpecs and task IDs bind consumed revisions; coordinator commits ignore
stale tasks; R3.5 ledgers are revision-aware; Campaign closure blocks unresolved
invalidations and stale ancestry. Full-Batch Plan Amendment remains the quiescent replay
path when task evidence cannot be safely reused.

The tested amendment matrix proves descendant invalidation and preserves unrelated
CategoryAuditPlan projections. Fault injection covers partial R3 adjudications, R1-R5
projection writes, R1 Batch status transition, atomic amendment/invalidation writes, and
R6 event/Batch completion recovery. Append-only history and terminal R6 amendment behavior
are preserved. Representative-host amendment behavior remains part of external release
qualification, not a local unit-test claim.

Acceptance: fault-injection tests at every write boundary; exact retry is idempotent;
conflicting retries do not mutate state; full-Batch replay preserves old history and
uses new IDs; in-place amendment after R1 invalidates R2 through R6, and amendment after
each later stage invalidates only its descendants; closure fails until affected
projections are recommitted. Existing terminal R6 behavior remains intact.

### 2. Compact R4 Task Payloads

Status: **LOCAL WIRE AND SYNTHETIC ACCEPTANCE COMPLETE**. R4 AxisRun Work Unit IDs may
be omitted and are inherited from the parent CategoryRun; explicit mismatches fail, and
canonical stage artifacts retain the complete ID. Bundled mechanism-card definitions and
repeated language/knowledge contexts are serialized once at bundle scope; v2 category
items inherit family and reference shared axis sets while retaining per-item plan, Work
Unit, card allowlist, budget, and hypothesis scope. The v1 bundle parser remains
supported. No additional local schema change is planned without representative size data;
real-project bundle-size qualification remains external.

Keep one canonical persisted CategoryRun per CategoryAuditPlan and preserve per-item
identity, allowed-hypothesis, altitude, and coverage validation across both wire versions.

Acceptance: old and compact forms have an explicit versioned contract; round-trip tests
prove byte-size reduction on multi-item bundles; omitted or mismatched references fail
while the task remains repairable; R4 reports remain unchanged.

### 3. Host Identity and Delegated Budgets

Status: **LOCAL RESERVATION MECHANICS IMPLEMENTED; IDENTITY ACCEPTANCE PARTIAL**. A
Campaign may set `max_delegated_agent_runs`; SQLite atomically reserves task-declared
delegated usage with each lease, counts completed/failed usage, frees released/expired
reservations, and excludes stale-revision tasks. Task reservations must fit within
`agent_runs`, and positive delegated results require an explicit reservation. Campaigns
can also opt into a host-wrapper HMAC bound to task/attempt/lease/worker/delegate fields.
Forged signatures, lease/worker mismatch, expired leases, replay across attempts,
over-reservation, unreserved delegated use, and concurrent over-allocation are rejected.
Host identity trust, key custody, and provider-side enforcement remain external.

Complete host-verified worker/reviewer identity integration and provider-side hard budget
reservations. Runtime claims must bind to a signed or host-verified identity and budget
envelope; labels alone must never count as authentication. Keep provider hard limits
distinct from estimates.

Acceptance: forged, expired, replayed, over-budget, or unbound attestations fail before
dispatch/finalization; concurrent workers cannot oversubscribe reserved budgets. Actual
identity and provider enforcement require a host integration acceptance run.

### 4. R5 Out-of-Band Evidence Provenance

Status: **LOCAL PROVENANCE PATH AND SYNTHETIC ACCEPTANCE COMPLETE; AUTHORITY ACCEPTANCE
EXTERNAL**. `r5-observation-register` verifies a host-authority HMAC and binds an observation to
Campaign/snapshot/Batch/hypothesis, observer/method/time, and Campaign-owned artifact
digests. Registration is evidence-only and cannot upgrade R5; matching observations enter
R5 task context, assessments may cite them without promotion, and citations plus signed
payloads survive Campaign closure and release evidence output. Authority key custody,
independently trusted observer identity, and real accept-path qualification remain
external.

The external accept-path must continue treating a string reference as non-proof and bind
observations to hypothesis, snapshot, target, observer identity, method, timestamp,
artifact digests, and an authority signature. Keep them distinct from managed harness
confirmation unless policy explicitly accepts the signed evidence class.

Acceptance: missing/invalid signatures, wrong snapshot/target/hypothesis, digest changes,
and unauthorized evidence classes fail; valid evidence preserves provenance through
R5, closure, and release reports. A real authority-held key and accept-path retest are
external prerequisites.

Local regression coverage now includes the negative registration matrix (snapshot,
target, Batch, hypothesis scope, evidence ownership, missing versus tampered digest,
and forged signature; each rejection leaves no observation event), post-Campaign-close
registration rejection with evidence retention and citation after reopen, refusal to
upgrade `NEEDS_REVIEW` to empirical confirmation from an observation alone, and
release-evaluation citation plus digest/manifest-signature validation of signed
observation evidence (`tests/test_batch_closure.py`, `tests/test_evaluation.py`).

### 5. Output Density and Structural Debt

Status: **LOCAL IMPLEMENTATION AND SYNTHETIC ACCEPTANCE COMPLETE**. Campaign
screening/substantive classification and ceiling state are pure and boundary-tested. All
CLI command families dispatch through focused handlers, including R3.5, R4/R5, Finding,
R6, signed observation registration, drift resolution, and Batch addition. CampaignCloser
gate decisions CG1-CG10 are decomposed into bounded helpers or explicit stale/ancestry
checks with direct behavior tests. R4 v2 removes repeated Work Unit/category/axis and
language/knowledge context fields while preserving v1 parsing and canonical reports.
Scoped CLI and CampaignCloser code has no catch-all Exception/BaseException handlers.

No additional local Phase 5 implementation remains. Real-project bundle sizing belongs to
Phase 2 qualification; synthetic scale and signed release runs belong to Phase 6.

Acceptance: preserved CLI reports/errors; direct tests per handler/gate; no widened
exception swallowing; byte reduction measured on multi-item bundles.

### 6. Scale and Release Qualification

Status: **LOCAL SYNTHETIC ACCEPTANCE COMPLETE; REAL-RUN QUALIFICATION EXTERNAL**. Local
tests cover 30k Handoffs with large evidence artifacts, 30k atomic rollback, oldest-first
task ordering, zero-target R3.5 latency under 2 seconds with 30k unrelated events, 1k-file
R1/R3 validation, all supported language strata, held-out mixed-language fixture gates,
and a large-campaign evidence fixture.

Remaining work is signed real-run acceptance using representative repositories and
independent held-out labels. Real project access, evaluator authority signatures,
host-read proof, and large-run capacity are external evidence; local synthetic tests cannot
mark these gates complete.

### 7. Cross-Stage Coverage and Finding Reconciliation

Status: **LOCAL CONTRACT AND SYNTHETIC REGRESSION TESTS IMPLEMENTED; SEMANTIC REVIEW
REMAINS AGENT/OPERATOR WORK**. R2 scheduling requires an explicit JSON checklist for
predeclared entrypoints, including an explicit empty array when none are known. Task
collection and stage commit require exact per-axis reviews with source anchors. R4 task
inputs include the scoped hypotheses and existing Findings; CategoryRuns must provide
one evidence-linked disposition per hypothesis and reconcile each applicable Finding.
R6 receives the canonical Finding set, requires one review per Finding, and reports
R3.5/R4 disposition disagreements and review-state counts. Reports explicitly state
that these reviews are Agent assertions, not independent human validation.

Acceptance: compact and per-axis R2 reject missing/duplicate/extra checklist IDs and
wrong source anchors; R4 individual and bundled tasks reject incomplete or cross-scope
hypothesis/Finding reviews; R6 rejects incomplete or duplicate Finding reviews and
preserves disagreement details in closure output. Evidence-reference and schema checks
do not verify semantic relevance, exploitability, or the truth of Agent assertions.
The host runner must deliver the task input and output contract unchanged; representative
real-target recall and independent human review remain external evidence.

## Current Test Gates

2026-10-23 follow-up: TR-13 repairs Batch-to-Campaign unresolved-scope inheritance,
per-hypothesis outcome visibility, revival summary semantics, task contracts,
state isolation defaults, provider reporting and local deadline/lease observability.
Workflow closure remains separate from resource and semantic qualification.
Final integrated verification passed **385 tests with 1 skipped in 39.96 seconds**
with pytest plugin auto-loading disabled. Compatibility scanning (zero findings),
Python syntax, local document targets and diff formatting pass. The skip requires
an unconfigured protected real held-out manifest. Details and a read-only replay of
the original outcome records are in the current generality review. Do not reuse the
earlier pilot as evidence that these changes passed real-host testing.

After the TR-12 offline migration residue-policy change, the focused migration/CLI/
experiment tests passed **45 tests** and the full suite passed **359 tests with 1
skipped in 42.96 seconds** with pytest plugin auto-loading disabled to avoid shared-host
memory pressure. A preceding default-plugin full-suite attempt was terminated by
SIGKILL (exit 137); the successful rerun is the verification result. The skipped
held-out test requires a protected manifest not configured locally. The latest
compatibility scan passes with no findings (49 Python files, 167 knowledge files,
1 prompt file); syntax, CLI help, Markdown links, and `git diff --check` pass. These
are working-tree checks, not a clean-commit or real-host qualification.

Phase 2 local gates now cover v1 compatibility, v2 compact multi-item serialization,
measured byte reduction, repairability after invalid references, and canonical R4 reports.
Before closing Phase 2, measure representative large-project bundle sizes. Phase 3 local
tests cover forged/unbound HMAC envelopes, expiry, replay, concurrent oversubscription,
release/expiry reclaim, failed-use accounting, reservation bounds, and stale-task exclusion.
Only host identity trust/key custody and provider hard limits require integration evidence.
Phase 4 local tests cover invalid signatures/scope/digests and trace valid provenance
through R5, closure, and release output. Only authority-held keys, independently trusted
observer identity, and the real accept path remain external. Phase 5 and Phase 6 local
synthetic acceptance tests pass; Phase 6 still requires signed real-run evidence.

External waiting items are host trust/key custody, provider-side hard budget reservation,
authority-held R5 signing keys, independently trusted observer identity, target-read
proof, held-out labels, supported-language strata, and representative large-project
capacity. These cannot be marked complete by repository unit tests.

## Execution Rule

Work proceeds in the order above. Each item is implemented, tested, documented, and
committed before moving on. A phase is not marked complete merely because its synthetic
unit tests pass when its stated external acceptance remains outstanding.