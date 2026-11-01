# Top-15 Language Real-Project Candidate Plan

Status: **CANDIDATE PORTFOLIO FOR OWNER REVIEW — NO TARGET IS AUTHORIZED OR
FROZEN.** This document proposes projects and bounded audit slices for the
Top-15 language pilot matrix in
[REAL_CODE_AUDIT_TEST_PLAN_VNEXT.md](REAL_CODE_AUDIT_TEST_PLAN_VNEXT.md).
It is a project-selection supplement, not runtime guidance, a finding catalog,
or evidence that any candidate has been audited.

The candidate names and CVE references below are starting points for intake
verification. They do not establish that a particular commit, affected path,
build configuration, language share, or audit scope is suitable. Do not put
candidate CVE details, affected paths, or expected outcomes into discovery
Campaign inputs. Keep them with an independent evaluator until discovery results
are frozen.

## 1. Selection and size rules

The portfolio is intended to compare bounded, production-relevant components,
not entire repositories of arbitrarily different sizes. Before approving a
candidate:

1. Verify repository identity, owner authorization, license/data-handling
   constraints, current supported branches, and an immutable commit.
2. Verify the CVE against NVD and the project's own advisory or release notes.
   Confirm the exact affected and fixed versions, that the cited code belongs
   to the proposed repository, and that the relevant code is in the proposed
   scope. A CVE is an evaluator-side known case, not a required finding.
3. Measure production source LOC for the selected component using a recorded,
   reproducible method. Exclude generated, vendored, test, and documentation
   files from the comparable production-LOC figure, but record their separate
   counts and scope dispositions. Aim for **10k–80k production LOC per
   language-specific audit slice**. This is a screening band, not a coverage
   claim; if a project cannot support a representative slice in this band,
   document the deviation or replace it.
4. Verify the target language is materially represented in the slice. For
   mixed-language projects, report per-language LOC and keep the result from
   being attributed to a language whose code was not actually audited.
5. Freeze the selected scope, build metadata, tools, budgets, prohibited
   actions, and stop authority before R0. Use the development-pilot gates in
   the real-code plan. Do not build or execute target code unless separately
   authorized under an isolated test plan.

No candidate below is approved until all applicable checks pass. If a CVE is
not attributable to the proposed source scope, keep it out of the expected-label
set for that run and either choose another evaluator case or replace the target.

## 2. Candidate matrix

