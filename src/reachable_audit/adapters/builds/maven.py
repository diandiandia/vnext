"""Maven POM adapter using the standard XML parser."""

from __future__ import annotations

from pathlib import Path
import xml.etree.ElementTree as ET

from .base import ParsedBuildDependency, ParsedBuildUnit


def _children(element: ET.Element, name: str) -> list[ET.Element]:
    return [child for child in element if child.tag.rsplit("}", 1)[-1] == name]


def _child_text(element: ET.Element, name: str) -> str | None:
    children = _children(element, name)
    if not children or children[0].text is None:
        return None
    return children[0].text.strip()


class MavenBuildAdapter:
    manifest_names = frozenset({"pom.xml"})

    def parse(self, manifest_path: Path) -> ParsedBuildUnit | None:
        project = ET.fromstring(manifest_path.read_text(encoding="utf-8"))
        artifact_id = _child_text(project, "artifactId")
        if not artifact_id:
            return None
        dependencies = []
        for modules in _children(project, "modules"):
            for module in _children(modules, "module"):
                if module.text and module.text.strip():
                    local_path = module.text.strip()
                    dependencies.append(ParsedBuildDependency(
                        name=Path(local_path).name,
                        local_path=local_path,
                        evidence=f"modules.module:{local_path}",
                    ))
        for dependencies_element in _children(project, "dependencies"):
            for dependency in _children(dependencies_element, "dependency"):
                dependency_id = _child_text(dependency, "artifactId")
                if dependency_id:
                    dependencies.append(ParsedBuildDependency(
                        name=dependency_id,
                        local_path=None,
                        evidence=f"dependencies.dependency:{dependency_id}",
                    ))
        return ParsedBuildUnit(
            ecosystem="maven",
            name=artifact_id,
            dependencies=tuple(sorted(
                dependencies, key=lambda item: (item.name, item.evidence)
            )),
        )