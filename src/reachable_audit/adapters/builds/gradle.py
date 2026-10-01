"""Conservative Gradle project-dependency adapter."""

from __future__ import annotations

from pathlib import Path
import re

from .base import ParsedBuildDependency, ParsedBuildUnit


_PROJECT = re.compile(
    r"\bproject\s*\(\s*(?:path\s*[:=]\s*)?['\"]:([^'\"]+)['\"]\s*\)"
)


class GradleBuildAdapter:
    manifest_names = frozenset({"build.gradle", "build.gradle.kts"})

    def parse(self, manifest_path: Path) -> ParsedBuildUnit | None:
        text = manifest_path.read_text(encoding="utf-8")
        name = manifest_path.parent.name
        if not name:
            name = "root"
        dependencies = {
            match.group(1).split(":")[-1]: ParsedBuildDependency(
                name=match.group(1).split(":")[-1],
                local_path=None,
                evidence=f"project:{match.group(1)}",
            )
            for match in _PROJECT.finditer(text)
        }
        return ParsedBuildUnit(
            ecosystem="gradle",
            name=name,
            dependencies=tuple(sorted(dependencies.values(), key=lambda item: item.name)),
        )