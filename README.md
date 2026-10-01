# Reachable Audit vNext

This directory contains the clean-room vNext implementation. It is isolated from the
v3 runtime and implements the planned Campaign workflow:

- canonical Campaign and Batch state models;
- SQLite-backed append-only events;
- idempotent event collection;
- content-addressed artifacts;
- resumable Campaign state;
- build-boundary component inventory;
- deterministic Work Unit and Batch planning;
- cross-Batch Handoff generation;
- R0-R6 analysis, refutation, CategoryRun, and experiment records;
- BG1-BG8 Batch and CG1-CG10 Campaign gates;
- root-cause Finding deduplication and derived Campaign reports;
- paired v3/vNext shadow-run release evaluation;
- durable leased R1/R2 execution tasks for host or manual Agents;
- compact six-axis R2 task mode to reduce claim/collect overhead per Work Unit;
- source-slice drift detection with reverse-dependency invalidation;
- source adapters for the approved 15-language portfolio;
- 150 ranked language-issue profiles and approved Mechanism Cards with provenance;
- build graph adapters for 14 ecosystems, including CMake, Make, .NET, Composer, Bundler, sbt, and Perl;
- R5 harness recipes and bounded, non-shell toolchain probes;
- managed POSIX-limited harness execution with artifactized observations;
- per-Campaign lessons, explicit abort cleanup, and runtime compatibility scanning;
- signed release manifests with evidence digests and per-language issue-stratum gates;
- a command-line interface.

The orchestration core records and validates Agent-produced discovery evidence; it does
not independently discover vulnerabilities. vNext remains experimental until real
representative-project and 20GB+ evidence passes the release gates. See
`docs/design/SYSTEM_DESIGN_VNEXT.md`, `docs/design/SOFTWARE_DESIGN_VNEXT.md`, and
`docs/design/ACCEPTANCE_PLAN_VNEXT.md`.

## Development

```bash
python3 -m pytest tests -q
PYTHONPATH=src python3 -m reachable_audit --help
```

## Minimal Usage

```bash
PYTHONPATH=src python3 -m reachable_audit init /path/to/target \
  --snapshot-id git:<commit>

PYTHONPATH=src python3 -m reachable_audit status /path/to/target

PYTHONPATH=src python3 -m reachable_audit inventory /path/to/target <campaign-id>

PYTHONPATH=src python3 -m reachable_audit graph /path/to/target <campaign-id>

PYTHONPATH=src python3 -m reachable_audit plan /path/to/target <campaign-id> \
  --categories MEMORY-SAFETY,STATE,RESOURCE-DOS

PYTHONPATH=vnext/src python3 -m reachable_audit amend /path/to/target \
  <campaign-id> <plan-id> --reason "pilot exceeded budget" \
  --max-batch-files 500 --max-batch-work-units 2

PYTHONPATH=vnext/src python3 -m reachable_audit shadow-evaluate \
  --input /path/to/paired-runs.json --output /path/to/acceptance-report.json
```

When `--snapshot-id` is omitted, automatic detection accepts only a clean Git
worktree. Non-Git or dirty targets must provide an explicit frozen snapshot ID.
