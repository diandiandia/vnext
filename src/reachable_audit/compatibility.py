"""Runtime scan for forbidden v2/v3 compatibility imports and queue formats."""

from __future__ import annotations

import ast
from dataclasses import asdict, dataclass
from pathlib import Path
import re
from typing import Any


_FORBIDDEN_MODULES = frozenset({
    "surface_mapper", "signature_lib", "signature_matcher", "workflow_export",
    "batch_verify", "evidence_ledger", "language_issue_matrix", "r2_guard",
    "fixminer", "precedent_library", "checklist_binder",
})
_FORBIDDEN_RUNTIME_STRINGS = (
    "verify_" + "queue.json", "r2_filter_" + "result.json",
    "input_" + "surface.json", "TOOLING" + "_VERSION",
)
_PROJECT_TOKENS = (
    "gpac", "freetype", "s2n-tls", "nghttp2", "libarchive", "frameworks/av",
    "nacos", "tomcat", "mbedtls", "jsrsasign", "puma", "elasticsearch",
    "pillow", "flutter", "protobuf", "zookeeper", "kafka", "shardingsphere",
    "aiohttp", "gson", "libpng", "libjpeg", "libvpx", "aom", "media3",
    "quic-go", "pyjwt", "quarkus", "phpseclib", "cosign", "etcd", "sinatra",
    "lighttpd", "django", "nestjs", "ktor", "actix", "webrick", "usb-storage",
    "dummy_hcd", "nciemp", "quickjs", "qjs", "bjson", "awstats", "maintainwise",
    "swr-v3.11-004", "newresponserecorder", "matchquery.matchwitherror",
)


@dataclass(frozen=True)
class CompatibilityFinding:
    path: str
    line: int
    rule: str
    value: str


def scan_runtime_compatibility(root: str | Path) -> dict[str, Any]:
    base = Path(root).resolve()
    findings: list[CompatibilityFinding] = []
    source_root = base / "src"
    knowledge_root = base / "knowledge"
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

    if knowledge_root.exists():
        for path in sorted(knowledge_root.rglob("*.json")):
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as error:
                findings.append(CompatibilityFinding(
                    path.relative_to(base).as_posix(), 0,
                    "runtime_knowledge_read_error", str(error),
                ))
                continue
            lower = text.lower()
            for token in _PROJECT_TOKENS:
                if token in lower:
                    line = text[:lower.index(token)].count("\n") + 1
                    findings.append(CompatibilityFinding(
                        path.relative_to(base).as_posix(), line,
                        "project_specific_runtime_knowledge", token,
                    ))

    findings.sort(key=lambda item: (item.path, item.line, item.rule, item.value))
    return {
        "schema_version": "1.0",
        "runtime_root": str(base),
        "passed": not findings,
        "findings": [asdict(item) for item in findings],
        "scanned_python_files": len(list(source_root.rglob("*.py"))) if source_root.exists() else 0,
        "scanned_knowledge_files": len(list(knowledge_root.rglob("*.json"))) if knowledge_root.exists() else 0,
    }


def scan_runtime_deproject(root: str | Path) -> dict[str, Any]:
    """Scan runtime-eligible knowledge for known project-specific residue."""
    base = Path(root).resolve()
    knowledge_root = base / "knowledge"
    runtime_roots = (
        knowledge_root / "profiles",
        knowledge_root / "cards",
        knowledge_root / "portfolio.json",
        knowledge_root / "provenance.json",
    )
    findings: list[CompatibilityFinding] = []
    scanned = 0
    paths = []
    for candidate in runtime_roots:
        if candidate.is_file():
            paths.append(candidate)
        elif candidate.is_dir():
            paths.extend(candidate.rglob("*.json"))
    for path in sorted(paths):
        scanned += 1
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            findings.append(CompatibilityFinding(
                path.relative_to(base).as_posix(), 0,
                "runtime_knowledge_read_error", str(error),
            ))
            continue
        lower = text.lower()
        for token in _PROJECT_TOKENS:
            offset = lower.find(token)
            if offset >= 0:
                findings.append(CompatibilityFinding(
                    path.relative_to(base).as_posix(),
                    text[:offset].count("\n") + 1,
                    "project_specific_runtime_knowledge", token,
                ))
    findings.sort(key=lambda item: (item.path, item.line, item.rule, item.value))
    return {
        "schema_version": "1.0",
        "passed": not findings,
        "findings": [asdict(item) for item in findings],
        "scanned_knowledge_files": scanned,
    }