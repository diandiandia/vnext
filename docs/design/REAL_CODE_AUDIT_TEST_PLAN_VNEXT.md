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

For each reported item, record `SECURITY_VULNERABILITY`, `ORDINARY_DEFECT`,
`HARDENING`, or `INSUFFICIENT_EVIDENCE` as appropriate. Security-vulnerability
classification must explain attacker capability, trust boundary, protected asset,
security property, concrete impact, and severity rationale with source/artifact
references. A reviewer separate from the discovery author must inspect whether the
cited source actually supports each claimed precondition, sink, and impact, and record
an accept/reclassify/unresolved disposition with evidence. If this review is not
performed, mark semantic validation NOT ASSESSED; do not present the Agent classification
count as an independently validated vulnerability count. A passing structural validator,
reachability result, or confirmed experiment is not alone proof of security impact.

**Finding-classification pass:** ordinary functional/robustness defects and hardening
recommendations remain visible but are not counted as confirmed vulnerabilities;
unsupported security-impact claims are rejected or retained as unresolved.

### B1. Current-policy large-project development test (originating policy-38 protocol)

**Test ID:** `RTA-38-LARGE-01`. This is a development real-target test, not release
qualification. Its purpose is to determine whether the current R2/R4/R6 traceability
contracts improve coverage and reconciliation on a large repository, and to measure
workflow capacity under a real target. It does not by itself establish vulnerability
recall, precision, exploitability, or complete physical source reads.

2026-10-23 repair retest: retain this test ID as the originating protocol, but record
the actual new engine commit/worktree digest and task policy rather than claiming a
policy-38 run. First execute the bounded TR-13 regressions. For the host retest:

- Use target-external Campaign state and frozen source-path searches. Confirm worker
  dispatch after each claim and release failed dispatches; do not infer liveness from
  a lease.
- Set a numeric `init --max-wall-seconds` and host/provider limits. The local deadline
  includes pauses and stops new claims only; record explicit operator decisions on
  stopping/restarting a run, and use a new Campaign for a new frozen budget. Retain
  per-attempt input/cache/output usage or mark resource assessment NOT ASSESSED.
- Verify Batch unresolved scope cannot disappear from Campaign JSON, Markdown or
  lessons. Check every hypothesis's final report outcome, including candidates with
  no canonical Finding; unknown or conflicting dispositions remain unresolved.
- Check revival outcomes, not the legacy reviewed-list field name. UPHOLD is not a
  reversal and does not itself require a new positive adjudication.
- Register an authorized bounded harness before asking for empirical confirmation;
  preserve infeasibility if the host cannot execute. A separate qualified reviewer,
  not another worker label, is needed for an independently validated impact claim.

#### Objectives

1. Measure inventory and planned-scope coverage across the target's actual languages,
   paths, Work Units and Batches; identify unsupported paths and cross-language or
   cross-Batch boundaries.
2. Verify that predeclared entrypoints/helpers are carried into R2 review checklists,
   receive source-backed dispositions, and are reconciled through R4 hypotheses and R6
   Finding/surface review.
3. Measure R4 bundle size, input/token use, latency, task completion and repair/retry
   behavior at the observed large-project scale.
4. Identify misses, irrelevant evidence, unresolved reviews, false positives and
   resource-limit failures for follow-up. Do not convert these observations to a
   capability or release claim without independently adjudicated labels.

#### Test setup and execution requirements

- Freeze and record the engine commit, runtime task policy (expected baseline:
  the actual current version, originally `vnext-task-policy-38`), target commit/snapshot, language inventory, authorized paths,
  categories, model/tools, host limits and budgets before analysis. Use a fresh disposable
  clone and Campaign with no prior target findings, lessons or regression backlog in
  discovery inputs.
- Select the complete authorized project scope if the goal is a whole-project audit.
  Execute every planned Batch in that scope. If only representative slices are run, label
  the result a sampled pilot and list all omitted/deferred scope; do not report it as a
  completed project audit. For scale/boundary observations, include at least two Batches
  when the target can be partitioned that way, and record an observed cross-Batch or
  cross-language boundary when one exists.
- Before task outputs are visible, record stable IDs and source anchors for representative
  security-sensitive entrypoint/helper pairs. Include known parser/iterator/configuration,
  evaluation or deserialization-style paths only when they actually exist in the target.
  Preserve the expected set with the test protocol; do not add targets after seeing
  results and count them as predeclared coverage.
