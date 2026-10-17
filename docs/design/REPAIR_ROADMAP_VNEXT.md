# vNext Repair Roadmap

Status: ordered implementation plan, reviewed 2026-10-17 against commit `9a97cba`. System/software design and requirements now document current contracts; this roadmap retains missing targets and defects. A completed code milestone does not imply improved vulnerability recall until acceptance criteria are measured.

## Baseline

The current implementation has a durable Campaign/Batch workflow, source/build inventory, language profiles, evidence gates, and a signed release evaluator. A bounded Python AST hotspot provider now supplies advisory candidates to R1/R2; language-wide coverage and candidate quality remain unmeasured. The knowledge portfolio is structurally complete but materially templated and not yet validated for balanced per-language discovery. Real held-out language runs, mixed-language runs, and 20GB+ recovery evidence remain unavailable.

## Ordered Work

### Core Contract Repair Sequence

1. **Implemented in this repair:** versioned fail-closed release authorization,
	content-bound Campaign knowledge, parsed hotspot-byte checks, per-claim cost
	completeness, retry-aware abort, safe note revisions, structural Handoff joins,
	executable per-Batch forecasts, all-six plan validation, and empty-root fallback.
2. **Bounded integration verified:** a synthetic Python/C Handoff with real source
	anchors records a late R4 candidate as unresolved risk; an explicitly declared
	follow-up Campaign re-verifies it without rewriting original verdict history.
	This is neither automatic stage reopening nor real vulnerability-discovery proof.
3. **Still required:** complete input dependency/invalidation contracts, revision-aware
	candidate reopening, distinct ownership/review/evidence metrics, and interface/
	principal/data-mapping proof records. Software design section 1.1 is the target.
4. **External acceptance remains blocked:** RG12-RG15 implementation/evidence,
	held-out discovery quality, matched cost studies, and representative scale/recovery.

| Order | Work item | State | Exit criteria |
|---|---|---|---|
| 0 | Keep requirements, design, and acceptance plan aligned with measured implementation status. | Current baseline revised; ongoing maintenance | Retain SYSR/SWDR IDs and bounded contracts; verify references, JSON examples, current behavior, and explicit target/defect distinctions. Documentation changes do not close implementation defects. |
| 1 | Make a clean checkout run tests without environment-specific `PYTHONPATH`. | Done | `env -u PYTHONPATH python3 -m pytest tests` passes from the repository root; pytest loads `src` from `pyproject.toml`. |
| 2 | Implement and evaluate the first Python AST hotspot-provider slice. | Pilot implemented; capability evaluation pending | Frozen Work Unit input; stable rule IDs; LOC anchors to the frozen snapshot; candidate report retained in the content-addressed R1/R2 task input; positive, negative/lookalike, alias, malformed-source, and unsupported-language fixtures; explicit coverage limitations; bounded, advisory-only integration. Still requires a real-project candidate-quality/cost pilot before enabling recall claims. |
| 3 | Measure and improve Agent workflow ergonomics. | Not started | One supported command path drives routine schedule/claim/collect/commit work; compare operator/Agent calls, wall time, and task-context size against the current manual path without weakening evidence gates. |
| 4 | Rebuild knowledge quality incrementally, starting with one language/family vertical slice. | Not started | Source/API-specific mechanisms, counterexamples, and recipes reviewed by a security reviewer; seeded/battle evidence distinguished; held-out regression fixtures; no promotion by entry count alone. |
| 5 | Add reusable cross-language mechanism variants and durable source archives. | Not started | Shared cards are used only when semantics match; language differences are explicit; provenance basis is digest-verifiable and linked to an access-controlled source archive/reviewer decision. |
| 6 | Close remaining evidence-contract and trust gaps. | Not started | Typed evidence references resolve to source/artifact records across stages; worker independence is attested by the execution host or explicitly remains uncertified. |
| 7 | Run real paired capability and scale evaluation. | Blocked on external evidence | Frozen held-out samples for all 150 cells, at least one mixed-language Campaign, comparable v3/vNext budgets, independent adjudication, and a real 20GB+ recovery run. Promotion only on signed acceptance. |
| 8 | Control task fan-out without changing audit scope: forecasts, safe empty-component omission, and opt-in same-family R4 bundles. | Mechanics repaired and regression-tested; savings unvalidated | Multi-Batch counts and rounded costs reconcile; real applicable cards work in R4 bundles; completely empty repositories retain one Work Unit. Forecasts assume compact R2. Compare matched cost/quality runs; default R4 stays unbundled. |
| 9 | Close confirmed retry-state, task-ID, R4 schema/coverage, and token-accounting defects from Campaign evidence. | Code and focused regressions implemented; full evaluation pending | Exhausted released claims recover only through bounded authorization; R2 IDs are task-scoped; R4 status/axes/variants fail at collect with actionable errors; closure reports failed-attempt usage and marks missing telemetry incomplete. Historical account aggregates cannot reconstruct missing per-task usage. |

