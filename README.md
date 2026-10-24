# Reachable Audit vNext

Reachable Audit vNext is an experimental, evidence-oriented workflow for auditing
whether inputs from declared principals can reach security-sensitive operations in
large, mixed-language repositories.

It provides the durable campaign engine around an AI host: frozen scope, inventory,
work planning, task leases, evidence validation, independent refutation, experiments,
handoffs, recovery, and derived reports. The host Agent performs the source analysis;
the runtime records and validates its submissions. vNext is not a standalone static
analyzer and does not discover vulnerabilities without an Agent and an execution host.

> **Status:** vNext is a shadow candidate, not a replacement for v3. Promotion requires
> real paired, held-out acceptance across the approved language portfolio, mixed-language
> boundary tests, and a qualifying large-repository recovery run. The current evidence
> does not establish that vNext finds more vulnerabilities than v3.

## How It Works

An audit is a Campaign over a frozen repository snapshot. The planner divides its
inventory into Work Units and resumable Batches; cross-Batch work is assigned through
Handoffs. Campaign and Batch state is persisted in an SQLite event store, while evidence
and task outputs are retained as content-addressed artifacts.

The analysis workflow is organized into stages:

| Stage | Purpose |
|---|---|
| R0 | Freeze the snapshot, scope, tools, and declared constraints |
| R1 | Map entry surfaces, principals, components, and trust boundaries |
| R2 | Generate falsifiable hypotheses across applicable discovery axes |
| R3 | Verify reachability and the proposed vulnerability mechanism |
| R3.5 | Separate-task refutation, adjudication, and review of selected dispositions |
| R4 | Audit planned security categories and record evidenced coverage |
| R5 | Run justified experiments or preserve an explicit unresolved disposition |
| R6 | Reconcile evidence, scope, handoffs, risks, and Batch completion |

Campaign closure is separate from Batch completion. A passed gate means the recorded
requirements were satisfied; it does not mean that every file was inspected or that no
undiscovered vulnerability exists. Reports preserve excluded, deferred, and unresolved
scope.

Campaign reports inherit unresolved scope from every current Batch report; a
coordinator cannot erase it by submitting an empty list. A derived per-hypothesis
outcome ledger joins late Findings by hypothesis ID and retains non-finding candidates
without consistent rejection as `NEEDS_REVIEW`. These are traceability records, not
independent semantic decisions. Workflow `PASS` is separate from resource assessment:
missing attempt usage or limits cannot produce a resource `PASS`.

Findings are explicitly classified as security vulnerabilities, ordinary defects,
hardening recommendations, or insufficient evidence. A confirmed behavior defect is
not automatically a confirmed vulnerability; security-impact declarations are
evidence-linked structure, not automated proof of exploitability. Runtime
classification counts are Agent-declared; they are not independently human-validated
vulnerability counts. Require qualified independent review before externally presenting
a security-impact declaration as validated or release-ready.

## What Is Included

- Durable task scheduling, leases, retries, collection-time contracts, and resumable
  Campaign state.
- Source and build inventory, deterministic Work Unit/Batch plans, boundary records,
  and cross-Batch Handoff resolution.
- Append-only events, content-addressed evidence, drift tracking, and derived reports.
- Refutation/adjudication workflows and bounded, non-shell harness execution with
  artifactized observations. Harness resource limits are not a security sandbox for
  hostile native code; use an external container or VM for that threat model.
- A versioned 15-language certification portfolio, language/build adapters, issue
  profiles, and provenance-backed Mechanism Cards.
- Signed paired-run evaluation contracts and release gates.

Adapter presence is not language certification. The default static hotspot provider is
an advisory Python AST implementation; broader providers and balanced held-out
quality evidence remain incomplete. Build and import edges are not a complete security
call graph. Unsupported syntax, unresolved boundaries, and missing tools must remain
visible as limitations, not be treated as evidence of safety.