- Run the selected scope through the normal Inventory/ComponentGraph/Plan and R0-R6
  claim/collect/commit workflow. For every predeclared entrypoint, require an R2 checklist
  row and record the source-backed result. For every selected hypothesis, require an R4
  disposition and evidence relevant to that hypothesis. Reconcile every applicable
  Finding in R4 and every canonical Finding/surface in R6. Missing or duplicate IDs,
  mismatched anchors, cross-scope evidence and unsupported claims are test failures, not
  successful empty results.
- Record all in-scope, excluded, deferred, unsupported and unreviewed paths explicitly.
  For each large source file, record digest, byte/line count, input size, observed ranges,
  task outcome and approved deferral. A completed task or `ALL_SOURCE_FILES` declaration
  is not proof of physical read or line coverage.
- Record R4 bundle item counts and serialized bytes, measured token usage, latency,
  failures/retries, task/agent runs, time/cost and budget reconciliation per Batch and
  overall. Exercise interruption/retry and amendment/invalidation in a disposable
  Campaign copy, not by corrupting the evidence Campaign.
- Have a reviewer separate from the discovery author adjudicate each security-impact
  declaration and a sample of rejected, deferred and unreviewed items. Record
  accept/reclassify/unresolved with source evidence. If no such reviewer is available,
  mark semantic validation `NOT ASSESSED`; do not publish independently confirmed
  vulnerability counts or quality rates.

#### Acceptance and reporting

Report four separate outcomes: **workflow/contracts**, **declared-scope coverage**,
**semantic adjudication**, and **capacity/resources**. Each is `PASS`, `FAIL`,
`INCONCLUSIVE` or `NOT ASSESSED`, with evidence references.

- **Workflow/contracts PASS:** all exercised stage contracts and exact ID/anchor
  reconciliations pass; task failures/retries are recoverable; stale outputs cannot reach
  closure; recorded usage is within declared limits or explicitly reported as a limit
  breach.
- **Declared-scope coverage PASS:** every item in the frozen selected scope has an
  explicit reviewed, excluded, deferred or unsupported disposition, and every
  predeclared helper has a traceable R2-to-R4/R6 disposition. Any `UNREVIEWED` or
  unmeasured source range prevents a complete-coverage claim for that scope. A disclosed
  deferral can allow the workflow test to finish but cannot be represented as reviewed.
- **Semantic adjudication PASS:** the independent reviewer has recorded evidence-based
  dispositions for the required claims. Without independent labels, report
  `NOT ASSESSED`; structural validation alone is insufficient.
- **Capacity/resources PASS:** actual per-Batch and total usage, elapsed time, bundle
  sizes and recovery costs reconcile with the frozen limits. Any missing measurement is
  `NOT ASSESSED`, not zero.

The test may establish workflow/contract behavior even when coverage or semantic
adjudication fails; report those outcomes separately and preserve all gaps. Do not claim
Top-15-language or Top-10-issue effectiveness from one repository. Use reviewer-adjudicated
misses and false positives to update a separate test corpus and acceptance thresholds
before implementing further providers, detectors or large-file slicing.

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

#### Top-15 language pilot matrix

The operator reports that real-project tests have been run for C, C++, Go and Java.
Retain their existing Campaign/evidence references in the test ledger; this status
records development workflow testing only and does not certify a provider or language.
Test the remaining 11 portfolio languages next. The order below is a practical
sequencing suggestion based on distinct runtime/build ecosystems, not a popularity
ranking or a capability claim. Use a separate fresh Campaign per language, even when
two languages share a repository; do not merge JavaScript and TypeScript evidence into
one language result.

