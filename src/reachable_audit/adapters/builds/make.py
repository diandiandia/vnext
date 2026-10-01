"""Make directory dependency adapter."""

from __future__ import annotations

from pathlib import Path
import re

from .base import ParsedBuildDependency, ParsedBuildUnit


_SUBDIRS = re.compile(r"^\s*(?:SUBDIRS|subdirs)\s*[:?+]?=\s*(.*?)\s*(?:#.*)?$", re.MULTILINE)
_INCLUDE = re.compile(r"^\s*-?include\s+([^\s#]+)", re.MULTILINE)


class MakeBuildAdapter:
    manifest_names = frozenset({"Makefile", "makefile", "GNUmakefile"})
    manifest_suffixes = frozenset()

    def parse(self, manifest_path: Path) -> ParsedBuildUnit:
        text = manifest_path.read_text(encoding="utf-8", errors="replace")
        values = [
            (item, "SUBDIRS")
            for match in _SUBDIRS.finditer(text)
            for item in match.group(1).split()
        ]
        values.extend((match.group(1), "include") for match in _INCLUDE.finditer(text))
        dependencies = tuple(
            ParsedBuildDependency(
                name=path.rstrip("/\\").replace("/", "::"),
                local_path=path,
                evidence=f"{kind}:{path}",
            )
            for path, kind in values
            if not path.startswith("$(") and "$" not in path and not path.startswith("-")
        )
        return ParsedBuildUnit(
            ecosystem="make",
            name=manifest_path.parent.name or "root",
            dependencies=dependencies,
        )