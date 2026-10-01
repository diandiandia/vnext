"""Cargo build metadata adapter."""

from __future__ import annotations

from pathlib import Path
import tomllib
from typing import Any

from .base import ParsedBuildDependency, ParsedBuildUnit


def _dependency_tables(value: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    tables = []
    for section in ("dependencies", "dev-dependencies", "build-dependencies"):
        table = value.get(section)
        if isinstance(table, dict):
            tables.append((section, table))
    target = value.get("target")
    if isinstance(target, dict):
        for target_name, target_value in target.items():
            if not isinstance(target_value, dict):
                continue
            for section in ("dependencies", "dev-dependencies", "build-dependencies"):
                table = target_value.get(section)
                if isinstance(table, dict):
                    tables.append((f"target.{target_name}.{section}", table))
    return tables


class CargoBuildAdapter:
    manifest_names = frozenset({"Cargo.toml"})

    def parse(self, manifest_path: Path) -> ParsedBuildUnit | None:
        value = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
        package = value.get("package")
        if not isinstance(package, dict) or not isinstance(package.get("name"), str):
            return None
        dependencies = []
        for section, table in _dependency_tables(value):
            for dependency_key, dependency_value in table.items():
                name = dependency_key
                local_path = None
                if isinstance(dependency_value, dict):
                    if isinstance(dependency_value.get("package"), str):
                        name = dependency_value["package"]
                    if isinstance(dependency_value.get("path"), str):
                        local_path = dependency_value["path"]
                dependencies.append(ParsedBuildDependency(
                    name=name,
                    local_path=local_path,
                    evidence=f"{section}.{dependency_key}",
                ))
        return ParsedBuildUnit(
            ecosystem="cargo",
            name=package["name"],
            dependencies=tuple(sorted(dependencies, key=lambda item: (item.name, item.evidence))),
        )