# Generality and Engineering Review

Date: 2026-10-20. Base: `a3b969c` plus this review's uncommitted changes.
This is a bounded engineering review and repair record, not a security certification,
exhaustive dead-code proof, Google internal approval, or ISO conformity assessment.
The historical [quality reassessment](QUALITY_REASSESSMENT_VNEXT.md) is retained as
dated evidence, not as the current implementation backlog.

## Product Objective and Decision

Preserve the approved **15 languages, ten prioritized security issues per language**:
C, C++, C#, Go, Java, Rust, Python, JavaScript, TypeScript, Kotlin, Scala, PHP, Ruby,
Swift, and Shell. Large, very large, and mixed-language repositories are primary
targets; bounded Work Units must not silently narrow Campaign scope.

The portfolio is declared product scope, not an independently measured universal
Top15 popularity ranking. Ten entries are prioritized review guidance, not a claim
that other mechanisms are irrelevant or that ten vulnerabilities must be found.
Language adapters, knowledge entries, and synthetic capacity tests are not evidence
of balanced discovery quality or production-scale qualification.

The architecture has not abandoned this objective: language/build separation,
bounded Campaign/Batch planning, Handoffs, durable task/artifact storage, and source
evidence support it. Operational guidance had drifted toward release certification
and one active mechanism retained deployment-specific assumptions. These are
corrected below. It is not justified to call the entire skill unbiased or completely
free of historical influence.

## Review Scope and Evidence

- Read the README, main skill, architecture/requirements/lifecycle documents, test
  and real-target plans, and local acceptance/investigation records.
- Trace catalog selection/serialization, offline refinement, stage amendment and
  invalidation, policy digests, compatibility scanning, and selected closure behavior.
- Validate the complete portfolio structurally and inspect selected semantic entries.
  Searches for known historical target identifiers and private paths are bounded
  checks, not an exhaustive semantic review of all 150 mechanisms.
- Inspect top-level runtime definition references and import usage with Python AST.
  No unreferenced top-level function/class candidate was found in the source/test
  name inventory. Dynamic usage, unreachable branches, redundant algorithms and
  every public API were not exhaustively proven.
- Reproduce the active trust-material and migration-guidance gaps with two failing
  regression assertions before repairing them.

## Confirmed Findings and Repairs

| Priority | Finding | Repair / verification |
|---|---|---|
| P1 | Main skill discovery wording emphasized testing a replacement rather than auditing authorized large/mixed-language projects. | Restore the product use cases in skill discovery text and distinguish experimental status from permission to use it. |
| P1 | The real-target plan added a development layer but still said every run required all identity/key/held-out gates; later sections repeated the ambiguity. | Separate development entry, external-evidence qualification, stop conditions, run records and required inputs. Preserve ordinary permissions, isolation, limits and validators; do not weaken signed-feature or release checks. |
| P1 | Go trust-store guidance embedded particular filenames, an API name and root/Linux/noninteractive assumptions; offline migration could recreate it. | Generalize source/sink/preconditions and counterevidence in both catalog and migration refinement; update digest-backed provenance. Mark the rewritten shipped guidance seeded, not a new observed target result. Test both the shipped catalog and regenerated output. |
| P1 | Runtime task guidance did not explicitly distinguish training evidence state/ranking from target applicability. | Add a shared catalog-context instruction requiring current target evidence, counterevidence, no expected-finding quota, and no exclusion of other evidenced mechanisms. Bump the task-policy digest version. |
| P1 | Current-contract documents still claimed supported post-commit amendment, invalidation and projection recovery were absent. | Correct system/software design and requirements; refresh lifecycle mechanism boundaries. Label old quality/roadmap registers historical and point to current completion evidence. |
| P2 | Four imports were unused, not public re-exports. | Remove `Counter`, two unused `Path` imports, and `asdict`; retain package re-exports and registration interfaces. |

Preserve provenance for generalized training mechanisms. A legacy source identifier
or `battle_observed` training state alone is not target contamination; target names,
private paths, expected verdicts, and unjustified environmental assumptions are the
actual concern. Framework/API examples are useful when applicability is demonstrated;
do not delete them simply because they are specific enough to guide source inspection.

Knowledge is content-bound to Campaign/task inputs. Existing Campaigns retain their
recorded catalog identity; use a new Campaign for the revised catalog rather than
silently replacing knowledge in an in-flight audit.

## Remaining Limits and Architecture Debt

1. No real balanced 150-cell discovery study, qualifying mixed-language boundary
   study, or 20GB+ recovery run establishes the stated capability yet. These remain
   capability evidence gaps, not reasons to block a development real-target audit.
2. Static hotspot generation currently has a Python AST implementation. Other
   languages still rely on host Agent source analysis plus their language guidance;
   adapters do not constitute equivalent automatic static analyzers.
