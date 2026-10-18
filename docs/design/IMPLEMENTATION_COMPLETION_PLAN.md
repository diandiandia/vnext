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

Status: **LOCAL WIRE SLICE COMPLETE**. R4 AxisRun Work Unit IDs may be omitted and are
inherited from the parent CategoryRun; explicit mismatches fail, and canonical stage
artifacts retain the complete ID. Bundled mechanism-card definitions and repeated
language/knowledge contexts are serialized once at bundle scope; v2 category items
inherit family and reference shared axis sets while retaining per-item plan, Work Unit,
card allowlist, budget, and hypothesis scope. The v1 bundle parser remains supported.
Broader payload reduction and measured real-project bundle-size qualification remain open.

Reduce repeated Work Unit/category/axis fields in bundled R4 inputs without weakening
per-item identity, allowed-hypothesis, altitude, or coverage validation. Keep one
canonical persisted CategoryRun per CategoryAuditPlan.

Acceptance: old and compact forms have an explicit versioned contract; round-trip tests
prove byte-size reduction on multi-item bundles; omitted or mismatched references fail
while the task remains repairable; R4 reports remain unchanged.

### 3. Host Identity and Delegated Budgets

Status: **PARTIAL**. Tasks can require and cap an aggregate `delegated_agent_runs`
measurement bounded by `agent_runs`; Campaigns can opt into a host-wrapper HMAC envelope
bound to task/attempt/lease/worker/delegate fields. Host identity trust, key custody, and
pre-dispatch/provider-side reservations remain open.

Add runtime mechanics for host-attested worker/reviewer identities and explicit delegated
budget reservations. Runtime claims must bind to a signed or host-verified identity and
budget envelope; labels alone must never count as authentication. Keep provider hard
limits distinct from estimates.

Acceptance: forged, expired, replayed, over-budget, or unbound attestations fail before
dispatch/finalization; concurrent workers cannot oversubscribe reserved budgets. Actual
identity and provider enforcement require a host integration acceptance run.

### 4. R5 Out-of-Band Evidence Provenance

Status: **PARTIAL MECHANICS IMPLEMENTED**. `r5-observation-register` verifies a
host-authority HMAC and binds an observation to Campaign/snapshot/Batch/hypothesis,
observer/method/time, and Campaign-owned artifact digests. Registration is evidence-only
and cannot upgrade R5; R5 task context exposes matching observations and assessments may
cite them without promotion. Authority key custody, observer identity trust, and
independent accept-path qualification remain external.

Support authorized external observations without treating a string reference as proof.
Bind evidence to hypothesis, snapshot, target, observer identity, method, timestamp,
artifact digests, and an authority signature. Keep it distinct from managed harness
confirmation unless policy explicitly accepts the signed evidence class.

Acceptance: missing/invalid signatures, wrong snapshot/target/hypothesis, digest changes,
and unauthorized evidence classes fail; valid evidence preserves provenance through
R5, closure, and release reports. A real authority-held key and accept-path retest are
external prerequisites.

### 5. Output Density and Structural Debt

Status: **IN PROGRESS**. Campaign screening/substantive classification and ceiling state
are isolated in a pure helper with direct boundary-case tests. CLI initialization, status,
skill review/backlog, resources, Inventory, ComponentGraph, Plan/amend, R0-R3, Handoff,
harness, execution tasks, Campaign close/abort, shadow evaluation, toolchain probe, and
compatibility scan dispatch through focused handlers. CG5 Handoff evaluation is isolated
with direct pass/fail coverage. Campaign closure also validates stale stage markers and
upstream revision ancestry. R4 AxisRun IDs and bundled mechanism-card definitions are
compacted at the wire. Remaining work includes R3.5/R4/R5/Finding CLI groups, other
CampaignCloser gates, further R4 repetition, and selective exception narrowing.

Deduplicate repeated R4 schema fields where safe. Split the CLI dispatcher and
CampaignCloser gate evaluation into bounded helpers only with behavior-pinned tests.
Narrow broad exception handling only where rollback/cleanup semantics are explicit.

Acceptance: same canonical reports and failure behavior; focused unit tests per helper;
no widened exception swallowing; measured R4 bundle input reduction.

### 6. Scale and Release Qualification

Complete the remaining synthetic scale measurements and signed real-run acceptance:
30k Handoffs with large artifacts, atomic failure/recovery, task ordering, zero-target
latency budgets, 1k-file R1/R3 validation, all supported language strata, held-out mixed
language campaigns, and large-repository runs.

Acceptance: measured budgets and reproducible harness/fixtures. Real project access,
held-out labels, evaluator authority signatures, host-read proof, and large-run capacity
are external evidence; local synthetic tests cannot mark these gates complete.

## Current Test Gates

The latest full local verification after stage provenance, invalidation, revision-bound
tasks, R3.5 ledger replay, closure ancestry, commit-boundary recovery, and compact R4 v2
wire tests is **319 passed, 1 skipped**; compatibility-scan passes with no findings
(49 Python files, 167 knowledge files, 1 prompt file). Phase 1's local acceptance tests
pass; its real-host behavior remains unverified until release qualification.

Phase 2 local gates now cover v1 compatibility, v2 compact multi-item serialization,
measured byte reduction, repairability after invalid references, and canonical R4 reports.
Before closing Phase 2, measure representative large-project bundle sizes. Before closing
Phase 3, test forgery, expiry, replay, identity binding, budget overrun, and concurrent
reservation contention. Before closing Phase 4,
test invalid signatures/scope/digests and trace valid provenance through R5, closure, and
release output. Before closing Phase 5, test each extracted command/gate and confirm
canonical output/error behavior is unchanged. Before closing Phase 6, run synthetic
scale budgets locally and attach the required signed real-run evidence separately.

External waiting items are host trust/key custody, provider-side hard budget reservation,
authority-held R5 signing keys, independently trusted observer identity, target-read
proof, held-out labels, supported-language strata, and representative large-project
capacity. These cannot be marked complete by repository unit tests.

## Execution Rule

Work proceeds in the order above. Each item is implemented, tested, documented, and
committed before moving on. A phase is not marked complete merely because its synthetic
unit tests pass when its stated external acceptance remains outstanding.