| Language | Candidate repository | Proposed bounded audit slice | CVE example for intake verification | Key fit/scale caveat |
|---|---|---|---|---|
| C | [openssl/openssl](https://github.com/openssl/openssl) | A bounded `libcrypto` X.509 parsing/validation component | [CVE-2022-3602](https://nvd.nist.gov/vuln/detail/CVE-2022-3602) | Confirm the selected commit and exact X.509 path; do not expand the scope to all of libcrypto by default. |
| C++ | [FFmpeg/FFmpeg](https://github.com/FFmpeg/FFmpeg) | One demuxer/decoder family and its directly required shared helpers | [CVE-2023-49502](https://nvd.nist.gov/vuln/detail/CVE-2023-49502) | Large, mixed C/C++ codebase; verify language attribution and keep the component within the size band. |
| C# | [dotnet/aspnetcore](https://github.com/dotnet/aspnetcore) | Kestrel HTTP/2 request-processing component | [CVE-2023-44487](https://nvd.nist.gov/vuln/detail/CVE-2023-44487) | The CVE is protocol-wide; verify Microsoft's affected-product statement and the exact ASP.NET Core implementation path before treating it as an evaluator case. |
| Go | [prometheus/prometheus](https://github.com/prometheus/prometheus) | Web handler and redirect handling, including `/new` only when the frozen revision contains the affected endpoint | [CVE-2021-29622](https://nvd.nist.gov/vuln/detail/CVE-2021-29622); [project advisory](https://github.com/prometheus/prometheus/security/advisories/GHSA-vx57-7f4q-fpc7) | Verify affected/fixed tags and endpoint presence; record build tags and generated files. The endpoint was removed in a later release, so select the snapshot from advisory evidence rather than assuming current behavior. |
| Java | [apache/tomcat](https://github.com/apache/tomcat) | A bounded HTTP request parsing / connector component | [CVE-2024-50379](https://nvd.nist.gov/vuln/detail/CVE-2024-50379) | Verify affected branch, runtime/configuration prerequisites, and whether the relevant code is in the selected component. |
| Rust | [rustls/rustls](https://github.com/rustls/rustls) | Core connection I/O and TLS state-transition component | [CVE-2024-32650](https://nvd.nist.gov/vuln/detail/CVE-2024-32650) | Record workspace members, feature flags, and the exact fixed/affected versions; avoid claiming macro/build-script coverage unless inspected. |
| Python | [django/django](https://github.com/django/django) | A bounded request/input-handling component corresponding to a verified advisory | [CVE-2024-45230](https://nvd.nist.gov/vuln/detail/CVE-2024-45230) | Check the advisory's exact affected component and supported-branch fix; do not assume the URL/request layer is implicated without source verification. |
| JavaScript | [expressjs/express](https://github.com/expressjs/express) | Router and response handling component | [CVE-2024-29041](https://nvd.nist.gov/vuln/detail/CVE-2024-29041) | Small core may fall below the size band; measure it and add only directly related production modules, or replace it. Record Node/runtime as target context, not a universal JS assumption. |
| TypeScript | [vercel/next.js](https://github.com/vercel/next.js) | Server Actions request-processing component | [CVE-2024-34351](https://nvd.nist.gov/vuln/detail/CVE-2024-34351) | Separate TS source, generated JS, runtime behavior, and framework integration. Verify the selected tag and route are affected. |
| Kotlin | [JetBrains/kotlin](https://github.com/JetBrains/kotlin) | A bounded compiler or standard-library component, selected after advisory-path verification | [CVE-2023-43813](https://nvd.nist.gov/vuln/detail/CVE-2023-43813) | The repository is a compiler/toolchain rather than a deployed service. Verify the issue's exact product/path and ensure the selected Kotlin LOC is comparable. |
| Scala | [apache/spark](https://github.com/apache/spark) | Spark SQL UI component and directly related request/rendering helpers | [CVE-2022-33891](https://nvd.nist.gov/vuln/detail/CVE-2022-33891) | Very large mixed Scala/Java repository; limit scope to a Scala-dominant module and record interop boundaries. |
| PHP | [laravel/framework](https://github.com/laravel/framework) | A bounded request/session or serialization-related framework component | [CVE-2018-15133](https://nvd.nist.gov/vuln/detail/CVE-2018-15133) | Old CVE: confirm the historical vulnerable tag is still retrievable and the current target scope contains the corresponding code; do not infer current exposure. |
| Ruby | [rails/rails](https://github.com/rails/rails) | A bounded request/response handling component | [CVE-2024-26143](https://nvd.nist.gov/vuln/detail/CVE-2024-26143) | Verify affected Rails branches, configuration prerequisites, and the exact path; track Ruby/Rails versions. |
| Swift | [apple/swift-nio-ssl](https://github.com/apple/swift-nio-ssl) | TLS handler and validation component | [CVE-2019-8849](https://nvd.nist.gov/vuln/detail/CVE-2019-8849) | Verify the advisory's repository attribution and Swift source path; record the Swift, platform, and dependency versions. |
| Shell | **Candidate unresolved**; [GNU Bash](https://git.savannah.gnu.org/cgit/bash.git) is a possible shell-runtime study target | Prefer a maintained, authorized repository whose in-scope production Bash/POSIX-shell scripts are a material part of the product | [CVE-2014-6271](https://nvd.nist.gov/vuln/detail/CVE-2014-6271) is a Bash CVE, but Bash is implemented primarily in C | Bash's CVE does not make Bash source a shell-script-language sample. Do not count a Bash-source audit toward Shell-language coverage. Find and verify a CVE-bearing shell-script project, or explicitly leave this language sample blocked. |

## 3. Candidate readiness record

For every candidate, create a separate intake record before starting its Campaign.
The record must contain:

- authorization owner, permitted operations, data restrictions, and stop authority;
- repository URL, immutable commit, clean-clone digest, branch/tag, and retrieval date;
- CVE ID, NVD record, project advisory/release note, affected/fixed versions, and
  a reviewer-only mapping from the issue to source paths and expected behavior;
- measured per-language production LOC for included paths and separate counts
  for tests, generated files, vendored files, and unsupported files;
- selected component rationale, explicit included/excluded/deferred paths,
  entrypoints/helpers to predeclare, and cross-module/language boundaries;
- build/runtime metadata, tool availability and permissions, network policy,
  filesystem/process/time/output limits, and whether any dynamic execution is
  specifically authorized;
- the planned independent reviewer and evaluator-label custody;
- a `PASS`, `FAIL`, or `BLOCKED` decision for each selection gate in Section 1.

Use a fresh Campaign per independent language sample. Keep affected CVE details
and expected labels outside discovery inputs; reveal them only to the independent
reviewer after discovery artifacts have been frozen. A public CVE proves neither
that the selected snapshot is vulnerable nor that vNext should rediscover it.

## 4. Development gates that require pilot evidence

The pilots may measure the following repository gaps. They do not authorize
implementation in advance:

| Area | Evidence to collect first | Development remains blocked until |
|---|---|---|
| Additional language hotspot providers (SWDR-031) | Independently reviewed candidate and non-candidate sites; language-specific misses, irrelevant leads, source/runtime context, and unsupported syntax | A bounded provider contract, false-positive expectations, and regression fixtures can be specified from observed evidence. Keep providers opt-in until separately accepted. |
| Automatic boundary discovery (SWDR-010) | Real cross-language, FFI, RPC, IPC, serialization, and generated-code boundaries where present; discovery misses and false proposals | The target mechanism and evidence needed to establish a boundary are explicit, and independently reviewed observations justify a narrowly scoped detector. Do not infer a generic detector from one project. |
| Large-source slicing/completeness (N-6) | Actual large files, bytes/LOC, task-input size, context/time use, inspected ranges, outcomes, and reconciliation gaps | A source-backed range ledger and reconciliation/deferral behavior are designed from measured failures and covered by tests. A file-size threshold alone is insufficient. |
| R5 recipes and dynamic tooling | Authorized target-supported build/runtime, registered harness capability, isolation, limits, artifact capture, and inconclusive/failure behavior | A host-approved, target-specific experiment can be run through the existing registered path. Tool availability or a CVE reproducer does not by itself justify a generic recipe or confirmed status. |
| Shared language guidance/catalogs | Whether repeated evidence-backed needs recur across independently reviewed targets, plus resulting misses and false leads | Guidance is mechanism-neutral, advisory where appropriate, backed by cross-target evidence, and does not carry a candidate's project/CVE plan into discovery. |

Record candidate-specific observations in that candidate's run ledger, not in
generic workflow requirements. A pilot can finish with `NOT ASSESSED` or
`BLOCKED`; lack of evidence is not permission to implement a speculative default.

## 5. Proposed execution sequence

This is a suggested order for owner review, not a universal dependency or
release-qualification order:

1. Intake and validate Python/Django, Rust/rustls, and Java/Tomcat candidates;
   they provide different managed/native/toolchain profiles.
2. Validate C/OpenSSL, C++/FFmpeg, Go/Prometheus, and C#/ASP.NET Core component
   scopes and their build/resource requirements.
3. Run separate JavaScript/Express and TypeScript/Next.js samples; preserve
   separate language scoring and distinguish source from deployed runtime.
4. Validate Kotlin, Scala, PHP, Ruby, and Swift candidates and their proposed
   bounded modules.
5. Keep Shell blocked until an actual shell-script-language sample meets the
   authorization, CVE-record, language-share, and size gates. Bash source alone
   does not satisfy this item.
6. Only after individual samples, run an explicitly scoped mixed-language
   boundary pilot and a separate large-project capacity pilot.

For all stages, use the target-independent run sequence and reporting rules in
[REAL_CODE_AUDIT_TEST_PLAN_VNEXT.md](REAL_CODE_AUDIT_TEST_PLAN_VNEXT.md). A
sampled component audit must not be reported as a complete repository audit.