3. Inventory/import/build graphs do not prove complete FFI/RPC/IPC/dataflow discovery.
   Supplied boundary validation does not establish semantic truth.
4. The single historical TR-07 wall-clock overrun remains unexplained. Preserve the
   2-second requirement and failure evidence; do not use retries or CPU-time
   substitution as proof of the wall-clock bound.
5. Runtime orchestration remains concentrated: the base checkout had roughly 3.3k
   lines in `execution.py`, 2.1k in `batch_workflow.py`, and 1.6k in
   `campaign_closure.py`. Size alone is not dead code. Extract cohesive components
   only against measured maintenance problems and behavior tests, not an unverified
   wholesale rewrite during an audit.
6. The main skill is a long operating contract. Progressive loading and a measured
   host-loop ergonomics study remain useful; this review does not establish prompt
   cost or reasoning quality merely by changing discovery wording.
7. Universal strict parser behavior, arbitrary host-input dependency tracking,
   independently observed reads, trusted reviewer identity and provider hard caps
   remain bounded or external. Ordinary development audits must label untested
   claims rather than manufacture trust evidence.
8. Semantic curation/ranking of every language's ten issues remains to be evaluated.
   Keeping a fixed portfolio is not bias by itself; historical sampling and unequal
   mechanism depth can still bias coverage and require counterexamples/real trials.

## Engineering and Standards Claims

Google internal criteria were not supplied; this review cannot establish compliance
with them. General code-review, maintainability and testing principles are not a
substitute for an authorized internal acceptance decision.

ISO/IEC/IEEE 12207 addresses lifecycle processes, not a code-quality score awarded
by pytest. No controlled applicable edition, organizational tailoring, process-owner
approval or clause-level objective-evidence assessment was supplied. Requirements,
design, tests, configuration history and repair records support only a preliminary
process-concept mapping. See the [lifecycle self-assessment](LIFECYCLE_CONFORMANCE_VNEXT.md).
Neither this review nor the repository establishes formal conformity.

## Verification

Interpreter: `/usr/bin/python3`, Python 3.14.4. The editor initially selected a
different virtual environment without pytest; verification used the established
system interpreter instead, without installing dependencies.

From the checkout root:

```bash
env -u PYTHONPATH /usr/bin/python3 -m pytest tests/test_knowledge_catalog.py tests/test_knowledge_migration.py -o addopts='' -q --tb=short
env -u PYTHONPATH /usr/bin/python3 -m pytest tests -o addopts='' -q --tb=short -ra
PYTHONPATH=src /usr/bin/python3 -m reachable_audit compatibility-scan
git diff --check
```

| Check | Result |
|---|---|
| Pre-fix regression run | 2 failed, 7 passed; confirmed shipped and migration gaps |
| Post-fix catalog/migration modules | 9 passed in 1.02 s |
| Complete post-fix suite | **342 passed, 1 skipped in 85.82 s**, exit 0 |
| Skip | Protected real held-out manifest not configured; not replaced with synthetic data |
| Compatibility scan | PASS, 0 findings; 49 Python / 167 knowledge / 1 prompt files |
| Editor diagnostics for changed Python files | No errors reported |
| Changed Markdown local-link targets | No missing targets |
| Skill discovery metadata | Required quoted fields present; description within 1024 characters |
| Portfolio | 15 languages / 150 issue entries retained |
| Patch formatting | `git diff --check` passed |

Results apply to the base commit plus these uncommitted changes, not the base commit
alone. No real target audit, Google assessment, or formal standards assessment was
performed. The full suite passing does not erase the historical TR-07 overrun.

## Next Real-Target Test

Use the [development pilot](REAL_CODE_AUDIT_TEST_PLAN_VNEXT.md) on authorized frozen
source with fresh state. Record source inspection, scope/boundaries, task
repair/retry behavior, usage and output size, evidence quality, unresolved cases,
and skill issues. Do not preload historical findings into fresh discovery.
Operator familiarity is disclosed, so this is not automatically a blind study.
Fix reproducible workflow defects and retest; reserve signed host/held-out release
qualification for its separately declared purpose.

## Recall and Long-Run Recommendations Review

The subsequent user proposal prioritizes discovery depth and stability over
certification machinery. Java tasks already select Java's ten entries, not all
150; a regression now checks this explicitly. HMAC authenticates an optional host
assertion or external-evidence envelope. It neither analyzes Java nor increases
vulnerability recall, and is not an ordinary audit prerequisite. Removing all
signed-feature code without migration would not improve source analysis and could
break callers; this change keeps it optional.

