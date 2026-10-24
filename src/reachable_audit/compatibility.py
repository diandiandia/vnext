"""Runtime-surface legacy compatibility and bounded project-residue checks."""

from __future__ import annotations

import ast
from dataclasses import asdict, dataclass
from pathlib import Path
import re
from typing import Any, Sequence


_FORBIDDEN_MODULES = frozenset({
    "surface_mapper", "signature_lib", "signature_matcher", "workflow_export",
    "batch_verify", "evidence_ledger", "language_issue_matrix", "r2_guard",
    "fixminer", "precedent_library", "checklist_binder",
})
_FORBIDDEN_RUNTIME_STRINGS = (
    "verify_" + "queue.json", "r2_filter_" + "result.json",
    "input_" + "surface.json", "TOOLING" + "_VERSION",
)
_RESIDUE_PATTERNS = (
    ("cve_identifier", re.compile(r"CVE-\d{4}-\d{4,}", re.IGNORECASE)),
    ("vcs_reference_url", re.compile(r"https?://[^\s\"']+/(?:commit|pull|issues)/[^\s\"']+", re.IGNORECASE)),
    ("private_host_path", re.compile(r"(?<![\w.])/(?:root|srv|home/[^/\s\"'<>]+|Users/[^/\s\"'<>]+)(?=/|[\s\"'<>]|$)(?:/[^\s\"'<>]*)?")),
)


def _residue_findings(
    relative: str, text: str, forbidden_tokens: Sequence[str],
) -> list["CompatibilityFinding"]:
    findings = []
    lower = text.lower()
    for token in forbidden_tokens:
        offset = lower.find(token.lower())
        if offset >= 0:
            findings.append(CompatibilityFinding(
                relative, text[:offset].count("\n") + 1,
                "project_specific_runtime_knowledge", token.lower(),
            ))
    for rule, pattern in _RESIDUE_PATTERNS:
        match = pattern.search(text)
        if match:
            findings.append(CompatibilityFinding(
                relative, text[:match.start()].count("\n") + 1,
                "project_specific_runtime_knowledge", rule,
            ))
    return findings


@dataclass(frozen=True)
class CompatibilityFinding:
    path: str
    line: int
    rule: str
    value: str


def scan_runtime_compatibility(root: str | Path, forbidden_tokens: Sequence[str] = ()) -> dict[str, Any]:
    base = Path(root).resolve()
    findings: list[CompatibilityFinding] = []
    source_root = base / "src"
    for path in sorted(source_root.rglob("*.py")) if source_root.exists() else []:
        try:
            text = path.read_text(encoding="utf-8")
            tree = ast.parse(text, filename=str(path))
        except (OSError, SyntaxError, UnicodeError) as error:
            findings.append(CompatibilityFinding(
                path=path.relative_to(base).as_posix(),
                line=0,
                rule="runtime_source_parse_error",
                value=str(error),
            ))
            continue
        relative = path.relative_to(base).as_posix()
        for node in ast.walk(tree):
            module_names = []
            if isinstance(node, ast.Import):
                module_names = [item.name.split(".", 1)[0] for item in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                module_names = [node.module.split(".", 1)[0]]
            for module_name in module_names:
                if module_name in _FORBIDDEN_MODULES:
                    findings.append(CompatibilityFinding(
                        relative, node.lineno, "forbidden_legacy_import", module_name
                    ))
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                for token in _FORBIDDEN_RUNTIME_STRINGS:
                    if token in node.value:
                        findings.append(CompatibilityFinding(
                            relative, node.lineno, "forbidden_legacy_format", token
                        ))

    residue_report = scan_runtime_deproject(base, forbidden_tokens)
    findings.extend(CompatibilityFinding(**item) for item in residue_report["findings"])

    findings.sort(key=lambda item: (item.path, item.line, item.rule, item.value))
    return {
        "schema_version": "1.0",
        "runtime_root": str(base),
        "passed": not findings,
        "findings": [asdict(item) for item in findings],
        "scanned_python_files": residue_report["scanned_python_files"],
        "scanned_helper_files": residue_report["scanned_helper_files"],
        "scanned_knowledge_files": residue_report["scanned_knowledge_files"],
        "scanned_prompt_files": residue_report["scanned_prompt_files"],
    }


def scan_runtime_deproject(root: str | Path, forbidden_tokens: Sequence[str] = ()) -> dict[str, Any]:
    """Scan runtime source, the main prompt, and eligible knowledge for bounded residue."""
    base = Path(root).resolve()
    knowledge_root = base / "knowledge"
    runtime_roots = (
        knowledge_root / "profiles",
        knowledge_root / "cards",
        knowledge_root / "portfolio.json",
        knowledge_root / "provenance.json",
    )
    findings: list[CompatibilityFinding] = []
    paths = []
    for candidate in runtime_roots:
        if candidate.is_file():
            paths.append(candidate)
        elif candidate.is_dir():
            paths.extend(candidate.rglob("*.json"))
    knowledge_count = len(paths)
    source_paths = list((base / "src").rglob("*.py"))
    helper_paths = [
        path for path in (base / "src").rglob("*")
        if path.is_file() and path.suffix in {".go", ".java"}
    ]
    prompt_paths = [base / "SKILL.md"] if (base / "SKILL.md").is_file() else []
    paths.extend(source_paths)
    paths.extend(helper_paths)
    paths.extend(prompt_paths)
    for path in sorted(paths):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            findings.append(CompatibilityFinding(
                path.relative_to(base).as_posix(), 0,
                "runtime_residue_read_error", str(error),
            ))
            continue
        findings.extend(_residue_findings(path.relative_to(base).as_posix(), text, forbidden_tokens))
    findings.sort(key=lambda item: (item.path, item.line, item.rule, item.value))
    return {
        "schema_version": "1.0",
        "passed": not findings,
        "findings": [asdict(item) for item in findings],
        "scanned_knowledge_files": knowledge_count,
        "scanned_python_files": len(source_paths),
        "scanned_helper_files": len(helper_paths),
        "scanned_prompt_files": len(prompt_paths),
    }