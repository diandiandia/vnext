"""Build-adapter orchestration and repository-local component graph resolution."""

from __future__ import annotations

from dataclasses import asdict
import hashlib
from pathlib import Path, PurePosixPath

from .adapters.languages import LANGUAGE_ADAPTERS
from .adapters.builds import BUILD_ADAPTERS, BuildAdapter
from .plan_models import (
    BoundaryEdge,
    BuildDependency,
    BuildUnit,
    ComponentGraph,
    GraphDiagnostic,
    ProjectInventory,
)


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\x00".join(parts).encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def _normalized_name(ecosystem: str, name: str) -> str:
    normalized = name.casefold()
    if ecosystem in {"python", "cargo"}:
        normalized = normalized.replace("_", "-").replace(".", "-")
    return normalized


def _component_for_path(
    relative_path: str, component_by_root: dict[str, str]
) -> str | None:
    matches = [
        (root, component_id)
        for root, component_id in component_by_root.items()
        if root == "." or relative_path == root or relative_path.startswith(root + "/")
    ]
    if not matches:
        return None
    return max(matches, key=lambda item: len(PurePosixPath(item[0]).parts))[1]


def _adapter_for_manifest(filename: str) -> BuildAdapter | None:
    return next(
        (
            adapter for adapter in BUILD_ADAPTERS
            if filename in adapter.manifest_names
            or Path(filename).suffix.lower() in getattr(adapter, "manifest_suffixes", frozenset())
        ),
        None,
    )


