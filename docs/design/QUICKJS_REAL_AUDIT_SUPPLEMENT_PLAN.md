# QuickJS Real-Audit Supplement: Scope and Deferred Improvements

Status: prospective supplement for the QuickJS development real-target pilot. This
plan defines a production-relevant audit scope and records evidence questions for
deferred workflow improvements. It is not a vulnerability checklist, a held-out
benchmark, or authorization to change the baseline prompts.

## 1. Objective and Audit Completeness

Audit all production-relevant code and configuration in the selected QuickJS snapshot,
not every repository file. A whole production-scope audit requires the operator to
inventory and disposition every source-like path, then complete every planned Batch in
the selected production scope. If time or budget requires selecting only some
components, label the result a **partial audit**, name the exact included/excluded/
deferred/unsupported scope, and do not describe it as a complete QuickJS audit.

Use the ordinary R0-R6 workflow and frozen scope. Do not change baseline discovery
prompts to include QuickJS-specific APIs, known issues, sink lists, red-team leads, or
language anti-patterns. Improvement observations are a separate track and cannot
silently narrow or expand the security audit.

## 2. Scope Guidance

### Include in the production-relevant scope

At minimum, assess the inventory and plan for:

- interpreter, parser/compiler, bytecode and execution engine;
- garbage collection, allocation, memory/object lifetime and resource handling;
- standard-library implementations and native/host bindings;
- module loading, import resolution, path handling and embedding APIs;
- command-line/runtime entrypoints and externally controlled input paths;
- build, generated-source and configuration inputs that materially change shipped
  runtime behavior or security boundaries.

These are scope areas to inspect, not a claim that a vulnerability exists in them.
The inventory and repository evidence determine the actual paths and ownership.
Do not assume all components are built, enabled, or reachable in every deployment;
record build/configuration preconditions and uncertainty.

### Tests and non-production material

Do not treat the entire test suite (including test262) as the main production
vulnerability-audit scope by default. Record test-only code as excluded or deferred
with a clear rationale, and do not count it as reviewed production source.

Tests may be consulted narrowly when needed to understand intended semantics, establish
a regression expectation, or corroborate a specific source-grounded hypothesis. Cite
such material as supporting evidence, not as proof that production code is safe or as
production-scope coverage.

Reassess a test, harness, CI workflow or fixture as in-scope if it is shipped, runs with
privileges on untrusted inputs, handles secrets, affects release artifacts, or otherwise
forms part of the deployment/security boundary. Do not blanket-exclude configuration:
security-relevant build, runtime, module, or release configuration remains in scope
when it changes production behavior.

## 3. Snapshot and Isolation

- Target snapshot: QuickJS commit
  `02368b6b1689c28ff2ebe6d1f73d9c1893ae4ce7`.
- Use a disposable clean clone and a new `fresh` Campaign with state outside the
  target. The source snapshot must not contain repository-local `.audit_results`,
  old reports, skill lessons, or regression records.
- The operator has prior v3 audit familiarity with this target. Record this as a
  limitation: the run is not blind or held-out. Do not inspect or provide prior v3
  findings, reports, fixes, or expected locations to discovery workers.
- Freeze engine commit, runtime policy version/digest, authorization, selected scope,
  categories, model/tools, resource limits, stop conditions and budget before
  inspecting task results.
- Use static-only discovery. Do not compile, import, execute, or probe target-derived
  code as part of this audit. Any separately authorized dynamic evidence must follow
  host authorization and the registered R5 harness contract.
- Reconcile all source paths, build inputs, components, Work Units, Batches,
  cross-component boundaries and scope dispositions. Missing or unsupported paths
  remain explicit limitations.

## 4. Deferred Improvement Evidence Questions

First complete and seal the baseline audit artifacts. The observations below must not
be fed back into baseline discovery. Record each item as
`SUPPORTED_FOR_FURTHER_EXPERIMENT`, `NOT_SUPPORTED_BY_THIS_AUDIT`, or `INCONCLUSIVE`.
A single target can motivate a follow-up experiment; it cannot establish portfolio-wide
benefit or justify default enablement.

