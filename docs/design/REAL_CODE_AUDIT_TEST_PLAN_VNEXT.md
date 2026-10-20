# Real Code Audit Pilot and Qualification Plan

Status: **DEVELOPMENT PILOT LAYER ACTIVE — NOT RELEASE CERTIFICATION.** A development
real-target pilot may proceed when the target/scope authorization, frozen snapshot, a
fresh disposable clone and Campaign, isolation, resource caps and logs are recorded.
Host-verified identity, key custody, provider hard limits, authority-signed external
evidence, independent review and release gates remain required for host integration
and release qualification and must stay BLOCKED unless separately evidenced. This
layer validates workflow and skill behavior only.

This plan complements [TEST_PLAN_VNEXT.md](TEST_PLAN_VNEXT.md),
[ACCEPTANCE_PLAN_VNEXT.md](ACCEPTANCE_PLAN_VNEXT.md), and the operator steps in
[LOCAL_TEST_HANDOFF.md](../LOCAL_TEST_HANDOFF.md).

## 1. Required Inputs and Responsibilities

Sections 1 and 2 list the full **host-integration/release qualification** requirements.
For a development real-target audit, use the development pilot layer below instead;
do not apply authority/key/held-out prerequisites to an audit that makes no such claims.
Record and approve all inputs applicable to the chosen run level before execution.

| Input | Required value/evidence | Owner |
|---|---|---|
| Authorization | Written permission to inspect the named repository and snapshot; allowed actions and prohibited data handling | Target owner |
| Frozen target | Disposable clean clone, immutable commit/snapshot ID, repository size and language inventory | Host operator |
| Scope | Included paths/components, category families, known boundaries, explicit exclusions and deferred scope | Target owner + auditor |
| Run mode | `fresh` for independent discovery; `follow-up` only with declared history sources and a regression-only claim | Campaign owner |
| Host identity | Host-verified worker/reviewer identities; signed attestation policy and a rotation/revocation owner | Trusted host operator |
| Keys | Host-worker and R5 authority HMAC keys provisioned through the host secret store, never sent in chat, task input, source tree, or report | Trusted host / authority |
| Budget | Frozen Campaign delegated-run cap, task/agent-run limits, wall-clock limit and monetary/provider limit where available | Campaign owner + provider owner |
| Execution boundary | VM/container identity, filesystem write scope, network policy, process/resource limits, cleanup owner | Host operator |
| Tools and model | Python/runtime, compiler/toolchain, model/version, tool versions, permissions and host policy digest | Host operator |
| Independent review | Reviewer identity, finding adjudication procedure and protected expected labels kept outside discovery context | Evaluation authority |
| Data handling | Evidence retention, redaction, access control, deletion and incident escalation rules | Target owner |

The local SQLite reservation cap is not provider-side enforcement. Provider hard limits
and dispatch-time reservations must be enforced by the host/provider integration and
recorded independently. A string worker label or a locally generated HMAC does not prove
a trusted identity.

## 2. Entry Gates

For host-integration/release qualification, all applicable entry gates must be PASS
before the qualifying run. Development pilots use only their explicitly listed entry
requirements below and record untested qualification controls as NOT ASSESSED or BLOCKED.

1. **Authorization:** exact target, commit, scope and allowed commands are approved.
2. **Clean-room state:** a fresh Campaign has no prior target reports, findings, scope
   decisions, lessons or regression backlog in R1/R2 inputs. Follow-up history is declared
   and cannot be counted as independent capability evidence.
3. **Frozen policy:** categories, path dispositions, screening ceiling, batch sizes,
   delegated budget, wall-clock and provider limits are fixed before inspecting results.
4. **Host controls:** verified worker identity, attestation key custody, provider caps,
   sandbox limits and cleanup are demonstrated by the host owner.
5. **Evidence readiness:** output artifacts are stored by content digest, the evaluator
   signing key is authority-controlled, timestamps are normalized, and evidence access is
   logged.
