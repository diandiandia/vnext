# Campaign Orchestrator Runbook

This is the operating guide for authorized development audits of large and
mixed-language repositories. The objective is source-backed vulnerability discovery,
not maximizing completed tasks or reported findings. Top15 languages and ten
prioritized issue patterns per language remain the portfolio; apply only the
target's relevant mechanisms and retain other source-evidenced candidates.

Release qualification, signed external observations and optional host-worker
attestation have separate prerequisites. Ordinary audit use does not require HMAC
keys. This runbook does not weaken existing stage validators or host permissions.

## 1. Stable Command Entry

Set the installation root once to the location of this checkout, not the target.
The Python launcher locates its own source tree, so it works from other directories
without installing a package or modifying `PYTHONPATH`.

```bash
VNEXT_ROOT=/path/to/vnext
TARGET=/path/to/authorized-frozen-copy
CAMPAIGN_ID=audit-local-001

vnext() { python3 "$VNEXT_ROOT/tools/vnext.py" "$@"; }
vnext --help
vnext init "$TARGET" --campaign-id "$CAMPAIGN_ID" --audit-mode fresh
vnext inventory "$TARGET" "$CAMPAIGN_ID"
vnext graph "$TARGET" "$CAMPAIGN_ID"
```

Automatic snapshot detection requires a clean Git worktree. For a non-Git target,
provide an approved immutable `--snapshot-id` and retain its provenance; do not invent
a stable identity for mutable source. Keep source permissions, isolation, runtime
limits, logs, stop owner and allowed commands explicit.

New CLI `init` defaults to a target-path-hashed store below
`$XDG_STATE_HOME/reachable-audit` (or `~/.local/state/reachable-audit` when
`XDG_STATE_HOME` is unset, empty, or relative), outside the source tree. Other commands
reuse that store or a sole legacy `<target>/.audit_vnext` store. If both exist, select
explicitly with `--state-dir`; no silent merge occurs.
An explicit absolute `--state-dir` selects the same store from any working directory;
relative paths remain target-relative for compatibility. Pass an explicit choice to
every command when overriding the default. Existing stores are not automatically
moved. The library `CampaignManager` retains its legacy default; embedded hosts must
provide an external location themselves. Source workers may search only inventoried
source paths, not arbitrary files under the target root.

Select categories from the applicable language profiles and threat model before
planning. Categories are hard scope: a Java Top10 audit must not silently use only
the three categories in an example or only deserialization/JNDI leads. Record any
excluded family as a limitation and obtain scope approval.

```bash
CATEGORIES=INJECTION,AUTHN,STATE
vnext plan "$TARGET" "$CAMPAIGN_ID" --categories "$CATEGORIES"
vnext status "$TARGET"
```

The categories above are an illustrative limited scope, not the complete Java
profile. Read the plan's actual Batch IDs and scope summaries, and set `BATCH_ID`
to one of them before the stage loop. Do not paste angle-bracket command templates
as literal shell input.

The launcher forwards the canonical CLI and exit code. It is **not** an unattended
model driver: it does not allocate Agents, authorize retries, or infer completion.

## 2. Coordinator and Worker Contexts

The host coordinator retains compact task IDs, stages, attempts, revisions,
budgets and blockers. Delegate source analysis to a fresh host-provided worker
context per claimed task when supported. Deliver the exact current task input,
output/analysis contracts, applicable skill rules, permitted source/tool access
and execution limits. Do not send prior worker transcripts or unrelated Campaign
findings; do not send signing/provider secrets.

- Claim by Batch/operation or task ID and retain worker, attempt and lease expiry.
  Keep concurrent claims within host and task budgets.
- Immediately confirm dispatch through the host. If a worker was not started,
  release the lease with the owner/attempt and reason rather than waiting for expiry.
  Poll lease timing and expiry; `worker_liveness: UNKNOWN` is deliberate, not evidence
  of a running or dead worker. The CLI does not observe host process health.
- A worker reads its scoped source, follows explicit boundaries, and returns the
  result plus actual measurements. The coordinator validates/collects the result,
  not a rewritten or fabricated answer.
- For a repairable output error, retain the same live lease and task-local worker
  context for bounded correction. Reusing it for that repair is intentional.
