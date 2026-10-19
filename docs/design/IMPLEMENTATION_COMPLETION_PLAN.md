# vNext Implementation Completion Plan

## Purpose

Finish repository-owned design requirements before treating representative-project
audits as the only remaining work. Synthetic tests establish implementation behavior;
they do not substitute for host attestation, held-out campaigns, or release qualification.

## Ordered Work

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

## Current Test Gates

The latest full local verification after stage provenance, invalidation, revision-bound
tasks, closure ancestry, compact R4 v2 wire, delegated-budget reservations, host
attestation expiry/replay, R5 report provenance, Phase 5 CLI/gate decomposition, and Phase
6 synthetic scale fixtures is **338 passed, 1 skipped**; compatibility-scan passes with no
findings (49 Python files, 167 knowledge files, 1 prompt file). Phase 1 and Phase 5 local
acceptance tests pass; real-host behavior remains unverified until release qualification.

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