| Suggested order | Language | Select a representative authorized project/component with | Pilot-specific questions |
|---:|---|---|---|
| 1 | Python | `pyproject.toml`, `setup.cfg` or an established application package | Does the workflow inventory runtime/package boundaries, framework entrypoints and dynamic imports without treating missing static resolution as coverage? |
| 2 | C# | `.sln`/`.slnx` and `.csproj`, preferably a multi-project application | Are solution/project references, generated code and framework-specific entrypoints represented and scoped? |
| 3 | Rust | `Cargo.toml` workspace and lockfile, preferably a service or library with features | Are workspace members, feature-gated code, macros/build scripts and unsafe blocks represented without claiming macro expansion was reviewed when it was not? |
| 4 | JavaScript | `package.json` plus lockfile and a maintained server or client application | Are module format, runtime version, dependency boundaries, framework routes and dynamic loading handled or explicitly limited? |
| 5 | TypeScript | `tsconfig.json`/project references plus package metadata and runtime application | Are TS/JS source boundaries, path aliases, generated output and the actual deployed runtime distinguished? Keep it separate from JavaScript pilot scoring. |
| 6 | Kotlin | Gradle or Maven multi-module project, with Kotlin/JVM or Android platform recorded | Are Kotlin source sets, platform boundaries, generated code and Java interop represented? Record JVM/Android distinctions. |
| 7 | Scala | `build.sbt` or equivalent multi-module build, with Scala version recorded | Are Scala version, macros/compiler plugins, JVM interop and module boundaries explicit? |
| 8 | PHP | `composer.json`/lockfile and a maintained web or CLI application | Are autoloading, framework routes/middleware, configuration and PHP/runtime-version assumptions represented? |
| 9 | Ruby | `Gemfile`/lockfile and a maintained web or background-job application | Are Rails/Rack/job entrypoints, autoloading and gem boundaries represented without assuming framework behavior? |
| 10 | Swift | `Package.swift` or an authorized Xcode project, with platform recorded | Are package targets, platform-specific code, generated sources and Objective-C/C interop boundaries represented? |
| 11 | Shell | A maintained repository of scripts with declared interpreters and invocation paths | Are shebangs, sourced scripts, environment/config inputs, CI/container entrypoints and shell dialects in scope? Do not execute scripts merely to inspect them. |

For all 11:

1. Freeze authorization, target commit, language/framework/version, project marker
   files, scope, budgets and stop owner before R0. Use a disposable clean clone,
   separate state directory and fresh Campaign. Do not supply prior findings or
   expected-answer labels to R1/R2.
2. Run Inventory, ComponentGraph and Plan first. Reconcile source files, generated
   files, build units, language tags, included/excluded/deferred paths, unsupported
   extensions, Work Units, Batches and cross-component boundaries against an
   independently sampled file/build inventory. Missing or misclassified paths must
   be recorded, not silently dropped.
3. Run the normal R0-R6 workflow on a representative component and evaluate all ten
   versioned issue profiles for that language. For each profile, retain applicability
   disposition and reason, relevant current-source areas examined, evidence refs,
   hypotheses, counterevidence and unresolved questions. Do not force a finding for
   each profile and do not use catalog prose as proof of a target condition.
4. Independently review candidate and non-candidate samples against source. Record
   whether entrypoint, guard, dataflow/call path and sink claims are supported,
   misclassified, false positive or unresolved. Keep the reviewer outside the
   discovery context. Where no independent expected-answer set exists, label recall
   **NOT MEASURED**; do not infer it from successful completion or zero findings.
5. Record stage/task/artifact refs; source/build coverage; all unsupported, skipped,
   malformed and over-limit files; R3.5/refutation coverage; R4 validation; R5/R6
   outcomes; Handoffs; interruption/recovery; input size, elapsed time and actual
   usage. Preserve exact limitations and approved deferrals in closure.
6. Never compile, execute, install or run target code/dependencies as part of static
   inspection unless the target owner separately authorizes a specific isolated test.
   Any such test uses a disposable sandbox and its own explicit resource/network
   policy. Do not expose secrets, protected labels or private source in reports.

**Development-pilot pass:** each requested stage completes under its contract; all
authorized paths are accounted for or explicitly deferred; project/build boundaries
are plausible on independent spot-check; all ten profiles have reviewable dispositions;
every reported candidate is source-anchored and independently adjudicated or marked
unresolved; resource use and limitations are recorded. **Fail** on reproducible
contract/data-integrity defects, silent scope loss, unsafe behavior or unsupported
claims. **Blocked** if authorization, a representative project, required evidence or
toolchain is unavailable. A clean-looking result, no findings, one project, or a
passing adapter test is not evidence of language recall or release readiness.

**Recommended sequence:** start with Python as the existing default-provider
reference, then C# and Rust; test JavaScript and TypeScript in separate Campaigns;
continue Kotlin, Scala, PHP, Ruby, Swift and Shell. If a candidate test repository
contains multiple portfolio languages, keep a separate language-specific Campaign
for each and add a later mixed-language Campaign to assess boundary ownership and
handoff behavior. This avoids attributing mixed-run results to an individual language.

**After the 11 pilots:** run at least one separate mixed-language Campaign with
predeclared source/destination boundary cases, then a representative large-project
capacity run. These development pilots do not satisfy the release evaluator's
per-language/per-issue held-out sample floors (default three samples for each of the
150 cells); do not pool exploratory, follow-up or same-target regression runs as
independent held-out evidence.

