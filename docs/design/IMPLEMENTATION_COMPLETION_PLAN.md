# vNext Implementation Completion Plan

## Purpose

Finish repository-owned design requirements before treating representative-project
audits as the only remaining work. Synthetic tests establish implementation behavior;
they do not substitute for host attestation, held-out campaigns, or release qualification.

## Ordered Work

### 1. Stage Revision, Invalidation, and Recovery

Status: **IN PROGRESS**. R3's per-hypothesis verdict writes and R4 screening projections
now preflight existing records, reject conflicting retries before mutation, and recover
from exact retries after partial writes. A quiescent Plan Amendment can supersede
completed Batches with fresh IDs so all R0-R6 stages replay from immutable task evidence.
R1/R2/R4 main/R5 projection recovery and the in-place post-commit invalidation/revision
model remain open.

Define an append-only stage revision model for R1-R5. Each committed projection must
pin the exact task-output artifact set and upstream revision IDs it consumed. A supported
post-commit amendment must atomically record the replacement and mark every dependent
projection stale; Campaign closure must refuse stale projections. Recommit/replay must
be deterministic and preserve prior artifacts. Extend partial-write recovery beyond the
R3 verdict path already covered.

Acceptance: fault-injection tests at every write boundary; exact retry is idempotent;
conflicting retries do not mutate state; full-Batch replay preserves old history and
uses new IDs; in-place amendment after R1 invalidates R2 through R6, and amendment after
each later stage invalidates only its descendants; closure fails until affected
projections are recommitted. Existing terminal R6 behavior remains intact.

### 2. Compact R4 Task Payloads

Status: **LOCAL WIRE SLICE COMPLETE**. R4 AxisRun Work Unit IDs may be omitted and are
inherited from the parent CategoryRun; explicit mismatches fail, and canonical stage
artifacts retain the complete ID. Bundled mechanism-card definitions are serialized
once at bundle scope while each item retains its seed-card allowlist. Broader payload
reduction and measured real-project bundle-size acceptance remain open.

Reduce repeated Work Unit/category/axis fields in bundled R4 inputs without weakening
per-item identity, allowed-hypothesis, altitude, or coverage validation. Keep one
canonical persisted CategoryRun per CategoryAuditPlan.

Acceptance: old and compact forms have an explicit versioned contract; round-trip tests
prove byte-size reduction on multi-item bundles; omitted or mismatched references fail
while the task remains repairable; R4 reports remain unchanged.

### 3. Host Identity and Delegated Budgets

Status: **PARTIAL**. Tasks can require and cap an aggregate `delegated_agent_runs`
measurement bounded by `agent_runs`. Authenticated worker/delegate identities and
pre-dispatch/provider-side reservations remain open.

Add runtime mechanics for host-attested worker/reviewer identities and explicit delegated
budget reservations. Runtime claims must bind to a signed or host-verified identity and
budget envelope; labels alone must never count as authentication. Keep provider hard
limits distinct from estimates.

Acceptance: forged, expired, replayed, over-budget, or unbound attestations fail before
dispatch/finalization; concurrent workers cannot oversubscribe reserved budgets. Actual
identity and provider enforcement require a host integration acceptance run.

### 4. R5 Out-of-Band Evidence Provenance

Support authorized external observations without treating a string reference as proof.
Bind evidence to hypothesis, snapshot, target, observer identity, method, timestamp,
artifact digests, and an authority signature. Keep it distinct from managed harness
confirmation unless policy explicitly accepts the signed evidence class.

Acceptance: missing/invalid signatures, wrong snapshot/target/hypothesis, digest changes,
and unauthorized evidence classes fail; valid evidence preserves provenance through
R5, closure, and release reports. A real authority-held key and accept-path retest are
external prerequisites.

### 5. Output Density and Structural Debt

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

## Execution Rule

Work proceeds in the order above. Each item is implemented, tested, documented, and
committed before moving on. A phase is not marked complete merely because its synthetic
unit tests pass when its stated external acceptance remains outstanding.