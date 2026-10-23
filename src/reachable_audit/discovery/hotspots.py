"""Bounded language-specific API hotspots for Agent review."""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path
from typing import Any, Mapping

from ..models import ModelError
from .go_provider import (
    GO_HOTSPOT_PROVIDER_ID,
    MAX_GO_CANDIDATES,
    MAX_GO_FILE_BYTES,
    MAX_GO_FILES,
    MAX_GO_TOTAL_BYTES,
    GoProviderError,
    scan_go_bytes,
)


_PYTHON_RULES = {
    "os.system": ("PY-CMD-001", "INJECTION", "CWE-78", "OS command execution"),
    "os.popen": ("PY-CMD-001", "INJECTION", "CWE-78", "OS command execution"),
    "subprocess.run": ("PY-CMD-001", "INJECTION", "CWE-78", "subprocess execution; inspect shell and argv semantics"),
    "subprocess.call": ("PY-CMD-001", "INJECTION", "CWE-78", "subprocess execution; inspect shell and argv semantics"),
    "subprocess.Popen": ("PY-CMD-001", "INJECTION", "CWE-78", "subprocess execution; inspect shell and argv semantics"),
    "subprocess.check_call": ("PY-CMD-001", "INJECTION", "CWE-78", "subprocess execution; inspect shell and argv semantics"),
    "subprocess.check_output": ("PY-CMD-001", "INJECTION", "CWE-78", "subprocess execution; inspect shell and argv semantics"),
    "eval": ("PY-EVAL-001", "INJECTION", "CWE-94", "dynamic expression evaluation"),
    "exec": ("PY-EVAL-001", "INJECTION", "CWE-94", "dynamic code execution"),
    "builtins.eval": ("PY-EVAL-001", "INJECTION", "CWE-94", "dynamic expression evaluation"),
    "builtins.exec": ("PY-EVAL-001", "INJECTION", "CWE-94", "dynamic code execution"),
    "pickle.load": ("PY-DESER-001", "INJECTION", "CWE-502", "pickle object deserialization"),
    "pickle.loads": ("PY-DESER-001", "INJECTION", "CWE-502", "pickle object deserialization"),
    "_pickle.load": ("PY-DESER-001", "INJECTION", "CWE-502", "pickle object deserialization"),
    "_pickle.loads": ("PY-DESER-001", "INJECTION", "CWE-502", "pickle object deserialization"),
    "yaml.load": ("PY-DESER-002", "INJECTION", "CWE-502", "YAML load; verify Loader configuration and input trust"),
    "requests.get": ("PY-HTTP-001", "WEB", "CWE-918", "HTTP request destination"),
    "requests.post": ("PY-HTTP-001", "WEB", "CWE-918", "HTTP request destination"),
    "requests.request": ("PY-HTTP-001", "WEB", "CWE-918", "HTTP request destination"),
    "httpx.get": ("PY-HTTP-001", "WEB", "CWE-918", "HTTP request destination"),
    "httpx.post": ("PY-HTTP-001", "WEB", "CWE-918", "HTTP request destination"),
    "httpx.request": ("PY-HTTP-001", "WEB", "CWE-918", "HTTP request destination"),
    "urllib.request.urlopen": ("PY-HTTP-001", "WEB", "CWE-918", "URL open/request destination"),
    "urlopen": ("PY-HTTP-001", "WEB", "CWE-918", "URL open/request destination"),
}
_SQL_METHODS = {"execute", "executemany", "executescript"}
_MAX_CANDIDATES = 200
PYTHON_HOTSPOT_PROVIDER_ID = "python-ast-hotspots-v1"
_GO_RULES = {
    "os/exec.Command": ("GO-CMD-001", "INJECTION", "CWE-78", "command construction; inspect executable and argv trust (no implicit shell)"),
    "os/exec.CommandContext": ("GO-CMD-001", "INJECTION", "CWE-78", "command construction; inspect executable and argv trust (no implicit shell)"),
    "io.ReadAll": ("GO-READ-001", "RESOURCE-DOS", "CWE-400", "whole-stream read; verify upstream size limits"),
    "io/ioutil.ReadAll": ("GO-READ-001", "RESOURCE-DOS", "CWE-400", "whole-stream read; verify upstream size limits"),
    **{
        api: ("GO-PATH-001", "INJECTION", "CWE-22", "path construction/normalization; verify containment at filesystem use")
        for api in (
            "path.Join", "path.Clean", "path/filepath.Join", "path/filepath.Clean",
            "path/filepath.Abs", "path/filepath.Rel",
        )
    },
}


def enabled_hotspot_provider_ids() -> tuple[str, ...]:
    return (PYTHON_HOTSPOT_PROVIDER_ID,)


