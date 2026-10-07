from pathlib import Path
from types import SimpleNamespace

from reachable_audit.graph import build_component_graph
from reachable_audit.inventory import build_inventory


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_graph_resolves_python_cargo_and_go_local_dependencies(tmp_path: Path) -> None:
    _write(
        tmp_path / "python" / "app" / "pyproject.toml",
        "[project]\nname='py-app'\ndependencies=['py-core @ file:../../core']\n",
    )
    _write(tmp_path / "python" / "app" / "app.py", "import core\n")
    _write(tmp_path / "core" / "pyproject.toml", "[project]\nname='py-core'\n")
    _write(tmp_path / "core" / "core.py", "VALUE = 1\n")
    _write(
        tmp_path / "rust" / "app" / "Cargo.toml",
        "[package]\nname='rust-app'\n[dependencies]\nrust-core={path='../core'}\n",
    )
    _write(tmp_path / "rust" / "app" / "src" / "main.rs", "fn main() {}\n")
    _write(tmp_path / "rust" / "core" / "Cargo.toml", "[package]\nname='rust-core'\n")
    _write(tmp_path / "rust" / "core" / "src" / "lib.rs", "pub fn run() {}\n")
    _write(
        tmp_path / "go" / "app" / "go.mod",
        "module example/app\nrequire example/core v0.0.0\nreplace example/core => ../core\n",
    )
    _write(tmp_path / "go" / "app" / "main.go", "package main\n")
    _write(tmp_path / "go" / "core" / "go.mod", "module example/core\n")
    _write(tmp_path / "go" / "core" / "core.go", "package core\n")

    inventory = build_inventory(tmp_path, "fixture:graph")
    graph = build_component_graph(tmp_path, inventory)
    roots_by_id = {
        component.component_id: component.root for component in inventory.components
    }
    edge_roots = {
        (roots_by_id[edge.source_component_id], roots_by_id[edge.target_component_id])
        for edge in graph.edges
    }

    assert len(graph.build_units) == 6
    assert edge_roots == {
        ("python/app", "core"),
        ("rust/app", "rust/core"),
        ("go/app", "go/core"),
    }
    assert graph.diagnostics == ()


def test_graph_reports_malformed_and_unresolved_local_manifests(tmp_path: Path) -> None:
    _write(tmp_path / "bad" / "pyproject.toml", "[project\n")
    _write(tmp_path / "bad" / "main.py", "print('bad')\n")
    _write(
        tmp_path / "app" / "Cargo.toml",
        "[package]\nname='app'\n[dependencies]\nmissing={path='../../outside'}\n",
    )
    _write(tmp_path / "app" / "src" / "main.rs", "fn main() {}\n")

    graph = build_component_graph(tmp_path, build_inventory(tmp_path, "fixture:errors"))

    assert graph.edges == ()
    assert {diagnostic.code for diagnostic in graph.diagnostics} == {
        "LOCAL_DEPENDENCY_UNRESOLVED",
        "MANIFEST_PARSE_ERROR",
    }


def test_graph_resolves_npm_maven_gradle_and_swift_local_dependencies(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "npm" / "app" / "package.json",
        '{"name":"npm-app","dependencies":{"npm-core":"file:../core"}}',
    )
    _write(tmp_path / "npm" / "app" / "app.ts", "export {};\n")
    _write(tmp_path / "npm" / "core" / "package.json", '{"name":"npm-core"}')
    _write(tmp_path / "npm" / "core" / "core.ts", "export {};\n")
    _write(
        tmp_path / "maven" / "pom.xml",
        "<project><artifactId>parent</artifactId><modules><module>core</module></modules></project>",
    )
    _write(tmp_path / "maven" / "Main.java", "class Main {}\n")
    _write(
        tmp_path / "maven" / "core" / "pom.xml",
        "<project><artifactId>core</artifactId></project>",
    )
    _write(tmp_path / "maven" / "core" / "Core.java", "class Core {}\n")
    _write(tmp_path / "gradle" / "app" / "build.gradle", "implementation project(':core')\n")
    _write(tmp_path / "gradle" / "app" / "App.kt", "class App\n")
    _write(tmp_path / "gradle" / "core" / "build.gradle", "plugins {}\n")
    _write(tmp_path / "gradle" / "core" / "Core.kt", "class Core\n")
    _write(
        tmp_path / "swift" / "app" / "Package.swift",
        'let package = Package(name: "SwiftApp", dependencies: [.package(path: "../core")])\n',
    )
    _write(tmp_path / "swift" / "app" / "App.swift", "public struct App {}\n")
    _write(
        tmp_path / "swift" / "core" / "Package.swift",
        'let package = Package(name: "core")\n',
    )
    _write(tmp_path / "swift" / "core" / "Core.swift", "public struct Core {}\n")
    _write(tmp_path / "native" / "CMakeLists.txt", "add_library(native native.c)\n")
    _write(tmp_path / "native" / "native.c", "int native(void) { return 0; }\n")

    inventory = build_inventory(tmp_path, "fixture:more-builds")
    graph = build_component_graph(tmp_path, inventory)
    roots_by_id = {
        component.component_id: component.root for component in inventory.components
    }
    edge_roots = {
        (roots_by_id[edge.source_component_id], roots_by_id[edge.target_component_id])
        for edge in graph.edges
    }
    assert {
        ("npm/app", "npm/core"),
        ("maven", "maven/core"),
        ("gradle/app", "gradle/core"),
        ("swift/app", "swift/core"),
    }.issubset(edge_roots)
    assert any(
        unit.ecosystem == "cmake" and unit.name == "native"
        for unit in graph.build_units
    )