For large repositories, measure v1/v2 R4 bundle input bytes, provider token usage, latency,
per-item coverage and canonical artifact size at representative bundle counts. Synthetic
30k/1k fixtures remain implementation tests, not substitutes for this measurement.

For any Work Unit containing a source file flagged by `plan.r2_large_source_files`,
record host context/time limits and whether the complete file was inspected. A failed
or incomplete inspection must block R2 completion for that scope; either continue with
full-file coverage through bounded reads or obtain an approved `DEFERRED` disposition
and reconcile it in the Campaign report. The 1 MiB planner flag is advisory and does
not prove that smaller files are tractable. The runtime does not observe physical file
reads or verify line-range coverage.

When a target has known security-sensitive helper paths, predeclare representative
entry/helper pairs in the test protocol and verify that the relevant R1/R2 evidence
contains the actual helper path, guards, and sink/call chain before claiming recall.
An R1 surface list containing only general API entry points is not evidence that
specialized iterator/helper paths were analyzed.

### Development data collection for deferred implementation

The development pilot is also the next evidence-gathering step for SWDR-010, SWDR-031,
and N-6; these gaps do **not** require another round of repository-only synthetic tests
before a pilot may start. Label the observations as exploratory, not as release or
held-out qualification:

1. **Language coverage:** record source-file counts and extensions per Work Unit, current
   provider coverage, unsupported paths, and independently reviewed candidate sites for
   the sampled language/framework. Do not claim a provider's precision/recall from an
   unreviewed inventory or from synthetic fixtures.
2. **Large source:** for each flagged file, record digest, bytes, lines, task-input size,
   usage/time limits, completion state, source-backed anchors, and any approved deferral.
   Preserve the exact uncovered ranges or explicitly mark them unmeasured; do not infer
   line coverage from an `ALL_SOURCE_FILES` declaration.
3. **Cross-language boundaries:** record observed FFI/RPC/IPC/serialization/generated-
   code paths, language/framework pair, source/destination anchors, expected owner/route,
   and whether Inventory/Plan/R1 found them. Have the target owner or reviewer adjudicate
   misses and unrelated dependency edges.
4. Retain these observations in the authorized evidence bundle. Use the reviewed miss,
   false-positive, resource, and coverage patterns to define the test-first fixtures and
   acceptance thresholds in [TEST_PLAN_VNEXT.md](TEST_PLAN_VNEXT.md). A bounded,
   explicit development-only prototype may be implemented after its concrete behavior
   and fixtures are specified; do not require it to demonstrate capability before it
   exists. Default enablement, general slicing/detector claims and release qualification
   still need independently reviewed representative evidence.

The Go pilot unlocks the experimental provider and managed synthetic runtime probe
under TR-14. Test Go lead quality on a new frozen Campaign with
`--experimental-go-hotspots`; retain scan failures and source-backed false positives.
Keep expected historical issues outside fresh discovery inputs. The synthetic probe
establishes harness mechanics only, not that any prior target candidate is exploitable.

The Java module pilot on `9d513e7` additionally unlocks the bounded TR-15 infrastructure
repairs, supporting-resource digests, audited resumption and opt-in static challenges,
plus an explicit experimental Java parser. These are now local implementation features,
not Java quality certification. For the next targeted retest:

- Use a new Campaign and register needed XML/SPI/build evidence before first R0.
- Retain an included-to-excluded module edge and verify an explicit boundary gap;
  do not shrink the snapshot merely to avoid graph fanout.
- Exercise a controlled host interruption and original-attempt recovery, recording
  actual failed-attempt usage and worker termination. Budget extension is explicit;
  retain original breach and approved-limit results separately.
- If testing Java leads, opt in with `--experimental-java-hotspots`; predeclare source
  sites/counterexamples for independent post-run adjudication, outside fresh discovery
  input. To test static challenges, freeze `--static-challenges` at creation.
- Preserve original evidence; do not reopen completed pilot Campaigns or replace their
  findings, task counts or resource result with repaired output.

No new full audit is required to justify defects already reproduced. Automatic slicing
still requires measured large-file failures/coverage, generic boundary detectors need
real mixed-language mechanisms/misses, and Java execution needs an authorized actual
probe. No static module pilot supplies those missing observations.

If the pilot cannot measure physical reads or exact line ranges, record that limitation
and treat the result as workflow/skill evidence only. Never convert missing observations
to full coverage. A pilot may proceed with the currently implemented warning and
candidate-only behavior; unresolved targets remain **NOT QUALIFIED**, rather than
blocking all further development or being silently treated as complete.

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
