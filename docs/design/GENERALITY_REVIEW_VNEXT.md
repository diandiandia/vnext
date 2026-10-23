# Generality and Engineering Review

Initial review: 2026-10-20. Base: `a3b969c` plus that review's uncommitted changes.
Current reassessment addendum: 2026-10-23, against the present working tree.
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
`vnext-task-policy-37`; the current checkout reports `vnext-task-policy-38`.
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
