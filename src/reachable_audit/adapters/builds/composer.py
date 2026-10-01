"""Composer package and local path repository adapter."""

from __future__ import annotations

import json
from pathlib import Path

from .base import ParsedBuildDependency, ParsedBuildUnit


class ComposerBuildAdapter:
    manifest_names = frozenset({"composer.json"})
    manifest_suffixes = frozenset()

    def parse(self, manifest_path: Path) -> ParsedBuildUnit:
        value = json.loads(manifest_path.read_text(encoding="utf-8"))
        dependencies = []
        for repository in value.get("repositories", []):
            if repository.get("type") == "path" and repository.get("url"):
                path = str(repository["url"])
                dependencies.append(ParsedBuildDependency(
                    name=path.rstrip("/").replace("/", "::"),
                    local_path=path,
                    evidence=f"path-repository:{path}",
                ))
        name = str(value.get("name") or manifest_path.parent.name)
        return ParsedBuildUnit("composer", name, tuple(dependencies))