"""Go module build metadata adapter."""

from __future__ import annotations

from pathlib import Path
import re

from .base import ParsedBuildDependency, ParsedBuildUnit


_MODULE = re.compile(r"^module\s+(\S+)")
_REQUIRE = re.compile(r"^require\s+(\S+)\s+\S+")
_REPLACE = re.compile(r"^replace\s+(\S+)(?:\s+\S+)?\s+=>\s+(\S+)")


class GoBuildAdapter:
    manifest_names = frozenset({"go.mod"})

    def parse(self, manifest_path: Path) -> ParsedBuildUnit | None:
        module_name = None
        requirements: list[tuple[str, str]] = []
        replacements: dict[str, str] = {}
        in_require_block = False
        for line_number, raw_line in enumerate(
            manifest_path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            line = raw_line.split("//", 1)[0].strip()
            if not line:
                continue
            module_match = _MODULE.match(line)
            if module_match:
                module_name = module_match.group(1)
                continue
            if line == "require (":
                in_require_block = True
                continue
            if in_require_block and line == ")":
                in_require_block = False
                continue
            if in_require_block:
                parts = line.split()
                if len(parts) >= 2:
                    requirements.append((parts[0], f"require:{line_number}"))
                continue
            require_match = _REQUIRE.match(line)
            if require_match:
                requirements.append((require_match.group(1), f"require:{line_number}"))
                continue
            replace_match = _REPLACE.match(line)
            if replace_match:
                replacements[replace_match.group(1)] = replace_match.group(2)
        if module_name is None:
            return None
        dependencies = tuple(
            ParsedBuildDependency(
                name=name,
                local_path=replacements.get(name) if replacements.get(name, "").startswith((".", "/")) else None,
                evidence=evidence,
            )
            for name, evidence in sorted(requirements)
        )
        return ParsedBuildUnit(ecosystem="go", name=module_name, dependencies=dependencies)