| Backlog item | What to record after baseline is sealed | Evidence needed before development | What this run cannot establish |
|---|---|---|---|
| OPT-01: external dependency contracts/defaults | For an unresolved decision, record the exact dependency/version, external behavior/default that would resolve it, source anchors and current uncertainty. Do not inject external contract data into baseline prompts. | Independent check of version match, primary source, relevance to the source path, whether it changes the disposition, and ongoing version-drift/maintenance cost. | General usefulness or a portfolio-wide reduction in unresolved cases. |
| OPT-02: structured NEEDS_REVIEW | Classify the missing premise after output sealing: source fact, external contract/configuration, authorization/environment, or genuinely undecidable. Record the smallest decisive evidence and why absent; do not alter schemas during this run. | Reviewer agreement that a small stable set of fields would improve follow-up decisions without creating false certainty. Retain counterexamples where structure adds no value. | Improved resolution rate or reduced reviewer effort without a prospective comparison. |
| OPT-07: mechanism-card/variant disposition | Archive exact task knowledge contexts. Independently assess applicable cards after discovery: condition evidenced, counterevidence checked, or card irrelevant. Do not require workers to exhaustively disposition every card. | Verify applicability and selection; record useful source-backed leads, omissions, counterevidence, noise and reviewer effort. | Recall benefit of mandatory card-level coverage; that requires a paired benchmark. |
| OPT-13: sink census | Do not provide a census to baseline workers. After sealing, an independent reviewer may construct a bounded, source-anchored lead list of externally influenced operations, input hypotheses and observed guards for selected Work Units. | Compare the lead list with baseline outputs and independently adjudicated source paths; record unique useful leads, noise, duplication and effort. | Causal recall uplift or an optimal census scope. |
| OPT-14: discovery-stage red team | Do not add a red-team pass to baseline. If separately authorized, use a distinct fresh Campaign and context with no baseline output or old v3 history. Route additional candidates through an explicitly declared follow-up, not retroactively into the original Campaign. | Preserve independent inputs, output digests, candidate overlap/differences, cost and third-party review of new candidates and false positives. | General benefit or a defensible recall rate from one repository. |
| OPT-15: language negative-pattern guidance | Record only concrete incorrect language/runtime assumptions observed in baseline reasoning, with source/runtime evidence, counterexample, and a judgment on whether target-specific. Do not add QuickJS examples to shipped prompts. | Require repeated evidence across independent projects/versions and review for counterexamples and prompt-induced bias. | A generally valid C/JavaScript anti-pattern rule or guidance for other languages. |
| OPT-03: CVE replay benchmark | Treat this as an ordinary development audit. Do not score known historical v3 cases as held-out recall or disclose CVE labels, fixes or expected locations to workers. | Separate evaluator selects vulnerable pre-fix cases, protects labels/patches, freezes matching criteria and conducts paired runs under the discovery-quality protocol. | Held-out recall, precision, causal improvement or release qualification. |

The existing HIGH-risk Surface-to-Hypothesis report may be captured as its documented
exploratory, non-gating measurement. It is derived from Agent-declared risk tiers and
hypothesis links; it is not observed reading coverage, a missed-vulnerability metric,
or a safety conclusion.

## 5. Observation Record and Decision

For each improvement-relevant observation, retain:

- observation ID and backlog item;
- Campaign, Batch, Work Unit and whether observed before or after baseline sealing;
- source/artifact references and exact anchors where available;
- observation, competing explanations, counterevidence and unresolved premise;
- observer role (worker, coordinator, independent reviewer);
- possible target-specific or prior-knowledge influence;
- proposed change, explicitly labeled as a hypothesis;
- observation/review effort and likely maintenance or prompt-cost trade-off.

Do not copy target-specific paths, APIs, expected findings or outcomes into reusable
runtime knowledge. Retain target evidence only in the Campaign/evaluation record under
the target owner's data-retention rules.

Close the supplement with a status and evidence table for each OPT item. A development
proposal requires a concrete recurring failure mode and a narrow test plan. If evidence
is inconclusive, keep the item deferred. This audit alone must not be used to claim
recall/precision improvement, certify language capability, establish large-project
capacity, or claim release eligibility.

For operational execution and reporting, use the
[real code audit test plan](REAL_CODE_AUDIT_TEST_PLAN_VNEXT.md). For prospective paired
quality experiments, use the
[discovery quality evaluation protocol](DISCOVERY_QUALITY_EVALUATION_PROTOCOL.md).
