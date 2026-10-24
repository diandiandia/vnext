# Discovery Quality Evaluation Protocol

Status: proposed evaluation protocol; no held-out dataset or result is claimed by
this document. This protocol is separate from ordinary development audits and release
qualification.

## Purpose

Measure whether optional discovery aids improve source-backed candidate recall without
unacceptable precision, cost, or scope-coverage regressions. Candidate count, hypothesis
count, R4 `SUPPORTED` count, and a passing Campaign are not recall metrics.

## Benchmark construction and isolation

1. Build the initial set from independently adjudicated vulnerabilities with a known
   vulnerable (pre-fix) source snapshot and a separately retained fixed revision. Keep
   language, framework/runtime version, root-cause mechanism family and variant, and
   source location as evaluator metadata.
2. Before any run, have an evaluator define the expected candidate-matching rule:
   source evidence must identify the relevant vulnerable mechanism in the vulnerable
   snapshot. Do not require R3 reachability or R5 confirmation to score discovery;
   record those stages separately. A generic sink mention without the vulnerable
   mechanism and relevant path does not match.
3. Keep vulnerable/fixed labels, issue identifiers, patch diffs, expected locations,
   and evaluator notes outside the engine repository, Campaign state, task inputs,
   model context, and worker-accessible files. Use a trusted evaluator to select the
   source snapshot and verify isolation before signing results.
4. Target at least 20 independently adjudicated cases per language for a development
   comparison, or explicitly report underpowered language/mechanism strata. Deduplicate
   related fixes and avoid treating multiple variants of one root cause as independent
   cases. Keep a separate, untouched holdout for any prospective acceptance claim.
5. A signed evaluator manifest may contain opaque case IDs, scope digests, run artifact
   digests, matching outcomes, and resource measurements. Protected labels and patch
   data remain in the evaluator's offline store, not the repository or audit Campaign.

## Paired comparison

For every case, run the baseline and one treatment on the same frozen vulnerable
snapshot, equal approved scope, knowledge/catalog version, host execution policy,
model/runtime, task budgets, and worker instructions except for the single treatment.
Use fresh isolated Campaigns and contexts; randomize arm order. Do not pass prior
findings, labels, patches, or benchmark metadata into discovery.

Treatments must be isolated rather than combined in the first comparison:

- optional sink census supplied as a lead artifact;
- optional HIGH-risk Surface-to-Hypothesis mapping measurement;
- one independently chosen discovery aid, such as a blind second-pass reviewer;
- a versioned external contract/default-value artifact for a documented dependency;
- structured NEEDS_REVIEW fields, without authorizing execution of proposed probes.

An experiment compares one change at a time. Record missing/failed tasks and excluded
scope rather than dropping them from denominators. Report per-language and per-family
candidate recall, false-positive burden after independent review, candidate matching
agreement, R1/R2 coverage, task completion, agent runs, wall time, and token usage when
available. Show paired case-level outcomes and uncertainty; do not average away a
language or family regression.

## Candidate and evidence adjudication

Two reviewers who did not author the treatment independently compare blinded candidate
evidence against evaluator labels. Resolve disagreement through a third reviewer and
retain the adjudication record. Reviewers see candidate artifacts and the vulnerable
source snapshot, but not the treatment arm or expected answer until their initial
decision is recorded. A match is a discovery hit only when the candidate is source
anchored and describes the applicable mechanism; a sink-name coincidence is not a hit.

External contracts may establish a versioned premise or explain uncertainty, but they
do not replace source evidence and cannot alone promote a finding to confirmed.
Mechanism-level probes and worker-local execution do not count as empirical
confirmation. Any execution requires separate host authorization and a registered
harness under the ordinary R5 evidence rules; static-only runs execute no probes.

## Optional measurement safeguards

- Sink census entries are candidate leads, not vulnerability claims. A candidate may
  cite a census item or provide a reason it is not relevant; census coverage is not a
  collection gate.
- An unlinked HIGH-risk Surface is recorded as unmapped, not as a missed vulnerability
  or evidence of safety.
- Card/variant coverage and independent red-team differences are diagnostics only
  until a prospective paired comparison demonstrates benefit.
- Do not impose a target number of hypotheses, findings, or confirmed vulnerabilities.
- Do not turn benchmark cases or language-specific observations into discovery prompts
  for the same cases. Keep any regression cases used for development distinct from the
  untouched acceptance holdout.

## Decision rule

Before unblinding, the evaluator records the primary recall metric, acceptable
false-positive and cost trade-offs, minimum sample floors, and stopping rule. Do not
invent universal thresholds after seeing results. A treatment is eligible for wider
optional use only if independent review finds a credible recall benefit, no material
evidence-quality regression, and an acceptable cost profile across adequately sampled
strata. Default enablement or a release claim requires a separate prospective decision
and release evidence.

## Current evidence limit

The 11 language pilots recorded in the optimization backlog were static-only, had zero
confirmed findings, and did not have independent held-out ground truth. They can
motivate testable treatments and workflow fixes, but cannot establish recall, precision,
or causality. This protocol has not itself been executed.
