"""Swift Package Manager manifest adapter."""

from __future__ import annotations

from pathlib import Path
import re

from .base import ParsedBuildDependency, ParsedBuildUnit


_PACKAGE_NAME = re.compile(r"\bPackage\s*\(\s*name\s*:\s*['\"]([^'\"]+)['\"]")
_LOCAL_PACKAGE = re.compile(r"\.package\s*\(\s*path\s*:\s*['\"]([^'\"]+)['\"]")


class SwiftBuildAdapter:
    manifest_names = frozenset({"Package.swift"})

    def parse(self, manifest_path: Path) -> ParsedBuildUnit | None:
        text = manifest_path.read_text(encoding="utf-8")
        name_match = _PACKAGE_NAME.search(text)
        if name_match is None:
            return None
        dependencies = []
        for match in _LOCAL_PACKAGE.finditer(text):
            local_path = match.group(1)
            dependencies.append(ParsedBuildDependency(
                name=Path(local_path).name,
                local_path=local_path,
                evidence=f"package.path:{local_path}",
            ))
        return ParsedBuildUnit(
            ecosystem="swiftpm",
            name=name_match.group(1),
            dependencies=tuple(sorted(dependencies, key=lambda item: item.name)),
        )