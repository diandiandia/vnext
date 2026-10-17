# Local Debug and Test Handoff

Prepared: 2026-10-17. This is a local repair-validation handoff, not release
certification. Use the committed source checkout, not an older installed skill.
No real target audit is started by these instructions automatically.

## 1. Pin the Build

Run from the checkout that contains this document:

```bash
cd /root/vnext
git rev-parse HEAD
git status --short
python3 --version
export PYTHONPATH="$PWD/src"
python3 -m reachable_audit --help
```

Record the commit and any worktree changes before testing. The local handoff also
records the exact source commit outside this checkout in
`/root/vnext-debug-info.json`. That file is machine-local and is not a test result.
An installed copy under a host's skills directory is not automatically synchronized.
In a new terminal, restore PYTHONPATH to this checkout before running commands.

## 2. Establish the Mechanical Baseline

```bash
env -u PYTHONPATH python3 -m pytest tests -o addopts='' -q
git diff --check
PYTHONPATH=src python3 -m reachable_audit compatibility-scan
```

The repair baseline is 200 passing tests and one skipped external held-out test.
The skip is expected without the protected external bundle; do not invent that
bundle or set held-out labels on synthetic fixtures to remove the skip.

Focused checks:

```bash
python3 -m pytest tests/test_evaluation.py tests/test_cli.py -o addopts='' -q
python3 -m pytest tests/test_execution.py tests/test_category_runs.py -o addopts='' -q
python3 -m pytest tests/test_campaign_closure.py tests/test_handoffs.py -o addopts='' -q
python3 -m pytest tests/test_planning.py tests/test_hotspots.py tests/test_snapshot_drift.py -o addopts='' -q
```

## 3. Choose a Small Real Debug Target

Start with a disposable, frozen clone, one language/family slice, and a separately
identified cross-language boundary case. Do not resume or rewrite an old Firefox
Campaign as the first test of this build. Record the model, host/tool versions,
permissions, selected scope, and a fixed spending limit before execution.

If comparing builds, use separate target clones and Campaign state. Keep source,
scope, model, tools, and budget comparable. The previous parent commit is a repair
baseline, not independent capability ground truth. Keep independently reviewed
answers outside the discovery Agent's accessible context.

Replace the target placeholder below with your disposable clean Git clone. A fresh
Campaign must not receive previous target findings, reports, or lessons.

```bash
TARGET=/path/to/disposable-clean-target
CAMPAIGN_ID="debug-$(date -u +%Y%m%dT%H%M%SZ)"
python3 -m reachable_audit init "$TARGET" \
  --campaign-id "$CAMPAIGN_ID" --audit-mode fresh --max-screening-fraction 0.25
python3 -m reachable_audit inventory "$TARGET" "$CAMPAIGN_ID"
python3 -m reachable_audit graph "$TARGET" "$CAMPAIGN_ID"
python3 -m reachable_audit plan "$TARGET" "$CAMPAIGN_ID" \
  --categories INJECTION,STATE \
  --max-work-unit-files 20 --max-batch-files 40 --max-batch-work-units 2
```

The screening ceiling and plan sizes above are explicit debug choices, not validated
defaults. Categories define a hard scope: risks outside them are not audited by this
run. To compare cost, use the same plan limits in both builds. If you intentionally
vary plan sizes, report that as a separate experiment. Two Work Units in one Batch
can exercise R4 bundling; a cross-Batch Handoff requires distinct planned Batches.

Use an actual Batch ID printed by plan:

```bash
BATCH_ID='replace-with-actual-batch-id-from-plan'
python3 -m reachable_audit r0 "$TARGET" "$CAMPAIGN_ID" "$BATCH_ID"
python3 -m reachable_audit task-schedule-r1 "$TARGET" "$CAMPAIGN_ID" "$BATCH_ID"
python3 -m reachable_audit task-list "$TARGET" "$CAMPAIGN_ID" --batch-id "$BATCH_ID"
python3 -m reachable_audit task-claim "$TARGET" "$CAMPAIGN_ID" debug-worker \
  --batch-id "$BATCH_ID" --operation discover_surfaces
```

