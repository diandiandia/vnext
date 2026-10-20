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
