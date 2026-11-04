# Generality and Engineering Review

Initial review: 2026-10-20. Base: `a3b969c` plus that review's uncommitted changes.
Latest reassessment: 2026-11-04, base `494a698` plus the reviewed and repaired
changes in [the latest review](#latest-review-2026-11-04-generality-and-evaluation-integrity).
Earlier sections are dated historical evidence, not the current backlog or audit plan.
This is a bounded engineering review and repair record, not a security certification,
exhaustive dead-code proof, Google internal approval, or ISO conformity assessment.
The historical [quality reassessment](QUALITY_REASSESSMENT_VNEXT.md) is retained as
dated evidence, not as the current implementation backlog.
Earlier sections retain their dated review evidence; the latest linked section is
authoritative for this reassessment, not a new per-target audit procedure.
Subsequent user-approved default update (2026-10-25, task policy 49): new CLI
Campaigns and library Campaigns with omitted constraints now enable split deferral.
`--no-defer-r35-splits` / exact library constraints opt out; existing frozen selections
are preserved. Earlier references to opt-in deferral describe the reviewed policy 48,
not the current default. The unresolved-only and decision-packet contracts are unchanged.

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
6. The main skill remains an operating contract. Its command catalog and duplicated
   successful R1/R2 payload examples have been removed in favor of CLI help, the
   runbook, and each task's `output_contract`; the main file is now 453 lines.
   Progressive-loading ergonomics and prompt-cost effects have not been measured.
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

## Acceptance Follow-up: Finding Classification Gate

The 2026-10-21 acceptance package exposed a product-level false-positive risk:
three behavior/robustness/hardening items were accepted by the finding command as
`CONFIRMED` without recording security impact. The operator's review classified the
three items as ordinary defect, ordinary defect, and hardening respectively; none
was demonstrated to be a security vulnerability. The acceptance artifact checksums
passed, but the gate behavior itself failed.

The runtime now requires explicit Finding classification. Security-vulnerability
records require structured attacker, boundary, asset, security-property, impact,
severity-rationale, and evidence-reference fields. Reports separate those classes
and count only confirmed security-vulnerability records as confirmed vulnerabilities.
Focused regression coverage for finding recording/reporting and R4/R5 task contracts
passes (91 tests). The structural gate does not establish semantic truth,
exploitability, independent review, or severity correctness; those remain evidence and
adjudication responsibilities.

The same acceptance remains **partially unresolved**:

- The R2 run on the approximately 1.9 MB / 60k-line source file did not complete
  successfully within the observed 28-minute run, while a small slice was reviewable.
  The planner now flags included individual files of at least 1 MiB for explicit
  preflight; size lookup failures are surfaced rather than reported as zero bytes.
  This is advisory, not a hard capacity limit, source slicer, physical-read observer,
  or proof that all flagged work can be completed. The checkout has not demonstrated
  bounded, complete R2 analysis for an indivisible oversized source file. Do not
  increase the timeout and treat that as a fix; disclose/defer the affected path
  explicitly or run an independently scoped partitioned follow-up whose coverage can
  be reconciled. No 20GB+ recovery or balanced 15-language capability has been
  established.
- The acceptance R1 output omitted specialized iterator-helper entry points relevant
  to the selected core subsystem. This is a measured discovery limitation, not
  evidence that a parser/provider bug has been isolated or that an R2/R3 call chain
  was proved. The next core-subsystem trial must predeclare helper-level recall checks
  and inspect source-backed call/guard/sink evidence. A separate residual
  use-after-free candidate in the fixed snapshot remains static-only and requires
  dynamic confirmation or maintainer review; it is not a vNext defect fix or an
  empirically confirmed result.
- The acceptance summary reports T1 at commit `5d7dd33`, while its raw commit record
  names `c6ff0b4`. The reported 352 passed / 1 skipped result is therefore not
  attributable to one unambiguous source revision until the record is reconciled.

The focused finding-gate/task-contract run passed **91 tests**; the CLI planning
warning/stat-error regressions passed **26 tests**. Final local verification passed
**355 tests with 1 skip**; the skip is the protected held-out acceptance test because
no real manifest is configured. The compatibility scan passed with zero findings
(49 Python, 167 knowledge, 1 prompt file), and `git diff --check` passed. These are
local software regressions, not a rerun of the acceptance package, not confirmation
of R2 large-file scalability, and not real-target or release qualification evidence.

## 2026-10-22 Reassessment Addendum

This addendum reassesses the current checkout; it does not replace historical evidence
above. It covers active user-facing surfaces (`README.md`, `SKILL.md`, runbook), current
system/software design and requirements, completion/test plans, and the lifecycle
self-assessment. Target-specific names in explicitly historical engineering records
remain historical documentation and are not shipped runtime task context.

### Confirmed findings and repairs

| Priority | Finding | Repair and verification boundary |
|---|---|---|
| P1 | The runtime skill contained a named historical large-source target and run result. Although factually relevant to prior engineering, it could prime a generic audit with a past project's identity and distract from target-independent capacity rules. | Removed the named example and retained only the general qualification rule. Added a regression that supplies the historical token to the runtime residue scanner and requires the active prompt surface to pass. |
| P1 | The two documented R2 scheduling examples omitted `--entrypoint-checklist`, now a required CLI argument. The contract prose described fields but offered no valid file example. | Added the required argument to both command examples, documented exact keys and `[]`, and added a schema example using clearly illustrative IDs/anchors. Runtime CLI validation and R2 tests remain the executable authority. |
| P1 | Current design text said R4 Finding attribution was optional and described external-observation registration as absent, contradicting enforced reconciliation and the implemented signed evidence-only registration path. | Updated the R2/R4/R6 stage contracts, R5 external-observation boundary, SYSR-034 and software design. Added SYSR-041 and mapped SWDR-047 to it; confirmed contiguous traceability IDs (41 SYSR and 47 SWDR). |
| P2 | The runtime skill duplicated the full CLI command catalog and successful R1/R2 payload schemas, increasing maintenance and risking divergence from CLI/task contracts. | Replaced the catalog with a compact lifecycle entry point and pointers to CLI help/runbook; removed copied R1/R2 payloads in favor of each claimed task's `output_contract`. Added an explicit repository-audit applicability statement. The resulting `SKILL.md` is 457 lines; this is a readability change, not evidence of improved model performance. |
| P1 | The first large real-target run produced structurally valid but semantically off-target R4 reasoning and security-impact classifications later questioned by its coordinator; no independent human review or dynamic experiment occurred. | Clarified that runtime vulnerability counts are Agent-declared, not independent validation; the README, Skill, software design, test plan, and real-target plan now require a recorded separate review before external or release-ready claims. This is an operating/process control, not an engine-enforced reviewer-identity gate. |
| P1 | The offline knowledge migration utility embedded a fixed blacklist of historical target/project names, contradicting the stated caller-supplied residue policy and potentially biasing candidate exclusion. | Removed the built-in list. Migration now requires an explicit reviewer/evaluator token file and applies it to source filtering and generated-asset validation; updated SWDR-028 and added TR-12 tests for missing input, exclusion, and no token leakage. This remains pattern-based, not semantic portability proof. |

### Updated assessment

- **Generality:** The language/build/component separation and explicit limitations
  remain suitable for a general-purpose audit workflow. The 15-language portfolio and
  ten prioritized issue entries per language are explicit product scope, not a neutral
  or independently measured universal ranking. The named-target residue is removed
  from the active prompt, but no bounded residue scan can prove the absence of all
  semantic historical influence.
- **Bias and discovery quality:** The recent R2/R4/R6 gates improve declared recall
  checks and reconciliation, but they do not observe source reads or validate semantic
  evidence. Fixed counts, catalog provenance, and language adapters do not establish
  balanced discovery quality. Unequal profile depth, omission of mechanisms outside the
  prioritized ten, and operator/host context remain risks requiring predeclared,
  independently adjudicated, equal-budget real-target studies.
- **Dead code and redundancy:** No concrete dead-code deletion was justified by this
  review. The runtime has substantial orchestration concentration (`execution.py`,
  `batch_workflow.py`, and `campaign_closure.py`); this is maintainability debt, not
  proof of dead code or duplicate behavior. CLI registries, adapter registration,
  persisted schema compatibility, and event recovery make name-count heuristics
  unreliable. No dedicated unused-code linter is configured in `pyproject.toml`.
  Do not remove code or split these modules without a demonstrated unreachable path or
  measured maintenance/behavior benefit.
- **Documentation quality:** R2/R4/R6 structural contracts and requirement traceability
  align at the reviewed surfaces. The current test plan and completion plan now separate
  those structural checks from semantic quality and include the latest real-target
  limitations. The repair roadmap remains a dated historical register; its table is not
  the current implementation ledger.
- **Google/internal criteria:** No controlled Google internal engineering or security
  standard was supplied. Compliance cannot be evaluated or claimed from public coding
  conventions, and this repository has no organizational approval evidence.
- **ISO/IEC/IEEE 12207:** The lifecycle document is still only a preliminary process-
  concept self-assessment. The new traceability row improves evidence organization but
  is not clause-level conformity. No controlled edition, organizational tailoring,
  process-owner approvals, audit evidence, or certification was supplied. These are
  governance/evidence gaps, not repository defects that can be repaired by code.

This review does not find grounds for a broad architectural rewrite. The product remains
experimental: use an authorized development real-target audit to test behavior and
collect skill defects; do not represent it as Google-approved, ISO-conformant, unbiased,
dead-code-free, or release-qualified.

### 2026-10-22 Real-Target Evidence Addendum

The supplied real-target bundle passed its `SHA256SUMS` checks. Its recorded engine
revision is `5d7dd33` plus TR-09 worktree changes and its task policy is
`vnext-task-policy-37`; the 2026-10-23 checkout reported
`vnext-task-policy-38`. The current 2026-10-24 runtime policy is recorded in the
reassessment addendum below.
The run is therefore evidence about the earlier contract and is not a retest of the
current R2/R4/R6 gates.

The first Batch completed its planned stages and its R2 task finished in 532 seconds on
an individual source file above the 1 MiB advisory threshold. That demonstrates one
successful large-file task, not complete physical inspection, range coverage,
whole-project coverage, or general capacity. The recorded Batch had 61 R1 Surfaces
across 39 files, but only 17 files had a Surface reference; R2 evidence concentrated
on seven files and R6 left 23 Surfaces UNREVIEWED. Predeclared helper checks identified
missed iterator-helper, JSON, evaluation, and examples-boundary paths. The second Batch
was not run.

The same evidence records R4 reasoning that did not address its linked hypotheses and
security-impact classifications later questioned by the coordinator. No independent
human review was performed and no dynamic experiment ran. The machine-enforced checks
validate identities, coverage, and reference shape; they cannot establish that a
citation proves the stated claim. This is a confirmed limitation of the current
assurance boundary, not a demonstrated vulnerability in the audited target.

These observations motivated explicit R2 entrypoint checklists and R4/R6 Finding
reconciliation in the current policy-38 contract. The policy-37 trial cannot establish
whether those controls improve recall or semantic quality. The next authorized pilot
must measure them directly, preserve unreviewed scope, and record qualified independent
review of each security-impact declaration. One successful run cannot establish
balanced language/issue coverage or remove sampling and operator bias.

The active Skill, README, and runtime-eligible knowledge contain no matches for the
checked historical target/helper identifiers. The migration tool now has no baked-in
target-token blacklist; its caller-supplied input is mandatory. Historical names remain
in dated test/evidence documents and are not runtime task context. The compatibility
scan is still bounded pattern evidence; it does not prove semantic neutrality across
all guidance or development/history records.

### Addendum Verification

| Check | Current result |
|---|---|
| Full test suite | After TR-12: **359 passed, 1 skipped in 42.96 s** with pytest plugin auto-loading disabled; the skip requires a protected held-out manifest not configured locally. Focused migration/CLI/experiment tests: **45 passed**. A default-plugin rerun was terminated by SIGKILL (137); the reduced-overhead rerun completed successfully. |
| Runtime compatibility/residue scan | PASS, 0 findings; 49 Python, 167 knowledge, 1 prompt file |
| Python syntax | `compileall` for `src` and `tools`, plus migration tool `py_compile`, passed |
| R2 command contract | CLI help confirms `--entrypoint-checklist` is required |
| Historical-residue regression | Runtime-prompt test passes with a caller-supplied residue token |
| Migration residue policy | TR-12 caller-supplied token test and required CLI argument cover the offline migration path |
| Skill length and quick-start | `SKILL.md` is 457 lines; launcher invocation and required command arguments match the runbook/CLI |
| Documentation links | Local Markdown targets resolve across 15 user-facing/design documents |
| Patch formatting | `git diff --check` passed |

These checks establish local implementation and bounded residue-pattern behavior only.
They do not establish semantic neutrality, dead-code absence, real-target recall,
Google/internal compliance, ISO conformity, or release qualification.

## 2026-10-23 Pilot-Driven Repair and Reassessment

The supplied development pilot used engine `f1ec0bc`, one Batch, seven Work Units
and 369 source files. Read-only inspection verified 649 content-addressed artifacts
against their SHA-256 names and the durable Campaign state. This is artifact-byte
integrity, not a signed complete evidence manifest or independent target adjudication.
All 15 Findings were static-only and NEEDS_REVIEW; no confirmed security-vulnerability
or balanced portfolio-quality claim follows.

### Confirmed repair scope

- **Scope inheritance:** a current R6 report contained unresolved scope while the
  Campaign submission was empty. Closure previously allowed the final report to say
  no declared unreviewed scope. The report now unions current Batch items with
  coordinator scope and preserves Batch provenance, Markdown and lessons. Inherited
  unresolved items are not silently converted to approved exclusions.
- **Candidate visibility:** a derived per-hypothesis outcome ledger joins Findings by
  hypothesis ID even when recorded after R4. It retains stage evidence/rationales and
  marks non-finding candidates without consistent rejection NEEDS_REVIEW, adding them
  to unresolved scope. It neither forces a Finding nor adjudicates semantic truth.
- **Revival semantics:** the old `revived_hypothesis_ids` name actually means reviewed
  items, including UPHOLD. Empty `adjudicated_hypothesis_ids` is not proof that these
  reviews lacked required adjudication: that list belongs to the eligible
  REACHABLE/EDGE_PROVEN refutation path. New summaries explicitly separate reviewed,
  upheld and actual revivals while preserving the legacy field. Prior claims that all
  six UPHOLD items were unadjudicated overturns were not justified.
- **Execution reliability:** task contracts disclose pure source-anchor chains and
  target-version runtime-semantic assumptions; lease timing does not imply worker
  liveness. State-directory handling, R6 result shape compatibility and provider
  scan-coverage reporting are covered by TR-13. The host must still confirm dispatch,
  release failed dispatches, stop active workers and supply actual provider usage.
- **Resource honesty:** elapsed completion time and the optional local Campaign
  deadline are recorded separately from parallel worker-duration sums. Missing
  attempts, usage/configuration or wall limits cannot become resource PASS. The
  local deadline blocks new claims, including after a pause; it is not a provider
  hard cap or an autonomous worker terminator.

### Generality, complexity and standards decision

No target-specific detector, helper list, verdict exception, fixed historical-target
blacklist or expected-finding quota was added. The pilot target's names remain in
dated evidence, not active runtime rules. A bounded scan of source, runtime knowledge
and the main Skill for the two supplied historical target identifiers and private
root paths found no matches. This cannot prove semantic neutrality of all 150 issues.
The fixed 15-language/ten-issue scope and unequal automatic provider coverage remain
explicit product/evidence boundaries, not balanced capability certification.

A Python AST name/attribute/string reference inventory across 75 source/test/tool
files found no unreferenced candidate among 263 runtime top-level definitions at the
time of inspection. This is not a control-flow or dynamic dead-code proof. One duplicate
test import in a touched module was removed. No runtime deletion or wholesale module
split was justified; orchestration modules remain large and maintenance-heavy.
The repairs derive new report views from existing events rather than add a second
state machine, extra mandatory review stages, or a target-specific rule system.

README, Skill, runbook, system/software requirements and design, and test plans now
name the same structural and host boundaries (SYSR-042, SWDR-048, TR-13). A closed
workflow with missing usage, unresolved candidates, or no independent reviewer must
not be advertised as full coverage, confirmed vulnerabilities or capacity qualification.
The old pilot cannot validate these later repairs; use the updated real-target protocol
for a new regression run.

Google internal criteria were not supplied and cannot be assessed or claimed.
ISO/IEC/IEEE 12207 remains a preliminary process-concept mapping: controlled edition,
organizational tailoring, process ownership, approvals and clause-level independent
evidence are absent. More code, tests or documentation cannot manufacture conformity.
The architecture is usable for authorized development pilots; excellent universal
audit quality, dead-code freedom, absence of bias and release qualification remain
unproven.

### Final Local Verification (2026-10-23)

- Full suite: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests -o addopts='' -q --tb=short`
  completed with **385 passed, 1 skipped in 39.96 seconds**. The skip is
  `protected real held-out manifest is not configured`; no protected labels were
  fabricated. The two initial reproductions failed on lost scope and missing resource
  assessment before their repairs.
- Compatibility scan: PASS, zero findings across 49 runtime Python files, 167
  knowledge files and one prompt. Python `compileall` and `git diff --check` pass.
- Pylance reports no diagnostics in the modified closure/workflow modules; task/CLI
  changes were also checked during implementation. An unused local binding in the
  touched revival method was removed without removing its prerequisite check.
- Local Markdown targets resolve across 15 user-facing/design documents; the main
  Skill remains below 500 lines (470 lines at verification).
- Read-only replay of the new outcome derivation on the original pilot retains all
  15 Findings through 18 linked hypotheses (a many-to-many relation, not a 15-item
  hypothesis quota); the 56 hypotheses receive 18 FINDING_RECORDED, 2 REJECTED and
  36 NEEDS_REVIEW outcomes. The original R6 supplies four unresolved-scope inheritance
  inputs. This replay exercises derived reporting, not a new full Campaign or a
  semantic adjudication. Original evidence was not rewritten or reopened.

These are working-tree implementation checks. Actual host dispatch/termination,
provider metering, independently reviewed impact, mixed-Batch boundaries and
large-project capacity still need the updated real-target retest.

## Evidence-Ready Development Increment (2026-10-23)

The Go-heavy pilot permits an experimental automatic-lead implementation and a
registered Go-runtime probe, not automatic large-file slicing or a universal
cross-language detector. The new development provider is selected once at Campaign
creation, uses standard-library AST parsing of supplied snapshot bytes, and emits
only generic imported-call review hints. It does not add the pilot's helper names,
historical findings, expected issue counts or platform-specific exploitation rules.
Python remains the default provider; independently reviewed Go coverage/precision
and default enablement remain separate acceptance decisions.

R1 and both R2 scheduling modes use the frozen provider opt-in and current R0 digests.
The report retains the experimental-feature selection. Missing Go tooling is an
explicit failed/unavailable scan rather than a successful no-candidate result.
The trusted Go parser source ships as package data, not a path into a developer's
checkout. TR-14 covers installation, provider contracts and managed runtime evidence.

The R5 work reuses the existing registered harness, explicit resource limits and
eligible observation refs. A synthetic offline runtime check can establish that the
execution path works on this host; it cannot confirm a historical target claim or
replace independent impact review. Large-file reading measurements and actual
mixed-language boundary miss samples remain unprovided. No broader feature is
declared complete merely because a development prototype is now permitted.

### Increment Verification and Remaining Gate

- Full suite: **421 passed, 1 skipped in 53.20 seconds**, using
  `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests -o addopts='' -q --tb=short`.
  The protected held-out manifest remains unconfigured; no real labels were fabricated.
- This host's `go version go1.26.0 linux/arm64` compiled and executed synthetic Go
  probes through the registered harness, including hypothesis binding, unchanged
  source and cleanup. The CLI also executes the explicit `go-offline` profile.
  The default profile remains unchanged. Complete nonzero-exit observations are
  eligible for review, not automatic confirmation; timeout/truncation cannot upgrade
  through the actual R5 evidence validator.
- An offline wheel build, extraction and smoke run outside this checkout verified
  packaged Go parser availability and a synthetic imported-call candidate. This is
  installation evidence, not a new qualified provider identity.
- Compatibility scan passes with **zero findings** across 50 Python runtime files,
  167 knowledge files and one prompt. `compileall` and `git diff --check` pass.
  The main Skill is 476 lines, below the 500-line guideline.
- Production CLI diagnostics were checked during implementation. Editor import
  resolution for new pytest files is not a clean type-check claim: the terminal
  suite succeeds, but the editor reported unresolved pytest/package imports under
  its selected workspace/interpreter configuration.

No Caddy rerun, independent semantic adjudication, Go Top10 qualification, balanced
15-language validation, large-file capacity measurement or mixed-language boundary
study was performed by this increment. Keep the provider opt-in and make those
claims only after the corresponding real-target evidence is available.

## Java-Pilot Repair and Generality Reassessment (2026-10-24)

### Evidence and decision boundary

Read-only inspection verified all 618 content-addressed artifacts and all 397 frozen
Java source digests in the supplied module pilot on `9d513e7`. The archived module
digest matches its protocol. Exported Campaign JSON matches the registered artifact
apart from its added self `artifact_id`. The formal run has one Batch, seven Work
Units, zero Handoffs and no target execution; no >1 MiB Java file exists. It cannot
establish whole-project, mixed-language, large-file or empirical Java capability.

Task events record 159 claims, 149 completions and ten cancellations, not the self
evaluation's 155 collected results. All 49 R4 runs were eventually imported directly;
39 task outputs had completed normally. Therefore do not treat this as a completed
task-only recovery exercise. All 21 Findings remain static-only NEEDS_REVIEW, with
26 linked hypotheses, nine rejected hypotheses and 43 unresolved hypotheses. Source
review declarations and classification labels are not independent semantic review.
Original resource elapsed time is 38,979 seconds against 21,600 declared: FAIL.

The full-repository probe independently confirms planning fanout (71 WUs, 64 empty,
16,495 edges, 9,990 Handoffs). Two isolated validator probes established that both
task R4 and direct R4 accepted nonexistent concrete anchors. Another probe established
that R3 already accepted resource supporting references but rejected them as code
call-chain steps. The latter was a contract/provenance problem, not a universal
Java-only evidence restriction.

### Implemented repairs and intentionally rejected shortcuts

- Project scoped plans instead of stripping all excluded endpoints. Read-only replay
  produces 50 WUs, 1,662 edges and 723 Handoffs, with all 397 included files retained.
  The 43 remaining empty units have cross-scope boundary obligations. These counts
  measure a planning projection, not execution savings or security recall.
- Share concrete LOC/artifact and CategoryRun schema validation across individual,
  bundled, screening and direct R4; include nested axis/review evidence. Legacy
  symbolic labels remain compatibility references, not verified source proof.
- Freeze supporting evidence by explicit bounded pre-R0 registration and check
  source/resource digests at concrete LOC validation. Preserve resource provenance
  separately from reviewed-source coverage; do not discard anchors to pass a validator.
- Supply an actually nested R3 contract and a complete shape example. The example
  uses NEEDS_REVIEW with an instruction to replace the rationale, not a positive
  finding template or expected result.
- Reuse existing task finalization for explicit output/attempt-bound late collection,
  including normal output, attestation and measurement checks. Transactional
  authorization cannot rescue superseded, terminal or invalidated attempts. Unknown
  usage stays unknown; an output's schema does not authenticate its author.
- Reuse Campaign budget/events for monotone extensions, preserving creation time,
  original limit and breach FAIL. Do not silently subtract pauses or rewrite budgets.
- Reuse R3.5's two-perspective protocol through a frozen static-challenge opt-in;
  do not add a second challenge engine or promote static grade.
- Add a bounded opt-in JDK parse-only provider with three generic method-site families,
  not target-specific detections. Receiver/type/import/shadowing resolution is absent;
  same-name false positives must remain explicit. Default/release roster is unchanged.
- Share the bounded parser subprocess implementation between Java and Go. Review also
  identified relative-cwd helper caches as an audit-tree pollution risk. Both now use
  private external temporary roots, ignore ambient target-local TMPDIR, and reject
  cached helper paths inside a target. Regression runs verify unchanged target
  paths/content, private permissions, cleanup, file-size and descriptor caps.

Do not auto-exempt test directories, fuzzy-match mechanism text, create a second
experiment engine or store historical expected findings in runtime rules. Existing
evidenced NOT_APPLICABLE dispositions already support reduced R4 work. Host-supplied
output path verification remains a host responsibility. No new undirected full audit
is needed before repairing demonstrated infrastructure failures; the unmeasured
capacity/recall claims still require their specific evidence.

### Cleanliness, bias, dead code and complexity

This is a general workflow for the approved 15-language/150-priority-issue portfolio,
not a certified universal analyzer. The portfolio and its training selection can bias
attention; ten entries are review guidance, never finding quotas or permission to omit
other evidenced mechanisms. Python-only defaults and experimental Go/Java slices are
unequal capabilities and are explicitly labeled rather than disguised as parity.

No target names, private pilot paths, target APIs, historical vulnerability IDs or
expected finding counts were added to active rules. Historical targets appear here as
dated evaluation provenance, not discovery inputs. Runtime residue scanning now covers
packaged Go/Java source as well as Python, the main Skill and eligible knowledge.
Operator-supplied forbidden tokens remain inputs, not a new embedded target blacklist.
A clean bounded scan does not prove absence of every semantic historical influence.

The AST name/import inventory found no unreferenced top-level definition or unused
non-reexport import candidate in its source/test name scope. It is not a whole-program
dead-code proof: dynamic registration, unreachable branches, method-level dead paths,
redundant algorithms and all 150 knowledge mechanisms were not exhaustively verified.
No speculative deletion or unrelated rewrite was made.

The system is not a minimal prompt: durable state, ownership, handoffs, revision
invalidation, bounded recovery and evidence provenance support the stated long-running
large-project requirement. This increment reuses those mechanisms rather than replacing
them with parallel systems. However core modules remain concentrated (roughly 4k lines
in execution, 2.3k in workflow and 1.9k in closure). This is real maintenance debt,
not proof of dead code or a reason for a risky wholesale rewrite during validation.
Keep new runtime features opt-in where they change cost/coverage; prioritize measured
extraction opportunities rather than inventing more layers.

### Documentation and standards conclusion

README, main Skill, runbook, completion/real-test plans and system/software requirements
and designs now distinguish scoped graph projection, supporting evidence, authorized
resumption, static challenges, parser candidates and qualification. SYSR-043/SWDR-049
and TR-15 trace the increment. The main Skill remains below the 500-line guideline and
delegates operation examples to the runbook.

The evidence supports a usable, improving development audit workflow, not a claim of
an excellent/neutral/dead-code-free universal skill. Google internal criteria were
not supplied; conformity cannot be inferred from general engineering practice.
ISO/IEC/IEEE 12207 conformity remains unestablished without a controlled applicable
edition, organizational tailoring, accountable process owners, approvals, objective
work-product evidence and independent assessment. The lifecycle document is a partial
process-concept mapping, not certification. Code repairs and passing tests do not close
those governance gaps.

### Verification record

Final implementation regression: **488 passed, 1 skipped**. The skip is the
protected held-out manifest test whose external manifest is intentionally not
configured; it was not replaced with synthetic labels. The runtime compatibility
scan passed with zero findings across 52 Python files, two packaged parser helpers,
167 eligible knowledge files and one prompt, including pilot-specific forbidden-token
inputs. `compileall`, `git diff --check`, local Markdown-link validation (17 files,
zero broken targets), and an offline wheel smoke from outside the checkout passed.
The wheel contained and successfully exercised both Java and Go helper resources.
`SKILL.md` is 486 lines. These checks establish local regression and packaging
behavior only, not production-scale performance or security-analysis recall.

### Current reassessment addendum (2026-10-24)

The implementation after the historical verification above includes the CG2
scope-owned component rule for fully and evidentially excluded/deferred components,
the non-gating HIGH-risk Surface-to-Hypothesis mapping diagnostic, R4 compact bundle
v2 guidance, and the paired discovery-quality evaluation protocol. These additions
address bookkeeping/traceability and evaluation design; none is evidence of recall
improvement. The 11 language pilots remain exploratory workflow observations, not
held-out ground truth.

The current compatibility scan and targeted residue inspection are bounded evidence
against accidental historical-project leakage in runtime Python, the main prompt, and
eligible knowledge. They cannot establish semantic neutrality of all guidance.
Likewise, the existing AST name/import inventory is not a whole-program dead-code
proof; no code was removed solely on textual non-reference. Concentrated orchestration
modules remain measured maintenance debt, not demonstrated dead code or a reason for
an unmeasured rewrite.

Google internal criteria remain unavailable and unassessed. ISO/IEC/IEEE 12207 is
addressed only by the preliminary, non-normative process self-assessment in
[LIFECYCLE_CONFORMANCE_VNEXT.md](LIFECYCLE_CONFORMANCE_VNEXT.md). Neither local tests
nor document traceability establish organizational conformity or certification.

Validation for this reassessment: **497 passed, 1 skipped**. The skip is the protected
held-out manifest test, which requires an external manifest intentionally not
configured in this checkout. `compileall`, `git diff --check`, and Markdown-link
validation across README/design documents (206 local links) passed. The runtime
compatibility scan passed with zero findings across 52 Python files, 2 packaged helper
files, 167 eligible knowledge files, and 1 prompt file. These results establish local
regression and bounded residue/link checks only; they do not establish dead-code
absence, recall, production-scale capability, standards conformity, or organizational
approval.

QuickJS pilot follow-up: Campaign closure exposed a reproduced CG2 failure for a
zero-byte excluded inventory source, because a nonexistent `LOC-<path>:1` could not
serve as evidence. The path-scope contract now supports a path-bound empty-file digest
that must match the file and frozen snapshot baseline; focused positive and drift
regressions cover it. This restores valid scope evidence without weakening source-line
anchors or treating the excluded file as reviewed.

## Latest Review (2026-10-24): Packaging and Contract Boundaries

### Conclusion and scope

vNext is a usable experimental orchestration Skill with substantial evidence and
recovery controls, not a demonstrated excellent universal vulnerability analyzer.
The architecture separates language/build adapters, catalog selection, task execution,
state/artifacts, evidence, closure and evaluation. That separation is meaningful for
long-running mixed-language audits; it does not make the implementation small, neutral,
fully qualified or semantically correct.

This review inspected active guidance/catalogs, runtime catalog selection, distribution,
inventory/graph boundaries, revision/closure/evaluation contracts, requirements/designs
and operational/test plans. It used local reproductions, bounded AST inventories and
the full regression suite; it was not line-by-line verification of every branch or
independent adjudication of all 150 mechanisms. No target audit was launched and no
historical target report was promoted to confirmed vulnerability evidence.

### Confirmed defects and repairs

Priorities below are engineering priorities, not vulnerability severities.

| Priority | Reproduced or directly verified issue | Repair and discriminating evidence |
|---|---|---|
| P1 | The wheel contained zero catalog JSON files. Default catalog loading outside the checkout raised `ModelError` for the missing portfolio; the earlier helper-only wheel smoke did not test this. | Package the 167 reviewed runtime JSON assets under `reachable_audit.knowledge_assets`; preserve source-checkout lookup. The isolated wheel test checks every runtime Python module, CLI/coordinator imports, 15 profiles, 150 cards and both helper resources. History, migration reports and host instructions are not runtime catalog assets. |
| P1 | A STATE profile could reference an INJECTION card and still load; family-filtered tasks then received the wrong mechanism. | Reject profile/card family mismatch in the shared loader; retain language/provenance checks and add a discriminating negative regression. |
| P1 | RG8/RG9 could consume an empty/partial local runtime scan as clean; a wheel-only installation has no source-checkout prompt/catalog layout to inspect. | Release policy 7 requires nonzero local source, knowledge and prompt coverage. Low-level partial scan helpers remain usable, but missing any required surface blocks both release gates; qualification requires the complete checkout. |
| P1 | CG2 rejected a legitimate zero-byte excluded source because `LOC-<path>:1` cannot exist. | Add only path-disposition `EMPTY-FILE` evidence, bound to the exact inventory path, current zero-byte regular file and snapshot digest. Test exclusion/deferment, wrong path/digest/format, non-empty/drift and symlink replacement; reject invalid paths before content reads. LOC semantics remain unchanged. |
| P2 | The generic real-target procedure directed readers into one selected project's supplement and retained a stale "remaining 11 languages" execution sequence. | Keep entry/scope rules target-independent and the sampling guide portfolio-wide; completion status belongs in the run ledger. Identify the project supplement as development evidence and separate its README listing from normative operating documents. Preserve the requested pilot record without loading it as fresh discovery input. |
| P2 | Current system/software designs incorrectly claimed every required release gate could pass while the evaluator still returned BLOCKED, and described only one runtime provider. A core contract still treated supported committed amendments as absent. | Match actual evaluator fields: all required gates passing yields ACCEPTED/eligible; independent real-bundle approval remains external. Distinguish default Python from experimental Go/Java providers, and supported amendment/recommit from arbitrary new-scope reopening. No release check is weakened. |
| P2 | Catalog cues and ranks could be read as target-risk evidence, and test-first matrices were nested under unrelated test requirements. | Clarify optional cue/rank/presence/provenance boundaries in shared worker context; restore large-source/boundary matrices to TR-10 and add the distribution contract TR-19. No ranking algorithm or discovery-quality improvement is claimed. |

The pending empty-file repair from the preceding task is included in this change set.
No target-specific detector, expected finding, target API, sink list or verdict rule
was added to active runtime guidance.

### Cleanliness, bias and complexity limits

- No observed target names or private pilot paths were introduced into active guidance.
  Target-specific plans and dated evaluations remain intentionally identifiable in the
  development documents, not erased or presented as universal requirements. A fresh
  worker must not import them just because a document links to them.
- The fixed portfolio, ranked top-ten entries, seeded/observed selection, training
  provenance and Python-first default can bias attention. They are disclosed policy
  and capability asymmetries; clearer wording is not evidence that bias is eliminated.
  Equal-budget paired, independently labeled results remain necessary.
- A local AST name/attribute/import inventory found no unreferenced top-level runtime
  function/class candidate. Exact AST function-body comparison found no duplicate
  groups of at least 12 lines. These are syntactic screens only: public entrypoints,
  dynamic use, unreachable branches, equivalent algorithms and method-level dead code
  need different evidence. No deletion was justified from a text match alone.
- The catalog remains materially templated, with repeated profile/card guidance.
  The two forms have different consumers; repetition alone does not establish a
  removable mechanism or a false-positive rule. Per-card consumer/counterexample
  review and context-cost measurement remain debt, not completed cleanup.
- Large orchestration modules remain maintenance debt (execution roughly 4.1k lines,
  Batch workflow 2.3k, closure 2.1k). This increment fixes shared producers and reuses
  existing validation rather than adding a second state/experiment/report engine.
  A wholesale split without a measured interface/test plan is not justified here.

### Standards and remaining acceptance

No controlled Google internal criteria were supplied, so compliance is **not assessed**,
not implied by a style comparison or passing tests. ISO/IEC/IEEE 12207 conformity is
**not established**: a selected controlled edition, organizational tailoring, accountable
owners, objective lifecycle outcomes and independent assessment remain missing. The
[lifecycle self-assessment](LIFECYCLE_CONFORMANCE_VNEXT.md) identifies responsible roles
and required evidence without inventing approvals.

Remaining qualification work is independent language/mechanism quality, mixed-language
boundary completeness, representative large-project recovery, host identity/isolation,
provider-enforced budgets, and per-card semantic review. Local repairs do not complete
those outcomes or justify replacing the production baseline.

### Verification of this change set

- Full suite: **511 passed, 1 skipped**. The skip is the protected held-out acceptance
  test: no external signed manifest was configured. It remains an acceptance gap.
- The first full run exposed an existing Java wheel-smoke fixture that copied only
  source code. It now copies the newly required catalog as well; the successful full
  rerun includes actual parse-only Java helper execution outside the source checkout.
- Three release-scan regressions separately omit source, knowledge or main prompt.
  Each blocks RG8/RG9 despite a clean partial scan and a signed PASS declaration.
  Release policy is `vnext-release-policy-7`; task policy is `vnext-task-policy-46`.
- Distribution regression verifies all 52 runtime Python files, 167 catalog JSON
  files, both parser helpers and isolated default-catalog/CLI/coordinator imports.
- Runtime compatibility/residue scan: PASS, zero findings over 52 Python files,
  two helpers, 167 knowledge files and one prompt. This includes caller-supplied tokens
  for the recent pilot, local pilot program, older target and project-plan/backlog
  filenames. These bounded patterns do not establish universal semantic neutrality.
- `compileall` and `git diff --check` passed. README, Skill and documentation link
  validation checked 237 local targets across 19 documents, with zero missing files.
  The main Skill remains 500 lines: within the current guideline, but not a small prompt.

The historical helper-only wheel success and earlier test totals above remain dated
records; they must not be substituted for this broader distribution verification.

## Latest Review (2026-10-25): Retry Identity and Documentation

### Decision and scope

vNext remains a usable **experimental audit orchestration Skill**, not an independently
qualified excellent universal analyzer. Durable workflow, frozen scope, content-bound
evidence and conservative unresolved states are strengths. Large orchestration
modules, templated knowledge, uneven language-provider depth and substantial
unmeasured host/cost/semantic assumptions prevent a stronger quality claim.

This review includes the pending R2/R4 reliability, static-only, optional split-deferral
and derived review/recovery changes from the preceding task. It directly inspected
their producers/consumers and tests, active Skill/runbook/README, catalog selection,
distribution/residue boundaries, requirements/design/completion and lifecycle
documents. It did not audit a target, modify sealed runs, inspect every line of the
roughly 21.5k runtime Python lines, or independently adjudicate all 150 mechanisms.

### Confirmed issues and corrections

Priorities are engineering priorities, not exploitable-vulnerability severities.

| Priority | Reproduction / direct evidence | Correction |
|---|---|---|
| P1 | A frozen split-deferral Campaign could schedule a fresh AUTO NEEDS_REVIEW after a human disposition, or return the old deferred artifact instead of the active human result on retry. Both history layouts failed regression tests. | Reuse the current active human adjudication only when it covers the same refutations; retain shared coverage/source-demotion validation. No new approval or automated human identity is claimed. |
| P1 | Same task ID with different Batch, bundled Work Units, bundle items or upstream revision pins returned the old task as though the request were an ordinary prompt retry. All four negative cases failed. | Include those fields in immutable identity comparison and reject mismatch without changing events. Prompt/budget-only resubmission still returns the original authoritative spec, preserving intended legacy retry behavior. |
| P1 | A later event for hypothesis B cleared hypothesis A's invalidation marker when Batch/type matched. Refutation, adjudication, revival and verdict-ledger cases failed. | Compare the original event's entity as well as Batch/type/time. This does not replace full coverage gates, relax cascading invalidation or authorize stale-result reuse. Legacy markers without a resolvable target retain the existing stage-level fallback; full event history is the supported input. |
| P2 | Chinese project overview described NOT_FEASIBLE/external observations/committed R3 correction as absent and generalized one historical Python/large-repository record into current language status. | Match current bounded contracts and distinguish dated examples, development trials, provider availability and independent qualification. Do not replace the old project's evidence or invent a full language matrix. |
| P2 | An unresolved outcome with a recorded Finding could be described as having “no canonical Finding.” | Describe the actual NEEDS_REVIEW state without denying existing linked records or treating the Finding as confirmation. |

The focused pre-fix reproduction produced **10 failed, 1 passed**; the passing case
preserved the intended original prompt/budget retry contract. Corrections are shared
workflow rules with synthetic identifiers, not branches for a past target or audit plan.
The preceding R2/R4/static/deferral repairs are also included in this commit and
remain covered by TR-20.

### Cleanliness, bias, dead code and redundancy

- Runtime Python/helpers, eligible knowledge and the main Skill are scanned for legacy
  formats and bounded residue patterns, with separately supplied recent-target/plan
  tokens. No target-specific runtime branch or fixed expected-finding quota was
  found in the inspected paths. Pattern cleanliness is not semantic neutrality.
- Project-specific supplements and old run observations remain in development/history
  documents, identified as evidence records. They must not become fresh R1/R2 input.
  Framework/API examples, CWE identifiers, generic build profiles and opaque provenance
  are not automatically contamination; actual applicability still requires target
  evidence. Do not erase traceability merely to hide historical influence.
- Fixed portfolio/ranking, historical training samples, generic or cross-language cue
  wording, uneven default/experimental providers and model behavior can bias
  attention. No balanced blind 150-cell study establishes their quality or neutrality.
  Independent per-card counterexample review and equal-budget paired evaluation remain
  necessary; deleting history tokens alone cannot fix these limitations.
- A fresh AST name/attribute inventory across runtime/tests/tools found no unreferenced
  top-level runtime definition candidate or unused non-reexport import. Exact AST
  function-body comparison found no duplicate groups of at least 12 lines. These are
  syntactic screens, not whole-program liveness or equivalent-algorithm proofs.
  No code was deleted solely on a text/AST non-reference.
- Architecture concentration remains: execution about 4.2k lines, Batch workflow 2.3k,
  closure 2.2k and store 1.5k. Knowledge and operational documents repeat some concepts.
  Distinct evidence/consumer roles justify some repetition; context-cost and maintenance
  measurements are needed before extracting or deleting shared behavior. No second
  ledger, experiment system or target-specific recovery engine was introduced.
- The main Skill remains 500 lines, not a small prompt. The wheel regression continues
  to test runtime assets outside the checkout; Skill/runbook delivery and real host
  enforcement remain separate responsibilities. “General-purpose” means reusable
  within the declared security-audit scope, not every software-engineering task.

### Engineering criteria and lifecycle standards

**Google internal requirements: NOT ASSESSED.** No authorized controlled criteria or
internal acceptance owner was supplied. Source clarity, tests and public engineering
practice cannot establish internal approval.

**ISO/IEC/IEEE 12207 conformity: NOT ESTABLISHED.** The repository supplies partial
maintenance/configuration/verification/traceability evidence, not a controlled
edition-specific lifecycle assessment. Applicable edition, organizational tailoring,
named process owners, required objective outcomes and independent assessment remain
external prerequisites, as recorded in
[the lifecycle self-assessment](LIFECYCLE_CONFORMANCE_VNEXT.md).
Neither this table nor passing tests closes those gaps.

### Verification

- Python **3.14.4**, full command:
  `env -u PYTHONPATH python3 -m pytest tests -o addopts='' -q -rs --tb=short`.
  Result: **574 passed, 1 skipped**, 65.28 seconds. The skip is
  `test_heldout_release_acceptance.py`: protected real held-out manifest not configured.
  No synthetic substitute was created to remove the acceptance gap.
- Focused identity/deferral/workflow modules: **130 passed** after repairing the
  pre-fix failures. The full suite also exercises isolated wheel catalog/CLI/coordinator
  imports and packaged parser helpers outside the checkout.
- Compatibility/residue scan: **PASS**, zero findings across **53 Python files,
  2 helpers, 167 eligible knowledge JSON files and 1 main prompt**. The caller supplied
  the recent target name, target-audit path token, supplement/report filenames and
  three pilot issue IDs; these were not made a built-in target blacklist.
- `python3 -m compileall -q src tools` and `git diff --check`: **PASS**.
- **19 Markdown files, 253 local file links, zero missing targets**. Skill metadata
  retains `name`/quoted `description` and the **500-line** progressive-loading bound.
  Link existence is not proof of prose correctness or normative standards coverage.

These results establish bounded local behavior on this environment. They do not
establish all supported Python versions/platforms, dead-code absence, unbiased
discovery, provider hard caps, real-host static-only enforcement or lifecycle conformity.

## Latest Review (2026-10-25): Supersession and Current Policy

### Scope and decision

Reviewed base `d9c01f4` after default split deferral was committed. The working tree
was clean at the start. This review directly inspected default creation/retry rules,
decision-packet producers and report consumers, Plan Amendment lifecycle records,
catalog selection and a representative state card, distribution configuration,
the main Skill/README/runbook and current requirements/design/lifecycle documents.
It did not perform a new target audit or alter sealed audit evidence.

The conclusion remains **usable experimental security-audit orchestration**, not an
independently qualified excellent universal analyzer. This is a bounded engineering
assessment, not a line-by-line review of every runtime path or semantic review of
all knowledge cards. No public-source style comparison can establish private approval.

### Reproduced defects and repairs

Priorities below concern workflow correctness, not exploitable vulnerabilities.

| Priority | Verified defect | Repair and evidence boundary |
|---|---|---|
| P1 | After a real Plan Amendment, `derive_review_queue` still included superseded Batch evidence. The report consumes those hypothesis IDs as unresolved, so old packets could contaminate current report uncertainty. | The shared Batch packet producer honors the durable `BATCH_SUPERSEDED` event. Archive events/artifacts remain intact. A merely DEFERRED Batch retains its packets. No guessed reachability, deletion, new ledger or target-specific rule is introduced. |
| P2 | Current operational/requirements text still described deferral as opt-in or the default human handling as unchanged; the current completion summary still named policy 48. Superseding paragraphs elsewhere did not make those local instructions unambiguous. | Reconcile current README/Skill/runbook, Chinese overview, system/software requirements/designs and completion/test records with default deferral and supersession boundaries. Dated historical verification totals and policy decisions remain history, not current instructions. |

Before the fix, the supersession/control regressions produced **1 failed, 1 passed**.
The passing control confirms that DEFERRED alone must not hide uncertainty. The
expanded end-to-end case replays discovery under a replacement Batch, reuses
Work Unit/hypothesis identities and closes R4/R5/R6/Campaign reporting: only the
replacement packet appears, and its unresolved state remains explicit. Queue reads
do not append events. Task policy is now **50**; release policy remains **7**.

### Cleanliness, bias and architecture

- The compatibility/residue check found zero findings across runtime Python,
  packaged helpers, eligible knowledge and the main Skill. Recent target/plan/report
  tokens were supplied by the reviewer, not embedded as runtime exceptions.
  Historical project documents remain evaluation provenance, not universal audit
  requirements. Host-controlled context can still leak history if operating rules
  are ignored; a clean pattern scan is not semantic isolation.
- Catalog loading validates 15 profiles and 150 cards. Selection is family-filtered,
  rank-ordered and round-robin across requested languages under an entry-count cap.
  This is transparent guidance selection, not evidence of neutral or balanced recall.
  Fixed roster/ranks, templated cards (including repeated precondition/transition
  wording), training selection and unequal language-provider depth remain genuine
  bias/quality risks. They require independently reviewed counterexamples and
  equal-budget held-out measurements, not speculative rewriting during this repair.
- A fresh AST screen found no unreferenced top-level runtime definition candidate,
  unused non-reexport import candidate, or exact function-body duplicate group of
  at least 12 source lines. This does not prove branch/method liveness, equivalent
  algorithm absence or absence of redundant design. No speculative deletion was made.
- Architecture still separates catalog, planning, state/artifacts, execution,
  evidence, closure and evaluation. The repair reuses the existing lifecycle event
  in the shared packet producer. Core module concentration remains approximately
  4.2k lines in execution, 2.3k in Batch workflow, 2.2k in closure and 1.5k in store.
  That is real maintenance debt, not grounds for an unmeasured wholesale rewrite.
  The 500-line main Skill is also a context-cost concern, not a minimal prompt.

### Verification and standards

- Python **3.14.4**; full command
  `env -u PYTHONPATH python3 -m pytest tests -o addopts='' -q -rs --tb=short`:
  **579 passed, 1 skipped**, 65.45 seconds. The protected real held-out manifest is
  not configured; the skip remains an external acceptance gap.
- Focused decision-packet and Plan Amendment modules: **32 passed**.
- Compatibility/residue scan: **PASS**, zero findings across **53 Python files,
  2 helpers, 167 eligible knowledge JSON files and 1 main prompt**.
- Compilation, whitespace, main Skill metadata/500-line bound and local Markdown
  file-link checks passed. These establish bounded local regression and document
  delivery, not prose infallibility, whole-program correctness or audit recall.

**Google internal requirements: NOT ASSESSED.** No authorized controlled requirement
set or internal acceptance authority was supplied. **ISO/IEC/IEEE 12207 conformity:
NOT ESTABLISHED.** The standard concerns lifecycle processes/outcomes, not a code
quality score. The applicable controlled edition, organizational tailoring,
accountable owners, objective outcomes and assessment/approval evidence remain
missing. See the lifecycle self-assessment for adopter responsibilities. This
repair adds maintenance/verification evidence; it supplies no organizational
approval, certification or independent real-project quality evidence.

## Latest Review (2026-10-25): Shared Guidance Scope

### Scope and finding

The preceding bounded cleanliness checks did not establish semantic neutrality:
this review found additional scope leaks after the R5 sanitizer wording was removed.
Starting from clean base `c90664f`, it directly inspected shared R1/R2/R3/R3.5/R4/R5/R6
task contracts, the main Skill and operational runbook, recipe prerequisites,
adapter/probe context, hotspot coverage declarations and catalog applicability
guidance. It did not independently qualify every language, review every card's
semantics, or audit a new target. Prior passing scans must not be read as evidence
that these omissions were absent.

| Surface | Confirmed scope problem | Correction |
|---|---|---|
| Shared R3.5 revival task | Every hypothesis received fixed regex/string-processing bypass guidance, including mechanisms without those operations. An existing test explicitly required that wording. | Use target-evidenced guard semantics, transformations, state/failure behavior and boundary contracts, preserving valid rejection without assuming a language/API/bypass. |
| Go experiment prerequisites | Every family received `-race` advice, without an optional marker, not just concurrency recipes. | Retain optional race-detector advice for RACE and remove it from unrelated families. Existing optional sanitizer controls remain scoped to applicable families/languages. |
| JavaScript/TypeScript experiment prerequisites | Node.js was a fixed prerequisite even for other target runtimes/hosts. | Select target-declared runtime/host; TypeScript tooling is conditional. Shared R5 guidance labels all recipes as suggestions, not mandatory toolchains inferred from a language. Registered adapter version probes are explicitly candidates, not target-runtime facts or automatic blockers. |
| General operating instructions | Generic scope/deep-review sections singled out Java profile/JNDI guidance; a universal evidence section retained the Java-pilot heading. | Make current operational rules target/profile-neutral. Keep actual Java provider instructions and dated pilot evidence in their scoped sections. |

These are instruction/applicability defects, not findings of exploitable
vulnerabilities. The pre-fix focused command produced **7 failures**. After repair,
the execution/experiment modules passed **102 tests**; the additional emitted-task
assertions and full suite also pass. No new result schema, state, approval mechanism,
language knowledge asset or target exception was added. Task policy is **53**.

### Retained distinctions and limits

Language adapters, scoped API rules, family-specific recipes and conditional
boundary examples are not defects solely because they mention a language/tool.
For example, JNI/CGO examples remain explicitly conditional on their presence;
the optional Go/Java providers retain their actual toolchain limits. The default
Python-only hotspot depth remains an acknowledged capability imbalance, not a
claim of balanced coverage or a reason to silently enable unqualified providers.

The fixed portfolio, ranked/templated training knowledge, model attention and
semantic applicability still require independent evaluation. Recipe methods remain
family-level suggestions rather than target-specific experiment designs. This
review does not prove that all historical influence or language bias is gone.
It improves explicit selection boundaries, not semantic truth or audit recall.

### Verification

- Full command:
  `env -u PYTHONPATH python3 -m pytest tests -o addopts='' -q -rs --tb=short`.
  **585 passed, 1 skipped**, 62.89 seconds. The external protected real held-out
  manifest remains unconfigured; it was not replaced with synthetic acceptance.
- Compatibility scan: PASS, zero findings across 53 runtime Python files, 2 helpers,
  167 eligible knowledge files and 1 main prompt. This is bounded residue evidence.
- Compilation and whitespace checks passed. Main Skill remains 500 lines; language
  knowledge assets and sealed target-audit materials were not changed.
- Documentation links and metadata were checked separately. No Google internal
  approval, ISO/IEC/IEEE 12207 conformity or independent qualification is inferred.

## Latest Review (2026-11-01): Worktree Contracts and Generality Boundaries

### Scope and findings

This reassessment reviewed the current worktree changes to R3.5 collection/commit and
revision recovery, R4 disposition reporting, CLI state selection, graph anchors,
related regressions and the new development-candidate supplement. It also checked
the current Skill/README boundary, runtime residue scan, design/requirements/test
documents and the existing lifecycle self-assessment. It is not a new complete
security audit, independent code qualification, or proof that all dead code and bias
have been found.

| Area | Finding | Action and remaining limit |
|---|---|---|
| Shared explicit state directory | Read-only `status` rejected the entire store when any Campaign belonged to another target, although the store model allows multiple targets. This made a valid shared store unusable and conflated store identity with Campaign identity. | Filter to the requested target and fail only when a nonempty store has no matching Campaign. Regression tests verify each target sees only its own Campaigns and mismatched queries fail. |
| Import target anchors | Anchor discovery loaded and split the whole target file again after import parsing, increasing transient memory for large source files. | Stream lines until the first nonblank anchor; a regression test prevents a second full-file read. |
| Dead/redundant code | `_successful_tasks()` had two adjacent identical empty-input guards. | Removed the duplicate. This specific fix is not an exhaustive dead-code analysis. |
| Current R3.5/R4 contracts | Complex amendment and cross-stage reporting behavior is structural; it must not be presented as semantic confirmation or independent human review. | Documentation now records task-bound evidence validation, atomic commit/revision behavior, non-gating disagreements, and the requirement to inspect both evidence sides. |
| Candidate target information | A candidate-project/CVE supplement exists under design documentation and is referenced only by the development-pilot plan. It is explicitly a proposal, not authorization or discovery-worker input. | Keep it outside runtime Skill/knowledge and frozen discovery artifacts. The runtime residue scan found no project-specific tokens; that bounded scan cannot establish complete semantic neutrality. |
| Skill size | The current `SKILL.md` is 509 lines, not the 500 recorded in the prior review. | Record the corrected measurement; treat it as a context/maintenance cost rather than silently claiming the earlier bound. The Skill remains security-audit-specific by design and general only across authorized targets/languages within that scope. |

### Generality, bias and standards boundary

The Skill is not a universal all-domain evaluator or generic code-review assistant.
Its product scope is authorized source-code security auditing across the declared
language/build portfolio. The fixed portfolio and uneven hotspot depth remain known
coverage imbalances; neither adapters, ranked guidance nor passing synthetic tests
prove balanced discovery, absence of language bias, or real-target recall. No
per-audit candidate list or expected finding is part of the runtime knowledge
catalog; the new candidate plan is evaluator-side documentation only.

Google internal requirements remain **NOT ASSESSED** because no controlled
requirements or acceptance authority were supplied. ISO/IEC/IEEE 12207 conformity
remains **NOT ESTABLISHED**: the lifecycle document correctly limits itself to a
preliminary selected-concept mapping and lacks a controlled edition, organization
tailoring, accountable process outcomes, and independent approval evidence. Do not
relabel this repository review as Google approval or ISO certification.

### Verification

- Focused regressions for shared stores and import anchors: **8 passed**.
- Full command:
  `env -u PYTHONPATH python3 -m pytest tests -o addopts='' -q -rs --tb=short`.
  **690 passed, 1 skipped**, 71.58 seconds. The protected real held-out manifest
  remains unconfigured; the skip is not replaced with synthetic acceptance.
- Compatibility scan: PASS, zero findings across **53 runtime Python files,
  2 helpers, 167 eligible knowledge files and 1 main prompt**. This is bounded
  residue evidence, not proof of zero historical influence or zero bias.
- `git diff --check` passed. Newly added relative documentation targets and the
  TR-21 anchor exist. No Google internal approval, ISO conformity, or independent
  qualification is inferred.

## Latest Review (Task Policy 55): Generic Recovery, Scope and Experiment Evidence

### Assessment basis

This review starts from commit `9c7090a` and includes the pending development
changes to R0 supporting-evidence preflight, boundary projection, R2 boundary
context, early R5 validation, harness provenance and explicit JVM resource limits.
It reviews those changes as cross-target software contracts, not as rules inferred
from one pilot's expected findings. No target source, audit plan, result label,
language knowledge asset or external audit package was modified.

The declared scope remains authorized source-code security auditing across the
supported languages/build systems. Within that scope, the implementation is a
general workflow rather than a project-specific scanner. It is still experimental:
passing the software tests does not establish excellent discovery quality,
representative real-target coverage or release qualification.

### Reproduced defects and repairs

Four failing regression cases established three defects before repair:

| Defect | Root-cause repair | Preserved behavior / verification |
|---|---|---|
| An old R0 receipt conflicted with a new idempotent R0 event because newly added preflight metadata changed the receipt bytes. | Revalidate the frozen source and scope, then compare and reuse the old receipt through the existing artifact/event machinery when it lacks the new metadata. Require an object receipt; do not rewrite historical evidence or create another R0 event. | Source drift still fails. CLI preflight reports the current frozen supporting-evidence registrations even when an old receipt is reused. |
| Scope projection removed component-only incoming edges and incoming edges from DEFERRED paths along with explicitly EXCLUDED callers. | Apply the caller exclusion only to a concrete path with an EXCLUDED decision; retain the existing either-endpoint-in-scope selection for other edges. | Retain included-to-outside, DEFERRED-to-included and component-only incoming edges. No directory-name, language or project-name exclusion heuristic was added. |
| A required inconclusive experiment could accompany REFUTED through task collection, despite being incompatible with the R5 disposition. | Share `R5Assessment.validate_experiments()` between collection and direct stage recording; validate references, ownership, required/infeasible combinations and result/disposition consistency. | Required inconclusive evidence stays NEEDS_REVIEW. Duplicate experiment IDs and non-boolean `experiment_required` inputs fail explicitly. Structural validation does not confirm a vulnerability's semantics. |

Additional safeguards and simplifications:

- Both R2 scheduling modes receive the same bounded boundary summary. The limit is
  **64 edges / 64 KiB**, including omission metadata; oversized early edges do not
  prevent later fitting context. Counts distinguish selected, included and omitted
  evidence rather than implying complete boundary coverage.
- R0 supporting-evidence preflight is shared by the receipt and CLI. It reports a
  reminder when no build/runtime support is registered, not a completeness gate
  or an automatic claim that those inputs are needed for every target.
- Harness recording and the R5 empirical gate share
  `validate_execution_provenance()`. Built-copy evidence must reference registered
  artifacts and the matching snapshot/fidelity. Integrity uses the existing
  content-addressed artifact store rather than a second SHA-256 map.
  Missing/mechanism-only provenance can record an experiment but is explicitly
  ineligible for empirical upgrades. Provenance remains an operator declaration:
  it does not prove that the executed argv consumed the declared bytes.
- Removed an unused workflow import and duplicate operational instructions.
  The main Skill now has **500 lines**; this corrects the prior review's measured
  509-line entry rather than rewriting that historical measurement.
- Task policy is **55**. The Skill, runbook, README, requirements, system/software
  design and [TR-22](TEST_PLAN_VNEXT.md#tr-22-generic-boundary-scope-r0-compatibility-and-r5-provenance)
  describe the changed contracts and their limits.

### Resource profiles do not choose audit scope

`jvm-bounded` is an explicit opt-in resource profile. It sets a default **4 GiB
address-space ceiling**, not a heap size or a promise that every JVM will start.
The caller still supplies JVM heap/other options; the runtime does not detect a
language/project and silently switch profiles or inject JVM arguments. An explicit
memory override takes precedence. The normal profile remains **2 GiB**, and
`go-offline` remains **8 GiB**. STATIC_ONLY rejects execution under every profile
before subprocess/resource side effects. The real available JVM startup check
passed; that is an environment-specific probe, not a JVM/platform certification.

### Historical information, bias and architecture limits

The runtime catalog loads approved profiles/cards/provenance, not design reviews
or candidate-project plans. Fresh Campaigns do not inherit prior Skill regression
sources; follow-up history requires explicit same-target input. Wheel isolation
and fresh-mode regressions pass. The Skill explicitly forbids passing evaluator
plans, prior reviews or expected results to discovery workers.

Historical reviews and candidate/pilot documents still exist in the repository as
evaluator-side development evidence. A full Skill installation or an operator can
read them, so this is not physical isolation or proof that model attention cannot
be influenced. The runtime residue scan below found no supplied historical tokens
in its selected surfaces; it is not a semantic proof of zero contamination.

Ranked training knowledge, templated verification text, the fixed language
portfolio and unequal hotspot depth remain quality/coverage risks. Representative
Java proxy-trust and C parser-boundary cards describe reusable mechanisms, but
their applicability must be established from the current target rather than
assuming the named API/header or memory operation exists. No blind rewriting of
all knowledge cards was justified by this review. Independent discovery-quality
evaluation remains necessary.

A bounded AST screen found no unreferenced top-level candidates or exact
function-body duplicate groups of at least 12 lines in the inspected runtime
Python files. One unused import was removed. This is not exhaustive dead-code
proof; dynamic dispatch, semantic duplication and the large workflow modules
remain outside that screen's assurance. The repairs reuse existing validators,
artifact integrity and stage recovery rather than introducing a parallel runtime
architecture or target-specific exceptions.

Google internal requirements remain **NOT ASSESSED**: no controlled requirements
or acceptance authority were supplied. ISO/IEC/IEEE 12207 conformity remains
**NOT ESTABLISHED**. The lifecycle document records selected-concept maintenance
and verification evidence only; controlled applicability, organizational tailoring,
accountable process outcomes and acceptance evidence are still missing.

### Final verification

- Full command: `pytest -q -o addopts= -rs --tb=short`.
  **706 passed, 1 skipped**, 66.98 seconds. The protected real held-out manifest
  remains unconfigured; no synthetic replacement or passing certification is
  inferred from that skip.
- Final focused command covering exact R2 byte/count limits, harness provenance,
  required-inconclusive R5 and legacy R0 recovery: **10 passed**.
- Compatibility scan: PASS, zero findings across **53 runtime Python files,
  2 helpers, 167 eligible knowledge files and 1 main prompt**. Historical project
  tokens were supplied to the scanner externally, not embedded as runtime rules.
- Python source/helpers compiled successfully. Changed Markdown file-link targets,
  Skill scalar metadata and the 500-line bound were checked. These checks are not
  a complete editor type check or semantic documentation validation.
- Final patch whitespace and commit-state checks are recorded with the repository
  change, not interpreted as independent qualification.

## Latest Review (Task Policy 56): Direct Submission and Failure Transparency

### Basis and conclusion

Reassessment baseline: clean commit `6d9528f`. Reviewed the active Skill,
README/runbook, Chinese overview, system/software design, requirements and lifecycle
assessment, together with R0/R5/harness contracts, catalog loading, package isolation
and bounded runtime screens. This is an engineering/Skill quality review, not a
complete vulnerability audit or independent release qualification.

| Question | Evidence-bounded conclusion |
|---|---|
| General-purpose Skill? | General across authorized source-security targets within its declared language/build scope, not across every software task. Persistent scope, leases, evidence, recovery and closure gates support the long-running objective. Real discovery quality remains unqualified. |
| Clean implementation? | No supplied target-residue tokens were found in the scanned runtime surfaces. Two reproducible validation/error-handling defects were repaired below. “Clean” does not mean bug-free. |
| Historical project or plan contamination? | Candidate-project plans and dated reviews still exist under development documentation, but the catalog does not load them and the Skill forbids discovery-worker use. Fresh Campaign and wheel-isolation tests pass. A full checkout/Skill copy and an operator can still read history; physical/model-context isolation is not proven. |
| Bias? | Fixed portfolio ranks, templated cards, training-derived guidance and unequal hotspot-provider depth remain coverage/attention risks. Guidance requires current-target preconditions and counterevidence; neither adapter counts nor tests establish unbiased recall. |
| Dead/redundant code? | The bounded AST screen found no unused-import candidates or exact function-body duplicate groups of at least 12 lines. Its one runtime-only unreferenced-function candidate, public `sign_manifest`, is called by evaluation tests and retained. Dynamic use, semantic duplicates and all dead branches were not exhaustively analyzed. |
| Architecture and documentation? | Existing canonical events/artifacts and shared validators are appropriate engineering support, not target-specific patches. Large modules and accumulated dated design updates remain maintenance debt. One overview statement overstated observed Agent activity; it now distinguishes validated submissions from actual source reading. |
| Google internal requirements? | **NOT ASSESSED**: no controlled criteria or authorized acceptance decision supplied. Public engineering practice and local tests cannot substitute for these. |
| ISO/IEC/IEEE 12207? | **NOT ESTABLISHED**: selected lifecycle-concept mapping and local maintenance evidence do not supply controlled applicability, organizational tailoring, accountable process outcomes or independent acceptance. |

Representative knowledge inspection included a Python deserialization/C-extension
profile and migration provenance. Language APIs are conditional cues, not assumed
target behavior. Migration digest bases retain training lineage; they are not passed
as discovery task knowledge. No broad rewrite or deletion of the catalog, public API
or historical verification records was justified by this evidence.

### Reproductions and repairs

The new focused regressions produced **11 failures and 2 passes** before repair:

- **Direct R5 structure gap:** JSON parsing rejected non-boolean requirement flags,
  but direct objects did not use that check; `0` and `None` could persist an R5
  stage as a false requirement. Missing evidence/rationale and invalid external
  reference sets also bypassed the shared experiment validator. Move the existing
  structure checks into one helper used by parsing and experiment validation;
  direct stage recording validates before external-observation lookup. Remove
  duplicated disposition checks. Valid disposition semantics are unchanged.
- **Swallowed harness registration failure:** registration exceptions were only
  rethrown while the child was live. An already-exited child could therefore lead
  to a completed managed-run record after registration failed. Replace the broad
  catch with failure cleanup in `finally`, match the returned registration event,
  terminate/reap a live unregistered child and always propagate the failure.
  Fault injection covers model and database errors with both live/exited children.
  No completed execution event or empirical-upgrade record is produced on failure.
- **Documentation assurance gap:** correct the Chinese overview's “actually did”
  claim to submitted/validated evidence. Align the Skill, README, runbook,
  system/software design, requirements and lifecycle record with the repaired
  contracts and [TR-23](TEST_PLAN_VNEXT.md#tr-23-direct-r5-structure-and-harness-registration-failure).

Task policy is **56**. These are language/project-neutral fixes to existing entry
paths; no knowledge asset, target audit package, candidate plan, profile default,
new approval workflow or runtime target-name blacklist was added.

### Verification and limits

- Related R5/harness/Go/static-only/Batch-closure modules: **113 passed**.
- Full command: `pytest -q -o addopts= -rs --tb=short`.
  **719 passed, 1 skipped**, 60.82 seconds. The protected real held-out manifest is
  still unconfigured; the skip is not a successful qualification result.
- Runtime compatibility/residue scan: PASS, zero findings across **53 Python
  files, 2 parser helpers, 167 knowledge JSON files and 1 main prompt**.
  Historical tokens were external scanner inputs. Catalog loading validated
  **15 languages, 150 cards and 150 provenance records**.
- Python compilation, changed Markdown file/heading links, scalar Skill metadata,
  the **500-line** Skill bound and patch whitespace checks pass. No complete
  editor type-check or exhaustive semantic documentation audit is claimed.

This corrects policy 55's overstatement of shared direct-object validation rather
than treating its previous passing suite as proof. Representative host/target
acceptance, independently measured discovery quality and actual context isolation
remain required before an “excellent production-grade” claim.

## Latest Review (2026-11-04): Generality and Evaluation Integrity

### Scope and decision

Baseline: clean `494a698`. Inspected the Skill, README/runbook, requirements,
system/software design and acceptance/lifecycle documents; traced catalog loading,
migration and release-evaluation inputs. Screened all 53 runtime Python files for
imports, top-level references and exact function-body duplication, and all 150
profile counterevidence/pitfall rows. This is a bounded engineering reassessment,
not an exhaustive semantic audit of every branch or knowledge field.

| Question | Current conclusion |
|---|---|
| General Skill? | General within authorized source-security auditing and its declared portfolio, not every task/language/framework. The event/artifact/task architecture supports resumable mixed-language work. Excellent real discovery quality is not yet demonstrated. |
| Clean of history? | Runtime loaders do not load candidate plans or dated audit reports. However, six reviewed mechanisms contained historical rule references, implementation-specific assumptions or predetermined classifications. These were generalized below. No evidence supports a universal zero-contamination claim. |
| Bias? | Training/rank/portfolio/provider asymmetry remains. Corrected concrete historical decision bias; retained conditional language APIs, counterevidence and out-of-catalog candidates. No balanced blind benchmark establishes unbiased recall. |
| Dead/redundant code? | No unused-import, unreferenced top-level-definition or exact function-body duplicate candidate of at least 12 lines in the bounded AST screen, including source/test/tool name uses. This does not prove all methods/branches live or rule out semantic duplication. Public interfaces were not deleted on name-count evidence. |
| Architecture? | Reuse of canonical events, artifacts and validators is appropriate. Large orchestration modules (4,443/2,414/2,152 baseline lines for execution/Batch/Campaign closure) and accumulated dated design updates remain maintenance debt. No safe wholesale rewrite was justified. |
| Documentation? | Operational history boundaries and R3.5 amendment guidance clarified. Current acceptance documentation had contradicted its real test entry point; corrected. Historical evidence remains dated, not silently deleted or promoted into current guarantees. |
| Google internal requirements? | NOT ASSESSED: no authorized internal criteria or acceptance authority. Public engineering-practice comparison is not internal approval. |
| ISO/IEC/IEEE 12207? | NOT ESTABLISHED: local traceability/maintenance evidence cannot establish controlled applicability, organizational tailoring, process ownership and lifecycle outcomes. No clause-level assessment was performed. |

Public comparison references:
[review standard](https://google.github.io/eng-practices/review/reviewer/standard.html)
and [review dimensions](https://google.github.io/eng-practices/review/reviewer/looking-for.html).
Their Markdown sources were inspected through the official `google/eng-practices`
repository. Design, functionality, complexity, tests and documentation are useful
review dimensions, not a certification checklist. No controlled ISO text was supplied;
this review does not choose an edition or assert its publication status.

### Confirmed problems and repairs

- **Evaluation parity:** RG13 omitted compact R2 and accepted arbitrary per-axis
  suffixes. Enumerate base/compact operations and the six existing `DiscoveryAxis`
  values; apply the same primary-input snapshot/history checks to each.
- **Evaluation input integrity:** truthy run/language/issue flags and RG9 scan
  labels could be treated as true; non-finite tolerances were accepted. Validate
  booleans explicitly, require finite numeric tolerances and preserve conservative
  omission defaults. This is not a claim that every domain parser is universally strict.
- **Operational scan gap:** the required runbook was outside residue scanning.
  Scan both declared operating prompts and require both at RG8/RG9. Partial
  low-level scans still support fixtures but cannot qualify a release. This is
  bounded pattern detection, not a host filesystem or model-context boundary.
- **Historical decision bias:** C resource/authentication and C++ decoded-length
  entries retained old rule IDs, implementation names, a particular handshake or
  fixed severity advice; Java race/iteration entries assumed specific operations,
  parameter defaults or evaluation order. Regenerated six entries through the
  existing offline generator with conditional current-target checks and genuine
  limiting conditions. IDs/ranks/families/CWEs remain unchanged; rewritten
  profiles/cards/provenance are digest-backed seeded guidance, not new battle evidence.
- **Mislabelled counterevidence:** migration copied arbitrary pitfall text into
  counterevidence, including statements describing a vulnerability rather than a
  blocking condition. Stop that fallback; preserve explicit reviewed counterevidence.
  Existing untouched entries still require semantic curation; do not infer a full
  catalog-quality certificate from these six repairs.
- **Documentation drift:** the acceptance guide still described RG12 as
  unimplemented despite an ACCEPTED-result held-out entry point. Align the guide,
  current design/requirements and TR-24 with evaluator policy 8. Clarify external
  CLI state versus legacy `.audit_vnext`, and the supported R3.5 amendment path.

No target audit, original Campaign, candidate-project plan, scope/category default,
provider default, language roster, new ledger or runtime target blacklist was added
or modified. Knowledge content binding remains enforced: preserve a frozen engine/
catalog for an existing Campaign; do not replace its installed knowledge in place
and bypass a mismatch. Use a new Campaign for revised knowledge.

### Verification

The original mechanical baseline was **719 passed, 1 skipped**. Focused reproduction
first produced **30 failures / 4 passes** for evaluator/scan checks and **13 failures**
for the knowledge checks (two migration cases initially used incorrect source IDs;
those IDs were corrected before verification). Post-repair evaluator/CLI/helper
tests passed **125 cases**; catalog/migration tests passed **25 cases**.
The final expanded regression covers every registered R2 axis in both clean and
history-bearing input cases, and exactly recreates all six shipped revised issues,
cards and provenance records through the offline generator.

Validation environment: Python **3.14.4**, task policy **56**, release policy **8**,
baseline `494a698` plus the changes recorded in this review's commit. Full command:
`env -u PYTHONPATH python3 -m pytest tests -o addopts='' -q -rs --tb=short`.

- Full suite: **782 passed, 1 skipped**. The protected real held-out test is skipped
  because its manifest is not configured; no real discovery/release qualification
  is inferred from this result.
- Compatibility/residue scan: **PASS**, zero findings across **53 Python files,
  2 parser helpers, 167 knowledge JSON files and 2 operating prompts**, using
  reviewer-supplied historical tokens rather than a runtime target blacklist.
- Catalog validation: **15 languages, 150 cards, 150 provenance records**. All six
  rewritten entries retain their issue/card IDs, ranks, families and CWEs.
- Validated **258 local file/heading links in 12 changed Markdown documents**,
  scalar Skill frontmatter, the **500-line** Skill bound and patch whitespace.
- Pylance reported no diagnostics for the changed evaluator, compatibility scanner
  and migration tool; checked Python syntax passed. Editor test-file import
  resolution still reports missing modules despite successful terminal tests; no
  complete project-wide type-check is claimed.

Remaining work includes balanced independent discovery-quality evidence, full
semantic knowledge curation, large-source coverage, additional hotspot providers,
mixed-language boundary discovery and host-context enforcement. These are not
replaced by passing unit tests or by deleting historical assessment evidence.
