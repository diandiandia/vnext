# Reachable Audit vNext Release Acceptance Plan

Status: required before promoting vNext over v3. Passing unit tests alone does not
certify audit capability. No real portfolio or 20GB+ acceptance run is recorded yet.

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

Each run records its init-frozen `max_screening_fraction` policy and screening/substantive
Work Unit counts. The signer verifies the policy was set before R1; `shadow-evaluate`
rejects runs with a missing/exceeded ceiling or a human override in any held-out stratum.

Every clean-room capability run must record `audit_mode: fresh` and an empty
`history_source_campaign_ids` list. The trusted signer must verify that prior target
Campaign reports, findings, scope decisions, lessons, and skill-regression backlog were
not supplied to R1/R2 discovery. Follow-up runs may measure regression behavior but do
not qualify as held-out clean-room capability evidence. The evaluator does not yet
validate this provenance contract; RG13 below remains a promotion blocker.

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

Without the manifest the test skips. A real run is certified only if the evaluator
returns `ACCEPTED` and a reviewer verifies the manifest against source Campaign reports.

## 3. Release Gates

| Gate | Requirement |
|---|---|
| RG1 | Every project is paired; snapshots, budgets, and expected finding sets match; vNext loses no v3 finding. |
| RG2 | Real held-out recall at equal budget does not regress and improves at least the configured number of weak families. |
| RG3 | False-positive plus NEEDS_REVIEW rate stays within the signed policy. |
| RG4 | Real vNext runs cover native, managed, dynamic, mixed, and JIT project classes; at least one completed 20GB+ Campaign demonstrates recovery. |
| RG5 | Every Handoff in every real run is reconciled. |
| RG6 | Exactly the 15 approved languages are certified; missing, duplicate, extra, or failed languages block release. |
| RG7 | The worst family, language, and language/issue recall delta stays within policy; per-language and per-cell confidence intervals are reported. |
| RG8 | Runtime knowledge passes provenance and deprojecting scans. |
| RG9 | Runtime, CLI, schemas, and docs pass the no-v2/v3-runtime-compatibility scan. |
| RG10 | Every referenced evidence artifact resolves and its digest verifies under the signed manifest. |
| RG11 | All 150 language/issue cells meet the frozen sample floor and at least one real held-out mixed-language Campaign has fully reconciled boundary cases. |
| RG12 | Every enabled hotspot provider passes positive, negative, alias, and malformed-source conformance fixtures; held-out evaluation reports candidate coverage/precision separately from Agent finding recall. Missing providers and unsupported paths are explicit, never counted as clean coverage. |
| RG13 | Clean-room capability runs use fresh Campaigns with no declared history sources; signed provenance confirms prior target audit artifacts and regression backlogs are absent from R1/R2 inputs. Follow-up runs cannot satisfy held-out recall gates. |
| RG14 | The Campaign freezes a screening ceiling before discovery; screened-only Work Units are reported separately and do not count as substantive language/issue recall coverage. Any human override is signed, disclosed, and blocks release certification for affected strata. |
| RG15 | A 30k-Handoff/10k-event fixture and a real large-Campaign run verify indexed/bulk resolution, per-edge reconciliation, atomic failure behavior, stable oldest-first task ordering, and bounded zero-target-stage cost. |

Synthetic fixtures may test evaluator mechanics only. They cannot satisfy any real
held-out, language certification, mixed-language, representative-project, or 20GB+
release gate.

## 4. Decision

Promotion is authorized only when `shadow-evaluate` reports `ACCEPTED`, all RG1-RG15
pass, and a reviewer confirms the signed evidence bundle against the actual Campaign
artifacts. RG12 is a planned gate and is not implemented in the current evaluator;
RG13-RG15 are not implemented in the current evaluator. Promotion therefore remains
blocked until hotspot-provider conformance, clean-room provenance verification,
screening-ceiling enforcement, and coverage evidence are implemented. Until then, vNext
remains an experimental shadow candidate and v3 remains the production audit skill.