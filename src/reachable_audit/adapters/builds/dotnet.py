"""MSBuild project and solution local-reference adapter."""

from __future__ import annotations

from pathlib import Path
import re
import xml.etree.ElementTree as ET

from .base import ParsedBuildDependency, ParsedBuildUnit


_PROJECT_REFERENCE = re.compile(r"Project\([^\n]+?\)\s*=\s*\"([^\"]+)\"\s*,\s*\"([^\"]+\.csproj)\"", re.IGNORECASE)


class DotnetBuildAdapter:
    manifest_names = frozenset()
    manifest_suffixes = frozenset({".sln", ".csproj"})

    def parse(self, manifest_path: Path) -> ParsedBuildUnit:
        suffix = manifest_path.suffix.lower()
        if suffix == ".sln":
            text = manifest_path.read_text(encoding="utf-8", errors="replace")
            dependencies = tuple(
                ParsedBuildDependency(
                    name=name,
                    local_path=Path(project_path).parent.as_posix(),
                    evidence=f"solution-project:{project_path}",
                )
                for name, project_path in _PROJECT_REFERENCE.findall(text)
            )
            return ParsedBuildUnit(
                ecosystem="dotnet",
                name=manifest_path.stem,
                dependencies=dependencies,
            )
        tree = ET.parse(manifest_path)
        dependencies = []
        for element in tree.iter():
            if element.tag.rsplit("}", 1)[-1] != "ProjectReference":
                continue
            include = element.attrib.get("Include", "")
            if include:
                dependencies.append(ParsedBuildDependency(
                    name=Path(include).stem,
                    local_path=Path(include).parent.as_posix(),
                    evidence=f"ProjectReference:{include}",
                ))
        return ParsedBuildUnit(
            ecosystem="dotnet",
            name=manifest_path.stem,
            dependencies=tuple(dependencies),
        )