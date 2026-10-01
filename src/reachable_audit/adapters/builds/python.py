"""PEP 621 build metadata adapter."""

from __future__ import annotations

from pathlib import Path
import re
import tomllib

from .base import ParsedBuildDependency, ParsedBuildUnit


_DEPENDENCY_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")
_FILE_REFERENCE = re.compile(r"@\s*file:(?://)?([^\s;]+)", re.IGNORECASE)


class PythonBuildAdapter:
    manifest_names = frozenset({"pyproject.toml"})

    def parse(self, manifest_path: Path) -> ParsedBuildUnit | None:
        value = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
        project = value.get("project")
        if not isinstance(project, dict) or not isinstance(project.get("name"), str):
            return None
        dependencies = []
        raw_dependencies = project.get("dependencies", [])
        if isinstance(raw_dependencies, list):
            for index, raw_dependency in enumerate(raw_dependencies):
                if not isinstance(raw_dependency, str):
                    continue
                name_match = _DEPENDENCY_NAME.match(raw_dependency)
                if not name_match:
                    continue
                path_match = _FILE_REFERENCE.search(raw_dependency)
                dependencies.append(ParsedBuildDependency(
                    name=name_match.group(1),
                    local_path=path_match.group(1) if path_match else None,
                    evidence=f"project.dependencies[{index}]",
                ))

        uv_sources = value.get("tool", {}).get("uv", {}).get("sources", {})
        if isinstance(uv_sources, dict):
            by_name = {dependency.name: dependency for dependency in dependencies}
            for name, source in uv_sources.items():
                if isinstance(name, str) and isinstance(source, dict) and isinstance(source.get("path"), str):
                    by_name[name] = ParsedBuildDependency(
                        name=name,
                        local_path=source["path"],
                        evidence=f"tool.uv.sources.{name}.path",
                    )
            dependencies = list(by_name.values())
        return ParsedBuildUnit(
            ecosystem="python",
            name=project["name"],
            dependencies=tuple(sorted(dependencies, key=lambda item: (item.name, item.evidence))),
        )