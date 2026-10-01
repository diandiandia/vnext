"""Normalized build-adapter contract."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class ParsedBuildDependency:
    name: str
    local_path: str | None
    evidence: str


@dataclass(frozen=True)
class ParsedBuildUnit:
    ecosystem: str
    name: str
    dependencies: tuple[ParsedBuildDependency, ...]


class BuildAdapter(Protocol):
    manifest_names: frozenset[str]
    manifest_suffixes: frozenset[str]

    def parse(self, manifest_path: Path) -> ParsedBuildUnit | None: ...