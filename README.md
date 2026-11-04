# Reachable Audit vNext

**Make AI-assisted security audits resumable, evidence-traceable, and explicit about
coverage gaps.**

Reachable Audit vNext is an experimental Agent Skill and campaign runtime for
authorized audits of large, mixed-language repositories. It helps an AI host trace
whether inputs from declared principals reach security-sensitive operations, retain
counterevidence, and resume long-running work without relying on chat history alone.

**中文：让 AI 大仓库安全审计可恢复、证据可追溯、覆盖缺口可见。**
它负责组织审计和保存证据，不是安装后就能自动找出漏洞的扫描器。
详见[中文项目介绍](docs/PROJECT_OVERVIEW_ZH.md)。

> **Experimental shadow candidate:** vNext is not a production-ready scanner or a
> drop-in replacement for v3. Its audit and host capabilities remain under
> evaluation; passing workflow checks does not prove a repository is secure.

[Install](#install) · [Quick start](#quick-start-runtime) · [Runnable demo](#runnable-demo) ·
[Limitations](#current-limitations) · [Operating guide](docs/ORCHESTRATOR_RUNBOOK.md)

## What It Solves

| Audit challenge | vNext workflow |
|---|---|
| Unclear which source was or was not inspected | Freeze a snapshot, inventory source, plan Work Units, and retain excluded, deferred, and unresolved scope |
| Long audits lose state after interruption | Persist Campaign/Batch events, task leases, evidence, and recovery state |
| Evidence and conclusions are hard to review | Bind records to source locations and artifacts, retain counterevidence, and validate workflow contracts |
| Cross-component paths are easy to drop | Track explicit cross-Batch Handoffs and closure requirements |
| “No finding” is mistaken for “safe” | Report workflow completion separately from uncovered scope, unresolved questions, and residual risks |

## Who Is It For?

- Security reviewers tracing entry points, principals, guards, and sensitive
  operations across components or languages.
- AI Agent users who need durable task ownership, cross-component handoffs, and
  recovery after an interruption.
- Review leads who need source-linked evidence, counterarguments, and visible
  excluded, deferred, or unresolved scope rather than just a list of findings.

For a small, one-off general code review, a simpler review prompt may be enough.
vNext is designed for audit coordination and traceability, not automatic proof of
exploitability.

## Install

Requirements: **Python 3.11+** and a host Agent with an available model/runtime and
permission to use the CLI. The Python runtime has no third-party dependencies.
The Skills CLI route also requires Node.js/npm.

### Agent Skill installation

From the project where you want the host to discover the Skill:

```bash
npx skills add diandiandia/vnext
```

Select your host in the installer. Review the Skill before granting permissions.
Installation does not dispatch an Agent, authorize target execution, or establish
host compatibility or language certification.

中文读者可先看[中文项目介绍](docs/PROJECT_OVERVIEW_ZH.md)。

The Skill needs its accompanying `tools/`, `src/`, `knowledge/`, and referenced
runbooks, not just `SKILL.md`. Set `VNEXT_ROOT` below to the installed Skill directory
containing those files, or use a complete checkout. Local-source copy installation
has been smoke-tested with the Skills CLI for GitHub Copilot; the public GitHub
installation and an end-to-end host audit have not been verified by that test.

### Complete checkout / local development

```bash
git clone https://github.com/diandiandia/vnext.git
cd vnext
VNEXT_ROOT="$PWD"
python3 "$VNEXT_ROOT/tools/vnext.py" --help
```

To install the checked-out Skill into another project's host, run
`npx skills add /absolute/path/to/vnext` from that project.

The launcher works from other directories without installing a Python package or
setting `PYTHONPATH`. A built wheel includes runtime knowledge and parser helpers,
but does not install the host Skill or its runbooks. Building the wheel requires the
setuptools dependency declared in [pyproject.toml](pyproject.toml).

## Quick Start (Runtime)

The `npx skills add` command above installs the Agent Skill. The commands below run
the accompanying Python Campaign runtime from a complete checkout or a complete
installed Skill directory; they are not an alternative Skill installation method.

Use an authorized, frozen source copy. Set `VNEXT_ROOT` to the absolute installation
or checkout directory, and keep an explicit absolute state directory **outside** the
target. Pass that same state directory to every command.

```bash
VNEXT_ROOT=/absolute/path/to/vnext
TARGET=/absolute/path/to/authorized-frozen-copy
STATE_DIR=/absolute/path/outside-target/audit-state
CAMPAIGN_ID=audit-local-001
CATEGORIES=INJECTION,AUTHN,STATE

vnext() { python3 "$VNEXT_ROOT/tools/vnext.py" "$@"; }
vnext --help
vnext init "$TARGET" --state-dir "$STATE_DIR" \
  --campaign-id "$CAMPAIGN_ID" --audit-mode fresh --static-only
vnext inventory "$TARGET" "$CAMPAIGN_ID" --state-dir "$STATE_DIR"
vnext graph "$TARGET" "$CAMPAIGN_ID" --state-dir "$STATE_DIR"
vnext plan "$TARGET" "$CAMPAIGN_ID" --state-dir "$STATE_DIR" \
  --categories "$CATEGORIES"
vnext status "$TARGET" --state-dir "$STATE_DIR"
```

Automatic snapshot detection requires a clean Git worktree. For a non-Git frozen
copy, add an approved immutable `--snapshot-id` and retain its provenance; do not
use a placeholder identity for mutable source.

The categories above are an illustrative limited scope, not a complete audit
checklist. Choose approved families from the target's threat model and language
profiles; explicitly account for exclusions. `--static-only` freezes a prohibition
on dynamic target execution, including managed harnesses; it is not an OS sandbox.

`plan` prints the actual Batch IDs and scope summaries. These commands prepare a
Campaign; **they do not perform the audit**. For a returned Batch, the host must
execute R0 and the durable schedule/claim/collect/commit lifecycle in
[SKILL.md](SKILL.md) and the [orchestrator runbook](docs/ORCHESTRATOR_RUNBOOK.md).
After an interruption, restore the same paths and Campaign ID, inspect `status`
and the runbook's recovery procedure; do not initialize a new Campaign as a
substitute for resuming the old one.

## Optional Coverage and Delivery Pilots

New Campaigns can opt into `init --coverage-critic --domain-guidance` and
`--task-budget-policy policy.json`. They remain experimental, disabled by default,
and do not certify discovery quality. Critic-enabled runs require source-evidenced
initial and final reviews before R3 and R6 respectively. New coverage uses an
approved, versioned Plan extension that replays **all** Batches, not an in-place
`amend`. Domain guidance is explicitly selected from current source, not inferred
from project names. Unresolved review items can retain blockers, validation plans
and investigation urgency without a vulnerability severity.

See [pilot commands and safety boundaries](docs/ORCHESTRATOR_RUNBOOK.md#optional-coverage-and-delivery-pilots)
before enabling them. Safe artifact transfer is not a sandbox; isolated target
execution remains unavailable until its complete host policy is qualified.

## Runnable Demo

This is a **workflow smoke demo, not a vulnerability-finding benchmark**. It creates
a tiny synthetic Python target, inventories it, plans work, and reopens saved state
from another working directory. Reuse `VNEXT_ROOT` and the `vnext` function above.
Run in a disposable directory; use a new directory for each independent demo.

```bash
mkdir -p vnext-demo/target vnext-demo/state
DEMO_ROOT="$(cd vnext-demo && pwd)"
TARGET="$DEMO_ROOT/target"
STATE_DIR="$DEMO_ROOT/state"
CAMPAIGN_ID=demo-001
printf 'def echo(value: str) -> str:\n    return value\n' > "$TARGET/app.py"

vnext init "$TARGET" --state-dir "$STATE_DIR" \
  --campaign-id "$CAMPAIGN_ID" --snapshot-id fixture:readme-demo \
  --audit-mode fresh --static-only
vnext inventory "$TARGET" "$CAMPAIGN_ID" --state-dir "$STATE_DIR"
vnext graph "$TARGET" "$CAMPAIGN_ID" --state-dir "$STATE_DIR"
vnext plan "$TARGET" "$CAMPAIGN_ID" --state-dir "$STATE_DIR" \
  --categories INJECTION
(cd "$DEMO_ROOT" && vnext status "$TARGET" --state-dir "$STATE_DIR")
```

Expected output is JSON: initialization identifies Campaign `demo-001`, planning
returns planned Batches, and the final status still contains that Campaign. The
source stays in `target/`; state stays in the sibling `state/` directory. Keep the
fixture unchanged while its Campaign is active.

A real audit adds source anchors, principal/precondition declarations, reachability
arguments, refutation records, evidence-linked classifications, and unresolved
scope. See the [review queue and report guide](docs/ORCHESTRATOR_RUNBOOK.md#1-stable-command-entry)
for how provisional claims remain visible. This demo produces no confirmed
vulnerability or completed audit report.

## Current Limitations

- **Experimental:** vNext is a shadow candidate, not release-certified.
- **Agent-dependent:** the host reads and analyzes source; the runtime validates
  submissions, not their complete semantic truth.
- **Not a universal scanner:** 15 language adapters and the knowledge portfolio
  are not proof of certified discovery quality in those languages.
- **Not a safety verdict:** workflow `PASS` does not mean complete inspection,
  absence of vulnerabilities, or independently validated exploitability.
- **Host-enforced isolation:** execution permissions, fresh worker contexts, and
  protection against hostile target code remain host responsibilities.

## How It Works

It provides the durable campaign engine around an AI host: frozen scope, inventory,
work planning, task leases, evidence validation, independent refutation, experiments,
handoffs, recovery, and derived reports. The host Agent performs the source analysis;
the runtime records and validates its submissions. vNext is not a standalone static
analyzer and does not discover vulnerabilities without an Agent and an execution host.

> **Status:** vNext is a shadow candidate, not a replacement for v3. Promotion requires
> real paired, held-out acceptance across the approved language portfolio, mixed-language
> boundary tests, and a qualifying large-repository recovery run. The current evidence
> does not establish that vNext finds more vulnerabilities than v3.

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

New Campaigns may freeze `init --static-only` to prohibit dynamic execution, including
managed harnesses. New Campaigns default to `--defer-r35-splits` to retain split
refutations as provisional `NEEDS_REVIEW` without blocking on human adjudication.
Use `--no-defer-r35-splits` to require human split adjudication instead.
Existing Campaigns retain their frozen policy. `review-queue` derives current evidence
packets, excluding superseded Batches without deleting their historical records;
`recovery-plan` lists invalidated projections without reusing stale results. See the
[orchestrator runbook](docs/ORCHESTRATOR_RUNBOOK.md) for defaults and limitations.

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
The optional `"profile": "jvm-bounded"` uses a 4 GiB address-space default for
JVM startup; an explicit memory limit overrides it, and JVM heap limits must be set
in the approved command. R5 empirical evidence also requires declared execution
provenance; built-copy runs use `equivalent` fidelity with content-addressed evidence.
Process-resource registration failure is an execution error even if the child has
already exited; it cannot produce a completed harness record or empirical upgrade.

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

## Audit Scope and Qualification

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

Run release evaluation from the complete source checkout: RG8/RG9 require local source,
knowledge, main Skill and operating-runbook scan coverage. A wheel-only installation cannot satisfy that
qualification requirement.

`plan` records planned Batches and prints their IDs and scope summaries. An optional
`--cost-profile <json>` adds task-fanout and cost scenarios from caller-supplied measured
rates and explicit assumptions; it does not replan. For R4, the default remains one task
per CategoryAuditPlan. `task-schedule-r4 --bundle-work-units 2` opts into bundling same-
family plans while retaining a separate CategoryRun per plan and Work Unit; compare total
cost, retries, coverage, and review quality before using it on a production Campaign.

## License and Permissions

The package currently declares `Proprietary` in [pyproject.toml](pyproject.toml);
this checkout does not include a standalone license granting reuse rights.
Public availability and Skill installation do not themselves grant permission to
copy, modify, or redistribute the project. Obtain appropriate permission from the
maintainer. Authorization to audit a target repository is a separate requirement.

## Development

pytest is required for development tests.

```bash
env -u PYTHONPATH python3 -m pytest tests -q
PYTHONPATH=src python3 -m reachable_audit compatibility-scan
```

On hosts where unrelated pytest plugins interfere with validation, record that fact
and use `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` with the same test selection. A killed or
incomplete run is not a passing result.

The compatibility scan checks legacy imports/formats and generic residue patterns in
runtime Python/helper source, the main Skill, its operating runbook, and runtime-eligible knowledge. It reports
the actual file counts; development/history documents and test fixtures are not runtime
knowledge. Project-specific residue tokens are caller-supplied rather than taken from a
built-in list of past targets. The offline legacy-knowledge migration tool also requires
an explicit reviewer/evaluator token file. A passing scan is bounded pattern evidence,
not semantic proof that no historical bias or project-specific guidance remains.
Full checkout/Skill copies retain evaluator-side history; these checks do not isolate
host contexts or authorize loading prior project plans into discovery workers.

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
- [Historical quality reassessment](docs/design/QUALITY_REASSESSMENT_VNEXT.md)
- [Current generality and architecture review](docs/design/GENERALITY_REVIEW_VNEXT.md)

### Development and Evaluation Records

Dated candidate plans and real-target records under `docs/design/` document
development/evaluation work; they are not universal audit requirements or discovery
input. Fresh discovery workers must not receive prior target plans, findings or
lessons merely because an evaluator-side document links to them. See the [Skill's
context boundary](SKILL.md#host-agent-loop).

### Assurance Boundaries

The lifecycle document is a preliminary engineering self-assessment, not an ISO/IEC/IEEE
12207 conformity claim or certification. ISO lists the 2026 second edition as current,
but this repository has no controlled text, approved applicability/tailoring decision,
or clause-level evidence; see the linked lifecycle document for the bounded basis.
Google internal engineering requirements were not supplied and have not been assessed.