def _import_aliases(tree: ast.Module) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for item in node.names:
                bound_name = item.asname or item.name.split(".", 1)[0]
                aliases[bound_name] = item.name if item.asname else bound_name
        elif isinstance(node, ast.ImportFrom) and node.module:
            for item in node.names:
                if item.name != "*":
                    aliases[item.asname or item.name] = f"{node.module}.{item.name}"
    return aliases


def _qualified_name(node: ast.expr, aliases: dict[str, str]) -> str | None:
    if isinstance(node, ast.Name):
        return aliases.get(node.id, node.id)
    if isinstance(node, ast.Attribute):
        prefix = _qualified_name(node.value, aliases)
        return f"{prefix}.{node.attr}" if prefix else None
    return None


def _python_candidates(path: str, source: str, tree: ast.Module) -> list[dict[str, Any]]:
    aliases = _import_aliases(tree)
    candidates = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        api = _qualified_name(node.func, aliases)
        if not api:
            continue
        rule = _PYTHON_RULES.get(api)
        if rule is None and api.rsplit(".", 1)[-1] in _SQL_METHODS:
            rule = ("PY-SQL-001", "INJECTION", "CWE-89", "SQL execution method; verify receiver and query construction")
        if rule is None:
            continue
        rule_id, family, cwe, reason = rule
        line = node.lineno
        column = node.col_offset + 1
        candidate_id = "HOT-" + hashlib.sha256(
            f"{path}:{line}:{column}:{rule_id}".encode("utf-8")
        ).hexdigest()[:16]
        candidates.append({
            "candidate_id": candidate_id,
            "rule_id": rule_id,
            "language": "python",
            "family_hint": family,
            "cwe_hint": cwe,
            "path": path,
            "line": line,
            "column": column,
            "evidence_ref": f"LOC-{path}:{line}",
            "api": api,
            "reason": reason,
        })
    return sorted(candidates, key=lambda item: (
        item["path"], item["line"], item["column"], item["rule_id"],
    ))


def compact_hotspot_report(report: dict[str, Any]) -> dict[str, Any]:
    """Agent-facing form: path lists are derivable from the Work Unit, so report counts."""
    extensions: dict[str, int] = {}
    for path in report["unsupported_paths"]:
        suffix = Path(path).suffix.lower() or "(none)"
        extensions[suffix] = extensions.get(suffix, 0) + 1
    compact = {
        key: value for key, value in report.items()
        if key not in {"scanned_paths", "unsupported_paths"}
    }
    compact["scanned_path_count"] = len(report["scanned_paths"])
    compact["unsupported_path_count"] = len(report["unsupported_paths"])
    compact["unsupported_extension_counts"] = dict(sorted(extensions.items()))
    compact["path_lists_note"] = (
        "scanned paths are successfully parsed supported files (.py/.pyw by default; "
        ".go only with explicit opt-in); unsupported files and errored/unavailable "
        "paths were not scanned"
    )
    return compact


