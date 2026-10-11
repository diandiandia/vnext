---
name: vnext
description: "Experimental campaign-scale reachable vulnerability audit skill. Use when explicitly testing or developing the vNext Campaign/Batch workflow for large repositories; replacement of v3 requires representative shadow-run acceptance."
---

# Reachable Critical Audit vNext

## Current Capability

This is an experimental replacement candidate for v3. The current build provides
Campaign and Batch state management, idempotent events, artifacts, recovery, component
inventory, deterministic Work Unit planning, cross-Batch Handoffs, R0-R6 execution,
CG1-CG10 Campaign closure, durable Agent task leases, source-slice drift invalidation,
15 source-language adapters, 14 build ecosystem adapters, the approved 15-language /
150-issue knowledge catalog, R5 recipes and bounded toolchain probes, and derived final reports. The implementation remains an
experimental shadow candidate until RG1-RG15 acceptance is completed on representative
projects, including all 15 language certifications, a mixed-language Campaign, and a
20GB+ Campaign. See `docs/design/ACCEPTANCE_PLAN_VNEXT.md`.

## Hard Rules

1. Never report a vulnerability audit as complete while a required stage is absent.
2. Never write vNext state into `.audit_results`; use `.audit_vnext` only.
3. A Batch completion is not a Campaign completion.
4. Store facts as events and artifacts; derive status and reports from the store.
5. Do not import v3 queues, compatibility fields, prompts, or runtime knowledge.
6. Default R1/R2 execution uses durable tasks; direct `r1`/`r2` imports are recovery-only.
7. Never claim review coverage (`reviewed_scope` or a path in `reviewed_paths`) unless the scoped source was actually inspected.
8. Every reported Surface needs a real `LOC-<project-relative-path>:<line>` anchor.
9. Register every background process group and temporary runtime directory with the
  Campaign. Successful closure releases registered resources. For a deliberate stop,
  use `campaign-abort` with the reason and `skill_issues`; it records a per-Campaign
  lesson file and releases registered resources. Retryable gate failures remain open;
  do not abort them accidentally. `resource-cleanup` is the manual recovery fallback.
10. Every Campaign closure must submit `skill_issues`, even when it is an empty array.
  Skill issues are tool-regression data, never vulnerability hypotheses or R1/R2 seeds.
11. A new independent audit uses `fresh` mode. Historical Campaign reports, findings,
  exclusions, lessons, and regression issues must not enter its discovery context.
12. A follow-up audit must explicitly name same-target history sources. Historical scope
  decisions are context only and require current-snapshot evidence and approval.
13. Every non-empty `unreviewed_scope` item needs one structured `scope_dispositions`
  record; `PASS` means closure gates passed, not that all scope was reviewed.

## Host Agent Loop

Start independent audits with `init` (default `--audit-mode fresh`). Do not inspect or
load prior Campaign artifacts while planning or generating hypotheses. A follow-up must
use `--audit-mode follow-up --history-source <campaign-id>` for each source. Only in a
follow-up, run `skill-backlog <target> <campaign-id>` and use its output in tool
regression checks; never copy it into R1/R2 prompts. During probes and runtime
experiments, start servers in their own process group (for example with `setsid`) and
immediately register the group. Use only temporary directories returned by
`resource-create-temp` for disposable runtime state.

After R0, schedule R1 and repeatedly claim tasks until the command returns `null`.
Each claim contains the Work Unit (source files grouped by directory under
`source_files_by_directory`; full path = directory + `/` + name, `.` is the project
root), a compact hotspot report (counts, not path lists), output
contract, and analysis contract. Read the scoped files, then submit one result JSON.
Do not inspect files outside the Work Unit except to follow an explicit boundary; create
a Handoff rather than silently expanding ownership.