- After successful collection, stop that worker. Distinct refutation/adjudication
  workers must not receive one another's intermediate conclusions. They receive
  the stage evidence required by their task contract.
- A provider's fresh context is not necessarily an OS sandbox. The host supplies
  isolation and permissions. The engine cannot prove physical context separation,
  absence of hidden host history, or that a fresh worker has perfect attention.
  If the host cannot isolate contexts, record the limitation rather than claim it.

Task leases and revisions survive coordinator restart. Resume from durable state,
not from a host conversation's assertion that a stage was completed:

```bash
vnext status "$TARGET"
vnext batch-report "$TARGET" "$CAMPAIGN_ID" "$BATCH_ID"
vnext task-list "$TARGET" "$CAMPAIGN_ID" --batch-id "$BATCH_ID"
```

Inspect errors as well as JSON. Do not discard stderr or interpret a nonzero exit
as an empty queue. `task-claim` returning JSON `null` means nothing claimable under
that filter at that instant; there may still be active leases, failed tasks,
missing prerequisites or budget blocks.

## 3. Campaign Lifecycle Matrix

For every durable task stage: schedule, claim compatible tasks, perform real source
analysis, collect each validated output, then commit. A task success is not a stage
commit. Use `vnext --help` for the exact CLI command arguments. The skill's
[stage contracts](../SKILL.md#detailed-stage-contracts) describe host-side constraints;
this runbook provides the lifecycle and recovery guide.

| Stage | Prerequisite / purpose | Normal command pair | Completion / recovery |
|---|---|---|---|
| Preparation | Approved snapshot, inventory, graph and plan | `init`, `inventory`, `graph`, `plan` | Review included/excluded/deferred paths, languages, families, Work Units and Handoff ownership; do not narrow scope silently |
| R0 | Planned Batch, frozen source | `r0` | Validate baseline; drift requires restoration or a new Campaign |
| R1 | R0, scoped Work Units | `task-schedule-r1`, `task-commit-r1` | Exact source coverage, real Surface anchors, supplied boundary reviews, review altitude |
| R2 | Current R1 | `task-schedule-r2`, `task-commit-r2` (compact) OR matching `-per-axis` pair; schedule with `--entrypoint-checklist <json>` | All six axes with evidenced applicability and exact reviews of predeclared entrypoints; do not mix scheduling modes |
| R3 | Current R2 hypotheses | `task-schedule-r3`, `task-commit-r3` | Source-backed reachability/blocking evidence; uncertain paths stay NEEDS_REVIEW |
| R3.5 refutation | Eligible current R3 evidence | `task-schedule-r35-refutations`, `task-commit-r35-refutations` | Independent counteranalysis with actual evidence |
| R3.5 adjudication | Collected refutations | `task-schedule-r35-adjudications`, `task-commit-r35-adjudications` | Reconcile claims and counterevidence, not reviewer labels alone |
| R3.5 revival | Current R2/R3 and recorded selection | `task-schedule-r35-revivals`, `task-commit-r35-revivals` | Default selects every initial UNREACHABLE verdict unless selection was already recorded; preserve valid rejection |
| R4 | Current required prior stages and category plans | `task-schedule-r4`, `task-commit-r4` | One canonical CategoryRun per plan, exact axes/variants, hypothesis-by-hypothesis dispositions and applicable Finding reconciliation; no finding quota |
| R5 | Current verdicts and applicable experimental evidence | `task-schedule-r5`, `task-commit-r5` | Registered managed evidence for empirical upgrades; honest infeasibility/uncertainty |
| Finding | Adjudicated evidence and required R5 support | Explicit finding commands from CLI help | Canonical finding workflow, not invented R4 finding IDs |
| R6 | Required Batch artifacts and scope reconciliation | `task-schedule-r6`, `task-commit-r6` | Surface states, one review per recorded Finding, residual risks, actual coverage, skill issues and Batch gates |
| Handoffs | Declared boundary, source/receiver ownership and evidence | `handoff-resolve`, `handoff-integrate` | Both endpoint evidence and matching joins; report unresolved/undiscovered boundary limitations |
| Campaign | All required Batches/Handoffs reconciled | `campaign-close` | CG1-CG10, explicit unreviewed dispositions and cleanup; not proof of exhaustive safety |

Use actual returned IDs and stage artifacts. Do not write events directly, synthesize
empty success payloads, bypass commits, or interpret no hypotheses as proof of safety.
Retries and amendments must preserve old history. Committed R1-R5 amendments
invalidate affected descendants: reschedule and recommit current revisions.
After Campaign completion do not amend history; use a declared new Campaign.
Schedulers return `tasks` arrays; R6 also retains the legacy single `task` alias.
New runners should consume `tasks`, not count an unknown JSON shape as an empty queue.

### Human adjudication is a separate operator action

A split refutation requires actual human review. A Worker must not turn itself into
a human by choosing `actor=human`, a `human:*` worker ID, or a standing-delegation
label. The human worker label remains necessary for the existing task path but is
not sufficient to commit. Pause and show the exact proposal and source evidence to
the operator; never automate the approval as part of the Worker driver.

After review, the operator supplies an approval JSON object containing `output_ref`
(the exact successful task output artifact), `reviewer`, `rationale`, and a nonempty
`evidence_refs` array of stored review-evidence artifacts. Record the actual review
notes as an artifact, not a fabricated observation.

```bash
vnext task-approve-r35-adjudication "$TARGET" "$CAMPAIGN_ID" "$BATCH_ID" "$TASK_ID" \
  --input /path/to/operator-review.json
vnext task-commit-r35-adjudications "$TARGET" "$CAMPAIGN_ID" "$BATCH_ID"
```

Approval is bound to the current task output digest; approval of another artifact
cannot authorize it. It is an explicit operator assertion, not authenticated human
identity or an OS permission boundary. A host that lets a Worker issue arbitrary
operator commands still needs to restrict that access. Existing completed Campaign
history is not rewritten by this check.

### R4 reconciliation and static-only R5

Each CategoryRun must link every supplied Work Unit/family `allowed_hypothesis_ids`
entry exactly once, including rejected and unresolved candidates. Explain the
dispositions in the run rationale; these links do not claim that every candidate
is a vulnerability. An empty list is valid only when there are no scoped candidates.
The same rule applies to bundled tasks and direct R4 submission. Late candidates
remain explicit unresolved follow-up items, not invented IDs.

R2 compact and per-axis scheduling require an explicit JSON entrypoint checklist;
use `[]` when no items were predeclared. Each checklist item binds an ID to one
Work Unit, discovery axis, description and current-source anchor. The corresponding
AxisRun must review each applicable ID exactly once and cite its declared anchor.
This improves recall of known helpers; it is not an exhaustive entrypoint census.

For every allowed R4 hypothesis, emit one `hypothesis_reviews` disposition with evidence
and rationale. Also reconcile each previously recorded Finding exactly once in the
applicable CategoryRun. At R6, provide one `finding_reviews` decision per canonical
Finding. The closure report exposes findings needing review and R3.5/R4 disposition
disagreements. These records are worker assertions enforced for identity/coverage and
resolvable references; they are not independent human semantic validation. Inspect the
referenced evidence before relying on the classification or reconciliation.

For a proposed but unexecuted R5 experiment, retain identity, target, proposed
command and rationale; use `result=inconclusive`, `observation_refs=[]`, and
assessment disposition `NEEDS_REVIEW`. Do not execute it without authorization or
invent observation artifacts. Confirmed/refuted results still require observations;
empirical upgrades still require the registered evidence described above.

## 4. Six-Axis Deep Review

All triggers are conditional on current source evidence. For Java, consult the
Java profile's ten issues rather than treating a few high-profile APIs as complete.

| Axis | Review questions / evidence |
|---|---|
| Surface | Which external or lower-trust principal controls each entry? Trace authentication, authorization, decoding, transformations, error paths and sensitive operations |
| Mechanism | For applicable cards trace the actual source/guard/sink sequence; test guard ordering, incomplete validation, alternate dispatch and counterexamples |
| State | Check TOCTOU, shared state/locks, session or capability invalidation, cancellation, failed initialization/reload, cleanup and exceptional ownership transfer |
| Fix variant | Compare sibling handlers, duplicated parsers, aliases and alternative paths in the frozen snapshot. Repository history is optional and must be approved/available; do not preload old audit answers or search external vulnerability reports by default |
| Boundary | Follow JNI/CGO/FFI, RPC/IPC, queues, serialization and storage where present; identify principal, endpoint contracts, length/type conversions and cross-Batch ownership |
| Differential | Compare evidenced production/debug, build/platform branches, permissive/strict configuration, parser disagreement, fallback and error behavior; do not assume those modes exist |

No candidates does not justify NOT_APPLICABLE. Provide source evidence for an absent
precondition; use DEFERRED with the blocker when required review cannot be done.
APPLICABLE can legitimately produce zero hypotheses after evidenced analysis.
An unavailable hotspot provider is different from a completed scan with no candidates.
Use `scan_status` (`not_scanned`, `completed`, `partial`, or `error`) and the
`supported_path_count`, `scanned_path_count`, `unsupported_path_count`, and
`parse_error_count` fields; candidate count alone is not a discovery-quality or
safe-source result.

R3.5 defaults to full initial-UNREACHABLE revival, not random sampling. Examine
regex anchoring, slicing, canonicalization, decoding order and cross-language guard
assumptions as potential rejection errors, not predetermined bypasses. A keyword,
severity label or boundary name does not prove exploitability. If budget cannot
cover the recorded review set, stop/report the unmet work instead of quietly sampling
or weakening selection. Weighted policies need prospective cost/recall evaluation.
The legacy `revived_hypothesis_ids` field includes UPHOLD reviews. New summaries split
reviewed, upheld and actual revivals. Empty positive adjudication coverage is not by
itself evidence that UPHOLD reviews were omitted.

## 5. Recovery Decision Table

Recovery is bounded by authorization, remaining attempts, budget and the current
lease/revision. Persist failure and usage evidence; missing telemetry is incomplete
cost, never free work. Do not create infinite retry loops.

| Symptom | Correct action | Do not do |
|---|---|---|
| Worker exit/timeout, lease still live | Stop its known process through the host, then `task-release ... --reason ...` for its owner/attempt. A replacement worker claims a new lease | Run duplicate workers or collect after lease loss |
| Lease expired | Re-read task state; normal claim can reclaim within attempt budget. Existing completed output requires explicit authorized recovery bound to the unreplaced original attempt; normal collect still rejects expiry | Collect an old result after a replacement claim, terminal result or invalidated revision |
| Failed/exhausted attempts | Retry within existing budget; exhausted work needs explicit bounded `task-retry --reason` authorization and remaining host budget | Automatically authorize unlimited retries |
| `task-collect` validation error | If same lease remains live, send exact error and original task contract for task-local repair; bound retries and preserve attempts/logs | Rewrite the schema, fabricate evidence, mark the task successful or restart the whole Campaign |
| Source snapshot drift | Pause dependent tasks. Restore the frozen bytes and verify `drift-resolve` with evidence; intentionally changed source needs a new Campaign/snapshot | Resolve drift by accepting changed bytes under the old snapshot |
| Corrected committed output | Use `task-amend` with reason/evidence; re-read invalidations and reschedule/recommit affected stages | Reuse stale downstream tasks or rewrite events |
| Runaway process / storage pressure | Pause dispatch; preserve durable artifacts; use `resource-cleanup` only for registered resources and stop known process groups under host control | Kill by process name, delete the evidence store, or treat cleanup as fixing a full disk |
| Required experiment cannot start | Record NOT_FEASIBLE, `experiment_required: true`, `experiment_id: null`, blocker evidence and NEEDS_REVIEW semantics | Claim empirical confirmation/refutation or hide a required experiment |
| Experiment actually ran but timed out/inconclusive | Preserve registered run/output, use NEEDS_REVIEW and reassess within limits | Label an attempted experiment NOT_FEASIBLE or infer safety from timeout |
| Budget/permission exhausted or unsafe cleanup | Pause and retain evidence; an approved wall-budget extension must append an amendment without resetting creation time. Abort with skill issues if abandoning | Invent usage, subtract pauses silently, bypass host controls, or force resource PASS |

## 6. Coverage and Closing Work

Read the Batch/Campaign coverage fields as declarations, not observed reads.
HIGH path risk tiers now require INSPECTED R1 Work Unit altitude at collection;
LOW also needs inspection to justify a low-risk claim. Omitted tiers remain
UNASSESSED. A declared altitude does not prove line-by-line review.

Before closure, compare planned paths/families/axes against actual artifacts and
record deferred axes/categories, unsupported languages/provider paths, missing
toolchains, unresolved boundaries, unreviewed Surfaces and dropped/late candidates.
Do not call SCREENED scope deeply inspected or assume DTO/generated code is safe.
Use justified excluded/deferred dispositions; a fresh scope-expansion/follow-up
Campaign must carry its declared relationship rather than erase the original gap.

Current reports expose several such fields but there is no single consolidated
per-module gap heatmap or automatic gap-attack planner. Keep that limitation explicit.
Handoff ownership exists for supplied edges; automatic symbol-to-security-boundary
discovery is not implemented. Any future index must emit candidates, not silently
declare a cross-language call chain proven.

Campaign closure inherits unresolved scope from current Batch reports. An empty
Campaign list cannot erase those items; inherited gaps are not implicit approvals.
The report also derives an outcome for every hypothesis, joining late Findings by
hypothesis ID. Without a Finding or consistent rejection, the candidate remains
NEEDS_REVIEW with stage evidence available in JSON; do not force a vulnerability.

Workflow PASS is separate from `resource_assessment`. Missing usage, configuration or
wall limits mean NOT ASSESSED; measured elapsed deadline breaches mean FAIL. Task
`wall_seconds` totals may sum concurrent work and are not Campaign elapsed time.
Use `init --max-wall-seconds <positive-int>` for a local claim deadline from Campaign
creation, including pauses. Collection/recovery remain possible after the deadline;
the host must stop active workers and enforce provider limits. Do not silently reset
the clock on coordinator restart or claim provider enforcement from a local budget.
Set up a registered, authorized bounded harness before R5 if experiments are needed;
without execution, retain proposed/infeasible outcomes and independent-review limits.

## 7. Evidence-Ready Go Development Slice

Use `init --experimental-go-hotspots` only when creating a new authorized development
Campaign. The choice is retained in Campaign constraints and propagated to R1 and
both R2 modes; do not inject a new provider into an in-flight Campaign. The local Go
toolchain parses the supplied frozen source bytes through a trusted bundled helper;
it must not build/import/execute target packages or fetch modules. Parser output is
candidate guidance, not a call graph, security verdict or measured language coverage.
Missing tools, failed scans and unhandled syntax remain visible limitations.

Before asking R5 workers to assess an actual experiment, use the existing `harness-run`
with an approved argv, hypothesis ID, timeout, resource policy and offline environment.
Go may require a larger virtual-address-space allowance than the default; do not
disable limits or confuse virtual address space with resident memory. A host container
or VM is still required for hostile code. Capture stdout/stderr and execution artifact
refs, verify the observed behavior, and pass the registered refs to normal R5 tasks.
Toolchain availability alone does not mean an experiment was executed.

For a trusted standard-library-only probe already present in the approved frozen
disposable target, an explicit harness input can be:

```json
{
  "profile": "go-offline",
  "command": ["go", "run", "./approved_probe.go"],
  "cwd": ".",
  "timeout_seconds": 120,
  "hypothesis_id": "HYP-from-the-current-campaign",
  "output_limit_bytes": 4096
}
```

The opt-in profile uses a bounded 8 GiB virtual-address-space default (an explicit
approved `memory_limit_bytes` still overrides it), a 64 MiB per-file build limit,
and independent captured-output limits. Ordinary harness defaults remain unchanged.
It supplies private Go cache/temp paths and disables Go module/toolchain fetching.
This is not OS network isolation and cannot authorize hostile target execution.
Do not copy these limits without checking host approval. Do not create or alter a
probe inside an already frozen source snapshot; prepare the approved copy first.
After the run, inspect actual output and eligibility, then register the appropriate
experiment through the normal R5 task result; an exit code alone is not confirmation.

## 8. Evidence and Scope Controls After the Java Pilot

### Supporting resources

After inventory and before the first Batch R0, register required XML, SPI, schema or
build-file evidence. For example, pass `evidence-register TARGET CAMPAIGN --input FILE`
an operator-created JSON input:

```json
{
  "paths": ["resources/logging.xml", "pom.xml"],
  "reason": "Freeze configuration and dependency evidence used by source review"
}
```

Paths must exist inside the target and outside runtime/VCS state; registration is
bounded to 1024 unique paths, 16 MiB per file and 64 MiB per request. It records
digests, not a source-review claim. Content cannot be replaced under the same
Campaign. Concrete LOC evidence must match the source baseline or a registered
supporting digest, have a valid nonblank line and remain inside the target. A resource
does not become a code call-chain step. If a necessary resource was omitted, preserve
the limitation and prepare a new correctly frozen Campaign instead of deleting evidence
or rebaselining after R0. Existing Campaigns without registrations are not silently
certified under the stronger rule.

R4 applies the same concrete LOC/artifact checks on individual, bundled, screening
and direct records, including nested axis and hypothesis-review evidence. Legacy
symbolic IDs remain reference labels, not verified source anchors. Direct imports do
not reconstruct lost task attempts or measurements.

### Scoped planning

Use explicit per-path INCLUDED/EXCLUDED/DEFERRED decisions; unspecified paths remain
INCLUDED. Plans project wholly out-of-scope graph edges away while retaining incoming
and outgoing cross-scope boundary obligations. A boundary-only Work Unit can therefore
remain without included source files; it must explain unresolved external premises,
not claim excluded code was reviewed. A fully excluded/deferred repository can have
zero Batches. That is an empty declared audit scope, not evidence of repository safety.
Truly empty repositories and manifest-only components retain their existing behavior.
Tests/generated files are not automatically inapplicable; use evidenced axis dispositions.

### Experimental Java leads and static challenges

Create a new Campaign with `--experimental-java-hotspots` to opt into trusted local JDK
Tree API parsing of verified bytes. No target compilation, class loading or annotation
processing runs. The three generic method-site families are command/process creation,
object deserialization, and whole-stream/archive iteration. Receiver types, imports,
shadowing and dataflow are unresolved: a same-name ordinary method can be a false
positive. These are review leads, not a Java Top10 analyzer or a vulnerability verdict.

Bounds are 128 Java files, 1 MiB per file, 4 MiB per Work Unit, 200 retained candidates,
15-second parse/30-second helper-build timeouts and bounded process output/resources.
The helper uses host-JDK syntax and UTF-8 only. Unsupported syntax, missing tools,
over-limit and unparsed files are explicit gaps. Default providers and the qualified
release roster remain unchanged. Helper caches and temporary workspaces are created
under a private external temporary root, never in the target or current working
directory; target-local `TMPDIR` is ignored. If no safe external root is available,
the scan fails explicitly rather than falling back into the audit tree.

An optional `--static-challenges` requires the existing two-perspective R3.5 protocol
for static-only REACHABLE claims as well as edge-proven claims. Both scheduling and
completion use the same frozen selection. Adjudication still requires separate refuter
labels, call-chain plus premise perspectives, human handling of splits and source
verification of demotion. Labels are not authenticated identities. Retention cannot
promote evidence grade, and default static-only skips are exposed in the final JSON.

### Authorized late collection and wall-budget extension

Normal collection rejects expired leases. When a stopped worker left complete output,
the operator may use:

```text
task-collect TARGET CAMPAIGN TASK WORKER --input RESULT.json --recovery \
  --attempt ORIGINAL_ATTEMPT --reason "operator-verified recovery reason" \
  --evidence-ref sha256:RECOVERY_EVIDENCE
```

Use the original worker/attempt and actual result envelope/measurements. Preserve the
output digest, outage/termination evidence and unreported usage; do not invent zeros.
Recovery binds the exact output digest and original claim, rejects replacement attempts,
terminal tasks and stale revisions, and still runs normal validation/attestation.
Authorization consumption plus finalization are atomic. A schema-compatible output is
not independent authorship proof; the operator must verify its provenance. This recovers
existing output after a wall deadline, not permission to launch replacement work.

To approve further dispatch under an existing wall limit:

```text
campaign-wall-budget-amend TARGET CAMPAIGN --approved-max-wall-seconds NEW_TOTAL \
  --reason "approved extension reason" --evidence-ref sha256:APPROVAL_EVIDENCE
```

The new limit is total seconds from original creation, not additional seconds from now.
The event records the prior/original/approved limits, elapsed time, original breach,
actor, reason and resolvable evidence. It cannot silently reset pauses or reopen a
completed Campaign. Reports retain original-budget FAIL when breached, separately from
approved-limit conformance and incomplete usage. Local actor/evidence assertions do not
prove external approval authority or provider hard-cap enforcement.