def scan_work_unit_hotspots(
    project_root: str | Path,
    source_files: list[str] | tuple[str, ...],
    *,
    max_candidates: int = _MAX_CANDIDATES,
    expected_digests: Mapping[str, str] | None = None,
    enable_go: bool = False,
) -> dict[str, Any]:
    """Scan verified bytes; optional Go AST leads never imply vulnerability findings.

    ``enable_go`` is experimental and deliberately absent from the default
    release-qualified ``enabled_hotspot_provider_ids()`` list. Go requires a
    trusted, installed host toolchain; target packages are never built or loaded.
    """
    if max_candidates < 1:
        raise ValueError("max_candidates must be positive")
    root = Path(project_root).resolve()
    scanned_paths = []
    supported_paths = []
    unsupported_paths = []
    parse_errors = []
    candidates = []
    go_sources = {}
    go_total_bytes = 0
    go_paths = []
    unavailable_paths = []
    go_candidate_count = 0
    for relative_path in sorted(set(str(item) for item in source_files)):
        is_go = enable_go and Path(relative_path).suffix.lower() == ".go"
        if not is_go and Path(relative_path).suffix.lower() not in {".py", ".pyw"}:
            unsupported_paths.append(relative_path)
            continue
        supported_paths.append(relative_path)
        path = (root / relative_path).resolve()
        if root not in path.parents:
            parse_errors.append({"path": relative_path, "error": "path escapes project root"})
            continue
        try:
            if is_go:
                go_paths.append(relative_path)
                if len(go_paths) > MAX_GO_FILES or len(relative_path.encode("utf-8")) > 4096:
                    raise GoProviderError("Go file count or path length limit exceeded")
                with path.open("rb") as stream:
                    source_bytes = stream.read(MAX_GO_FILE_BYTES + 1)
                if len(source_bytes) > MAX_GO_FILE_BYTES:
                    raise GoProviderError("Go file byte limit exceeded")
                go_total_bytes += len(source_bytes)
                if go_total_bytes > MAX_GO_TOTAL_BYTES:
                    raise GoProviderError("Go Work Unit byte limit exceeded")
            else:
                source_bytes = path.read_bytes()
            if expected_digests is not None and hashlib.sha256(source_bytes).hexdigest() != expected_digests.get(relative_path):
                raise ModelError(f"snapshot drift detected while scanning hotspot source: {relative_path}")
            if is_go:
                go_sources[relative_path] = source_bytes
                continue
            source = source_bytes.decode("utf-8")
            tree = ast.parse(source, filename=relative_path)
        except (OSError, UnicodeError, SyntaxError, GoProviderError) as error:
            parse_errors.append({
                "path": relative_path,
                "error": f"{type(error).__name__}: {error}",
            })
            continue
        scanned_paths.append(relative_path)
        candidates.extend(_python_candidates(relative_path, source, tree))
    if go_sources:
        try:
            go_results = scan_go_bytes(go_sources, max_candidates=max_candidates)
        except GoProviderError as error:
            unavailable_paths.extend(sorted(go_sources))
            parse_errors.extend(
                {"path": path, "error": str(error)} for path in sorted(go_sources)
            )
        else:
            for result in go_results:
                relative_path = result["path"]
                if result.get("error"):
                    parse_errors.append({"path": relative_path, "error": result["error"]})
                    continue
                scanned_paths.append(relative_path)
                go_candidate_count += result["count"]
                for item in result["candidates"]:
                    rule_id, family, cwe, reason = _GO_RULES[item["api"]]
                    line, column = item["line"], item["column"]
                    candidate_id = "HOT-" + hashlib.sha256(
                        f"{relative_path}:{line}:{column}:{rule_id}".encode("utf-8")
                    ).hexdigest()[:16]
                    candidates.append({
                        "candidate_id": candidate_id, "rule_id": rule_id,
                        "language": "go", "family_hint": family, "cwe_hint": cwe,
                        "path": relative_path, "line": line, "column": column,
                        "evidence_ref": f"LOC-{relative_path}:{line}",
                        "api": item["api"], "reason": reason,
                    })
    candidate_count = sum(item["language"] == "python" for item in candidates) + go_candidate_count
    candidates.sort(key=lambda item: (
        item["path"], item["line"], item["column"], item["rule_id"],
    ))
    if not supported_paths:
        scan_status = "not_scanned"
    elif parse_errors and not scanned_paths:
        scan_status = "error"
    elif parse_errors:
        scan_status = "partial"
    else:
        scan_status = "completed"
    return {
        "schema_version": "1.0",
        "provider_status": "available" if scanned_paths else "provider_unavailable",
        "scan_status": scan_status,
        "provider_id": (
            GO_HOTSPOT_PROVIDER_ID if go_paths and all(Path(path).suffix.lower() == ".go" for path in supported_paths)
            else PYTHON_HOTSPOT_PROVIDER_ID
        ),
        "provider_ids": list(enabled_hotspot_provider_ids()) + ([GO_HOTSPOT_PROVIDER_ID] if enable_go else []),
        "supported_path_count": len(supported_paths),
        "scanned_path_count": len(scanned_paths),
        "unavailable_path_count": len(unavailable_paths),
        "unavailable_paths": sorted(unavailable_paths),
        "unsupported_path_count": len(unsupported_paths),
        "parse_error_count": len(parse_errors),
        "scanned_paths": sorted(scanned_paths),
        "unsupported_paths": unsupported_paths,
        "parse_errors": sorted(parse_errors, key=lambda item: item["path"]),
        "candidate_count": candidate_count,
        "included_count": min(len(candidates), max_candidates),
        "truncated": candidate_count > min(len(candidates), max_candidates),
        "candidates": candidates[:max_candidates],
        "limitations": [
            "API-name matching only; source-to-sink taint and reachability are not analyzed.",
            "Dynamic dispatch, reflective calls, generated code, and semantic aliases may be missed.",
            "A hotspot is a review lead, not a vulnerability verdict; no match is not evidence of safety.",
        ] + ([
            "Experimental Go parser requires a trusted optional POSIX Go toolchain; no target packages are built, imported, or executed.",
            "Go rules cover imported os/exec Command/CommandContext, io/io/ioutil ReadAll, and selected path/path/filepath functions only.",
            "Go dot imports, lexically shadowed package names, method calls, semantic aliases, and inter-file type/data flow are not resolved.",
            f"Go bounds: {MAX_GO_FILES} files, {MAX_GO_FILE_BYTES} bytes/file, {MAX_GO_TOTAL_BYTES} bytes/Work Unit, {MAX_GO_CANDIDATES} retained candidates; bound failures are errors, not clean scans.",
        ] if enable_go else []),
    }