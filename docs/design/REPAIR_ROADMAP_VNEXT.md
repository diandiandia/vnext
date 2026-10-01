# vNext Repair Roadmap

Status: ordered implementation plan, reviewed 2026-10-01. This roadmap separates local engineering fixes from claims requiring external evaluation evidence. A completed code milestone does not imply improved vulnerability recall until its acceptance criteria are measured.

## Baseline

The current implementation has a durable Campaign/Batch workflow, source/build inventory, language profiles, evidence gates, and a signed release evaluator. A bounded Python AST hotspot provider now supplies advisory candidates to R1/R2; language-wide coverage and candidate quality remain unmeasured. The knowledge portfolio is structurally complete but materially templated and not yet validated for balanced per-language discovery. Real held-out language runs, mixed-language runs, and 20GB+ recovery evidence remain unavailable.

## Ordered Work

| Order | Work item | State | Exit criteria |
|---|---|---|---|
| 0 | Keep requirements, design, and acceptance plan aligned with measured implementation status. | In progress | SYSR/SWDR IDs are unique; every normative discovery requirement has a design reference, explicit implementation status, and testable acceptance condition. |
| 1 | Make a clean checkout run tests without environment-specific `PYTHONPATH`. | Done | `env -u PYTHONPATH python3 -m pytest tests` passes from the repository root; pytest loads `src` from `pyproject.toml`. |
| 2 | Implement and evaluate the first Python AST hotspot-provider slice. | Pilot implemented; capability evaluation pending | Frozen Work Unit input; stable rule IDs; LOC anchors to the frozen snapshot; candidate report retained in the content-addressed R1/R2 task input; positive, negative/lookalike, alias, malformed-source, and unsupported-language fixtures; explicit coverage limitations; bounded, advisory-only integration. Still requires a real-project candidate-quality/cost pilot before enabling recall claims. |
| 3 | Measure and improve Agent workflow ergonomics. | Not started | One supported command path drives routine schedule/claim/collect/commit work; compare operator/Agent calls, wall time, and task-context size against the current manual path without weakening evidence gates. |
| 4 | Rebuild knowledge quality incrementally, starting with one language/family vertical slice. | Not started | Source/API-specific mechanisms, counterexamples, and recipes reviewed by a security reviewer; seeded/battle evidence distinguished; held-out regression fixtures; no promotion by entry count alone. |
| 5 | Add reusable cross-language mechanism variants and durable source archives. | Not started | Shared cards are used only when semantics match; language differences are explicit; provenance basis is digest-verifiable and linked to an access-controlled source archive/reviewer decision. |
| 6 | Close remaining evidence-contract and trust gaps. | Not started | Typed evidence references resolve to source/artifact records across stages; worker independence is attested by the execution host or explicitly remains uncertified. |
| 7 | Run real paired capability and scale evaluation. | Blocked on external evidence | Frozen held-out samples for all 150 cells, at least one mixed-language Campaign, comparable v3/vNext budgets, independent adjudication, and a real 20GB+ recovery run. Promotion only on signed acceptance. |

## First Implementation Slice: Python Hotspots

The first provider is deliberately narrow and advisory. It identifies selected Python API call families with the standard-library AST, including `pickle` deserialization and process execution. It does not claim taint flow, complete alias resolution, reachability, exploitability, or whole-language coverage. Reports include a provider/rule identifier, source anchor, scan coverage, and limitations. R3 remains the reachability-verification stage.

The pilot must report candidate count, reviewed-hit rate, known-case recall, unsupported constructs, scan time, and added task-context size. A clean scan means only that the enabled rules found no candidates; it never means the Work Unit is safe.