For development pilots, `init --experimental-go-hotspots` freezes an explicit Go AST
candidate-provider opt-in in the new Campaign. It requires a local Go toolchain and
does not build or run target packages. It is not enabled by default or language
certification; missing toolchains and parse failures remain visible. Review leads
against the target's actual guards, trust boundaries and counterevidence.
The existing `harness-run` accepts explicit JSON `"profile": "go-offline"` for
Go-compatible bounded builds/probes with private caches and offline fetch settings.
It changes neither ordinary harness defaults nor the need for host approval/isolation.
See the [Go execution example](docs/ORCHESTRATOR_RUNBOOK.md#7-evidence-ready-go-development-slice)
and TR-14 before claiming empirical evidence.

`init --experimental-java-hotspots` opts into bounded JDK parse-only Java method-site
leads; target packages are never compiled or loaded. Receiver types remain unresolved,
so same-name false positives are possible. Missing tools and unparsed files are gaps,
not evidence of safety. Neither experimental provider expands the release roster.
`init --static-challenges` also opts static-only REACHABLE hypotheses into the existing
two-perspective R3.5 process; retained claims remain static-only.

Before the first R0, inventory source files and component build manifests are included
in the frozen snapshot baseline. Register additional supporting XML/SPI/configuration
files not represented by those inventory entries through `evidence-register`; source
references must match their frozen digests. Scope-aware planning removes wholly
out-of-scope graph work but retains cross-scope boundary obligations. Campaign closure
can account for a component with no Work Unit only when all its source paths have
valid, evidence-backed EXCLUDED/DEFERRED dispositions and it has no boundary
obligation; this is scope accounting, not an audit or safety approval. See the runbook
for explicit late-output recovery and budget amendment; neither operation resets elapsed
time or fabricates missing usage.

The runtime uses its own Campaign state and canonical schemas. Use an explicit
absolute `--state-dir` outside the frozen target for source-search isolation; pass the
same location to every command. CLI defaults and legacy-state selection are described
in the [orchestrator runbook](docs/ORCHESTRATOR_RUNBOOK.md).
It does not load v3
queues or findings as discovery input. Fresh Campaigns isolate prior audit history;
follow-up history must be declared and remains context, not proof.

## Quick Start

The product objective is a versioned Top15-language portfolio with ten prioritized
security issues per language, including large, very large, and mixed-language
repositories. These are coverage goals, not expected findings or an exhaustive
checklist; the fixed roster is not a claim of an independently measured popularity
ranking. Catalog structure and synthetic scale tests do not prove real audit quality.

Ordinary authorized audits and development pilots do not require release certification,
HMAC key custody, or protected held-out labels. Signed host/external-evidence features
and promotion have separate prerequisites. Start with the
[development pilot requirements](docs/design/REAL_CODE_AUDIT_TEST_PLAN_VNEXT.md);
retain permissions, isolation, resource limits, and logs without inventing attestations.

Requirements: Python 3.11 or newer. The runtime has no third-party Python dependencies;
pytest is required for development tests. A host Agent and model/runtime are required to
perform the audit work.

For a working-directory-independent CLI, use
`python3 /path/to/vnext/tools/vnext.py --help` without setting `PYTHONPATH`.
The [orchestrator runbook](docs/ORCHESTRATOR_RUNBOOK.md) covers fresh task-local
workers, stage progression, restart, source-backed depth and bounded recovery.
Fresh worker contexts and sandbox enforcement are host responsibilities, not
guaranteed by the launcher.

From the repository root, set the target and Campaign ID, then initialize a Campaign.
Automatic snapshot detection accepts only a clean Git worktree; otherwise provide an
explicit frozen snapshot ID.

```bash
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
TARGET=/path/to/target
CAMPAIGN_ID=audit-2026-01

python3 -m reachable_audit init "$TARGET" \
  --campaign-id "$CAMPAIGN_ID" --snapshot-id "git:<commit>" --audit-mode fresh
python3 -m reachable_audit inventory "$TARGET" "$CAMPAIGN_ID"
python3 -m reachable_audit graph "$TARGET" "$CAMPAIGN_ID"
python3 -m reachable_audit plan "$TARGET" "$CAMPAIGN_ID" \
  --categories MEMORY-SAFETY,STATE,RESOURCE-DOS
```

`plan` records planned Batches and prints their IDs and scope summaries. An optional
`--cost-profile <json>` adds task-fanout and cost scenarios from caller-supplied measured
rates and explicit assumptions; it does not replan. For R4, the default remains one task
per CategoryAuditPlan. `task-schedule-r4 --bundle-work-units 2` opts into bundling same-
family plans while retaining a separate CategoryRun per plan and Work Unit; compare total
cost, retries, coverage, and review quality before using it on a production Campaign.

For each planned Batch, run R0 and use the durable task schedule/claim/collect/commit
workflow with a host Agent. The complete host protocol, evidence rules, and recovery commands are in
[`SKILL.md`](SKILL.md). Use the CLI help for the exact arguments supported by this build:

```bash
python3 -m reachable_audit --help
```

## Development

```bash
env -u PYTHONPATH python3 -m pytest tests -q
PYTHONPATH=src python3 -m reachable_audit compatibility-scan
```

On hosts where unrelated pytest plugins interfere with validation, record that fact
and use `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` with the same test selection. A killed or
incomplete run is not a passing result.

The compatibility scan checks legacy imports/formats and generic residue patterns in
runtime Python source, the main skill prompt, and runtime-eligible knowledge. It reports
the actual file counts; development/history documents and test fixtures are not runtime
knowledge. Project-specific residue tokens are caller-supplied rather than taken from a
built-in list of past targets. The offline legacy-knowledge migration tool also requires
an explicit reviewer/evaluator token file. A passing scan is bounded pattern evidence,
not semantic proof that no historical bias or project-specific guidance remains.

## Project Documents

- [面向非代码审计读者的项目介绍（中文）](docs/PROJECT_OVERVIEW_ZH.md)
- [Host skill and operating contract](SKILL.md)
- [System architecture](docs/design/SYSTEM_DESIGN_VNEXT.md)
- [Software design and data contracts](docs/design/SOFTWARE_DESIGN_VNEXT.md)
- [System requirements](docs/design/SYSTEM_REQUIREMENTS_VNEXT.md)
- [Software requirements and implementation status](docs/design/SOFTWARE_REQUIREMENTS_VNEXT.md)
- [Release acceptance plan](docs/design/ACCEPTANCE_PLAN_VNEXT.md)
- [Discovery quality evaluation protocol](docs/design/DISCOVERY_QUALITY_EVALUATION_PROTOCOL.md)
- [Test plan](docs/design/TEST_PLAN_VNEXT.md)
- [Repair roadmap](docs/design/REPAIR_ROADMAP_VNEXT.md)
- [ISO/IEC/IEEE 12207 lifecycle self-assessment](docs/design/LIFECYCLE_CONFORMANCE_VNEXT.md)
- [Quality reassessment and remaining acceptance gaps](docs/design/QUALITY_REASSESSMENT_VNEXT.md)
- [Current generality and architecture review](docs/design/GENERALITY_REVIEW_VNEXT.md)

The lifecycle document is a preliminary engineering self-assessment, not an ISO/IEC/IEEE
12207 conformity claim or certification. Formal assessment requires an authorized,
controlled edition, organizational tailoring, and clause-level evidence; these were not
supplied. This assessment does not establish edition publication/withdrawal status.
Google internal engineering requirements were not supplied and have not been assessed.
