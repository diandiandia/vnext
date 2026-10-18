# vNext Quality Reassessment

Status: local engineering reassessment of commit `beaef3b` plus uncommitted repairs,
2026-10-17. Not release acceptance, a certification, or a new target audit. The installed
skill, historical audit results, and external worker driver were not changed.

## 1. Decision

Keep vNext experimental and retain v3 as the production baseline. Improvements to
durability and evidence identity are concrete; superior vulnerability discovery at an
equal budget has **not been demonstrated**. The current evidence does not justify
"clean of all historical influence," "unbiased," "dead-code-free," "Google compliant,"
or "ISO/IEC/IEEE 12207 conformant."

This review includes local source/tests, runtime knowledge and prompts, all current
requirements/design/acceptance documents, the v3.47 skill, four old recall entries, and
11 project-local lesson records (741 lines). A separate read-only counter-review checked
documentation claims against nearby implementation. That is additional review, not
organizationally independent certification. It also reviewed retest3, a paid-model
follow-up Campaign containing controlled replays and fresh tasks; this is not an
independent quality/recall comparison or release acceptance. The family-scoped
sanitizer-guidance change described below postdates retest3 and was not exercised by
that Campaign.

## 2. Comparison With v3.47

| Dimension | Evidence and conclusion |
|---|---|
| Durable execution | vNext has SQLite WAL, content-addressed artifacts, leases, recorded drift, and Campaign/Batch ownership. These are mechanism improvements, not recall measurements. |
| Evidence identity | Bound catalog content, snapshot receipts, registered experiments, and append-only corrections reduce identity ambiguity. References still do not prove semantic truth. |
| Recovery | Pre-commit task corrections now include R5/R6. v3 has an explicit reopen path; vNext still lacks general post-commit revision and dependent-stage recomputation. This is a remaining gap, not an improvement claim. |
| Discovery channels | v3 includes surface/category channels, fix-mining guidance, differential/control probes, and runtime-specific manuals. vNext's catalog and Python hotspot pilot are not demonstrated replacements for all of them. |
| Generality | The workflow separates language, build, component, and boundary concepts. Its current support remains bounded by adapters, heuristics, and the fixed portfolio; arbitrary languages and complete boundary discovery are not certified. |
| Bias and cost | The user's target is the fixed Top 15 language / Top 10 issue portfolio; that declared scope is not itself bias. Bias risk lies in selection/ranking and whether equal counts deliver balanced discovery. All-six R2 axes and R4 fan-out are further policies whose quality/cost is unmeasured. |
| Audit quality | No matched held-out discovery comparison establishes superiority. Four legacy recall cases remain unmeasured in vNext; a fixture's existence is not recall evidence. |

## 3. Confirmed Findings and Repairs

Priority below is engineering priority, not a vulnerability severity or CVE assessment.

