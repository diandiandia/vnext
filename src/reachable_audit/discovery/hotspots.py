"""Bounded language-specific API hotspots for Agent review."""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path
from typing import Any


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


def scan_work_unit_hotspots(
    project_root: str | Path,
    source_files: list[str] | tuple[str, ...],
    *,
    max_candidates: int = _MAX_CANDIDATES,
) -> dict[str, Any]:
    """Scan supported Python files and report bounded candidate locations and coverage."""
    if max_candidates < 1:
        raise ValueError("max_candidates must be positive")
    root = Path(project_root).resolve()
    python_paths = []
    unsupported_paths = []
    parse_errors = []
    candidates = []
    for relative_path in sorted(set(str(item) for item in source_files)):
        if Path(relative_path).suffix.lower() not in {".py", ".pyw"}:
            unsupported_paths.append(relative_path)
            continue
        path = (root / relative_path).resolve()
        if root not in path.parents:
            parse_errors.append({"path": relative_path, "error": "path escapes project root"})
            continue
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=relative_path)
        except (OSError, UnicodeError, SyntaxError) as error:
            parse_errors.append({
                "path": relative_path,
                "error": f"{type(error).__name__}: {error}",
            })
            continue
        python_paths.append(relative_path)
        candidates.extend(_python_candidates(relative_path, source, tree))
    candidates.sort(key=lambda item: (
        item["path"], item["line"], item["column"], item["rule_id"],
    ))
    return {
        "schema_version": "1.0",
        "provider_status": "available" if python_paths else "provider_unavailable",
        "provider_id": "python-ast-hotspots-v1",
        "scanned_paths": python_paths,
        "unsupported_paths": unsupported_paths,
        "parse_errors": parse_errors,
        "candidate_count": len(candidates),
        "included_count": min(len(candidates), max_candidates),
        "truncated": len(candidates) > max_candidates,
        "candidates": candidates[:max_candidates],
        "limitations": [
            "API-name matching only; source-to-sink taint and reachability are not analyzed.",
            "Dynamic dispatch, reflective calls, generated code, and semantic aliases may be missed.",
            "A hotspot is a review lead, not a vulnerability verdict; no match is not evidence of safety.",
        ],
    }