Every `task-collect` input must include measured `agent_runs` and `wall_seconds`.
When the host exposes them, also report `input_tokens` (uncached), `cache_read_tokens`,
and `output_tokens` as integers; Campaign reports derive per-operation totals and the
cache-hit ratio from them, and flag `usage_complete: false` when any task omits them.
Missing usage never blocks collection. Result artifacts are asked to stay under 1 MiB
(output_discipline) and are hard-rejected above 4 MiB; coverage always wins over size.
A `discover_surfaces` result is checked at `task-collect`: `reviewed_scope` must be
`"ALL_SOURCE_FILES"` (preferred; do not echo the file list) or `reviewed_paths` must equal the
Work Unit's `source_files` and `boundary_reviews` must cover every supplied edge exactly
once. A rejection lists the gap (counts plus the first ten edge IDs) and leaves the task
leased so the same worker can resubmit the complete result.
`plan` prints `oversize_work_units` (required-output floor above the hard ceiling) and
per-batch `max_required_output_floor_bytes`; split or amend the plan before dispatching
any Work Unit listed there, because no valid result can fit the ceiling.
`configuration` may report `model_id`, `runtime_version`, and
`host_tool_policy_digest` (`sha256:<64 lowercase hex>`) when the host exposes them; never
invent host values. The runtime always adds its own deterministic `vnext_policy_digest`.
Missing host metadata does not block task collection, but is recorded in the Campaign
report and prevents release certification until the evaluation authority supplies the
attestation.

Successful R1 output:

```json
{
  "succeeded": true,
  "summary": "reviewed every scoped source file",
  "measurements": {"agent_runs": 1, "wall_seconds": 4},
  "configuration": {
    "model_id": "host-reported-model-id",
    "runtime_version": "host-runtime-version",
    "host_tool_policy_digest": "sha256:<64-lowercase-hex>"
  },
  "output": {
    "schema_version": "1.0",
    "reviewed_paths": ["src/example.py"],
    "surfaces": [{
      "surface_id": "SURF-stable-id",
      "work_unit_id": "WU-from-task",
      "component_id": "COMP-from-task",
      "kind": "http_handler",
      "entry_path": "src/example.py",
      "entry_symbol": "handle",
      "principal": "remote_unauthenticated",
      "evidence_refs": ["LOC-src/example.py:42"]
    }]
  }
}
```

After `task-commit-r1`, use compact R2 by default: one task per Work Unit contains all
six discovery axes, reducing claim/collect round trips. Use the per-axis mode only when
separate workers or context isolation materially helps. In either mode, every axis must
return an evidenced `AxisRun` disposition (`APPLICABLE`, `NOT_APPLICABLE`, or `DEFERRED`);
an inapplicable/deferred axis cannot emit hypotheses. Every hypothesis must use the task's
Work Unit and origin axis, reference known
Surfaces when applicable, stay within planned mechanism families, and state a
falsifiable security claim. Submit failures with `succeeded: false`, no `output`, and a
specific summary; failed or missing tasks block commit.

Successful R2 `output`:

```json
{
  "schema_version": "1.0",
  "reviewed_paths": ["src/example.py"],
  "axis_run": {
    "axis": "state",
    "applicability": "APPLICABLE",
    "evidence_refs": ["LOC-src/example.py:60"],
    "rationale": "reviewed lifecycle and state transitions"
  },
  "hypotheses": [{
    "hypothesis_id": "HYP-stable-id",
    "work_unit_id": "WU-from-task",
    "origin_axis": "state",
    "seed_refs": ["LOC-src/example.py:60"],
    "surface_ids": ["SURF-stable-id"],
    "mechanism": {"family": "STATE", "variant": "stale-owner"},
    "claim": "a cancelled owner remains usable by a retained callback",
    "status": "NEW"
  }]
}
```

Every R2 task input contains a pinned `knowledge_context` with issue-profile entries,
approved Mechanism Cards, provenance IDs, and any guidance omitted by the task budget.
Use that context as audit guidance, not as a finding or proof; inspect source and test
counterevidence. If `unsupported_languages` is non-empty or the context has no applicable
entries, record that limitation in the task result instead of implying language guidance
was applied.

Before building the plan, inspect `inventory` and `graph` diagnostics. Every `SourceFile`
has a `language_status`; `recognized_unsupported` languages remain visible and must be
listed as limitations. One Campaign may contain several portfolio languages. Use
`toolchain-probe <language>` only for registered version checks; it does not certify that
the language's build or runtime behavior was audited.

For behavior experiments, prefer `harness-run` with an explicit argv array and a bounded
timeout. The runner applies POSIX CPU, address-space, output-file, file-descriptor, and
core-dump limits and records stdout/stderr as artifacts. These limits are resource
controls, not a security sandbox for hostile code; use an external container/VM when the
target may execute adversarial native code.

