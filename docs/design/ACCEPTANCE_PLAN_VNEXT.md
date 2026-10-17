# Reachable Audit vNext Release Acceptance Plan

Status: current evaluator behavior and external promotion policy, reviewed 2026-10-17
against commit `beaef3b` plus working-tree repairs. RG1-RG11 and RG13-RG15 have
evaluator checks; RG12 remains unavailable and is reported as a failed
NOT_IMPLEMENTED gates.
Implemented-subset success never grants promotion. Passing unit tests does not certify
capability; no real full portfolio/20GB+ run is recorded.

## 1. Portfolio

The frozen portfolio is C, C++, C#, Go, Java, Rust, Python, JavaScript, TypeScript,
Kotlin, Scala, PHP, Ruby, Swift, and Shell. Certification is per language across the
portfolio; no single repository must contain all 15. At least one separate real
mixed-language Campaign must test cross-language boundaries and chain integration.

Each language has ten prioritized issue profiles, yielding 150 language/issue cells.
The evaluator default is at least three held-out samples per cell. The evaluation
authority may choose a higher threshold, but must freeze it in the signed policy before
examining results. It may not lower the threshold after runs begin.

## 2. Evidence Contract

Every evaluation run is paired with v3 on the same frozen snapshot, scope, budget,
tool/model configuration, and independently adjudicated expected findings. The manifest
contains run records, per-language certification results, all 150 issue-cell records,
mixed-language boundary outcomes, policy, and a content-addressed `evidence_artifacts`
registry. Every `evidence_refs` value must resolve to a content record whose SHA-256
digest matches. Each run's `measurement_artifact_ref` must resolve to content that
matches its repository size, scope/config digests, task/resource totals, Campaign
completion, interruption recovery, and Handoff counts; the evaluator checks those fields
against the signed run record.

Each completed task result must include positive `agent_runs` and `wall_seconds`; the
runtime generates its own vNext policy digest. When the host exposes them, task results
also include `model_id`, `runtime_version`, and a SHA-256 `host_tool_policy_digest`.
Missing host attestations do not block task collection but make the Campaign ineligible
for release evaluation. The parity digest covers only shared host model/runtime/tool
policy, not engine-specific policy. Repository bytes use the inventory-defined
worktree-footprint policy; scope identity uses the frozen inventory/plan digest. Paired
v3/vNext runs must use equal scope and host execution-configuration digests.

The Campaign report records an optional init-frozen `max_screening_fraction` and
axis-derived screening/substantive Work Unit counts. Missing/exceeded ceilings mark the
report not release-eligible but do not alone block closure. RG14 validates the digest-
verified measurement artifact's screened/total counts, recomputes the fraction against
the frozen ceiling, checks status consistency, and blocks any human override. It does
not prove that declared counts equal host-observed reading activity; that remains a
host/evidence qualification responsibility.

Every clean-room capability run must record `audit_mode: fresh` and an empty
`history_source_campaign_ids` list. The trusted signer must verify that prior target
Campaign reports, findings, scope decisions, lessons, and skill-regression backlog were
not supplied to R1/R2 discovery. Follow-up runs may measure regression behavior but do
not qualify as held-out clean-room capability evidence. RG13 validates a signed
provenance record against the Campaign measurement artifact, including fresh mode,
empty history sources, and R1/R2 task-input artifact refs. This checks signer
attestations and digest links, not actual host prompt/session contents or absence of
covertly supplied history; independent host-isolation evidence remains required.

Every claimed attempt is included in the attempt-cost view. Released, expired,
cancelled, or still-active claims without terminal usage make that view incomplete;
they are not zero-cost attempts. Catalog content/version is bound on first managed use.

The complete manifest is signed with HMAC-SHA256. The evaluator obtains its verification
key from `VNA_EVALUATION_HMAC_KEY`; that secret belongs only to the evaluation authority
and must never be put in the target repository, Agent task context, logs, or committed
configuration. A missing/invalid signature or evidence digest is a hard failure.

To sign an assembled manifest in the trusted evidence-generation process:

```python
import json
import os
from reachable_audit.evaluation import sign_manifest

key = os.environ["VNA_EVALUATION_HMAC_KEY"].encode()
signed = sign_manifest(manifest, key)
with open("paired-runs.signed.json", "w", encoding="utf-8") as handle:
    json.dump(signed, handle, ensure_ascii=False, sort_keys=True, indent=2)
```

