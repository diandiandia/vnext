"""Bundler Gemfile path and local gemspec adapter."""

from __future__ import annotations

from pathlib import Path
import re

from .base import ParsedBuildDependency, ParsedBuildUnit


_PATH = re.compile(r"^\s*path\s+[\"']([^\"']+)[\"']", re.MULTILINE)
_GEMSPEC = re.compile(r"^\s*gemspec\s+path:\s*[\"']([^\"']+)[\"']", re.MULTILINE)


class BundlerBuildAdapter:
    manifest_names = frozenset({"Gemfile"})
    manifest_suffixes = frozenset()

    def parse(self, manifest_path: Path) -> ParsedBuildUnit:
        text = manifest_path.read_text(encoding="utf-8", errors="replace")
        values = [(match.group(1), "path") for match in _PATH.finditer(text)]
        values.extend((match.group(1), "gemspec") for match in _GEMSPEC.finditer(text))
        dependencies = tuple(
            ParsedBuildDependency(
                name=path.rstrip("/\\").replace("/", "::"),
                local_path=path,
                evidence=f"{kind}:{path}",
            )
            for path, kind in values
        )
        return ParsedBuildUnit("bundler", manifest_path.parent.name, dependencies)