`harness-run` input may include `hypothesis_id` to bind the execution to an R5 claim;
without it, the run is recorded as ineligible for empirical upgrade. `cwd` is relative
to the target and must resolve inside its root. The managed resource limits are not an
OS sandbox.

Example input:

```json
{
  "command": ["python3", "-c", "print('probe')"],
  "cwd": ".",
  "timeout_seconds": 10,
  "hypothesis_id": "HYP-from-the-current-campaign"
}
```

The `hypothesis_id` must identify the R5 hypothesis being tested; do not reuse another
Campaign's ID. `cwd` must be an existing directory under the target root.

## Commands

```bash
PYTHONPATH=<vnext>/src python3 -m reachable_audit init <target> --snapshot-id <id> \
  --audit-mode fresh --max-screening-fraction <0..1>
PYTHONPATH=<vnext>/src python3 -m reachable_audit init <target> \
  --snapshot-id <id> --campaign-id <new-id> --audit-mode follow-up \
  --history-source <prior-campaign-id>
PYTHONPATH=<vnext>/src python3 -m reachable_audit status <target>
PYTHONPATH=<vnext>/src python3 -m reachable_audit skill-backlog <target> <campaign-id>
PYTHONPATH=<vnext>/src python3 -m reachable_audit skill-review \
  <target> <campaign-id> --input <skill-review.json>
PYTHONPATH=<vnext>/src python3 -m reachable_audit resource-register-process \
  <target> <campaign-id> <process-group-id> --label <purpose>
PYTHONPATH=<vnext>/src python3 -m reachable_audit resource-create-temp \
  <target> <campaign-id> --label <purpose>
PYTHONPATH=<vnext>/src python3 -m reachable_audit resource-cleanup \
  <target> <campaign-id>
PYTHONPATH=<vnext>/src python3 -m reachable_audit campaign-abort \
  <target> <campaign-id> --reason <reason> --input <skill-review.json>
PYTHONPATH=<vnext>/src python3 -m reachable_audit harness-run \
  <target> <campaign-id> --input <harness-run.json>
PYTHONPATH=<vnext>/src python3 -m reachable_audit compatibility-scan \
  [--forbidden-tokens-file <tokens.txt>]
PYTHONPATH=<vnext>/src python3 -m reachable_audit batch-add <target> \
  <campaign-id> <batch-id> --manifest <manifest.json>
PYTHONPATH=<vnext>/src python3 -m reachable_audit inventory <target> <campaign-id>
PYTHONPATH=<vnext>/src python3 -m reachable_audit toolchain-probe <language>
PYTHONPATH=<vnext>/src python3 -m reachable_audit graph <target> <campaign-id>
PYTHONPATH=<vnext>/src python3 -m reachable_audit plan <target> <campaign-id> \
  --categories MEMORY-SAFETY,STATE,RESOURCE-DOS
PYTHONPATH=<vnext>/src python3 -m reachable_audit amend <target> \
  <campaign-id> <plan-id> --reason <reason> \
  --max-batch-files 500 --max-batch-work-units 2
PYTHONPATH=<vnext>/src python3 -m reachable_audit r0 <target> <campaign-id> <batch-id>
PYTHONPATH=<vnext>/src python3 -m reachable_audit task-schedule-r1 \
  <target> <campaign-id> <batch-id>
PYTHONPATH=<vnext>/src python3 -m reachable_audit task-claim \
  <target> <campaign-id> <worker-id>
PYTHONPATH=<vnext>/src python3 -m reachable_audit task-list \
  <target> <campaign-id> --batch-id <batch-id> --operation <operation>
PYTHONPATH=<vnext>/src python3 -m reachable_audit task-retry \
  <target> <campaign-id> <task-id> --reason <operator-reason>
PYTHONPATH=<vnext>/src python3 -m reachable_audit task-release \
  <target> <campaign-id> <task-id> <worker-id> --reason <reason>
PYTHONPATH=<vnext>/src python3 -m reachable_audit task-cancel \
  <target> <campaign-id> <task-id> --reason <reason>
PYTHONPATH=<vnext>/src python3 -m reachable_audit task-amend \
  <target> <campaign-id> <task-id> --input <amendment.json>
PYTHONPATH=<vnext>/src python3 -m reachable_audit task-collect \
  <target> <campaign-id> <task-id> <worker-id> --input <result.json>
PYTHONPATH=<vnext>/src python3 -m reachable_audit task-commit-r1 \
  <target> <campaign-id> <batch-id>
PYTHONPATH=<vnext>/src python3 -m reachable_audit task-schedule-r2 \
  <target> <campaign-id> <batch-id>
PYTHONPATH=<vnext>/src python3 -m reachable_audit task-commit-r2 \
  <target> <campaign-id> <batch-id>
PYTHONPATH=<vnext>/src python3 -m reachable_audit task-schedule-r2-per-axis \
  <target> <campaign-id> <batch-id>
PYTHONPATH=<vnext>/src python3 -m reachable_audit task-commit-r2-per-axis \
  <target> <campaign-id> <batch-id>
PYTHONPATH=<vnext>/src python3 -m reachable_audit task-schedule-r3 \
  <target> <campaign-id> <batch-id>
PYTHONPATH=<vnext>/src python3 -m reachable_audit task-commit-r3 \
  <target> <campaign-id> <batch-id>
PYTHONPATH=<vnext>/src python3 -m reachable_audit task-schedule-r35-refutations \
  <target> <campaign-id> <batch-id>
PYTHONPATH=<vnext>/src python3 -m reachable_audit task-commit-r35-refutations \
  <target> <campaign-id> <batch-id>
PYTHONPATH=<vnext>/src python3 -m reachable_audit task-schedule-r35-adjudications \
  <target> <campaign-id> <batch-id>
PYTHONPATH=<vnext>/src python3 -m reachable_audit task-commit-r35-adjudications \
  <target> <campaign-id> <batch-id>
PYTHONPATH=<vnext>/src python3 -m reachable_audit task-schedule-r35-revivals \
  <target> <campaign-id> <batch-id>
PYTHONPATH=<vnext>/src python3 -m reachable_audit task-commit-r35-revivals \
  <target> <campaign-id> <batch-id>
PYTHONPATH=<vnext>/src python3 -m reachable_audit task-schedule-r4 \
  <target> <campaign-id> <batch-id>
PYTHONPATH=<vnext>/src python3 -m reachable_audit task-commit-r4 \
  <target> <campaign-id> <batch-id>
PYTHONPATH=<vnext>/src python3 -m reachable_audit task-schedule-r5 \
  <target> <campaign-id> <batch-id>
PYTHONPATH=<vnext>/src python3 -m reachable_audit task-commit-r5 \
  <target> <campaign-id> <batch-id>
PYTHONPATH=<vnext>/src python3 -m reachable_audit task-schedule-r6 \
  <target> <campaign-id> <batch-id>
PYTHONPATH=<vnext>/src python3 -m reachable_audit task-commit-r6 \
  <target> <campaign-id> <batch-id>
PYTHONPATH=<vnext>/src python3 -m reachable_audit r1 <target> <campaign-id> <batch-id> \
  --input <surfaces.json>
PYTHONPATH=<vnext>/src python3 -m reachable_audit r2 <target> <campaign-id> <batch-id> \
  --input <hypotheses.json>
PYTHONPATH=<vnext>/src python3 -m reachable_audit r3 <target> <campaign-id> <batch-id> \
  --input <verdicts.json>
PYTHONPATH=<vnext>/src python3 -m reachable_audit batch-report \
  <target> <campaign-id> <batch-id>
PYTHONPATH=<vnext>/src python3 -m reachable_audit handoff-resolve \
  <target> <campaign-id> <plan-id> --input <resolution.json>
PYTHONPATH=<vnext>/src python3 -m reachable_audit handoff-integrate \
  <target> <campaign-id> <plan-id> <handoff-id> --input <chain-prefix.json>
PYTHONPATH=<vnext>/src python3 -m reachable_audit r35-refute \
  <target> <campaign-id> <batch-id> --input <refutation.json>
PYTHONPATH=<vnext>/src python3 -m reachable_audit r35-adjudicate \
  <target> <campaign-id> <batch-id> --input <adjudication.json>
PYTHONPATH=<vnext>/src python3 -m reachable_audit r35-revival-select \
  <target> <campaign-id> <batch-id> --input <selection.json>
PYTHONPATH=<vnext>/src python3 -m reachable_audit r35-revival-review \
  <target> <campaign-id> <batch-id> --input <revival-review.json>
PYTHONPATH=<vnext>/src python3 -m reachable_audit r35-complete \
  <target> <campaign-id> <batch-id>
PYTHONPATH=<vnext>/src python3 -m reachable_audit category-plan \
  <target> <campaign-id> <batch-id> --input <category-plan-options.json>
PYTHONPATH=<vnext>/src python3 -m reachable_audit r4 \
  <target> <campaign-id> <batch-id> --input <category-runs.json>
PYTHONPATH=<vnext>/src python3 -m reachable_audit r5 \
  <target> <campaign-id> <batch-id> --input <experiments.json>
PYTHONPATH=<vnext>/src python3 -m reachable_audit metrics \
  <target> <campaign-id> <batch-id>
PYTHONPATH=<vnext>/src python3 -m reachable_audit finding \
  <target> <campaign-id> <batch-id> --input <finding.json>
PYTHONPATH=<vnext>/src python3 -m reachable_audit r6 \
  <target> <campaign-id> <batch-id> --input <closure.json>
PYTHONPATH=<vnext>/src python3 -m reachable_audit campaign-close \
  <target> <campaign-id> <plan-id> --input <campaign-closure.json>
PYTHONPATH=<vnext>/src python3 -m reachable_audit drift-resolve \
  <target> <campaign-id> <drift-event-id> --input <evidence.json>
PYTHONPATH=<vnext>/src python3 -m reachable_audit shadow-evaluate \
  --input <paired-runs.json> --output <acceptance-report.json>
```

