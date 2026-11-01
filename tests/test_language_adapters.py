import pytest

from reachable_audit.adapters.languages import LANGUAGE_ADAPTERS


_DECLARATIONS = {
    "c": "int main(void) { return 0; }",
    "cpp": "class Parser {};",
    "csharp": "public class Handler {}",
    "go": "func Handle() {}",
    "java": "public class Handler {}",
    "rust": "pub fn handle() {}",
    "python": "def handle(): pass",
    "javascript": "export function handle() {}",
    "typescript": "export interface Handler {}",
    "kotlin": "fun handle() {}",
    "scala": "object Handler {}",
    "php": "function handle() {}",
    "ruby": "def handle; end",
    "swift": "public func handle() {}",
    "shell": "handle() { :; }",
}

_IMPORTS = {
    "c": '#include "core.h"',
    "cpp": '#include "core.hpp"',
    "csharp": "using Company.Core;",
    "go": '"example.com/core"',
    "java": "import demo.Core;",
    "rust": "use crate::core;",
    "python": "from core import handle",
    "javascript": 'import { handle } from "./core";',
    "typescript": 'import { handle } from "./core";',
    "kotlin": "import demo.Core",
    "scala": "import demo.Core",
    "php": "use Core;",
    "ruby": 'require "core"',
    "swift": "import Core",
    "shell": "source core.sh",
}


@pytest.mark.parametrize("language", sorted(_DECLARATIONS))
@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_all_language_anchors_skip_leading_blank_lines(
    language: str, newline: str,
) -> None:
    adapter = LANGUAGE_ADAPTERS[language]
    for extractor, statement in (
        (adapter.import_references, _IMPORTS[language]),
        (adapter.symbols, _DECLARATIONS[language]),
    ):
        expected = extractor(statement)
        assert expected
        source = newline + " \t" + newline + "  " + statement + newline
        assert extractor(source) == tuple((3, name) for _, name in expected)


def test_multiline_import_keeps_statement_start_and_resolved_reference() -> None:
    source = '\n\nimport { handle } from\n  "./core";\n'
    for language in ("javascript", "typescript"):
        adapter = LANGUAGE_ADAPTERS[language]
        assert adapter.import_references(source) == ((3, "./core"),)


def test_all_portfolio_adapters_extract_symbols_and_normalize_locations() -> None:
    assert set(LANGUAGE_ADAPTERS) == set(_DECLARATIONS)
    for language, declaration in _DECLARATIONS.items():
        adapter = LANGUAGE_ADAPTERS[language]
        assert adapter.symbols(declaration), language
        assert adapter.normalize_location("src/./module.ext", 3) == "LOC-src/module.ext:3"


def test_adapters_resolve_local_modules_where_path_semantics_are_available() -> None:
    examples = {
        ("c", "src/main.c", "parser.h"): {"src/parser.h"},
        ("cpp", "src/main.cpp", "parser.hpp"): {"src/parser.hpp"},
        ("python", "app/main.py", "pkg.core"): {"pkg/core.py"},
        ("javascript", "app/main.js", "../lib/core"): {"lib/core.js"},
        ("typescript", "app/main.ts", "../lib/core"): {"lib/core.ts"},
        ("java", "app/Main.java", "com.example.Parser"): {"com/example/Parser.java"},
        ("kotlin", "app/Main.kt", "com.example.Parser"): {"com/example/Parser.kt"},
        ("scala", "app/Main.scala", "com.example.Parser"): {"com/example/Parser.scala"},
        ("rust", "src/main.rs", "crate::parser"): {"src/parser.rs"},
        ("go", "cmd/main.go", "example.com/project/lib"): {"lib/lib.go"},
        ("csharp", "app/Main.cs", "Company.Core"): {"Company/Core/Parser.cs"},
        ("php", "app/index.php", "../lib/parser"): {"lib/parser.php"},
        ("ruby", "app/main.rb", "../lib/parser"): {"lib/parser.rb"},
        ("shell", "app/main.sh", "../lib/setup"): {"lib/setup.sh"},
        ("swift", "app/Main.swift", "Core"): {"Core/Parser.swift"},
    }
    for (language, source, reference), expected in examples.items():
        paths = {source, *expected}
        assert set(LANGUAGE_ADAPTERS[language].resolve_import(
            reference, source, paths
        )) == expected, language

def test_python_stdlib_import_does_not_match_repository_leaf_name() -> None:
    adapter = LANGUAGE_ADAPTERS["python"]

    targets = adapter.resolve_import(
        "http.server",
        "examples/importer.py",
        {"examples/importer.py", "lib/network/server.py"},
    )

    assert targets == ()


@pytest.mark.parametrize("path", ("/absolute/source.py", "../escape.py", "src/../../escape.py"))
def test_language_adapters_reject_non_project_relative_locations(path: str) -> None:
    with pytest.raises(ValueError, match="project-relative"):
        LANGUAGE_ADAPTERS["python"].normalize_location(path, 1)