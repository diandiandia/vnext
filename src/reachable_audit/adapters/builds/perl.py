"""Perl distribution metadata adapter for Makefile.PL and cpanfile."""

from __future__ import annotations

from pathlib import Path
import re

from .base import ParsedBuildDependency, ParsedBuildUnit


_REQUIRES = re.compile(r"^\s*requires\s*[\"']([^\"']+)[\"']", re.MULTILINE)
_PREREQ_PM = re.compile(r"['\"]([^'\"]+)['\"]\s*=>\s*['\"][^'\"]+['\"]")


class PerlBuildAdapter:
    manifest_names = frozenset({"cpanfile", "Makefile.PL"})
    manifest_suffixes = frozenset()

    def parse(self, manifest_path: Path) -> ParsedBuildUnit:
        text = manifest_path.read_text(encoding="utf-8", errors="replace")
        names = set(_REQUIRES.findall(text)) | set(_PREREQ_PM.findall(text))
        dependencies = tuple(
            ParsedBuildDependency(name=name, local_path=None, evidence=f"dependency:{name}")
            for name in sorted(names)
        )
        return ParsedBuildUnit("perl", manifest_path.parent.name, dependencies)