Do not share the signing key with the audit Agent that produces run data. The signer is
responsible for verifying raw Campaign artifacts and independent adjudication before it
signs the evaluation manifest; HMAC authenticates that attestation but does not replace
that review.

The repository contains an opt-in test entry point, not the protected answer set. Run it
only in the isolated evaluation environment where the signed manifest and HMAC key are
mounted outside the repository:

```bash
VNA_HELDOUT_SIGNED_MANIFEST=/secure/evaluation/paired-runs.signed.json \
VNA_EVALUATION_HMAC_KEY=<evaluation-authority-secret> \
PYTHONPATH=src python3 -m pytest tests/test_heldout_release_acceptance.py -q
```

Without the manifest the test skips. With a bundle, this entry asserts that implemented
gates pass while release remains BLOCKED for unimplemented RG12. It is not complete
release authorization, even if a reviewer verifies the source Campaign records.

## 3. Release Gates

The versioned policy and complete required set live in runtime_policy.py. RG1-RG11
and RG13-RG15 below describe implemented checks over signed records and digest-verified artifacts.
Real-world held-out status/adjudication are trusted-signer attestations, not independently
verified answer-store facts. RG12 explicitly fails until its check is implemented.

| Gate | Requirement |
|---|---|
| RG1 | Every project is paired; snapshots, budgets, and expected finding sets match; vNext loses no v3 finding. |
| RG2 | Real held-out recall at equal budget does not regress and improves at least the configured number of weak families. |
| RG3 | False-positive plus NEEDS_REVIEW rate stays within the signed policy. |
| RG4 | Real vNext runs cover native, managed, dynamic, mixed, and JIT project classes; at least one completed 20GB+ Campaign demonstrates recovery. |
| RG5 | Every Handoff in every real run is reconciled. |
| RG6 | Exactly the 15 approved languages are certified; missing, duplicate, extra, or failed languages block release. |
| RG7 | The worst family, language, and language/issue recall delta stays within policy; per-language and per-cell confidence intervals are reported. |
| RG8 | Runtime knowledge passes provenance and deprojecting scans, including evaluator-supplied `forbidden_residue_tokens` from the signed manifest. |
| RG9 | Runtime AST import/legacy-format checks and source/main-prompt/eligible-knowledge residue scans pass. Full documentation consistency and semantic neutrality remain separate review obligations. |
| RG10 | Real vNext run records attest evidence_traceable=true. Artifact reference/digest validation is a separate mandatory evaluator preflight, not a semantic proof of traceability. |
| RG11 | All 150 language/issue cells meet the frozen sample floor and at least one real held-out mixed-language Campaign has fully reconciled boundary cases. |
| RG12 | Every enabled hotspot provider passes positive, negative, alias, and malformed-source conformance fixtures; held-out evaluation reports candidate coverage/precision separately from Agent finding recall. Missing providers and unsupported paths are explicit, never counted as clean coverage. |
| RG13 | Clean-room capability runs use fresh Campaigns with no declared history sources; signed provenance confirms prior target audit artifacts and regression backlogs are absent from R1/R2 inputs. Follow-up runs cannot satisfy held-out recall gates. |
| RG14 | The Campaign freezes a screening ceiling before discovery; screened-only Work Units are reported separately and do not count as substantive language/issue recall coverage. Any human override is signed, disclosed, and blocks release certification for affected strata. |
| RG15 | A 30k-Handoff/10k-event fixture and a real large-Campaign run verify indexed/bulk resolution, per-edge reconciliation, atomic failure behavior, stable oldest-first task ordering, and bounded zero-target-stage cost. |

Synthetic fixtures may test evaluator mechanics only. They cannot satisfy any real
held-out, language certification, mixed-language, representative-project, or 20GB+
release gate.

## 4. Decision

External policy authorizes promotion only after all RG1-RG15 pass and an independent
reviewer confirms the real evidence bundle. The evaluator now fails closed for missing
checks: implemented_subset_status=PASS describes RG1-RG11/RG13-RG15, status remains BLOCKED,
and eligible_for_promotion=false while RG12 is unavailable. Extra signed fields
do not waive checks. The sample floor is at least three cases per language/issue cell.

Promotion remains blocked until RG12 is implemented and RG15 evidence is supplied, in addition to
the real held-out/mixed-language/large-repository evidence. Until then, treat evaluator
success as subset-check success only. vNext remains experimental; v3 remains production.