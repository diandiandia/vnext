"""Data-driven source-language adapters for the approved vNext portfolio."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePath, PurePosixPath
import posixpath
import re


@dataclass(frozen=True)
class LanguageAdapter:
    language_id: str
    extensions: frozenset[str]
    import_pattern: str
    symbol_pattern: str
    boundary_markers: tuple[str, ...]
    toolchain_probe: tuple[str, ...]
    generated_path_markers: tuple[str, ...] = (
        "/generated/", "/build/", "/dist/", "/vendor/",
    )

    def imports(self, source: str) -> tuple[str, ...]:
        return tuple(dict.fromkeys(
            reference for _, reference in self.import_references(source)
        ))

    def import_references(self, source: str) -> tuple[tuple[int, str], ...]:
        expression = re.compile(self.import_pattern, re.MULTILINE)
        references = []
        for match in expression.finditer(source):
            reference = next(
                (value for value in match.groups() if value), None
            )
            if reference:
                line = source.count("\n", 0, match.start()) + 1
                references.append((line, reference))
        return tuple(references)

    def symbols(self, source: str) -> tuple[tuple[int, str], ...]:
        expression = re.compile(self.symbol_pattern, re.MULTILINE)
        symbols = []
        for match in expression.finditer(source):
            name = next((value for value in match.groups() if value), None)
            if name:
                line = source.count("\n", 0, match.start()) + 1
                symbols.append((line, name))
        return tuple(symbols)

    def resolve_import(
        self,
        reference: str,
        source_path: str,
        known_paths: set[str],
    ) -> tuple[str, ...]:
        source = PurePosixPath(source_path)
        candidates: set[str] = set()

        def add(value: str) -> None:
            normalized = posixpath.normpath(value)
            if normalized not in {".", ".."} and not normalized.startswith("../"):
                candidates.add(normalized)

        if self.language_id in {"c", "cpp"}:
            add((source.parent / reference).as_posix())
        elif self.language_id == "python":
            module = reference.replace(".", "/")
            add(f"{module}.py")
            add(f"{module}/__init__.py")
            add((source.parent / f"{module}.py").as_posix())
            add((source.parent / module / "__init__.py").as_posix())
            candidates.update(
                path for path in known_paths
                if path.endswith(f"/{module}.py")
                or path.endswith(f"/{module}/__init__.py")
            )
        elif self.language_id in {"javascript", "typescript"} and reference.startswith("."):
            base = posixpath.normpath((source.parent / reference).as_posix())
            add(base)
            for extension in (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"):
                add(base + extension)
                add(f"{base}/index{extension}")
        elif self.language_id in {"java", "kotlin", "scala"}:
            module = reference.removesuffix(".*").replace(".", "/")
            extension = {"java": ".java", "kotlin": ".kt", "scala": ".scala"}[self.language_id]
            add(f"{module}{extension}")
            add((source.parent / f"{module}{extension}").as_posix())
            candidates.update(path for path in known_paths if path.endswith(f"/{module}{extension}"))
        elif self.language_id == "rust":
            module = reference.removeprefix("crate::").replace("::", "/")
            add(f"{module}.rs")
            add(f"{module}/mod.rs")
            add((source.parent / f"{module}.rs").as_posix())
            add((source.parent / module / "mod.rs").as_posix())
        elif self.language_id == "go":
            package_name = reference.strip("/").rsplit("/", 1)[-1]
            candidates.update(
                path for path in known_paths
                if path.rsplit("/", 1)[0].rsplit("/", 1)[-1] == package_name
            )
        elif self.language_id == "csharp":
            namespace = reference.replace(".", "/")
            candidates.update(
                path for path in known_paths
                if path.endswith(".cs")
                and (f"/{namespace}/" in f"/{path}" or path.startswith(namespace + "/"))
            )
        elif self.language_id in {"php", "ruby", "shell"}:
            base = posixpath.normpath((source.parent / reference).as_posix())
            add(base)
            extensions = {
                "php": (".php", ".phtml"),
                "ruby": (".rb", ".rake"),
                "shell": (".sh", ".bash", ".zsh"),
            }[self.language_id]
            for extension in extensions:
                add(base + extension)
        elif self.language_id == "swift":
            module = reference.casefold()
            candidates.update(
                path for path in known_paths
                if PurePosixPath(path).parent.name.casefold() == module
                or PurePosixPath(path).stem.casefold() == module
            )
        return tuple(sorted(candidates.intersection(known_paths)))

    @staticmethod
    def normalize_location(path: str, line: int) -> str:
        normalized = path.replace("\\", "/")
        parsed = PurePosixPath(normalized)
        if (
            not normalized
            or parsed.is_absolute()
            or ".." in parsed.parts
            or line < 1
        ):
            raise ValueError("source location must be a project-relative path and positive line")
        return f"LOC-{parsed.as_posix()}:{line}"


_ADAPTERS = (
    LanguageAdapter("c", frozenset({".c", ".h"}), r"^\s*#\s*include\s*[<\"]([^>\"]+)", r"^\s*(?:static\s+)?[\w*\s]+\s+(\w+)\s*\([^;]*\)\s*\{", ("extern \"C\"", "dlopen", "LoadLibrary"), ("cc --version", "clang --version")),
    LanguageAdapter("cpp", frozenset({".cc", ".cpp", ".cxx", ".hpp", ".hh", ".hxx"}), r"^\s*#\s*include\s*[<\"]([^>\"]+)", r"^\s*(?:class|struct|namespace)\s+(\w+)|^\s*(?:template\s*<[^>]+>\s*)?(?:[\w:*&<>]+\s+)+(\w+)\s*\([^;]*\)\s*\{", ("extern \"C\"", "dlopen", "LoadLibrary"), ("c++ --version", "clang++ --version")),
    LanguageAdapter("csharp", frozenset({".cs"}), r"^\s*using\s+([\w.]+)\s*;", r"^\s*(?:public|internal|private|protected|static|async|sealed|abstract|partial|\s)*(?:class|struct|interface|enum|record|void|Task\s*<[^>]+>)\s+(\w+)\b", ("DllImport", "LibraryImport", "NamedPipe", "Grpc"), ("dotnet --info",)),
    LanguageAdapter("go", frozenset({".go"}), r"^\s*\"([^\"]+)\"\s*$", r"^\s*func\s+(?:\([^)]*\)\s*)?(\w+)\s*\(", ("cgo", "net/rpc", "grpc", "plugin"), ("go version",)),
    LanguageAdapter("java", frozenset({".java"}), r"^\s*import\s+(?:static\s+)?([\w.*]+)\s*;", r"^\s*(?:(?:public|protected|private|static|final|abstract|synchronized|native|default)\s+)*(?:class|interface|enum|record|[\w<>?\[\].]+)\s+(\w+)\s*(?:\(|\{|extends|implements)", ("JNI", "RMI", "JNA", "grpc"), ("java -version",)),
    LanguageAdapter("rust", frozenset({".rs"}), r"^\s*(?:pub\s+)?use\s+([\w:]+)", r"^\s*(?:(?:pub(?:\([^)]*\))?|async|unsafe|const|extern\s+\"C\")\s+)*(?:fn|struct|enum|trait|type|mod)\s+(\w+)", ("extern \"C\"", "unsafe", "FFI"), ("rustc --version",)),
    LanguageAdapter("python", frozenset({".py", ".pyw"}), r"^\s*(?:from\s+([\w.]+)|import\s+([\w.]+))", r"^\s*(?:async\s+)?(?:def|class)\s+(\w+)", ("ctypes", "cffi", "subprocess", "pickle"), ("python3 --version",)),
    LanguageAdapter("javascript", frozenset({".js", ".jsx", ".mjs", ".cjs"}), r"(?:import\s+.*?from\s*|require\s*\()\s*[\"']([^\"']+)", r"^\s*(?:export\s+)?(?:async\s+)?(?:function|class)\s+(\w+)|^\s*(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\(", ("N-API", "child_process", "IPC", "WebAssembly"), ("node --version",)),
    LanguageAdapter("typescript", frozenset({".ts", ".tsx", ".mts", ".cts"}), r"(?:import\s+.*?from\s*|require\s*\()\s*[\"']([^\"']+)", r"^\s*(?:export\s+)?(?:declare\s+)?(?:abstract\s+)?(?:async\s+)?(?:function|class|interface|type|enum)\s+(\w+)", ("N-API", "child_process", "IPC", "WebAssembly", "any"), ("node --version", "tsc --version")),
    LanguageAdapter("kotlin", frozenset({".kt", ".kts"}), r"^\s*import\s+([\w.*]+)", r"^\s*(?:(?:public|internal|private|protected|open|data|sealed|abstract|suspend|inline)\s+)*(?:fun|class|object|interface|typealias)\s+(\w+)", ("JNI", "JNA", "Ktor", "grpc"), ("kotlinc -version", "java -version")),
    LanguageAdapter("scala", frozenset({".scala", ".sc"}), r"^\s*import\s+([\w.*]+)", r"^\s*(?:(?:private|protected|final|sealed|abstract|case|override)\s+)*(?:def|class|object|trait|enum|type)\s+(\w+)", ("JNI", "Java serialization", "Akka remoting"), ("scala -version", "sbt --version")),
    LanguageAdapter("php", frozenset({".php", ".phtml"}), r"^\s*(?:use|require|include)(?:_once)?\s*(?:\(?\s*)[\"']?([\w./\\-]+)", r"^\s*(?:(?:public|protected|private|static|abstract|final)\s+)*(?:function|class|interface|trait|enum)\s+(\w+)", ("FFI", "unserialize", "proc_open"), ("php --version", "composer --version")),
    LanguageAdapter("ruby", frozenset({".rb", ".rake"}), r"^\s*require(?:_relative)?\s*[\"']([^\"']+)", r"^\s*(?:def|class|module)\s+(\w+)", ("Fiddle", "DRb", "Marshal.load"), ("ruby --version", "bundle --version")),
    LanguageAdapter("swift", frozenset({".swift"}), r"^\s*import\s+([\w]+)", r"^\s*(?:(?:public|private|fileprivate|internal|open|final|static|class|mutating|async|override)\s+)*(?:func|class|struct|enum|protocol|actor|typealias)\s+(\w+)", (" @_cdecl", "UnsafePointer", "XPC"), ("swift --version",)),
    LanguageAdapter("shell", frozenset({".sh", ".bash", ".zsh"}), r"^\s*(?:source|\.)\s+[\"']?([^\s\"']+)", r"^\s*(?:function\s+)?(\w+)\s*\(\s*\)\s*\{", ("eval", "source", "command substitution", "sudo"), ("bash --version",)),
)

LANGUAGE_ADAPTERS = {adapter.language_id: adapter for adapter in _ADAPTERS}
_EXTENSION_LANGUAGE = {
    extension: adapter.language_id
    for adapter in _ADAPTERS
    for extension in adapter.extensions
}
_RECOGNIZED_UNSUPPORTED = {
    ".m": "objective-c", ".mm": "objective-c", ".proto": "protobuf",
    ".thrift": "thrift", ".idl": "idl", ".sql": "sql",
}


def detect_language(path: str) -> tuple[str, str] | None:
    extension = PurePath(path).suffix.lower()
    if extension in _EXTENSION_LANGUAGE:
        return _EXTENSION_LANGUAGE[extension], "portfolio"
    if extension in _RECOGNIZED_UNSUPPORTED:
        return _RECOGNIZED_UNSUPPORTED[extension], "recognized_unsupported"
    return None