| Priority | Confirmed issue | Repair and discriminating evidence |
|---|---|---|
| P1 | R5 could collect an invalid experiment reference and fail only at commit, with no supported amendment recovery. | Shared collect/commit parsing rejects blank or foreign IDs while preserving the lease; absent IDs use JSON null. R5/R6 pre-commit amendments preserve original artifacts. Tests exercise corrected task commit and rejection after commit, including legacy-collected bad output. |
| P1 | R5 had no distinct state for a required experiment that could not be attempted, conflating environmental infeasibility with omission or an inconclusive run. | Added `NOT_FEASIBLE` with required=true, null experiment ID, blocker evidence/rationale, and rejection when that hypothesis has an attempted run. It remains NEEDS_REVIEW in Batch/Campaign reports and cannot provide empirical confirmation or refutation. Focused tests cover valid, malformed, attempted, and report-projection paths; no real host Campaign has yet exercised it. |
| P1 | R6 closure did not preserve an explicit review state for each R1 Surface, leaving no-hypothesis Surfaces indistinguishable from reviewed scope. | Added per-Surface `REVIEWED`/`DEFERRED`/`NOT_APPLICABLE`/`UNREVIEWED` declarations. Durable collection requires exact, unique R1 Surface-ID coverage; in-process closure projection defaults absent entries to `UNREVIEWED`. The task prompt and operator guidance now state the contract. Focused tests cover defaulting, explicit states, exact coverage, same-lease correction, Campaign aggregation, and prompt wording. These declarations are not host-observed reading evidence or safety proof. |
| P0 | Plans lacked path-level scope roles, so excluded/deferred inventory paths could not be distinguished from paths assigned for review. | Plans now retain exact INCLUDED/EXCLUDED/DEFERRED records for all inventory source paths; only INCLUDED paths enter Work Units. CG2 validates classification, ownership, and source/Campaign evidence; reports preserve all statuses. CLI/planner and Campaign regressions cover the flow. Approver strings remain self-attested and path states do not prove host-observed reading. |
| P1 | Campaign closure accepted a caller-supplied Plan without confirming it was the latest durable scope artifact. | Closure now rejects a stale Plan ID and a same-ID Plan object whose content differs from its stored artifact. Regression tests record a newer Plan and mutate an in-memory Plan to exercise both rejection paths. |
| P1 | A corrected terminal R6 task could not be amended after Batch closure, or Campaign closure could consume an older R6 report while an amendment was pending. | Terminal R6 task amendments are now append-only and allowed only before Campaign completion; recommitting appends the corrected Batch projection. Campaign closure rejects any R6 amendment not followed by a newer R6 projection. Tests cover successful reprojection, immutable prior report, stale-closure blocking, and closed-Campaign rejection. General R1-R5 post-commit invalidation/recomputation remains absent. |
| P1 | R4 accepted invented hypothesis references; R1 Surface entry anchors failed too late. | R4 task-local WU/family allowlists apply to individual and bundled tasks. R1 checks entry paths, LOC range and nonblank anchors at collect. Negative tests then resubmit valid output within the lease. |
| P1 | Runtime residue scans missed the main prompt and runtime Python, allowing a misleading clean result. | Both scan entry points now share residue checks over source, the main prompt and eligible knowledge. An artificial project token in source/prompt fails; the same token in tests/history does not become runtime pollution. |
| P2 | Main-prompt resource guidance had carried a historical target attribution and a platform-specific sanitizer/address-space example. | Removed target attribution, sanitizer-specific wording, and the numeric example from the runtime prompt. Kept only generic host-diagnostic, host-approval, address-space-versus-RAM, and external containment guidance; detailed test values remain in test evidence. |
| P1 | The host-agent contract had no explicit boundary for instructions embedded in repository-controlled files or tool output. | Added a general Hard Rule: treat such content as evidence, not authority to change scope, evidence rules, skill policy, or host permissions. This is prompt guidance only; the host must still enforce tool/resource policy and needs adversarial integration tests. |
| P2 | R5 recipe prerequisites advertised sanitizer tooling for every C/C++/Rust experiment family, including unrelated classes. | Scoped sanitizer advice to optional tooling for MEMORY-SAFETY/NUMERIC recipes; bumped the task-policy digest version and added a family-matrix regression. Runtime no longer names ASan or a platform-specific limit. |
| P2 | A C memory-safety profile/card carried an obsolete v3 `parser_fuzz` mandatory-test directive and duplicated it as counterevidence. | Replaced it with conditional, target-appropriate boundary/truncation guidance; removed the non-counterevidence duplicate. Added a regression that serializes the active C task context and rejects the legacy template directive. |
| P2 | A broad private-host-path pattern also matched relative certificate filenames during repair. | Added path boundaries and a negative regression for relative certificate names. Private per-user paths still fail. No knowledge was deleted to force a pass. |
| P2 | Overview/design claims overstated coverage, stage reopening, R5 states, and forecast defects; correction lists and scan descriptions were stale. | Aligned the bounded contracts across overview, README, requirements, system/software design, roadmap and acceptance plan; retained all 40 SYSR and 45 SWDR IDs. Removed an unverified standard-edition status assertion without asserting the opposite. |

Implementation and regression evidence:
[execution](../../src/reachable_audit/execution.py),
[scan](../../src/reachable_audit/compatibility.py),
[task policy](../../src/reachable_audit/runtime_policy.py),
[execution tests](../../tests/test_execution.py),
[R4 tests](../../tests/test_category_runs.py),
[R5 tests](../../tests/test_experiments_metrics.py), and
[scan tests](../../tests/test_cli.py).

## 4. Four-Defect Assessment