## Campaign-Scale Defect Register

Large-repository pilots exposed workflow failure modes that must be regression-tested
without retaining target names, paths, IDs, or source excerpts in this generic design
document. Preserve the original evidence only in the access-controlled Campaign record.

| Priority | Generic issue class | Current state and next action |
|---|---|---|
| P0 | Evaluator success incorrectly implies full promotion eligibility. | **Repaired and tested:** required RG12-RG15 fail as NOT_IMPLEMENTED; RG1-RG11 subset success cannot authorize promotion. Missing checks and real evidence still block release. |
| P1 | Planner axis subsets disagree with R2 and closure. | **Repaired and tested:** planning rejects unsupported subsets; all-six execution is the current supported contract. Adaptive selection remains target work. |
| P1 | Pre-commit amendment dispatch rejects per-axis R2 operations. | **Repaired and tested:** all six suffixed operations map to R2 pre-commit amendment; post-commit recomputation remains absent. |
| P1 | Multi-Batch forecasts do not reconcile. | **Repaired and tested:** Campaign counts, hypothesis rounding, R4 boundaries, R6 tasks, and rounded costs aggregate per Batch. Rates and savings still lack real calibration. |
| P1 | Real applicable catalog cards crash R4 bundling. | **Repaired and tested:** serialize raw card mappings directly; the existing bundle fixture now selects an applicable Python card and asserts nonempty card seeds. |
| P1 | Abort leaves a retry active; issue exports overwrite host notes. | **Repaired and tested:** cleanup uses latest task state; failed, released, and leased retries cancel; digest-marked issue revisions preserve host content and are idempotent. |
| P1 | Unjoined Handoff chains and post-R0 hotspot source changes are accepted. | **Repaired at structural/managed-input scope:** mismatched joins are rejected before integration; R1/R2 recheck R0 and providers verify parsed bytes. Semantic interface proof and host-wide isolation remain absent. |
| P1 | Released/expired/cancelled attempts disappear from cost completeness. | **Repaired and tested:** every unfinalized claim makes attempt usage incomplete, including active claims. Actual unreported tokens cannot be reconstructed. |
| P2 | Empty repositories lose all planned work; footprint counts symlink bytes. | **Repaired and tested:** retain one root Work Unit; footprint counts only regular files and excludes runtime state. |
| P0 | Static-only reachability, Surface coverage, and scope accounting can block closure. | **Partially fixed:** BG2 accepts explicit R5 dispositions; CG3 counts Work Unit axis review independently of Hypothesis links; closure records evidence-backed exclusions/deferments. General R3 amendment and path-level plan scope dispositions remain open; affected Campaigns require replay. |
| P0 | Prior Campaign decisions can silently narrow a nominally fresh audit. | **Partially fixed:** fresh is the default, prior skill issues are omitted from its baseline and backlog query, follow-up sources are explicit, and unreviewed scope requires current-snapshot evidence/approval. Host-authored prompt isolation, path-level plan dispositions, and evaluator enforcement of clean-room provenance remain open. |
| P1 | Findings can be recorded after an R6 projection, leaving reports stale. | **Code fixed, campaign replay pending:** R6 supports append-only revisions and Campaign closure uses the latest projection per Batch. Re-run R6 for affected completed Batches, then rerun Campaign gates. |
| P1 | Shared queues can lease incompatible tasks; failed/released tasks and collected outputs need correction paths. | **Partially fixed:** filtered claims/listing, retry hints, release/retry, and pre-commit R1/per-axis/compact-R2/R3/R4 amendments exist. Post-commit amendments, downstream invalidation, delegated budgets, and authenticated workers remain open. |
| P1 | Repeated source-anchor validation and whole-Campaign event materialization dominate large runs; screening creates avoidable R4 tasks. | **Code fixed for identified paths; scale proof pending:** R1/R3 stage calls cache line indexes; collect uses a snapshot-bound evidence-path index; task and Batch event reads are indexed; zero-target stages short-circuit; fully NOT_APPLICABLE R4 plans create persisted coverage without worker tasks. Validate against 1k-file and 10k-event/30k-Handoff budgets. |
| P1 | A real R5 confirmation can be blocked by the earlier static-only R3.5 disposition. | **Code fixed and regression-tested:** a CONFIRMED finding accepts either a REACHABLE R3.5 adjudication or a current R5 empirical confirmation for every hypothesis. Other static-only findings remain unconfirmed. |
| P1 | Valid schema/generator evidence outside the source inventory can abort R3 collection. | **Code fixed and regression-tested:** supporting evidence may cite existing in-repository LOC anchors; call-chain LOC anchors remain restricted to included source/build files, and blank-line anchors are rejected. |
| P1 | Large Handoff sweeps require per-edge writes and repeated plan lookup. | **Partially fixed:** `resolve_many` validates the whole input first, uses an indexed plan map, and atomically appends per-edge resolution events. Per-edge artifacts remain; the 30k-Handoff acceptance budget and specialized structural-disposition recipe are not yet validated. |
| P1 | R5 must support target-specific virtual-address limits and required-but-infeasible experiments. | **Partially fixed:** CLI forwards CPU/address-space limits. `NOT_FEASIBLE` and provenance-checked out-of-band evidence remain unimplemented; such evidence must not imply empirical confirmation. |
| P2 | Import heuristics and Handoffs need precise runtime-boundary semantics; review altitude must be explicit. | **Partially fixed:** Python stdlib leaf-name false edges are removed and evidence-backed `NOT_SECURITY_BOUNDARY` exists. Review altitude is specified in design but not yet enforced by task schema. |
| P2 | Campaign lessons and skill issues must not overwrite or drift from one another. | **Code fixed and tested:** issues and closure lessons are separate; reviews append revisions; digest-marked closure lessons preserve host-authored content. |
| P1 | Soft output-size guidance can displace mandatory coverage, and a Work Unit with many owned boundary edges can have a required-output floor above any ceiling. | **Partially fixed:** guidance is coverage-first with a 1 MiB soft target and 4 MiB hard ceiling; `discover_surfaces` coverage (reviewed paths, one review per supplied edge) is verified at collection with a gap list; `plan` reports `oversize_work_units`. Automatic splitting of edge-heavy Work Units and schema-level deduplication of repeated review fields remain open. |
| P1 | R4 exposes `CategoryRun.finding_ids` but the normal R4 task flow does not create canonical Findings; linked-finding counts were easy to misread as total findings. | **Clarified:** R4's field is optional attribution only; canonical batch finding counts/yield derive from `FINDING_RECORDED` events, and distinct R4 links are separately labeled. Finding creation remains the explicit finding workflow after adjudication/R5. |
| P1 | Malformed R2 Hypothesis objects can raise raw `KeyError` during stage commit after collection marked the task successful. | **Fixed and tested:** mechanism family/variant and hypothesis/axis shapes are parsed at collection; malformed shape returns `ModelError` while the lease remains repairable. The contract states the nested mechanism shape. |
| P1 | R1 can collect boundary reviews with empty evidence/rationale and rely on host repair to fill placeholders. | **Partially fixed:** collection now requires a valid disposition, matching Work Unit, non-empty evidence refs, rationale, and exact edge coverage. Anchor/snapshot validity remains a stage-commit check; evidence quality still needs semantic review. |
| P2 | Structural debt: `cli.main` and `CampaignCloser.close` are several-hundred-line functions and several store paths catch `Exception` broadly. | **Open:** split into per-command handlers and per-gate evaluators, narrow the exception types, and keep behavior pinned by the existing tests before any change. |

The system/software design documents define contracts for these groups. Implementation
order is P0 closure/scope semantics and history isolation, P1 durable correction and
queue reliability, P2 reporting/boundary semantics, then the broader knowledge and
workflow improvements.

## First Implementation Slice: Python Hotspots

The first provider is deliberately narrow and advisory. It identifies selected Python API call families with the standard-library AST, including `pickle` deserialization and process execution. It does not claim taint flow, complete alias resolution, reachability, exploitability, or whole-language coverage. Reports include a provider/rule identifier, source anchor, scan coverage, and limitations. R3 remains the reachability-verification stage.

The pilot must report candidate count, reviewed-hit rate, known-case recall, unsupported constructs, scan time, and added task-context size. A clean scan means only that the enabled rules found no candidates; it never means the Work Unit is safe.