After a `task-collect` validation error, the task remains leased and non-terminal;
correct the result JSON and resubmit it with the same task/worker before the lease
expires, or use `task-release` with a reason. Use `task-list --batch-id` to inspect a
partial batch. If a successful task output must be corrected after collection but before
its R1/R2/R3 stage commits, use `task-amend` with a replacement output, reason, and
content-addressed evidence refs. The prior output remains immutable. Amendments after
stage commit are rejected until downstream stage invalidation/recomputation is available.

`shadow-evaluate` requires a valid HMAC-signed manifest and
`VNA_EVALUATION_HMAC_KEY`; the key must be held only by the independent evaluation
authority, never by discovery Agents.

`category-plan-options.json` contains an optional `budget` and optional `card_ids`. When
`card_ids` is omitted, the planner uses all approved cards applicable to the planned
Work Unit languages and categories. Inline card definitions are rejected; knowledge is
loaded from the versioned catalog under `<vnext>/knowledge/`.

`shadow-evaluate` never promotes vNext or retires v3. It only reports whether supplied
evidence satisfies the release gates. Synthetic runs cannot satisfy held-out,
representative-project, 20GB+, Handoff reconciliation, or traceability gates.

Execution tasks are durable artifact references. A worker must claim a lease before
collecting a result. R1/R2 commit only after every planned Work Unit/axis task succeeds.
Snapshot drift blocks the Batch; it can only be resolved after source hashes match the
frozen baseline and resolution evidence is recorded.

