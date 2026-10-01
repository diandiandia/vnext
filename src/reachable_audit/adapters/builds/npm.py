"""npm package metadata adapter."""

from __future__ import annotations

import json
from pathlib import Path

from .base import ParsedBuildDependency, ParsedBuildUnit


class NpmBuildAdapter:
    manifest_names = frozenset({"package.json"})

    def parse(self, manifest_path: Path) -> ParsedBuildUnit | None:
        value = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or not isinstance(value.get("name"), str):
            return None
        dependencies: dict[str, ParsedBuildDependency] = {}
        for section in (
            "dependencies", "optionalDependencies", "peerDependencies", "devDependencies"
        ):
            entries = value.get(section, {})
            if not isinstance(entries, dict):
                continue
            for name, version in entries.items():
                if not isinstance(name, str) or not isinstance(version, str):
                    continue
                local_path = None
                for prefix in ("file:", "link:"):
                    if version.startswith(prefix):
                        local_path = version.removeprefix(prefix)
                dependencies[name] = ParsedBuildDependency(
                    name=name,
                    local_path=local_path,
                    evidence=f"{section}.{name}",
                )
        return ParsedBuildUnit(
            ecosystem="npm",
            name=value["name"],
            dependencies=tuple(sorted(
                dependencies.values(), key=lambda item: (item.name, item.evidence)
            )),
        )