The host Agent must actually inspect the scoped source. Follow the task's unchanged
output contract and the [host protocol](../SKILL.md) for collect/commit and later
stages. Do not replace actual analysis with empty successful results. Report measured
agent_runs, wall_seconds, input_tokens, cache_read_tokens, output_tokens, and host
configuration where available. Unknown usage is unknown, never zero.

## 4. Debug Objectives and Expected Behavior

| Check | Expected behavior |
|---|---|
| Release safety | RG1-RG11 can pass as implemented_subset_status=PASS; unavailable RG12-RG15 keep status=BLOCKED and eligible_for_promotion=false. |
| Real-card R4 bundle | After normal R3.5/category planning, task-schedule-r4 with --bundle-work-units 2 works with applicable nonempty card seeds and preserves each plan/WU result. |
| Per-axis R2 correction | Each of the six suffixed operations permits evidenced pre-commit correction; post-commit rewriting is rejected. |
| Interrupted work | Release/expiry/retry preserves attempt history; stale leases cannot finalize a newer attempt; missing attempt usage marks costs incomplete. |
| Abort | Pending, failed, released, and actively retried tasks are cancelled; registered resources are released or cleanup failures are disclosed. |
| Host notes | Generated issue/lesson revisions preserve existing host-authored content and do not duplicate identical revisions. |
| Source drift | R1/R2 scheduling blocks changed source and records drift; the hotspot provider rejects parsed bytes that differ from R0. Test edits only in disposable clones. |
| Knowledge drift | A resumed managed coordinator rejects changed catalog content, even with the same version string. Test this only in an isolated engine copy. |
| Handoff | An unjoined suffix is rejected before integration; a joined location chain still requires semantic human review. |
| Late candidate | Preserve the unresolved risk in the original report; use an explicit follow-up Campaign and re-verify without rewriting original verdicts. |
| Planning/cost | Empty repositories retain one root Work Unit; footprint excludes symlinks/runtime state; forecasts sum per Batch and never bundle across Batches. |

Use the regression fixtures for failure injection first. Do not corrupt an ongoing
audit or mutate the live knowledge catalog just to test an error path. Resource limits
are not a hostile-code sandbox: use an external container/VM for experiments.

## 5. Save Debug Evidence

Keep a private run note with:

- Engine commit, Python version, model/runtime/tool versions and tool permissions.
- Target commit, scope/plan IDs, Campaign ID, Batch IDs, selected categories and budget.
- Exact command, exit code, full error, task ID, operation, worker and lease attempt.
- Submitted result JSON, task input artifact refs, collected/amended output refs.
- Actual token/cost/time totals, missing-usage flags, retries and interruption points.
- Independently reviewed true issues, false positives, unresolved cases and duplicates.
- Unreviewed scope, open Handoffs, source drift and cleanup outcomes.

Preserve the target's complete `.audit_vnext` directory and host logs. Quiesce workers
before taking a consistent archive; do not copy only a live SQLite main database and
omit its WAL state. Capture failure evidence before abort/cleanup and retain the abort
report afterward. Never include signing keys, credentials, or sensitive target evidence
in public bug reports or commit them to the engine repository.

## 6. Interpretation and Remaining Limits

Success means correct state/evidence handling plus useful independently reviewed
results at the declared cost. Candidate counts alone are not a success metric.
Compare recall, false positives, unresolved rate, duplicates, coverage limitations,
and cost per independently confirmed issue; report uncertainty for small samples.

Automatic committed-stage reopening, complete dependency invalidation, rich interface
proofs, all-language hotspot coverage, and real held-out/scale qualification remain
incomplete. The current mixed-language late-candidate test is synthetic and exercises
explicit follow-up recovery, not autonomous rediscovery or release certification.