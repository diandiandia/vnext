"""Canonical inventory and audit-plan models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class SourceFile:
    path: str
    language: str
    component_id: str
    language_status: str = "portfolio"

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SourceFile":
        return cls(
            str(value["path"]),
            str(value["language"]),
            str(value["component_id"]),
            str(value.get("language_status", "portfolio")),
        )


@dataclass(frozen=True)
class Component:
    component_id: str
    root: str
    build_manifests: tuple[str, ...]
    languages: tuple[str, ...]
    source_file_count: int

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Component":
        return cls(
            component_id=str(value["component_id"]),
            root=str(value["root"]),
            build_manifests=tuple(str(item) for item in value["build_manifests"]),
            languages=tuple(str(item) for item in value["languages"]),
            source_file_count=int(value["source_file_count"]),
        )


@dataclass(frozen=True)
class ProjectInventory:
    schema_version: str
    snapshot_id: str
    components: tuple[Component, ...]
    source_files: tuple[SourceFile, ...]
    skipped_directories: tuple[str, ...]
    repository_size_bytes: int = 0

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProjectInventory":
        return cls(
            schema_version=str(value["schema_version"]),
            snapshot_id=str(value["snapshot_id"]),
            components=tuple(Component.from_dict(item) for item in value["components"]),
            source_files=tuple(SourceFile.from_dict(item) for item in value["source_files"]),
            skipped_directories=tuple(str(item) for item in value.get("skipped_directories", [])),
            repository_size_bytes=int(value.get("repository_size_bytes", 0)),
        )


@dataclass(frozen=True)
class BoundaryEdge:
    edge_id: str
    source_component_id: str
    target_component_id: str
    kind: str
    evidence: str
    source_path: str | None = None
    target_path: str | None = None
    source_language: str | None = None
    target_language: str | None = None
    evidence_refs: tuple[str, ...] = ()
    discovery_status: str = "agent_proposed"
    owner_work_unit_id: str | None = None

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "BoundaryEdge":
        return cls(
            edge_id=str(value["edge_id"]),
            source_component_id=str(value["source_component_id"]),
            target_component_id=str(value["target_component_id"]),
            kind=str(value["kind"]),
            evidence=str(value.get("evidence", "")),
            source_path=str(value["source_path"]) if value.get("source_path") is not None else None,
            target_path=str(value["target_path"]) if value.get("target_path") is not None else None,
            source_language=(
                str(value["source_language"])
                if value.get("source_language") is not None else None
            ),
            target_language=(
                str(value["target_language"])
                if value.get("target_language") is not None else None
            ),
            evidence_refs=tuple(str(item) for item in value.get("evidence_refs", [])),
            discovery_status=str(value.get("discovery_status", "agent_proposed")),
            owner_work_unit_id=(
                str(value["owner_work_unit_id"])
                if value.get("owner_work_unit_id") is not None else None
            ),
        )


@dataclass(frozen=True)
class BuildDependency:
    name: str
    local_path: str | None
    evidence: str


@dataclass(frozen=True)
class BuildUnit:
    build_unit_id: str
    component_id: str
    manifest_path: str
    ecosystem: str
    name: str
    dependencies: tuple[BuildDependency, ...]


@dataclass(frozen=True)
class GraphDiagnostic:
    manifest_path: str
    code: str
    detail: str


@dataclass(frozen=True)
class ComponentGraph:
    schema_version: str
    snapshot_id: str
    build_units: tuple[BuildUnit, ...]
    edges: tuple[BoundaryEdge, ...]
    diagnostics: tuple[GraphDiagnostic, ...]

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ComponentGraph":
        build_units = []
        for unit in value["build_units"]:
            build_units.append(BuildUnit(
                build_unit_id=str(unit["build_unit_id"]),
                component_id=str(unit["component_id"]),
                manifest_path=str(unit["manifest_path"]),
                ecosystem=str(unit["ecosystem"]),
                name=str(unit["name"]),
                dependencies=tuple(BuildDependency(
                    name=str(dependency["name"]),
                    local_path=(
                        str(dependency["local_path"])
                        if dependency.get("local_path") is not None
                        else None
                    ),
                    evidence=str(dependency["evidence"]),
                ) for dependency in unit["dependencies"]),
            ))
        return cls(
            schema_version=str(value["schema_version"]),
            snapshot_id=str(value["snapshot_id"]),
            build_units=tuple(build_units),
            edges=tuple(BoundaryEdge.from_dict(item) for item in value["edges"]),
            diagnostics=tuple(GraphDiagnostic(
                manifest_path=str(item["manifest_path"]),
                code=str(item["code"]),
                detail=str(item["detail"]),
            ) for item in value.get("diagnostics", [])),
        )


@dataclass(frozen=True)
class WorkUnit:
    work_unit_id: str
    component_id: str
    source_files: tuple[str, ...]
    languages: tuple[str, ...]
    category_families: tuple[str, ...]
    discovery_axes: tuple[str, ...]
    boundary_edge_ids: tuple[str, ...]

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "WorkUnit":
        return cls(
            work_unit_id=str(value["work_unit_id"]),
            component_id=str(value["component_id"]),
            source_files=tuple(str(item) for item in value["source_files"]),
            languages=tuple(str(item) for item in value["languages"]),
            category_families=tuple(str(item) for item in value["category_families"]),
            discovery_axes=tuple(str(item) for item in value["discovery_axes"]),
            boundary_edge_ids=tuple(str(item) for item in value["boundary_edge_ids"]),
        )


@dataclass(frozen=True)
class PlannedBatch:
    batch_id: str
    work_unit_ids: tuple[str, ...]
    source_file_count: int
    dependencies: tuple[str, ...]
    required_stages: tuple[str, ...]

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PlannedBatch":
        return cls(
            batch_id=str(value["batch_id"]),
            work_unit_ids=tuple(str(item) for item in value["work_unit_ids"]),
            source_file_count=int(value["source_file_count"]),
            dependencies=tuple(str(item) for item in value["dependencies"]),
            required_stages=tuple(str(item) for item in value["required_stages"]),
        )


@dataclass(frozen=True)
class Handoff:
    handoff_id: str
    edge_id: str
    from_batch: str
    owner_batch: str
    status: str

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Handoff":
        return cls(
            handoff_id=str(value["handoff_id"]),
            edge_id=str(value["edge_id"]),
            from_batch=str(value["from_batch"]),
            owner_batch=str(value["owner_batch"]),
            status=str(value["status"]),
        )


@dataclass(frozen=True)
class AuditPlan:
    schema_version: str
    plan_id: str
    campaign_id: str
    snapshot_id: str
    inventory_digest: str
    category_families: tuple[str, ...]
    discovery_axes: tuple[str, ...]
    work_units: tuple[WorkUnit, ...]
    batches: tuple[PlannedBatch, ...]
    handoffs: tuple[Handoff, ...]
    boundary_edges: tuple[BoundaryEdge, ...]
    omitted_empty_component_ids: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AuditPlan":
        return cls(
            schema_version=str(value["schema_version"]),
            plan_id=str(value["plan_id"]),
            campaign_id=str(value["campaign_id"]),
            snapshot_id=str(value["snapshot_id"]),
            inventory_digest=str(value["inventory_digest"]),
            category_families=tuple(str(item) for item in value["category_families"]),
            discovery_axes=tuple(str(item) for item in value["discovery_axes"]),
            work_units=tuple(WorkUnit.from_dict(item) for item in value["work_units"]),
            batches=tuple(PlannedBatch.from_dict(item) for item in value["batches"]),
            handoffs=tuple(Handoff.from_dict(item) for item in value["handoffs"]),
            boundary_edges=tuple(
                BoundaryEdge.from_dict(item) for item in value["boundary_edges"]
            ),
            omitted_empty_component_ids=tuple(
                str(item) for item in value.get("omitted_empty_component_ids", [])
            ),
        )


@dataclass(frozen=True)
class BatchReplacement:
    retired_batch_id: str
    replacement_batch_ids: tuple[str, ...]


@dataclass(frozen=True)
class PlanAmendment:
    schema_version: str
    amendment_id: str
    campaign_id: str
    base_plan_id: str
    amended_plan_id: str
    reason: str
    preserved_work_unit_ids: tuple[str, ...]
    batch_replacements: tuple[BatchReplacement, ...]
