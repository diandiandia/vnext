#!/usr/bin/env python3
"""Offline migration of reviewed v3 issue inventory into vNext knowledge assets."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
from typing import Any


LANGUAGES = (
    "c", "cpp", "csharp", "go", "java", "rust", "python", "javascript",
    "typescript", "kotlin", "scala", "php", "ruby", "swift", "shell",
)
_SOURCE_LANGUAGES = tuple(language for language in LANGUAGES if language != "typescript")
_SEVERITY_TIER = {
    "MEMORY-SAFETY": 1, "INJECTION": 1, "RESOURCE-DOS": 2, "RACE": 2,
    "STATE": 2, "AUTHN": 2, "ERROR-HANDLING": 2, "NUMERIC": 2,
    "TRUST-BOUNDARY": 2, "DATA-INTEGRITY": 3, "CRYPTO": 3, "WEB": 3, "OTHER": 4,
}
_SEVERE_CWES = {
    "787", "125", "416", "415", "476", "190", "129", "843", "78",
    "94", "77", "502", "191",
}
_PROJECT_TOKENS = (
    "gpac", "freetype", "s2n-tls", "nghttp2", "libarchive", "frameworks/av",
    "nacos", "tomcat", "mbedtls", "jsrsasign", "puma", "elasticsearch",
    "pillow", "flutter", "protobuf", "zookeeper", "kafka", "shardingsphere",
    "aiohttp", "gson", "libpng", "libjpeg", "libvpx", "aom", "media3",
    "quic-go", "pyjwt", "quarkus", "phpseclib", "cosign", "etcd", "sinatra",
    "lighttpd", "django", "nestjs", "ktor", "actix", "webrick", "usb-storage",
    "dummy_hcd", "nciemp", "quickjs", "qjs", "bjson", "awstats", "v8",
    "webkit", "firefox", "chrome", "maintainwise", "cand-",
)
_SOURCE_REFINEMENTS = {
    ("cpp", "INV-cpp-003"): {
        "refinement_id": "cpp-async-lifetime-contract-v1",
        "title": "Asynchronous task object destroyed before worker completion",
        "family": "STATE",
        "cwe": ["CWE-696"],
        "pattern": "An asynchronous worker retains access to an object that another thread can destroy or reset",
        "sink_hint": "task lifetime termination, release, or reset while worker execution may still be active",
        "pitfall": "A documented lifetime contract is counterevidence only if its preconditions are guaranteed and all callers obey them; inspect every API path and caller.",
    },
    ("go", "INV-go-013"): {
        "refinement_id": "go-http-response-buffer-budget-v1",
        "title": "Go HTTP middleware buffers complete responses without a size budget",
        "family": "RESOURCE-DOS",
        "cwe": ["CWE-770", "CWE-789"],
        "pattern": "Response interception, logging, or template middleware buffers a complete response without a byte limit",
        "sink_hint": "HTTP response recorder or middleware response-body buffer",
        "pitfall": "A limit applied after accumulation does not bound peak memory; distinguish attacker-controlled growth from a hardening-only concern.",
    },
    ("go", "INV-go-014"): {
        "refinement_id": "go-query-parse-fail-open-v1",
        "title": "Go query parse failure fails open in a routing or authorization decision",
        "family": "NUMERIC",
        "cwe": ["CWE-697"],
        "pattern": "A query parsing error is converted into a non-match or permissive result used by a routing or authorization gate",
        "sink_hint": "query parser error handling that feeds a route matcher or access decision",
        "pitfall": "Check malformed separators and escapes, partial parse results, and whether parse failure denies or accidentally permits the operation.",
    },
    ("go", "INV-go-015"): {
        "refinement_id": "go-listener-cleanup-cwe-404-v1",
        "title": "Failed Go service reload leaves a provisional listener running",
        "family": "ERROR-HANDLING",
        "cwe": ["CWE-404"],
        "pattern": "A failed configuration reload leaves a newly started listener or goroutine active",
        "sink_hint": "listener/server/goroutine lifecycle cleanup on failed reload paths",
        "pitfall": "This is resource lifecycle cleanup, not use-after-free; trace every provisional start to rollback/shutdown.",
    },
}
_SHELL_EXCLUSIONS = {
    "INV-shell-003": "generic no-shell command-injection row overlaps shell-native interpreter injection; replaced by an explicitly seeded shell word-splitting mechanism",
    "INV-shell-009": "generic access-control category lacks shell-specific source/sink semantics",
    "INV-shell-010": "generic authorization category lacks shell-specific source/sink semantics",
    "INV-shell-011": "web-style user-controlled object-key authorization is not a portable shell mechanism",
}
_REQUIRED_SOURCE_IDS = {
    "go": (
        "INV-go-007", "INV-go-012", "INV-go-013", "INV-go-014", "INV-go-015",
        "INV-go-016", "INV-go-017", "CURATED-go-race-001",
    ),
    "c": ("INV-c-003", "INV-c-006", "INV-c-007", "INV-c-016", "INV-c-017"),
}
_SWIFT_REFINEMENTS = {
    "78": {
        "title": "Shell-mediated Process launch from untrusted Swift values",
        "source_cues": ["untrusted input reaches a Process launch configuration", "a shell command string is assembled before launching a process"],
        "sink_cues": ["Foundation.Process executableURL/arguments", "Process launches /bin/sh or another interpreter with -c and attacker-influenced text"],
        "pitfalls": ["Foundation.Process arguments are argv elements and do not invoke a shell by themselves.", "Injection risk arises when the selected executable is a shell/interpreter or arguments are reinterpreted by a child command."],
        "transitions": ["untrusted text reaches an interpreter command string", "a shell is explicitly launched with -c and interpolated data"],
        "verification": ["Trace values into executableURL and every arguments element.", "Determine whether a shell/interpreter is launched; compare argv-based and shell-string behavior."],
    },
    "787": {
        "title": "Out-of-bounds write through Swift unsafe buffers or C interop",
        "source_cues": ["attacker-controlled lengths or indexes reach UnsafeMutablePointer/UnsafeMutableBufferPointer", "Swift code passes a pointer and length across a C ABI boundary"],
        "sink_cues": ["UnsafeMutablePointer/UnsafeMutableBufferPointer subscripts, pointer arithmetic, and raw-memory writes", "C functions receiving Swift buffer baseAddress/count pairs"],
        "pitfalls": ["Ordinary Array subscripting performs bounds checks; focus on unsafe buffers, raw pointers, and imported C contracts.", "withUnsafeBytes pointer lifetime ends at closure exit; do not retain the pointer."],
        "transitions": ["length/index is not bounded by the actual initialized buffer before unsafe write", "C callee writes beyond the count/capacity contract"],
        "verification": ["Trace count/capacity conversions and pointer arithmetic to the write.", "Check lifetime scope and imported C function length contract; use sanitizers where available."],
    },
    "416": {
        "title": "Dangling Swift/C object reference across ARC or Unmanaged lifetime boundary",
        "source_cues": ["Unmanaged/passRetained/passUnretained or a C callback retains a reference", "object lifetime ends while an unsafe pointer/callback remains reachable"],
        "sink_cues": ["Unmanaged.takeRetainedValue/takeUnretainedValue", "C/Objective-C callback or stored opaque pointer dereferences after owner release"],
        "pitfalls": ["ARC-managed strong references normally prevent UAF; examine Unmanaged, unsafe pointers, bridging, and foreign callbacks.", "Retain-count imbalance may cause leaks or premature release; distinguish the actual failure mode."],
        "transitions": ["foreign callback/pointer outlives the owning Swift object", "unretained opaque pointer is dereferenced after release"],
        "verification": ["Map retain/release ownership across the Swift/Objective-C/C boundary.", "Verify callback cancellation and owner lifetime with a controlled reproducer."],
    },
    "125": {
        "title": "Out-of-bounds read through Swift unsafe buffer or imported C pointer",
        "source_cues": ["untrusted count/index reaches UnsafeBufferPointer or raw pointer access", "a Swift buffer and count are passed to a C reader"],
        "sink_cues": ["unsafe buffer subscript and pointer advanced(by:)", "C functions reading beyond the supplied pointer/count contract"],
        "pitfalls": ["Ordinary Collection subscripts are bounds checked; focus on unsafe APIs and FFI contracts.", "Validate integer narrowing and element-count multiplication before constructing buffer views."],
        "transitions": ["read index exceeds initialized count", "pointer/count contract is widened or narrowed inconsistently across FFI"],
        "verification": ["Trace length units, integer casts, and pointer offsets to the read.", "Check initialized count and foreign function contract; use sanitizers where available."],
    },
    "284": {
        "title": "Missing authorization on a Swift server route or privileged operation",
        "source_cues": ["a Vapor/NIO request reaches a sensitive operation", "route registration or middleware determines whether a principal is required"],
        "sink_cues": ["Vapor route handlers and middleware", "database, filesystem, or administrative operations reachable from a request"],
        "pitfalls": ["Swift access control and type visibility are not request authorization.", "A route group or middleware declaration is not effective unless it dominates every alias and registration path."],
        "transitions": ["request reaches a sensitive operation without an effective authentication/authorization policy"],
        "verification": ["Enumerate route registrations, groups, middleware order, and aliases.", "Test anonymous and least-privileged requests against the sensitive operation."],
    },
    "863": {
        "title": "Incorrect principal/resource authorization in a Swift server handler",
        "source_cues": ["request principal and resource/role identifiers are checked in separate code paths", "authorization result is derived from a route parameter or decoded request value"],
        "sink_cues": ["Vapor/NIO route handlers and service methods", "resource read/write after a role, owner, or tenant comparison"],
        "pitfalls": ["Authentication proves identity, not permission for the selected object or action.", "Check middleware and service-layer policy consistency across aliases."],
        "transitions": ["incorrect subject/action/resource comparison authorizes a protected operation"],
        "verification": ["Trace the authenticated principal and selected resource through the exact policy branch.", "Compare owner, cross-tenant, and wrong-role controls."],
    },
    "639": {
        "title": "Swift server object lookup uses a request-controlled key without ownership scoping",
        "source_cues": ["route/query/body identifier selects a server-side object", "authenticated principal or tenant is available separately"],
        "sink_cues": ["Vapor route parameters and ORM/repository lookups", "resource mutation/read after lookup by a request-controlled key"],
        "pitfalls": ["UUIDs and opaque identifiers do not establish ownership.", "Authorization must cover nested, batch, and alternate route lookups."],
        "transitions": ["request-controlled object key reaches a lookup or mutation without principal/resource scoping"],
        "verification": ["Trace request identifiers into reads and writes and inspect query tenant/owner constraints.", "Test same-tenant and cross-tenant principals against the same object key."],
    },
}
_TYPESCRIPT_REFINEMENTS = {
    "78": {
        "title": "Node.js child_process command construction from untrusted input",
        "source_cues": ["HTTP/RPC/message values flow into command arguments", "TypeScript values cross erased type annotations or JavaScript interop"],
        "sink_cues": ["node:child_process exec/execSync command string", "execFile/spawn options including shell, argv, and executable path"],
        "pitfalls": ["exec and execSync invoke a shell; string concatenation and interpolation can enable command injection.", "execFile/spawn are safer only when shell execution is disabled and untrusted data remains a separate argument.", "Type annotations do not validate runtime input; validate deserialized and any-typed values."],
        "transitions": ["attacker-controlled value is concatenated into a shell command", "shell:true is selected or inherited at the process boundary"],
        "counterevidence": ["Only a fixed executable is invoked with a fixed argv structure, shell:false, and validated values."],
        "verification": ["Trace untrusted values to child_process APIs and identify the exact API/overload/options.", "Verify shell behavior, argument boundaries, executable selection, and platform-specific quoting.", "Use a harmless sentinel command in an isolated harness and compare an argv-based negative control."],
    },
    "94": {
        "title": "Dynamic code evaluation from untrusted TypeScript runtime values",
        "source_cues": ["untrusted data reaches an evaluation or module-loading input", "generated JavaScript runtime values bypass static TypeScript types"],
        "sink_cues": ["eval and Function constructors", "node:vm runIn* APIs and dynamic code-generation APIs"],
        "pitfalls": ["Dynamic import of a fixed module is not equivalent to evaluating attacker-controlled source.", "Template construction and transpilation can create an execution sink even when the input is typed as string."],
        "transitions": ["untrusted text is transformed into executable source", "a dynamic evaluator consumes attacker-controlled source or code fragments"],
        "counterevidence": ["Only fixed reviewed source is evaluated and untrusted input remains data."],
        "verification": ["Trace attacker-controlled bytes through decoding, templating, and code generation to the evaluator.", "Distinguish data arguments from source text and inspect sandbox/realm boundaries.", "Use a harmless expression sentinel and a non-evaluating control."],
    },
    "400": {
        "title": "Unbounded Node.js stream or request-body accumulation",
        "source_cues": ["remote request or stream chunks are appended to persistent buffers/arrays", "multiple consumers or retries retain chunks beyond request lifetime"],
        "sink_cues": ["Readable/data event accumulation and Buffer.concat", "body parsers, message queues, and per-request chunk arrays"],
        "pitfalls": ["A stream API does not imply backpressure is enabled.", "Count and byte limits must be applied before retaining each chunk; per-request limits may still permit aggregate exhaustion."],
        "transitions": ["each attacker-controlled chunk increases retained memory without a cumulative cap", "slow consumers prevent release while producers continue"],
        "counterevidence": ["A byte/count cap is enforced before append and overflow terminates or backpressures the producer."],
        "verification": ["Trace chunk production, buffering, consumption, cancellation, and cleanup.", "Measure retained bytes under bounded and over-limit streams with a negative control.", "Check per-connection and aggregate concurrency limits."],
    },
    "862": {
        "title": "Missing authorization on a TypeScript service operation",
        "source_cues": ["authenticated or anonymous request reaches a state-changing handler", "route parameter selects a protected object"],
        "sink_cues": ["Express/Koa/Fastify route handlers and service methods", "database writes, secret reads, and administrative operations"],
        "pitfalls": ["Authentication middleware does not prove object- or action-level authorization.", "Decorator/type declarations do not enforce runtime authorization unless middleware is wired on every route."],
        "transitions": ["request reaches sensitive service operation without principal/resource/action policy check"],
        "counterevidence": ["A verified authorization policy dominates the operation for every registered route and alias."],
        "verification": ["Enumerate route registration, middleware ordering, aliases, and service entry points.", "Test anonymous, low-privilege, owner, and cross-tenant principals."],
    },
    "770": {
        "title": "Unbounded queues, timers, retries, or object retention in a TypeScript runtime",
        "source_cues": ["attacker-controlled requests schedule retained work or objects", "queue growth outpaces bounded consumers"],
        "sink_cues": ["arrays/maps/queues, timers, promises, worker queues, and buffered streams", "retained closures/listeners and retry scheduling"],
        "pitfalls": ["Garbage collection does not reclaim objects reachable from queues, listeners, timers, or caches.", "Per-item limits do not bound aggregate concurrency or retry amplification."],
        "transitions": ["untrusted work is enqueued without a count/byte/time budget", "failure triggers unbounded retry or retained callbacks"],
        "counterevidence": ["Queue, concurrency, retention, and retry budgets are enforced before admitting work and on failure paths."],
        "verification": ["Identify the retaining owner and every enqueue, retry, cancellation, and drain transition.", "Measure queue depth and retained memory with bounded and adversarial-rate controls."],
    },
    "639": {
        "title": "Broken object-level authorization through a user-controlled TypeScript key",
        "source_cues": ["route/body/query identifier selects a database object", "tenant or owner identity is available separately from the selected key"],
        "sink_cues": ["ORM findById/findUnique and repository lookups", "filesystem/object-store keys and cache entries selected by request parameters"],
        "pitfalls": ["UUIDs and unguessable identifiers do not replace authorization.", "TypeScript DTO types do not establish ownership or tenant membership at runtime."],
        "transitions": ["user-controlled object key reaches a lookup or mutation without principal/object comparison"],
        "counterevidence": ["The query is scoped by the authenticated principal/tenant or an equivalent policy is checked before use."],
        "verification": ["Trace request-controlled identifiers to reads and writes, including batch and nested routes.", "Compare owner, same-tenant, and cross-tenant access outcomes."],
    },
    "327": {
        "title": "Unsafe cryptographic algorithm or parameter selection in a TypeScript runtime",
        "source_cues": ["request/config values select algorithm, digest, key, IV, or mode", "serialized keys/parameters cross a runtime trust boundary"],
        "sink_cues": ["node:crypto createCipheriv/createDecipheriv/createSign/createVerify", "WebCrypto subtle.importKey/sign/verify algorithm dictionaries"],
        "pitfalls": ["Runtime algorithm strings require an explicit allowlist and compatible parameter checks.", "A successful API call does not establish safe key size, mode, nonce handling, or protocol binding."],
        "transitions": ["untrusted algorithm/parameter choice reaches a cryptographic primitive", "weak mode or reused nonce is accepted by configuration"],
        "counterevidence": ["Algorithm and parameter choices are fixed or allowlisted with validated key/nonce constraints."],
        "verification": ["Trace algorithm and parameter sources to the exact Node/WebCrypto primitive.", "Check key length, mode, nonce uniqueness, tag verification, and error behavior."],
    },
    "79": {
        "title": "Untrusted data reaches an HTML or DOM execution sink",
        "source_cues": ["request/API/storage data reaches browser-rendered markup", "server template output is embedded into an HTML/JS context"],
        "sink_cues": ["DOM innerHTML/outerHTML/insertAdjacentHTML/document.write", "React dangerouslySetInnerHTML and unescaped server template output"],
        "pitfalls": ["Framework escaping is context-dependent; raw HTML escape hatches bypass it.", "URL, script, attribute, and HTML-body contexts require different encoding rules."],
        "transitions": ["untrusted value enters an executable markup/script context without context-appropriate encoding"],
        "counterevidence": ["The framework uses context-correct escaping and no raw HTML sink receives attacker-controlled data."],
        "verification": ["Trace the value into the final browser/template context and inspect sanitization order.", "Use a harmless markup sentinel and a context-matched encoded control."],
    },
    "352": {
        "title": "Cross-site request forgery against cookie-authenticated TypeScript endpoints",
        "source_cues": ["browser-originated state change uses ambient cookies", "cross-origin form/fetch reaches a mutation route"],
        "sink_cues": ["state-changing Express/Koa/Fastify routes", "cookie-authenticated JSON/form endpoints and credentialed fetch handlers"],
        "pitfalls": ["CORS is not a general CSRF defense for form submissions or simple requests.", "SameSite behavior depends on cookie attributes, browser context, and cross-site navigation."],
        "transitions": ["ambient cookie authorization accepts a cross-site state-changing request without a valid CSRF defense"],
        "counterevidence": ["A verified anti-CSRF token/origin policy protects every state-changing cookie-authenticated route."],
        "verification": ["Map cookie attributes and route methods, then test cross-site form and credentialed fetch controls.", "Check origin/referrer validation and token binding on aliases."],
    },
    "22": {
        "title": "Path traversal through TypeScript/Node filesystem operations",
        "source_cues": ["request/archive/object key controls a filesystem path", "base directory and user-controlled relative path are combined"],
        "sink_cues": ["node:fs open/readFile/writeFile/createReadStream/unlink", "path.join/path.resolve results used for filesystem access"],
        "pitfalls": ["path.join is normalization, not a containment proof.", "Check the resolved target against the intended root after normalization and account for symlinks."],
        "transitions": ["attacker-controlled path escapes the authorized root before a filesystem operation"],
        "counterevidence": ["The canonical resolved path remains under the trusted root and symlink policy is enforced."],
        "verification": ["Trace path inputs through decoding, path.resolve, symlinks, and the final fs operation.", "Test traversal encodings and symlink controls against an in-root negative case."],
    },
}


def _digits(value: Any) -> str:
    return re.sub(r"[^0-9]", "", str(value))


def _severity(entry: dict[str, Any]) -> tuple[int, int, str]:
    cwe_rank = 3
    for cwe in entry.get("cwe", []):
        value = _digits(cwe)
        if value in _SEVERE_CWES:
            cwe_rank = 1
            break
        if value:
            cwe_rank = min(cwe_rank, 2)
    return (
        _SEVERITY_TIER.get(str(entry.get("family", "OTHER")), 4),
        cwe_rank,
        0 if _source_evidence(entry) == "battle_observed" else 1,
        str(entry.get("id", "")),
    )


def _entry_digest(entry: dict[str, Any]) -> str:
    encoded = json.dumps(entry, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _source_digest_basis(entry: dict[str, Any]) -> dict[str, Any]:
    fields = ("id", "lang", "title", "family", "cwe", "pattern", "sink_hint", "pitfall")
    return {field: entry[field] for field in fields if field in entry}


def _portable(entry: dict[str, Any]) -> bool:
    text = json.dumps({
        key: entry.get(key, "")
        for key in ("title", "pattern", "sink_hint", "pitfall", "family", "cwe")
    }, ensure_ascii=False).lower()
    return not any(token in text for token in _PROJECT_TOKENS)


def _source_evidence(entry: dict[str, Any]) -> str:
    verification = entry.get("verify", {})
    source = entry.get("source", {})
    if verification.get("status") == "battle_confirmed" or source.get("tier") == "battle_verified":
        return "battle_observed"
    return "seeded"


def _prepare_source_entry(language: str, original: dict[str, Any]) -> dict[str, Any] | None:
    if language == "go" and original.get("id") == "INV-go-018":
        return None
    if language == "shell" and original.get("id") in _SHELL_EXCLUSIONS:
        return None
    entry = json.loads(json.dumps(original))
    refinement = _SOURCE_REFINEMENTS.get((language, str(original.get("id", ""))))
    if refinement:
        entry.update({key: value for key, value in refinement.items() if key != "refinement_id"})
        entry["_refinement_id"] = refinement["refinement_id"]
    if language == "swift":
        primary_cwe = _digits((entry.get("cwe") or [""])[0])
        refinement = _SWIFT_REFINEMENTS.get(primary_cwe)
        if refinement:
            entry["title"] = refinement["title"]
            entry["family"] = str(original.get("family", "OTHER"))
            entry["pattern"] = str(original.get("pattern") or original.get("title", ""))
            entry["sink_hint"] = " | ".join(refinement["sink_cues"])
            entry["pitfall"] = " | ".join(refinement["pitfalls"])
            entry["_refinement_id"] = f"swift-cwe-{primary_cwe}-runtime-v1"
            entry["_swift_refinement"] = refinement
    return entry


def _go_race_seed() -> dict[str, Any]:
    entry = {
        "id": "CURATED-go-race-001",
        "lang": "go",
        "title": "Unsynchronized shared mutable state across Go goroutines",
        "family": "RACE",
        "cwe": ["CWE-362"],
        "pattern": "Concurrent goroutines access shared mutable state without a lock, atomic operation, or ownership handoff",
        "sink_hint": "shared maps, slices, caches, and lifecycle fields crossing goroutine boundaries",
        "pitfall": "The race detector only covers executed schedules; review all reads/writes and cancellation/close ordering.",
        "source": {"tier": "curated_seeded", "origin": "Go memory-model concurrency mechanism"},
        "verify": {"status": "unverified"},
        "_refinement_id": "go-goroutine-race-seeded-v1",
    }
    return entry


def _shell_seeded_entries() -> list[dict[str, Any]]:
    seeds = [
        {
            "id": "CURATED-shell-word-splitting-001", "cwe": "CWE-88", "family": "INJECTION",
            "title": "Unquoted shell expansion changes argv through word splitting and globbing",
            "pattern": "An unquoted expansion is split into multiple arguments or pathname matches",
            "sink_hint": "command arguments populated by unquoted parameter expansion",
            "pitfall": "Inspect quote context, IFS, pathname expansion, arrays, and nested command substitutions; this differs from shell command-string injection.",
        },
        {
            "id": "CURATED-shell-temp-path-001", "cwe": "CWE-377", "family": "RACE",
            "title": "Predictable temporary path in a privileged shell workflow",
            "pattern": "A script creates or reuses a predictable path in a shared temporary directory",
            "sink_hint": "temporary path creation followed by redirection, chmod, copy, or privileged write",
            "pitfall": "Verify atomic creation, restrictive umask, ownership, symlink behavior, and whether the parent directory is attacker-writable.",
        },
        {
            "id": "CURATED-shell-path-lookup-001", "cwe": "CWE-426", "family": "TRUST-BOUNDARY",
            "title": "Attacker-influenced PATH selects an unintended executable",
            "pattern": "A privileged script invokes a command through an inherited or attacker-influenced search path",
            "sink_hint": "bare command invocation, PATH modification, env-based lookup, or sourced executable",
            "pitfall": "Trace effective UID, environment sanitization, PATH order, writable directories, and absolute executable paths.",
        },
        {
            "id": "CURATED-shell-toctou-001", "cwe": "CWE-367", "family": "RACE",
            "title": "Filesystem check-then-use race in a privileged shell workflow",
            "pattern": "A path is tested/stat'ed and later opened, renamed, removed, or executed",
            "sink_hint": "test/[[ -e ]]/stat followed by redirection, cp, mv, rm, chmod, or execution",
            "pitfall": "Check whether an attacker can replace a path component or symlink between check and use; quoting alone does not prevent races.",
        },
    ]
    for entry in seeds:
        entry.update({
            "lang": "shell", "cwe": [entry.pop("cwe")],
            "source": {"tier": "curated_seeded", "origin": "Shell command and filesystem semantics"},
            "verify": {"status": "unverified"},
            "_refinement_id": f"{entry['id']}-language-semantics-v1",
        })
    return seeds


def _select_distinct_primary_cwe(
    entries: list[dict[str, Any]], limit: int = 10,
    required_source_ids: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    selected = []
    used_cwes = set()

    def append_if_distinct(original: dict[str, Any]) -> bool:
        available = next(
            (_digits(item) for item in original.get("cwe", []) if _digits(item) not in used_cwes),
            None,
        )
        if available is None:
            return False
        entry = dict(original)
        entry["cwe"] = [f"CWE-{available}"]
        used_cwes.add(available)
        selected.append(entry)
        return True

    by_id = {str(entry.get("id", "")): entry for entry in entries}
    for source_id in required_source_ids:
        required = by_id.get(source_id)
        if required is None or not append_if_distinct(required):
            raise ValueError(f"required language mechanism unavailable or lacks a distinct CWE: {source_id}")
    for original in sorted(entries, key=_severity):
        if str(original.get("id", "")) in required_source_ids:
            continue
        append_if_distinct(original)
        if len(selected) == limit:
            break
    return sorted(selected[:limit], key=_severity)


def _issue_and_card(
    entry: dict[str, Any], *, language: str, rank: int, version: str,
    approved: bool, typescript_seed: bool = False,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    digest_basis = _source_digest_basis(entry)
    source_digest = _entry_digest(digest_basis)
    issue_id = f"{language}-issue-{rank:02d}"
    card_id = f"MECH-{language}-{rank:02d}"
    provenance_id = f"PROV-{language}-{rank:02d}-{source_digest[:12]}"
    pattern = str(entry.get("pattern") or entry["title"]).strip()
    sink_hint = str(entry.get("sink_hint") or "security-sensitive operation").strip()
    pitfall = str(entry.get("pitfall") or "Verify guards and counterevidence in source.").strip()
    typescript_refinement = None
    if typescript_seed:
        title = f"TypeScript runtime: {entry['title']}"
        source_cues = [
            pattern,
            "trace the value through emitted JavaScript and runtime boundaries",
        ]
        sink_cues = [sink_hint, "runtime values arriving through any, casts, JSON, or JavaScript interop"]
        pitfalls = [
            "Type annotations are erased at runtime; external and deserialized values require runtime validation.",
            "JavaScript interop and any-typed values can bypass compile-time assumptions.",
            pitfall,
        ]
        evidence_state = "seeded"
        source_type = "reviewed_javascript_mechanism_generalized_to_typescript"
        cwes = entry.get("cwe", [])
        primary_cwe = _digits(cwes[0]) if cwes else ""
        typescript_refinement = _TYPESCRIPT_REFINEMENTS.get(primary_cwe)
        if typescript_refinement:
            title = typescript_refinement["title"]
            source_cues = list(typescript_refinement["source_cues"])
            sink_cues = list(typescript_refinement["sink_cues"])
            pitfalls = [
                *typescript_refinement["pitfalls"],
                "Type annotations are erased at runtime; external values require runtime validation.",
            ]
    else:
        title = str(entry["title"]).strip()
        source_cues = [pattern]
        sink_cues = [sink_hint]
        pitfalls = [pitfall]
        evidence_state = _source_evidence(entry)
        source_type = "v3_language_issue_inventory"

    weakness_refs = [f"CWE-{_digits(value)}" for value in entry.get("cwe", []) if _digits(value)]
    family = str(entry.get("family", "OTHER")).upper()
    verification = [
        f"Trace the relevant source cue to the {sink_hint} operation.",
        "Establish attacker control, effective principal, guards, and security impact.",
        "Test the listed counterevidence and record source anchors for every edge.",
    ]
    counterevidence = [
        "A guard dominates the sensitive operation for every relevant path.",
        "The effective principal cannot control the source or the impact is not security relevant.",
    ]
    if not typescript_seed and pitfall:
        counterevidence.append(pitfall)
    dangerous_transitions = [pattern]
    if typescript_refinement:
        verification = list(typescript_refinement["verification"])
        counterevidence = list(typescript_refinement["counterevidence"])
        dangerous_transitions = list(typescript_refinement["transitions"])
    elif language == "swift" and entry.get("_swift_refinement"):
        refinement = entry["_swift_refinement"]
        source_cues = list(refinement["source_cues"])
        sink_cues = list(refinement["sink_cues"])
        pitfalls = list(refinement["pitfalls"])
        verification = list(refinement["verification"])
        dangerous_transitions = list(refinement["transitions"])
        counterevidence = [
            "Safe high-level Swift collection access retains runtime bounds checks.",
            "The foreign pointer contract and owner lifetime are validated at the boundary.",
        ]
    elif entry.get("_refinement_id"):
        source_cues = [pattern]
        sink_cues = [sink_hint]
        verification = [
            f"Trace the language-specific source cue to {sink_hint}.",
            "Establish attacker control, effective principal, guarding order, and security impact.",
            "Test the stated language-specific counterevidence against source and runtime behavior.",
        ]
        counterevidence = [pitfall]
        dangerous_transitions = [pattern]
    issue = {
        "issue_id": issue_id,
        "rank": rank,
        "title": title,
        "family": family,
        "weakness_refs": weakness_refs,
        "mechanism_card_ids": [card_id],
        "source_cues": source_cues,
        "sink_cues": sink_cues,
        "language_pitfalls": pitfalls,
        "counterevidence": counterevidence,
        "verification_steps": verification,
        "provenance_refs": [provenance_id],
    }
    card = {
        "schema_version": "1.0",
        "knowledge_version": version,
        "review_status": "approved" if approved else "draft",
        "mechanism_id": card_id,
        "family": family,
        "title": title,
        "preconditions": source_cues,
        "dangerous_transitions": dangerous_transitions,
        "sink_semantics": sink_cues,
        "counterevidence": counterevidence,
        "language_applicability": [language],
        "verification_recipe": verification,
        "provenance": [provenance_id],
        "evaluation_partition": "training",
        "evidence_state": evidence_state,
    }
    provenance = {
        "source_type": (
            "language_specific_seeded_refinement"
            if entry.get("_refinement_id") else source_type
        ),
        "source_record_id": str(entry.get("id", "")),
        **({"refinement_id": entry["_refinement_id"]} if entry.get("_refinement_id") else {}),
        "source_digest_basis": digest_basis,
        "source_digest": f"sha256:{source_digest}",
        "evidence_state": evidence_state,
        "review_status": "approved" if approved else "draft",
    }
    return issue, card, {provenance_id: provenance}


def migrate(inventory: dict[str, Any], version: str, approved: bool) -> tuple[dict[str, Any], dict[str, Any]]:
    entries = inventory.get("entries")
    if not isinstance(entries, list):
        raise ValueError("source inventory has no entries array")
    by_language: dict[str, list[dict[str, Any]]] = {language: [] for language in _SOURCE_LANGUAGES}
    for entry in entries:
        language = str(entry.get("lang", ""))
        if language in by_language and _portable(entry):
            prepared = _prepare_source_entry(language, entry)
            if prepared is not None:
                by_language[language].append(prepared)
    by_language["go"].append(_go_race_seed())
    by_language["shell"].extend(_shell_seeded_entries())

    draft: dict[str, Any] = {
        "portfolio.json": {
            "schema_version": "1.0",
            "portfolio_version": version,
            "approval_state": "approved" if approved else "draft",
            "languages": list(LANGUAGES),
        },
        "provenance.json": {"schema_version": "1.0", "records": {}},
    }
    report: dict[str, Any] = {
        "schema_version": "1.0",
        "portfolio_version": version,
        "publish_state": "approved" if approved else "draft",
        "languages": {},
        "excluded_project_specific_entries": [],
        "typescript_derivation": "javascript patterns; marked seeded and runtime-specific pitfalls added",
    }
    for language in _SOURCE_LANGUAGES:
        candidates = _select_distinct_primary_cwe(
            by_language[language], required_source_ids=_REQUIRED_SOURCE_IDS.get(language, ()),
        )
        excluded = [
            entry for entry in entries
            if entry.get("lang") == language and not _portable(entry)
        ]
        if len(candidates) < 10:
            raise ValueError(
                f"fewer than ten portable source entries for {language}: {len(candidates)}"
            )
        selected = candidates
        draft_entries = []
        for rank, entry in enumerate(selected, start=1):
            issue, card, provenance = _issue_and_card(
                entry, language=language, rank=rank, version=version, approved=approved,
            )
            draft_entries.append(issue)
            draft[f"cards/{family_path(issue['family'])}/{card['mechanism_id']}.json"] = card
            draft["provenance.json"]["records"].update(provenance)
        draft[f"profiles/{language}.json"] = {
            "schema_version": "1.0",
            "profile_id": f"PROFILE-{language}-{version}",
            "language_id": language,
            "portfolio_version": version,
            "review_status": "approved" if approved else "draft",
            "entries": draft_entries,
        }
        report["languages"][language] = {
            "source_candidates": len(by_language[language]),
            "selected_issue_ids": [item["issue_id"] for item in draft_entries],
            "primary_cwe_count": len({item["weakness_refs"][0] for item in draft_entries}),
            "evidence_states": dict(Counter(
                _source_evidence(entry) for entry in selected
            )),
            "excluded_for_project_tokens": [str(item.get("id", "")) for item in excluded],
            "excluded_for_semantic_scope": {
                entry_id: reason for entry_id, reason in _SHELL_EXCLUSIONS.items()
            } if language == "shell" else {},
            "excluded_false_positive_lessons": {
                "INV-go-018": "counterevidence/false-positive lesson (ReadFile slice bounds use capacity), not a vulnerability mechanism"
            } if language == "go" else {},
        }
        report["excluded_project_specific_entries"].extend(
            f"{language}:{item.get('id', '')}" for item in excluded
        )

    javascript_entries = _select_distinct_primary_cwe(by_language["javascript"])
    if len(javascript_entries) < 10:
        raise ValueError("fewer than ten distinct primary CWEs for typescript")
    ts_profile = []
    for rank, entry in enumerate(javascript_entries, start=1):
        issue, card, provenance = _issue_and_card(
            entry, language="typescript", rank=rank, version=version,
            approved=approved, typescript_seed=True,
        )
        ts_profile.append(issue)
        draft[f"cards/{family_path(issue['family'])}/{card['mechanism_id']}.json"] = card
        draft["provenance.json"]["records"].update(provenance)
    draft["profiles/typescript.json"] = {
        "schema_version": "1.0",
        "profile_id": f"PROFILE-typescript-{version}",
        "language_id": "typescript",
        "portfolio_version": version,
        "review_status": "approved" if approved else "draft",
        "entries": ts_profile,
    }
    report["languages"]["typescript"] = {
        "source_candidates": len(javascript_entries),
        "selected_issue_ids": [item["issue_id"] for item in ts_profile],
        "evidence_states": {"seeded": len(ts_profile)},
        "excluded_for_project_tokens": [],
    }
    _validate_runtime_payloads(draft)
    return draft, report


def family_path(family: str) -> str:
    return family.lower().replace("_", "-")


def _validate_runtime_payloads(files: dict[str, Any]) -> None:
    approved = files["portfolio.json"]["approval_state"] == "approved"
    for path, value in files.items():
        encoded = json.dumps(value, ensure_ascii=False).lower()
        if any(token in encoded for token in _PROJECT_TOKENS):
            raise ValueError(f"project-specific token remains in generated runtime asset: {path}")
        if not approved and "review_status" in value and value["review_status"] == "approved":
            raise ValueError("draft migration cannot create approved child assets")


def _remove_stale_generated_cards(
    output: Path, files: dict[str, Any], languages: list[str],
) -> None:
    previous_card_ids = set()
    for language in languages:
        profile_path = output / "profiles" / f"{language}.json"
        if not profile_path.is_file():
            continue
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
        for issue in profile.get("entries", []):
            previous_card_ids.update(issue.get("mechanism_card_ids", []))
    expected_paths = {
        Path(relative_path) for relative_path in files if relative_path.startswith("cards/")
    }
    card_root = output / "cards"
    if not card_root.is_dir():
        return
    for path in card_root.rglob("MECH-*.json"):
        relative_path = path.relative_to(output)
        if path.stem in previous_card_ids and relative_path not in expected_paths:
            path.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--version", default="knowledge-v1")
    parser.add_argument(
        "--replace-existing-catalog", action="store_true",
        help="refresh generated catalog files only when the existing portfolio version matches",
    )
    parser.add_argument(
        "--publish-reviewed", action="store_true",
        help="publish output as approved after the operator has reviewed the migration report",
    )
    args = parser.parse_args()
    if args.output.exists() and any(args.output.iterdir()):
        existing_portfolio = args.output / "portfolio.json"
        if not args.replace_existing_catalog or not existing_portfolio.is_file():
            parser.error("output directory is not empty; choose a new directory or explicitly refresh its catalog")
        current_version = json.loads(existing_portfolio.read_text(encoding="utf-8")).get(
            "portfolio_version"
        )
        if current_version != args.version:
            parser.error(
                "refusing to refresh catalog with a different version: "
                f"{current_version!r} != {args.version!r}"
            )
    inventory = json.loads(args.inventory.read_text(encoding="utf-8"))
    files, report = migrate(inventory, args.version, args.publish_reviewed)
    if args.replace_existing_catalog:
        _remove_stale_generated_cards(args.output, files, list(LANGUAGES))
    for relative_path, value in files.items():
        destination = args.output / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    report_path = args.output / "migration-report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        "output": str(args.output),
        "languages": len(report["languages"]),
        "profiles": sum(path.startswith("profiles/") for path in files),
        "cards": sum(path.startswith("cards/") for path in files),
        "approval_state": report["publish_state"],
        "excluded_project_specific_entries": len(report["excluded_project_specific_entries"]),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())