def test_build_dependency_edge_ids_distinguish_same_name_declarations(
    tmp_path: Path, monkeypatch,
) -> None:
    from reachable_audit import graph
    from reachable_audit.adapters.builds.base import (
        ParsedBuildDependency,
        ParsedBuildUnit,
    )

    _write(tmp_path / "app" / "Makefile", "# app build\n")
    _write(tmp_path / "app" / "main.c", "int main(void) { return 0; }\n")
    _write(tmp_path / "core" / "core.c", "int core(void) { return 0; }\n")
    inventory = build_inventory(tmp_path, "fixture:duplicate-build-dependencies")

    adapter = SimpleNamespace(
        manifest_names=frozenset({"Makefile"}),
        manifest_suffixes=frozenset(),
        parse=lambda path: ParsedBuildUnit(
            "test-build",
            "app",
            (
                ParsedBuildDependency("core", "../core", "dependencies.log:1"),
                ParsedBuildDependency("core", "../core/nested", "build-dependencies.log:8"),
            ),
        ),
    )
    monkeypatch.setattr(graph, "_adapter_for_manifest", lambda _: adapter)

    component_graph = build_component_graph(tmp_path, inventory)
    build_edges = [edge for edge in component_graph.edges if edge.kind == "build_dependency"]

    assert len(build_edges) == 2
    assert len({edge.edge_id for edge in build_edges}) == 2


def test_inventory_preserves_mixed_languages_and_unsupported_dispositions(
    tmp_path: Path,
) -> None:
    _write(tmp_path / "app" / "main.py", "import parser\n")
    _write(tmp_path / "app" / "bridge.ts", "import value from './native';\n")
    _write(tmp_path / "app" / "native.cpp", "#include <native.h>\n")
    _write(tmp_path / "app" / "legacy.ps1", "Write-Output 'legacy'\n")
    _write(tmp_path / "app" / "objc.m", "@interface Legacy @end\n")

    inventory = build_inventory(tmp_path, "fixture:mixed-languages")

    component = inventory.components[0]
    assert component.languages == (
        "cpp", "objective-c", "powershell", "python", "typescript",
    )
    statuses = {source.language: source.language_status for source in inventory.source_files}
    assert statuses["python"] == "portfolio"
    assert statuses["typescript"] == "portfolio"
    assert statuses["cpp"] == "portfolio"
    assert statuses["powershell"] == "recognized_unsupported"
    assert statuses["objective-c"] == "recognized_unsupported"


