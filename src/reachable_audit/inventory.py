"""Streaming source inventory and build-boundary component discovery."""

from __future__ import annotations

from collections import defaultdict
import hashlib
import os
from pathlib import Path, PurePosixPath
import re

from .adapters.languages import detect_language
from .plan_models import Component, ProjectInventory, SourceFile


BUILD_MANIFESTS = frozenset({
    "BUILD", "BUILD.bazel", "BUILD.gn", ".gn", "CMakeLists.txt", "Cargo.toml", "Package.swift",
    "Gemfile", "Makefile", "GNUmakefile", "Makefile.PL", "WORKSPACE",
    "build.gradle", "build.gradle.kts", "build.sbt", "composer.json", "go.mod",
    "package.json", "pom.xml", "pyproject.toml", "setup.cfg", "cpanfile",
})
BUILD_MANIFEST_SUFFIXES = frozenset({".csproj", ".sln"})
NON_SOURCE_TEXT_SUFFIXES = frozenset({
    ".md", ".markdown", ".rst", ".txt", ".json", ".json5", ".jsonl",
    ".yaml", ".yml", ".toml", ".xml", ".html", ".htm", ".css", ".scss",
    ".sass", ".less", ".csv", ".tsv", ".ini", ".cfg", ".conf", ".properties",
    ".lock", ".map", ".svg",
})
SOURCE_LANGUAGES = {
    ".pl": ("perl", "recognized_unsupported"),
    ".pm": ("perl", "recognized_unsupported"),
    ".ps1": ("powershell", "recognized_unsupported"),
    ".psm1": ("powershell", "recognized_unsupported"),
    ".m": ("objective-c", "recognized_unsupported"),
    ".mm": ("objective-c", "recognized_unsupported"),
    ".proto": ("protobuf", "recognized_unsupported"),
    ".thrift": ("thrift", "recognized_unsupported"),
    ".idl": ("idl", "recognized_unsupported"),
    ".sql": ("sql", "recognized_unsupported"),
}
SKIP_DIRECTORIES = frozenset({
    ".audit_results", ".audit_vnext", ".git", ".hg", ".mypy_cache",
    ".pytest_cache", ".svn", ".tox", ".venv", "__pycache__", "node_modules", "target",
})
_UNKNOWN_SOURCE_HINT = re.compile(
    r"^\s*(?:#!|#\s*include\b|import\s+|from\s+\S+\s+import\s+|"
    r"package\s+\w+|using\s+\w+|func\s+\w+|fn\s+\w+|def\s+\w+|"
    r"class\s+\w+|namespace\s+\w+|module\s+\w+|export\s+(?:default|function|class)|"
    r"<\?php|require\s*[('])",
    re.MULTILINE,
)


def _stable_id(prefix: str, value: str) -> str:
    return f"{prefix}-{hashlib.sha256(value.encode('utf-8')).hexdigest()[:16]}"


def _relative(root: Path, path: Path) -> str:
    value = path.relative_to(root).as_posix()
    return value or "."


def _worktree_size_bytes(root: Path) -> int:
    total = 0
    for directory, directories, files in os.walk(root, topdown=True, followlinks=False):
        directories[:] = [name for name in directories if name != ".audit_vnext"]
        for filename in files:
            path = Path(directory) / filename
            try:
                total += path.stat(follow_symlinks=False).st_size
            except OSError:
                continue
    return total


def _contains(component_root: str, source_path: str) -> bool:
    return component_root == "." or source_path == component_root or source_path.startswith(component_root + "/")


def _unknown_source_file(path: Path) -> bool:
    try:
        prefix = path.open("rb").read(4096)
        sample = prefix.decode("utf-8", errors="strict")
    except (OSError, UnicodeDecodeError):
        return False
    return bool(_UNKNOWN_SOURCE_HINT.search(sample))


def build_inventory(target_root: str | Path, snapshot_id: str) -> ProjectInventory:
    root = Path(target_root).resolve()
    if not root.is_dir():
        raise ValueError(f"target root is not a directory: {root}")

    source_candidates: list[tuple[str, str, str]] = []
    manifests_by_root: dict[str, list[str]] = defaultdict(list)
    skipped: set[str] = set()
    for directory, directories, files in os.walk(root, topdown=True, followlinks=False):
        directory_path = Path(directory)
        kept_directories = []
        for name in directories:
            if name in SKIP_DIRECTORIES:
                skipped.add(_relative(root, directory_path / name))
            else:
                kept_directories.append(name)
        directories[:] = kept_directories
        relative_directory = _relative(root, directory_path)
        for filename in files:
            relative_file = _relative(root, directory_path / filename)
            if filename in BUILD_MANIFESTS or Path(filename).suffix.lower() in BUILD_MANIFEST_SUFFIXES:
                manifests_by_root[relative_directory].append(relative_file)
            detected = detect_language(relative_file)
            if detected is None:
                detected = SOURCE_LANGUAGES.get(Path(filename).suffix.lower())
            if (
                detected is None
                and filename not in BUILD_MANIFESTS
                and Path(filename).suffix.lower() not in NON_SOURCE_TEXT_SUFFIXES
                and _unknown_source_file(directory_path / filename)
            ):
                detected = ("unknown", "unknown")
            if detected is not None:
                source_candidates.append((relative_file, detected[0], detected[1]))

    component_roots = set(manifests_by_root) | {"."}
    ordered_roots = sorted(
        component_roots,
        key=lambda value: (len(PurePosixPath(value).parts), value),
        reverse=True,
    )
    component_id_by_root = {
        component_root: _stable_id("COMP", component_root) for component_root in component_roots
    }
    owned_files: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for source_path, language, language_status in source_candidates:
        owner_root = next(root for root in ordered_roots if _contains(root, source_path))
        owned_files[owner_root].append((source_path, language, language_status))

    represented_roots = set(owned_files) | set(manifests_by_root)
    components = []
    source_files = []
    for component_root in sorted(represented_roots):
        component_files = sorted(owned_files[component_root])
        component_id = component_id_by_root[component_root]
        components.append(Component(
            component_id=component_id,
            root=component_root,
            build_manifests=tuple(sorted(manifests_by_root.get(component_root, []))),
            languages=tuple(sorted({language for _, language, _ in component_files})),
            source_file_count=len(component_files),
        ))
        source_files.extend(
            SourceFile(
                path=path,
                language=language,
                component_id=component_id,
                language_status=language_status,
            )
            for path, language, language_status in component_files
        )
    return ProjectInventory(
        schema_version="1.0",
        snapshot_id=snapshot_id,
        components=tuple(components),
        source_files=tuple(sorted(source_files, key=lambda item: item.path)),
        skipped_directories=tuple(sorted(skipped)),
        repository_size_bytes=_worktree_size_bytes(root),
    )
