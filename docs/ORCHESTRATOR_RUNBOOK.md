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

R3.5 defaults to full initial-UNREACHABLE revival, not random sampling. Examine
regex anchoring, slicing, canonicalization, decoding order and cross-language guard
assumptions as potential rejection errors, not predetermined bypasses. A keyword,
severity label or boundary name does not prove exploitability. If budget cannot
cover the recorded review set, stop/report the unmet work instead of quietly sampling
or weakening selection. Weighted policies need prospective cost/recall evaluation.

## 5. Recovery Decision Table

Recovery is bounded by authorization, remaining attempts, budget and the current
lease/revision. Persist failure and usage evidence; missing telemetry is incomplete
cost, never free work. Do not create infinite retry loops.

| Symptom | Correct action | Do not do |
|---|---|---|
| Worker exit/timeout, lease still live | Stop its known process through the host, then `task-release ... --reason ...` for its owner/attempt. A replacement worker claims a new lease | Run duplicate workers or collect after lease loss |
| Lease expired | Re-read task state; normal claim can reclaim within attempt budget. Reject any late output from the old attempt | Assume `task-release` is necessary or valid after expiry |
| Failed/exhausted attempts | Retry within existing budget; exhausted work needs explicit bounded `task-retry --reason` authorization and remaining host budget | Automatically authorize unlimited retries |
| `task-collect` validation error | If same lease remains live, send exact error and original task contract for task-local repair; bound retries and preserve attempts/logs | Rewrite the schema, fabricate evidence, mark the task successful or restart the whole Campaign |
| Source snapshot drift | Pause dependent tasks. Restore the frozen bytes and verify `drift-resolve` with evidence; intentionally changed source needs a new Campaign/snapshot | Resolve drift by accepting changed bytes under the old snapshot |
| Corrected committed output | Use `task-amend` with reason/evidence; re-read invalidations and reschedule/recommit affected stages | Reuse stale downstream tasks or rewrite events |
| Runaway process / storage pressure | Pause dispatch; preserve durable artifacts; use `resource-cleanup` only for registered resources and stop known process groups under host control | Kill by process name, delete the evidence store, or treat cleanup as fixing a full disk |
| Required experiment cannot start | Record NOT_FEASIBLE, `experiment_required: true`, `experiment_id: null`, blocker evidence and NEEDS_REVIEW semantics | Claim empirical confirmation/refutation or hide a required experiment |
| Experiment actually ran but timed out/inconclusive | Preserve registered run/output, use NEEDS_REVIEW and reassess within limits | Label an attempted experiment NOT_FEASIBLE or infer safety from timeout |
| Budget/permission exhausted or unsafe cleanup | Pause, retain leases/state/evidence; explicitly abort with skill issues if abandoning | Invent usage, bypass host controls, or force Campaign PASS |

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