6. **Independent labels:** any expected findings/held-out labels are adjudicated and
   unavailable to the discovery workers.
7. **Baseline:** engine commit, compatibility scan, full local test result, target commit,
   execution configuration and budget are recorded.
8. **Stop authority:** named operator can pause claims, revoke a worker/key, abort the
   Campaign and preserve state without deleting evidence.

If an entry gate is unavailable, record **BLOCKED** with the owner and missing artifact;
do not substitute a mock and call it a qualified host or release run.

### Development pilot layer (workflow/skill validation)

A development pilot explicitly labeled **“development real-target pilot, not release
certification”** may start with only the following recorded inputs:

- written target/scope authorization and prohibited actions;
- a frozen target snapshot and a fresh disposable clone with a fresh Campaign (no
  prior target reports, findings, lessons, regression backlog, or reused Campaign
  state in R1/R2 inputs);
- isolation and resource caps (filesystem, network, process, wall-clock and token
  limits) and complete logs;
- task inputs, prompts, outputs, usage and campaign state retained for review.

It must not claim host-verified identity, key custody, provider-side hard limits,
authority-signed observations, independent review, held-out labels, or release
eligibility. Those remain BLOCKED for host integration and release qualification under
the sections above. Operator familiarity with the target is recorded as a limitation:
a fresh clone is not a strict blind independent evaluation.

## 3. Run Sequence

### A. Preflight

- Verify the target commit is clean and the clone is disposable.
- Run Inventory, ComponentGraph and Plan against the frozen scope.
- Review Work Unit, Batch, boundary/Handoff and excluded/deferred path projections.
- Confirm the screening ceiling and all budgets are frozen in Campaign/Plan artifacts.
- Capture host identity, runtime/tool versions, permissions and policy digests.

**Pass:** plan paths are wholly within authorization; all scope is classified; each
cross-Batch boundary has an owner and route; no budget or identity field is implicit.

### B. Bounded Pilot

Run one small, representative language/family slice through R0-R6 using actual source
inspection and the normal task claim/collect/commit workflow. Do not use empty successful
outputs, direct store writes, fabricated artifacts, bypassed validators or R5 string
references as a substitute for execution.

Exercise one predeclared task failure/retry and one controlled interruption in a disposable
Campaign copy. If a completed stage output is amended, verify append-only invalidation,
revision-bound downstream rescheduling, stale-task rejection and closure blocking until
recommit. Preserve the original Campaign and artifacts.

**Pass:** all task outputs meet contracts; exact retries are idempotent; invalid outputs
remain repairable; no stale stage reaches closure; resource cleanup is complete or failures
are reported; token/time/budget usage reconciles with host records. A run executed under
the development pilot layer is labeled development-only; host and release gates are not
implied.

### C. Real External Evidence Path (signed-feature qualification only)

This step is not required for a development audit that does not exercise signed
external observations. Record it as NOT ASSESSED in that case; normal managed R5
evidence requirements and unresolved dispositions still apply.

For one eligible hypothesis, have an independently authenticated observer produce an
out-of-band observation. The authority signs the exact Campaign, target snapshot, Batch,
hypothesis, observer, method, timestamp and Campaign-owned artifact digests. Register it
through `r5-observation-register`; use it in an R5 assessment without promoting
`NEEDS_REVIEW` or another non-confirming disposition. Separately exercise a managed
`harness-run` if empirical confirmation is claimed.

**Pass:** invalid signature/scope/digest attempts are rejected; the valid signature and
artifact refs survive R5, Batch/Campaign closure and the signed release evidence bundle;
no observation alone upgrades R5. The authority, not the discovery worker, controls the
key and observer identity.

### D. Representative Expansion

