"""CMake project and add_subdirectory adapter."""

from __future__ import annotations

from pathlib import Path
import re

from .base import ParsedBuildDependency, ParsedBuildUnit


_PROJECT = re.compile(r"^\s*project\s*\(\s*([\w.+-]+)", re.IGNORECASE | re.MULTILINE)
_SUBDIR = re.compile(r"^\s*add_subdirectory\s*\(\s*[\"']?([^\s)\"']+)", re.IGNORECASE | re.MULTILINE)


class CMakeBuildAdapter:
    manifest_names = frozenset({"CMakeLists.txt"})
    manifest_suffixes = frozenset()

    def parse(self, manifest_path: Path) -> ParsedBuildUnit:
        text = manifest_path.read_text(encoding="utf-8", errors="replace")
        project = _PROJECT.search(text)
        dependencies = tuple(
            ParsedBuildDependency(
                name=path.rstrip("/\\").replace("/", "::"),
                local_path=path,
                evidence=f"add_subdirectory:{match.start()}",
            )
            for match in _SUBDIR.finditer(text)
            for path in [match.group(1)]
        )
        return ParsedBuildUnit(
            ecosystem="cmake",
            name=project.group(1) if project else manifest_path.parent.name,
            dependencies=dependencies,
        )