`campaign-close` automatically cancels unfinished durable tasks and releases registered
resources after all Campaign gates pass. `campaign-abort` is the explicit terminal path
for an abandoned audit; it always requires a `skill_issues` array, even when empty, and
writes `.audit_vnext/campaigns/<campaign-id>/lessons.md`. Every successful
`campaign-close` also writes that per-Campaign lessons file. Retryable gate failures do
not trigger cleanup; resume them or explicitly abort. The review input and Campaign closure JSON must
contain a `skill_issues` array. Each item requires `issue_id`, `kind` (`ERROR` or
`DEFECT`), `stage`, `summary`, non-empty `evidence_refs`, `regression_expectation`, and
`status` (`REGRESSION_PENDING` or `RESOLVED`). The consolidated backlog is written to
`.audit_vnext/skill-regression.json` and `.audit_vnext/lessons.md`.

Campaign closure JSON must contain `scope_dispositions`, including an empty array when
there is no unreviewed scope. Each `unreviewed_scope` item must match exactly one record
with `scope_ref`, `disposition` (`EXCLUDED` or `DEFERRED`), current `snapshot_id`,
`rationale`, `approved_by`, and evidence references. Evidence must resolve to a current
source `LOC-<path>:<line>` or an artifact recorded by the current Campaign. A follow-up
may cite an artifact from a declared history source, but the decision still requires
current-snapshot approval. Fresh Campaigns reject historical artifact references.

The complete intended workflow is specified in
`docs/design/SYSTEM_DESIGN_VNEXT.md` in the development repository.