**Historical carryover.** A real main-prompt attribution and a case-derived sanitizer
configuration were removed from the runtime prompt; optional sanitizer advice is now
family-scoped. The obsolete C `parser_fuzz` task directive was removed from active
profile/card context and its test-method duplicate was removed from counterevidence.
Source-digest provenance remains for traceability, but the KnowledgeTaskContext
serializer does not send it to Agents. The scan blind spot was repaired: scans cover 48
Python files, 167 eligible knowledge files and one main prompt; caller-supplied
historical project tokens pass. The runtime does not ship that token list. Pattern
checks still cannot prove semantic neutrality, host/session isolation, or prompt
injection resistance. A Hard Rule now tells Agents not to follow scope/policy changes
embedded in repository text; it is not a runtime-enforced sandbox. Preserve provenance
and test evidence; keep them separate from active task guidance.

**Design bias.** The fixed 15-language/10-issue portfolio is the intended product
scope, not a defect by itself. Selection provenance, ranks, templated card semantics,
Python-only hotspots and six-axis/R4 fan-out remain policy/coverage risks whose
quality/cost is not demonstrated. No new language, score, gate or compulsory audit
stage was invented to mask missing evidence. Revisit selection or ranking only with
declared scope, semantic counterexamples, and matched quality/cost measurements.

**Dead code.** A conservative AST consumer screen parsed 72 source/tool/test files,
including loaded names, attributes and string-based references, and found no obvious
zero-reference private-function candidate. Public APIs, dynamic dispatch, fields,
unexecuted branches and semantic no-ops are not thereby proven live. No function was
deleted on name matching alone. The new scanner is consumed by CLI/evaluation paths;
the new validation and amendment helpers are exercised by normal task commits.

**Redundancy and complexity.** Shared residue logic removes duplicated scan policy.
Shared R5 parsing avoids different collect/commit schema interpretations. R2/R4 overlap
may be useful independent discovery or costly duplication; current tests cannot decide.
Large CLI/closure functions and broad exception handling remain structural debt in the
[roadmap](REPAIR_ROADMAP_VNEXT.md), not a reason for an unmeasured wholesale rewrite.

## 5. Historical-Lesson Disposition

Project names below identify review evidence only, not runtime dispatch conditions or
fresh-discovery inputs. Entries refer to the locally reviewed lesson records; they do
not claim that every semantic lesson has been implemented in the catalog.

| Review source | Disposition of skill lessons |
|---|---|
| MaintainWise, items 1-6 | 1-2: current artifact/collection contracts provide bounded equivalents. 3-5: encoding matrices, severity attribution and shipped-data defaults remain semantic review candidates. 6: positive observation, no new obligation. |
| WebKit, items 1-9 | 1-2: explicit schema/artifact contracts. 3: refutation/revival exists. 4-5: fidelity/grade checks exist but do not prove equivalence. 6: semantic verification remains external. 7: probes exist, universal up-front feasibility routing does not. 8: committed-stage contradiction repair remains partial. 9: publication completeness remains operator-reviewed. |
| caddy, items 1-3 | 1: immutable task artifacts avoid assuming worker cwd. 2-3: slice capacity and magnitude ownership require language-specific review/counterexamples; no framework branch is added. |
| firefox, items 1-13 and real-target follow-up | 1: explicit partitioning, not a size-tier capability guarantee. 2, 6: positive observations; artifacts retained. 3: bounded drift checks. 4-5, 11: semantic claim/severity/deduplication review, not proven by schema. 7-9: size/schema/artifact checks are partial safeguards, not loss-free host delivery. 10: decisions can use durable events. 12: explicit revival selection exists. 13: this disposition records review, not enforced publication completeness. Real-target follow-up: ownership equivalence and fidelity remain evidence obligations. |
| hadoop, items 1-7 | 1: mechanism-only experiments cannot upgrade empirically. 2-4, 6: attacker-data flow, sibling-fix discovery, bit layouts and gate direction remain semantic/knowledge work, not LOC guarantees. 5: deployment topology stays project-local. 7: observations require eligible registered evidence; general external-observation registration is absent. |
| haproxy, items 1-4 | 1: positive observation, no new rule. 2: build membership/scope needs explicit interpretation. 3: keyword lookalikes need counterexamples, not a target blacklist. 4: late R4 discoveries require follow-up verification, not invented canonical IDs. |
| hibernate-orm, items 1-6 | 1, 5: typed contracts and rejection rather than silent guessed normalization. 2-4: dialect/channel matrices and equal-capability reasoning remain semantic review. 6: exact classpaths stay project-local. |
| keycloak, items 1-6 | 1-2: branch/upstream claims need current-tree/target evidence, not version labels. 3: cross-channel discovery remains valuable but unmeasured. 4: typed assessment states avoid relying on prose prefixes; they do not establish semantic truth. 5: protocol setup remains project evidence. 6: managed process groups exist; no process-name recipe is added to the scheduler. |
| quickjs, items 1-5 and experiment observations | 1: R4 versus R2 superiority remains unmeasured. 2-3: allocation accounting and arithmetic boundaries are semantic review candidates. 4: positive same-fact observation, not proof of canonical deduplication. 5: sibling-vector review remains explicit follow-up where needed. Build/ASan parameters and peak-memory measurement timing stay experiment-specific. |
| servo, observations N-1 through N-5 | N-1: ID/reference validation exists, not complete semantic merge proof. N-2: anchor validation does not verify snippet meaning. N-3: fix-mining coverage and unavailable build context remain explicit limitations. N-4: build-feature and dependency ownership need current-source evidence, not invented IDs or a coverage declaration. N-5: dependency locking/offline feasibility are harness-fidelity work; exact crate versions stay project-local. |
| v8, initial items 1-5 and follow-up sections | Initial 1: typed corrections; 2: API reachability is not a defect; 3-4: positive observations, not vNext recall evidence; 5: leases/retries provide bounded recovery. Empirical follow-up 1-2: disposition/revival records are explicit, not automatic semantic decisions; 3-4: configuration/causal controls need evidence. Debug-build, ABI, parallelism and checksum details stay project-local. Recall follow-up: JIT optimization recall remains unmeasured. |