def test_additional_language_build_ecosystems_resolve_local_edges(
    tmp_path: Path,
) -> None:
    _write(tmp_path / "cmake" / "app" / "CMakeLists.txt", "project(app)\nadd_subdirectory(../core)\n")
    _write(tmp_path / "cmake" / "app" / "main.cpp", "int main() {}\n")
    _write(tmp_path / "cmake" / "core" / "CMakeLists.txt", "project(core)\n")
    _write(tmp_path / "cmake" / "core" / "core.cpp", "int core() {}\n")
    _write(tmp_path / "make" / "app" / "Makefile", "SUBDIRS = ../core\n")
    _write(tmp_path / "make" / "app" / "main.c", "int main(void) {}\n")
    _write(tmp_path / "make" / "core" / "Makefile", "all:\n\t@echo core\n")
    _write(tmp_path / "make" / "core" / "core.c", "int core(void) {}\n")
    _write(tmp_path / "dotnet" / "app" / "App.csproj", "<Project><ItemGroup><ProjectReference Include='../core/Core.csproj' /></ItemGroup></Project>")
    _write(tmp_path / "dotnet" / "app" / "App.cs", "class App {}\n")
    _write(tmp_path / "dotnet" / "core" / "Core.csproj", "<Project />")
    _write(tmp_path / "dotnet" / "core" / "Core.cs", "class Core {}\n")
    _write(tmp_path / "composer" / "app" / "composer.json", '{"name":"app","repositories":[{"type":"path","url":"../core"}]}')
    _write(tmp_path / "composer" / "app" / "index.php", "<?php\n")
    _write(tmp_path / "composer" / "core" / "composer.json", '{"name":"core"}')
    _write(tmp_path / "composer" / "core" / "core.php", "<?php\n")
    _write(tmp_path / "bundler" / "app" / "Gemfile", "path '../core'\n")
    _write(tmp_path / "bundler" / "app" / "app.rb", "puts :app\n")
    _write(tmp_path / "bundler" / "core" / "Gemfile", "source 'https://rubygems.org'\n")
    _write(tmp_path / "bundler" / "core" / "core.rb", "puts :core\n")
    _write(tmp_path / "sbt" / "app" / "build.sbt", 'lazy val app = project.dependsOn(ProjectRef(file("../core"), "core"))\n')
    _write(tmp_path / "sbt" / "app" / "App.scala", "object App\n")
    _write(tmp_path / "sbt" / "core" / "build.sbt", 'lazy val core = project\n')
    _write(tmp_path / "sbt" / "core" / "Core.scala", "object Core\n")
    _write(tmp_path / "perl" / "app" / "cpanfile", "requires 'JSON::PP';\n")
    _write(tmp_path / "perl" / "app" / "app.pl", "print 'ok';\n")

    inventory = build_inventory(tmp_path, "fixture:additional-builds")
    graph = build_component_graph(tmp_path, inventory)
    roots_by_id = {
        component.component_id: component.root for component in inventory.components
    }
    edge_roots = {
        (roots_by_id[edge.source_component_id], roots_by_id[edge.target_component_id])
        for edge in graph.edges
    }
    ecosystems = {unit.ecosystem for unit in graph.build_units}

    assert {
        "cmake", "make", "dotnet", "composer", "bundler", "sbt", "perl",
    }.issubset(ecosystems)
    assert {
        ("cmake/app", "cmake/core"),
        ("make/app", "make/core"),
        ("dotnet/app", "dotnet/core"),
        ("composer/app", "composer/core"),
        ("bundler/app", "bundler/core"),
        ("sbt/app", "sbt/core"),
    }.issubset(edge_roots)


def test_graph_proposes_anchored_typescript_to_javascript_boundary(tmp_path: Path) -> None:
    _write(tmp_path / "app" / "ts" / "package.json", '{"name":"ts-app"}')
    _write(
        tmp_path / "app" / "ts" / "index.ts",
        'import core from "../../lib/js/core.js";\nexport { core };\n',
    )
    _write(tmp_path / "lib" / "js" / "package.json", '{"name":"js-core"}')
    _write(tmp_path / "lib" / "js" / "core.js", "export default function core() {}\n")

    inventory = build_inventory(tmp_path, "fixture:ts-js-boundary")
    graph = build_component_graph(tmp_path, inventory)

    boundary = next(
        edge for edge in graph.edges if edge.kind == "language_import_candidate"
    )
    assert boundary.source_language == "typescript"
    assert boundary.target_language == "javascript"
    assert boundary.source_path == "app/ts/index.ts"
    assert boundary.target_path == "lib/js/core.js"
    assert boundary.evidence_refs == (
        "LOC-app/ts/index.ts:1", "LOC-lib/js/core.js:1",
    )
    assert boundary.discovery_status == "agent_proposed"


def test_inventory_marks_code_with_unrecognized_extension_as_unknown(
    tmp_path: Path,
) -> None:
    _write(tmp_path / "custom" / "entry.acme", "fn main() { return; }\n")
    _write(tmp_path / "custom" / "script", "#!/usr/bin/env custom-runtime\nclass Worker {}\n")
    _write(tmp_path / "custom" / "README.md", "importantly, this is documentation.\n")

    inventory = build_inventory(tmp_path, "fixture:unknown-source")

    assert {source.path for source in inventory.source_files} == {
        "custom/entry.acme", "custom/script",
    }
    assert all(source.language == "unknown" for source in inventory.source_files)
    assert all(source.language_status == "unknown" for source in inventory.source_files)
    assert inventory.components[0].languages == ("unknown",)