After the bounded pilot passes, run predeclared language/family slices and at least one
cross-language/cross-Batch boundary case. Use separate fresh Campaigns for independent
capability samples. Follow-up Campaigns are labeled as regression-only. Record per-language
and per-issue coverage, unsupported paths, unresolved cases, Handoffs, duplicates,
`NEEDS_REVIEW`, false positives, scope limitations and actual spend.

For large repositories, measure v1/v2 R4 bundle input bytes, provider token usage, latency,
per-item coverage and canonical artifact size at representative bundle counts. Synthetic
30k/1k fixtures remain implementation tests, not substitutes for this measurement.

### E. Held-Out and Release Qualification

Only the evaluation authority may expose frozen held-out labels to the evaluator. Pair
v3/vNext on identical target snapshots, scope, model/tool configuration and budget. Require
all RG1-RG15 evidence, per-language/per-issue sample floors, mixed-language boundary
reconciliation, supported project classes, recovery evidence and any required large-project
run. The authority signs the evidence manifest; an independent reviewer verifies source
artifacts and adjudications before promotion.

**Pass:** every required release gate passes on signed, digest-verified real evidence and
an independent reviewer approves. Otherwise report **BLOCKED** or **FAIL**; never relabel
synthetic or follow-up data as held-out.

## 4. Stop Conditions

Apply identity/key/provider conditions when the run uses or claims those controls.
Their absence is not an automatic stop for a development pilot that never claimed
them. Authorization, scope, configured resource limits, evidence integrity, and safe
cleanup remain mandatory at every run level.

Pause claims immediately if authorization/scope changes, the target snapshot drifts, a
worker identity or key is revoked, a provider cap is unavailable, usage becomes
unreconcilable, a task exceeds limits, evidence digest/signature fails, stale output can
reach a commit, resource cleanup fails unsafely, or a secret/held-out label is exposed.

Record the stopping event, active leases, task attempts, artifact refs, budget used/reserved,
Campaign/Batch state and recovery owner. Preserve the durable store and artifacts before
abort or cleanup.

## 5. Required Run Record

For every pilot/qualification run, produce a redacted record containing the applicable
items below. Mark unexercised qualification-only controls NOT ASSESSED; do not invent
worker identity attestations, independent review, signatures, or held-out evidence.

- Engine commit, worktree state, test/compatibility baseline and target commit/snapshot.
- Authorization reference, scope digest, languages/categories, path dispositions and Plan IDs.
- Campaign/Batch IDs, task IDs/attempts, worker identity evidence and lease transitions.
- Model/tool/runtime versions, permissions, host policy digest and environment limits.
- Frozen and actual budgets, delegated runs, reservations, token/time/provider measurements.
- R1-R6 artifact/revision refs, R5 observation refs, Handoff status and cleanup results.
- Findings/adjudication status, independent reviewer, held-out policy and unresolved risks.
- Pass/fail/blocked gate IDs, test/log locations, signed manifest ref and deviations.

Do not store credentials, HMAC secrets, protected labels, or sensitive target contents in
this repository. Keep the evidence bundle in the authority-controlled location and commit
only redacted metadata or non-sensitive test-fixture references.

## 6. Inputs Needed to Start a Real Pilot

For a development pilot, provide items 1-4 and an evidence-retention location and stop
owner before execution. Record unavailable provider monetary enforcement as a limitation,
never as a verified hard cap; enforce the declared local limits and host policy.
Items 5-6 add the trust/independence prerequisites for qualification:

1. Authorized disposable target path and immutable commit/snapshot.
2. Approved language, category, component/path scope and prohibited actions.
3. Frozen runtime/tool/model configuration and sandbox/network policy.
4. Numeric time, provider-cost, agent-run and delegated-run limits plus abort owner.
5. Host-verified worker/reviewer identity and confirmation that required secrets are
   provisioned outside the agent session.
6. Independent reviewer and evidence-retention location.

Secrets are configured directly by the trusted host; never paste them into this document
or the conversation. Missing development inputs block the development pilot; missing
qualification inputs block the corresponding qualification only.
