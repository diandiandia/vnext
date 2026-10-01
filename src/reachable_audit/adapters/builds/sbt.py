"""sbt local ProjectRef dependency adapter."""

from __future__ import annotations

from pathlib import Path
import re

from .base import ParsedBuildDependency, ParsedBuildUnit


_PROJECT_REF = re.compile(
    r"ProjectRef\s*\(\s*file\s*\(\s*[\"']([^\"']+)[\"']\s*\)\s*,\s*[\"']([^\"']+)[\"']",
    re.MULTILINE,
)


class SbtBuildAdapter:
    manifest_names = frozenset({"build.sbt"})
    manifest_suffixes = frozenset()

    def parse(self, manifest_path: Path) -> ParsedBuildUnit:
        text = manifest_path.read_text(encoding="utf-8", errors="replace")
        dependencies = tuple(
            ParsedBuildDependency(
                name=project,
                local_path=path,
                evidence=f"ProjectRef:{path}:{project}",
            )
            for path, project in _PROJECT_REF.findall(text)
        )
        return ParsedBuildUnit("sbt", manifest_path.parent.name, dependencies)