The four legacy recall entries cover JIT type tracking, asynchronous ownership,
cross-process origin and graphics/GPU boundaries. Their directions remain queued for
isolated comparative evaluation; neither catalog cell counts nor known-case disclosure
to a worker can satisfy a held-out recall claim.

## 6. Standards and Acceptance Boundary

No proprietary Google requirements, authorized checklist, organizational controls or
assessor mandate were supplied. Public engineering principles can guide review but do
not establish compliance with Google's internal requirements.

ISO/IEC/IEEE 12207 concerns lifecycle process outcomes, not a unit-test threshold or a
required number of design documents. The [lifecycle self-assessment](LIFECYCLE_CONFORMANCE_VNEXT.md)
is a partial high-level mapping only. Formal assessment needs a controlled applicable
edition, approved tailoring, owners, configuration/quality/risk records, independent
verification and acceptance evidence. Those missing records cannot be generated by
declaring the code conformant. Requirements traceability is useful but insufficient.

The original real single-Batch report remains strict task-only **FAIL**: direct R5
recovery was used and declared input/output caps were exceeded. The later retest3
follow-up Campaign passed the exercised R5/R6 task-only correction mechanics and
budget admission ledger; it does not retroactively change the original run or establish
fresh discovery. Its R1/R2/R3/R3.5 inputs were controlled replays, D3 host-registered
empirical acceptance was not exercised, and its host had no cgroup memory cap. A 64 TiB
`RLIMIT_AS` allowed ASan shadow mapping but is not physical-memory containment. See the
[local retest handoff](../LOCAL_TEST_HANDOFF.md#7-real-run-feedback-and-retest) and
[retest3 report](../../../xnext_debug_run/retest3/REPORT.md).

Evidence review found two report-boundary issues: the retest3 LEDGER narrates the D3
host registration/amendment path as a requirement/procedure, but `retest.log` records
`EMPIRICAL none` and REPORT §7/§12 confirms that path was not exercised. Also, REPORT
§6's final “effective control” wording is unsupported when `memory.max` and
`memory.high` are both unset. This reassessment treats D3 as untested and D2 as an ASan
mapping compatibility result only; original logs, report, ledger, and archive remain
unaltered.

## 7. Verification and Exit Criteria

- Current full regression after R5 infeasibility-state and RG12-RG15 evaluator-gate implementation: **240 passed, 1 skipped**; the
  skip requires a protected external held-out bundle. No real discovery or scale
  qualification is inferred from that suite.
- Compatibility/residue scan: PASS on 48 Python, 167 knowledge and one prompt file,
  including an evaluation-side historical-token probe. This is a bounded scan result.
- Real repair-behavior retest: task-only R5/R6, live R1/R4/R5 collect rejections with
  same-lease correction, and the R6 artifact contract passed in a controlled follow-up.
  D3 empirical accept path and D2 physical-memory containment remain unverified.
  Measured budget admission stayed under declared totals, but provider-side hard
  interruption is unavailable.
- Documentation: stable 40/45 requirement IDs, Markdown fences and JSON examples checked;
  local links checked separately. Editor diagnostics and whitespace checks are local
  engineering checks, not external acceptance.
- Retest3 predates the family-scoped optional-tooling change and records the preceding
  task-policy digest and 212-test suite. It also predates `NOT_FEASIBLE`; that state has
  local regression coverage but no real Campaign validation yet.
- Retest3 also predates RG13/RG14/RG15 and release-policy-5; signed clean-room, screening,
  and scale-gate behavior has contract coverage only, not qualifying real Campaign evidence.
- RG14's digest-backed validation is covered by signed synthetic evaluator fixtures;
  no real Campaign measurement artifact has yet qualified its screening evidence or
  host-observation semantics.
- Promotion remains blocked by unimplemented RG12 and missing real RG15 scale evidence,
  in addition to the other required real acceptance evidence.
  Next close the D3 registered-harness accept path and verify an actual host memory
  limit; separately qualify clean-room paired discovery, language/mixed-language
  coverage, and real scale/fault recovery as defined in the
  [acceptance plan](ACCEPTANCE_PLAN_VNEXT.md).

Remaining runtime targets include full input dependency invalidation, general committed
stage revision, per-path/per-Surface review records, principal/interface proof,
authenticated reviewer identity, delegated budgets, universal strict domain parsers,
authorized external-observation registration, and non-Python hotspot quality.
They are neither silently implemented nor waived by this reassessment.

## 8. Implementation Gap and Code-Audit Queue

This matrix follows the software design's revised core contracts and the SYSR/SWDR
status tables. “Not implemented” is a known capability gap; “audit/evidence required”
means code exists but its semantics or real-world operation are not yet established.
Neither label alone is a confirmed exploitable vulnerability.

### 8.1 Missing or Partial Implementation

| Priority | Design/requirement | Current implementation boundary | Work needed |
|---|---|---|---|
| P0 | Software Design §1.1 #2-3; SWDR-018/034; SYSR-032 | Drift invalidates detected/recorded dependencies, and pre-commit amendments exist. There is no complete dependency graph for every task input, general post-commit stage revision, or automatic downstream recomputation. | Define dependency edges for source, plan, knowledge, contract and host attestations; make invalidation/reopen atomic and retain prior evidence. Add a late-candidate path that reaches verification/adjudication without rewriting history. |
| P0 | Software Design §1.1 #4; SWDR-011/023/032/033/040; SYSR-012/019/030/031/038 | Plan records path scope; task-coordinated R1/R2/R4 declare SCREENED/INSPECTED altitude, and optional R1 path-priority tiers cross-tab Work Unit altitude by risk label; R6 records Agent-declared Surface states. These are separate from ownership but do not prove host-observed reads. Tier semantics are not independently validated; closure-time screening enforcement remains absent. | Add host-observed review evidence if available; validate tier consistency/quality and test ceiling interactions. Do not equate Agent claims, `REVIEWED`, `reviewed_scope`, or approver strings with observed reads or authenticated identity. |
| P0 | Software Design §1.1 #5; SWDR-010/013; SYSR-016/017/018 | Typed supplied boundaries, structural joins, and typed Handoff endpoint/interface/principal/data-mapping declarations exist. Resolver validates planned-edge identity, endpoint component ownership, and source/Campaign artifact references. These checks do not prove semantic truth. Automatic FFI/RPC/IPC/serialization completeness and independently adjudicated truth remain absent. | Measure missing-edge discovery separately and exercise semantic proof review on real cross-language campaigns; do not equate structurally valid Agent declarations with verified data flow. |
| P1 | SWDR-035/036; SYSR-033/034 | Bounded retries, managed-run evidence, and an evidence-backed `NOT_FEASIBLE` unresolved state exist. Authenticated worker/reviewer identity, delegated budgets, and authorized external-observation registration do not. | Implement identity/budget authority contracts and independently attest external observations; keep NOT_FEASIBLE non-confirming and non-refuting. |
| P1 | SWDR-031; SYSR-029; RG12 | RG12 gate logic exists; the only enabled provider is Python AST. Other portfolio languages have no provider, and current signed fixture metrics do not establish real provider quality. | Add language providers incrementally with positive, negative, alias, malformed-source, unsupported-path and real held-out quality evidence; never interpret zero matches as safety. |
| P1 | Software Design §3; SWDR-041 | Selected task-collection validators check scope, anchors and shapes, but several domain parsers still ignore unknown fields or can raise raw exceptions; stage-level checks may still fail after collect. | Audit each public parser/CLI boundary, normalize malformed input to actionable errors, define strictness/versioning policy, and preserve same-lease repair behavior. |
| P1 | SWDR-039; SYSR-037; RG13 | RG13 validates signed fresh/history declarations and links R1/R2 task-input artifacts to the Campaign report. Actual host prompt/session isolation and independent proof that the signer saw all supplied context remain external. | Exercise the gate with real host-generated manifests; adversarially verify prior target/QA data cannot enter fresh prompts, and retain independent host attestation. |
| P1 | RG14; SWDR-040; SYSR-038 | The evaluator validates digest-backed counts/fraction, status consistency, and rejects overrides. It cannot prove host-observed reads; Campaign closure remains non-blocking and no authenticated override mechanism exists. | Qualify trusted report generation/host observation; preserve signed override rejection and verify with real campaigns. |
| P1 | RG15; SWDR-042; SYSR-040 | Evaluator logic validates a digest-backed 30k-Handoff/10k-event fixture declaration and cross-checks a qualifying real-run record; only synthetic signed fixture evidence exists, and no representative large Campaign has qualified the behavior. | Run the actual stress fixture and real large Campaign; independently verify performance/atomicity and interruption/recovery, then qualify 20GB+ operation. |
| P2 | SWDR-003/005/028; SYSR-003/009 | The approved 15×10 portfolio is structurally complete, but cards are templated and semantic review/counterexample coverage, cross-language variants, and selection/rank quality are not mechanically demonstrated. | Keep Top15×Top10 as the declared product objective; improve selection only from reviewed semantic evidence and paired held-out quality/cost data, not project-specific branches or counts alone. |

RG12 gate logic exists, but real provider-quality evidence is not supplied. RG13's
checked provenance is signer-attested, not independently observed host isolation; RG15
evaluator mechanics do not constitute scale acceptance. In addition, retest3 did not exercise
the D3 host-registration acceptance path; the tested host had no cgroup memory cap, so
the ASan address-map result is not physical-memory containment. The earlier QuickJS
single-Batch run remains strict task-only FAIL and is not repaired retroactively.

### 8.2 Independent Code-Security Review Still Required

These are audit targets, not findings already proven exploitable:

| Area | Code surface | Questions to verify |
|---|---|---|
| Event/lease integrity | `store.py`, `execution.py`, `batch_workflow.py` | Can concurrent claims, retries, amendments or commits produce duplicate ownership, stale acceptance, event-order races, or non-atomic stage state? Are actor/worker labels authenticated or merely caller supplied? |
| Dependency invalidation | `drift.py`, `campaign.py`, `execution.py`, `campaign_closure.py` | Are all source/plan/knowledge/config changes detected transitively? Can old findings or closure projections survive a changed dependency? What host reads remain outside observation? |
| Path/artifact boundaries | `artifacts.py`, `runner.py`, CLI parsing | Test traversal, symlink swaps, non-regular files, cwd escapes, digest/reference confusion, output-size edges, and cleanup after signals/process-group escape. |
| Boundary and reachability truth | `graph.py`, language/build adapters, `handoffs.py`, R1/R3 validators | Establish false/missing edge rates, ownership consistency, attacker-data mapping, principal authorization, generated-code and FFI/RPC/IPC coverage; structural joins are not semantic proof. |
| Release signer and metrics | `evaluation.py`, `runtime_policy.py` | Review HMAC key custody, signer separation, manifest/evidence binding, duplicate/ambiguous JSON inputs, budget parity, interval/statistical calculations, and fail-closed behavior for malformed signatures/artifacts. |
| Knowledge migration and task injection | `migrate_legacy_knowledge.py`, `knowledge_catalog.py`, `execution.py` | Ensure raw source provenance is not sent to Agents, private/project-specific guidance cannot enter active task context, ranking does not privilege one test corpus, and every published card has relevant consumers/counterexamples. |
| Host prompt/tool isolation | `SKILL.md` plus external driver/Agent host | The new untrusted-content rule is advisory. Run adversarial prompt-injection tests and verify the host, not repository text, controls shell/network, secrets, budget caps, memory limits and held-out access. |

The retest3 report covers only its declared controlled follow-up and predates policy-9
plus the latest knowledge/prompt changes. Its task-only mechanics do not discharge this
code-audit queue, real acceptance gates, or independent discovery-quality evaluation.