| Proposal | Decision and delivered change / boundary |
|---|---|
| Fresh worker per task, lightweight host | Adopt as the explicit host operating contract in the [runbook](../ORCHESTRATOR_RUNBOOK.md). The engine already exposes task leases and artifacts. Do not add a second provider-specific scheduler or claim that documentation enforces physical isolation/perfect attention. Same-lease corrections retain task-local context. |
| Six-axis expert triggers | Implement shared task prompts for surface, mechanism, state, fix variant, boundary and differential axes. Both compact/per-axis modes use the same triggers. Require evidence for non-applicability; historical commits are optional/authorized, not automatically loaded into fresh discovery. This is guidance, not semantic enforcement or proven recall improvement. |
| High-risk weighted revival sampling | Do not replace the default: `schedule_r35_revivals` already selects every initial R3 UNREACHABLE hypothesis when no selection exists. Existing explicit selections are honored. Add full-selection regression and stronger independent guard/boundary review guidance. Weighting may order reviews in future but must not silently reduce coverage or ignore budget. |
| HIGH paths must be deeply inspected | Implement HIGH -> INSPECTED checks at both durable R1 collection and direct R1 claim validation, with same-lease repair tests. LOW's existing inspection requirement remains. This intentionally rejects previously accepted HIGH/SCREENED outputs; correct the actual analysis and resubmit, not just the label. Declared depth still does not prove reading. |
| Only DTO/generated code may be screened | Do not adopt as a universal rule: both may carry security-relevant serialization or boundary semantics, and filename/type labels do not prove low risk. Preserve explicit screening, inspection and deferred scope rather than force unsupported claims. |
| Portable environment / restart | Add `tools/vnext.py`, resolving the source tree from its own location and forwarding the canonical CLI/exit code without `PYTHONPATH` or cwd dependence. Tests initialize and reopen state from another directory with spaces. It is a command entry, not an automatic provider/Agent driver. |
| Disaster recovery matrix | Deliver stage matrix, lease-aware bounded retries, same-lease correction, registered cleanup, honest experiment outcomes and restart procedure. Correct unsafe assumptions: expired leases can be reclaimed normally; drift resolution verifies restored bytes, not changed-source acceptance; an attempted timeout is not NOT_FEASIBLE; cleanup does not fix storage exhaustion. |
| C/C++/Java/Go hotspot expansion | Defer to a measured language-provider slice with source-bound parsing, positive/negative/lookalike/alias fixtures and precision/cost evidence. Regex/API matching is advisory, not a call graph or vulnerability proof. It is not implemented by this change. |
| Automatic Handoff symbol stitching | Current plans already route supplied cross-Batch edges to owners and validate endpoint proof/chain joins. Automatic symbol/security-edge discovery remains unimplemented; a future index must preserve ambiguity, dynamic dispatch and data-mapping evidence rather than invent closed chains. |
| Consolidated gap heatmap / attack planner | Existing reports retain several coverage/limitations fields, but no unified per-module ledger or automatic follow-up planner is delivered here. The runbook requires reconciliation of actual scope/axes/tool/provider gaps before closure and honest reporting of residual work. |

These changes are bounded foundations for a development real-target comparison,
not a claim of 24/72-hour unattended reliability, exhaustive inspection or multiplied
recall. Measure source-backed findings, false rejections, unresolved boundaries,
retry/repair rate, scope gaps, task input bytes, tokens and wall time at the same
scope and budget before claiming quality or efficiency gains.

### Post-Recommendation Verification

The same base checkout plus the accumulated review changes was validated with
`/usr/bin/python3` (Python 3.14.4); no new dependencies were installed.

| Check | Result |
|---|---|
| Pre-fix focused reproduction | 4 failed, 1 passed: missing launcher, accepted HIGH/SCREENED result, and missing deep-axis guidance |
| Post-fix focused recall/launcher selection | 8 passed, 68 deselected, 1.55 s |
| Final complete suite | **349 passed, 1 skipped in 40.53 s**, exit 0 |
| Skip | Protected real held-out manifest not configured |
| Compatibility scan | PASS, 0 findings; 49 runtime Python / 167 knowledge / 1 prompt files |
| Changed Python editor diagnostics | No errors reported |
| Runbook and related local links | All checked targets resolve |
| `git diff --check` | PASS |

Full verification command:

```bash
env -u PYTHONPATH /usr/bin/python3 -m pytest tests -o addopts='' -q --tb=short -ra
PYTHONPATH=src /usr/bin/python3 -m reachable_audit compatibility-scan
git diff --check
```

Regressions cover default complete revival selection and repeat scheduling, Java-only
knowledge scope, shared compact R2 triggers, revived-worker guidance, HIGH/LOW
depth rejection at collection and direct R1 commit, same-lease correction, launcher
state reopening and propagated CLI errors. No real-target discovery comparison or
24/72-hour endurance run was performed; these results do not establish those outcomes.