def build_component_graph(
    target_root: str | Path, inventory: ProjectInventory
) -> ComponentGraph:
    root = Path(target_root).resolve()
    component_by_root = {
        component.root: component.component_id for component in inventory.components
    }
    languages_by_component = {
        component.component_id: component.languages for component in inventory.components
    }
    units = []
    diagnostics = []
    for component in inventory.components:
        for manifest_path in component.build_manifests:
            adapter = _adapter_for_manifest(Path(manifest_path).name)
            if adapter is None:
                diagnostics.append(GraphDiagnostic(
                    manifest_path=manifest_path,
                    code="UNSUPPORTED_BUILD_MANIFEST",
                    detail="no Build Adapter is registered for this recognized manifest",
                ))
                continue
            try:
                parsed = adapter.parse(root / manifest_path)
            except (OSError, UnicodeError, ValueError) as error:
                diagnostics.append(GraphDiagnostic(
                    manifest_path=manifest_path,
                    code="MANIFEST_PARSE_ERROR",
                    detail=str(error),
                ))
                continue
            if parsed is None:
                diagnostics.append(GraphDiagnostic(
                    manifest_path=manifest_path,
                    code="BUILD_UNIT_UNRESOLVED",
                    detail="manifest does not declare an adapter-supported build unit",
                ))
                continue
            units.append(BuildUnit(
                build_unit_id=_stable_id(
                    "BU", inventory.snapshot_id, parsed.ecosystem, parsed.name, manifest_path
                ),
                component_id=component.component_id,
                manifest_path=manifest_path,
                ecosystem=parsed.ecosystem,
                name=parsed.name,
                dependencies=tuple(BuildDependency(
                    name=dependency.name,
                    local_path=dependency.local_path,
                    evidence=dependency.evidence,
                ) for dependency in parsed.dependencies),
            ))

    unit_by_name: dict[tuple[str, str], list[BuildUnit]] = {}
    for unit in units:
        key = (unit.ecosystem, _normalized_name(unit.ecosystem, unit.name))
        unit_by_name.setdefault(key, []).append(unit)

    edges = []
    edge_keys: set[tuple[str, str, str]] = set()
    for source_unit in sorted(units, key=lambda item: item.build_unit_id):
        for dependency in source_unit.dependencies:
            target_component_id = None
            if dependency.local_path:
                dependency_path = (
                    root / Path(source_unit.manifest_path).parent / dependency.local_path
                ).resolve()
                try:
                    relative_path = dependency_path.relative_to(root).as_posix()
                except ValueError:
                    relative_path = ""
                target_component_id = _component_for_path(relative_path, component_by_root)
                if target_component_id is None:
                    diagnostics.append(GraphDiagnostic(
                        manifest_path=source_unit.manifest_path,
                        code="LOCAL_DEPENDENCY_UNRESOLVED",
                        detail=f"{dependency.name}: {dependency.local_path}",
                    ))
                    continue
            else:
                candidates = unit_by_name.get((
                    source_unit.ecosystem,
                    _normalized_name(source_unit.ecosystem, dependency.name),
                ), [])
                if len(candidates) == 1:
                    target_component_id = candidates[0].component_id
                elif len(candidates) > 1:
                    diagnostics.append(GraphDiagnostic(
                        manifest_path=source_unit.manifest_path,
                        code="LOCAL_DEPENDENCY_AMBIGUOUS",
                        detail=dependency.name,
                    ))
                    continue
            if target_component_id is None or target_component_id == source_unit.component_id:
                continue
            edge_evidence = f"{source_unit.manifest_path}:{dependency.evidence}"
            edges.append(BoundaryEdge(
                edge_id=_stable_id(
                    "EDGE",
                    source_unit.build_unit_id,
                    target_component_id,
                    dependency.name,
                    dependency.local_path or "",
                    dependency.evidence,
                ),
                source_component_id=source_unit.component_id,
                target_component_id=target_component_id,
                kind="build_dependency",
                evidence=edge_evidence,
                source_language=(
                    languages_by_component[source_unit.component_id][0]
                    if len(languages_by_component[source_unit.component_id]) == 1 else None
                ),
                target_language=(
                    languages_by_component[target_component_id][0]
                    if len(languages_by_component[target_component_id]) == 1 else None
                ),
                discovery_status="build_candidate",
            ))
            edge_keys.add((source_unit.manifest_path, dependency.name, "build_dependency"))

    source_by_path = {item.path: item for item in inventory.source_files}
    for source_path, source_file in sorted(source_by_path.items()):
        adapter = LANGUAGE_ADAPTERS.get(source_file.language)
        if adapter is None:
            continue
        try:
            source_text = (root / source_path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line_number, reference in adapter.import_references(source_text):
            targets = adapter.resolve_import(reference, source_path, set(source_by_path))
            target_components = {
                source_by_path[target].component_id for target in targets
                if source_by_path[target].component_id != source_file.component_id
            }
            if len(target_components) != 1:
                continue
            target_component_id = next(iter(target_components))
            target_path = next(
                target for target in targets
                if source_by_path[target].component_id == target_component_id
            )
            key = (source_path, target_path, "language_import_candidate")
            if key in edge_keys:
                continue
            edge_keys.add(key)
            edges.append(BoundaryEdge(
                edge_id=_stable_id(
                    "EDGE", inventory.snapshot_id, source_path, target_path,
                    str(line_number), reference,
                ),
                source_component_id=source_file.component_id,
                target_component_id=target_component_id,
                kind="language_import_candidate",
                evidence=f"{source_path}:{line_number}: import {reference}",
                source_path=source_path,
                target_path=target_path,
                source_language=source_file.language,
                target_language=source_by_path[target_path].language,
                evidence_refs=(f"LOC-{source_path}:{line_number}", f"LOC-{target_path}:1"),
                discovery_status="agent_proposed",
            ))
    return ComponentGraph(
        schema_version="1.0",
        snapshot_id=inventory.snapshot_id,
        build_units=tuple(sorted(units, key=lambda item: item.build_unit_id)),
        edges=tuple(sorted(edges, key=lambda item: item.edge_id)),
        diagnostics=tuple(sorted(
            diagnostics, key=lambda item: (item.manifest_path, item.code, item.detail)
        )),
    )