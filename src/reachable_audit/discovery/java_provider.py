"""Experimental parse-only JDK Tree API bridge over verified in-memory bytes.

Only the bundled trusted helper is compiled. Targets are never compiled,
resolved, loaded, or executed. A private process-local helper cache is removed
at exit. No third-party dependencies, target build, or network access is needed.
"""

from __future__ import annotations

import atexit
import base64
import os
from pathlib import Path
import shutil
import subprocess
import threading
from typing import Any

from .bounded_process import child_limits as _child_limits, create_workspace, run_bounded


JAVA_HOTSPOT_PROVIDER_ID = "java-ast-hotspots-v1"
MAX_JAVA_FILES = 128
MAX_JAVA_FILE_BYTES = 1024 * 1024
MAX_JAVA_TOTAL_BYTES = 4 * MAX_JAVA_FILE_BYTES
MAX_JAVA_CANDIDATES = 200
JAVA_METHOD_FAMILIES = {
    "exec": "JAVA-CMD-001",
    "start": "JAVA-CMD-001",
    "readObject": "JAVA-DESER-001",
    "readUnshared": "JAVA-DESER-001",
    "readAllBytes": "JAVA-STREAM-001",
    "transferTo": "JAVA-STREAM-001",
    "getNextEntry": "JAVA-STREAM-001",
}
_BUILD_TIMEOUT = 30
_PARSE_TIMEOUT = 15
_OUTPUT_LIMIT = 2 * 1024 * 1024
MAX_JAVA_CACHE_BYTES = 256 * 1024
_LOCK = threading.Lock()
_WORKSPACE: Path | None = None
_HELPER: Path | None = None
_JAVA: Path | None = None
_JVM_FLAGS = [
    "-Xmx128m", "-Xss512k", "-XX:MaxMetaspaceSize=128m",
    "-XX:CompressedClassSpaceSize=64m", "-XX:ReservedCodeCacheSize=32m",
    "-XX:ActiveProcessorCount=2", "-XX:-UsePerfData",
    "-XX:ErrorFile=/dev/null", "-XX:-CreateCoredumpOnCrash",
]


class JavaProviderError(Exception):
    """Provider unavailable or failed; never a clean scan."""


def _cleanup() -> None:
    global _WORKSPACE, _HELPER, _JAVA
    if _WORKSPACE is not None:
        shutil.rmtree(_WORKSPACE, ignore_errors=True)
    _WORKSPACE = _HELPER = _JAVA = None


atexit.register(_cleanup)


def _environment(workspace: Path) -> dict[str, str]:
    return {
        "PATH": os.defpath, "HOME": str(workspace), "TMPDIR": str(workspace),
        "LANG": "C.UTF-8",
    }


def _run_bounded(
    command: list[str], workspace: Path, input_bytes: bytes, timeout: int,
) -> bytes:
    return run_bounded(
        command, workspace, input_bytes, timeout,
        environment=_environment(workspace), child_limits=_child_limits,
        error_type=JavaProviderError, label="Java", output_limit=_OUTPUT_LIMIT,
    )


def _helper(target_root: Path | None = None) -> tuple[Path, Path]:
    global _WORKSPACE, _HELPER, _JAVA
    if os.name != "posix":
        raise JavaProviderError("bounded Java provider requires a POSIX host")
    javac, java = shutil.which("javac"), shutil.which("java")
    if javac is None or java is None:
        raise JavaProviderError("optional Java JDK toolchain is unavailable")
    with _LOCK:
        if _WORKSPACE is not None and _HELPER is not None:
            if target_root is not None and _WORKSPACE.is_relative_to(target_root.resolve()):
                raise JavaProviderError("cached Java helper is inside the target")
            return _HELPER, _WORKSPACE
        workspace = create_workspace("reachable-audit-java-", target_root)
        try:
            source = workspace / "JavaHotspots.java"
            source.write_bytes(Path(__file__).with_name("JavaHotspots.java").read_bytes())
            _run_bounded(
                [str(Path(javac).resolve()), *["-J" + flag for flag in _JVM_FLAGS],
                 "-J-Djava.io.tmpdir=" + str(workspace),
                 "-proc:none", "-implicit:none", "-classpath", str(workspace),
                 "-sourcepath", str(workspace), "-d", str(workspace), str(source)],
                workspace, b"", _BUILD_TIMEOUT,
            )
            if (
                not (workspace / "JavaHotspots.class").is_file()
                or sum(path.stat().st_size for path in workspace.rglob("*") if path.is_file())
                > MAX_JAVA_CACHE_BYTES
            ):
                raise JavaProviderError("Java helper cache limit or build failure")
        except Exception:
            shutil.rmtree(workspace, ignore_errors=True)
            raise
        _WORKSPACE, _HELPER, _JAVA = workspace, workspace, Path(java).resolve()
        return workspace, workspace


def scan_java_bytes(
    sources: dict[str, bytes], *, max_candidates: int, target_root: Path | None = None,
) -> list[dict[str, Any]]:
    """Parse one bounded batch; method labels deliberately claim no type identity."""
    if (
        max_candidates < 1 or len(sources) > MAX_JAVA_FILES
        or any(len(source) > MAX_JAVA_FILE_BYTES for source in sources.values())
        or sum(map(len, sources.values())) > MAX_JAVA_TOTAL_BYTES
        or any(len(path.encode("utf-8")) > 4096 for path in sources)
    ):
        raise JavaProviderError("Java parser input limit exceeded")
    limit = min(max_candidates, MAX_JAVA_CANDIDATES)
    try:
        helper, workspace = _helper(target_root) if target_root is not None else _helper()
        payload = str(limit) + "\n" + "".join(
            base64.b64encode(path.encode()).decode() + "\t"
            + base64.b64encode(source).decode() + "\n"
            for path, source in sorted(sources.items())
        )
        output = _run_bounded(
            [str(_JAVA), *_JVM_FLAGS, "-Djava.io.tmpdir=" + str(workspace),
             "-cp", str(helper), "JavaHotspots"],
            workspace, payload.encode("ascii"), _PARSE_TIMEOUT,
        )
        results: dict[str, dict[str, Any]] = {}
        retained = 0
        for line in output.decode("ascii").splitlines():
            fields = line.split("\t")
            if len(fields) not in {4, 5}:
                raise JavaProviderError("invalid Java helper response")
            path = base64.b64decode(fields[1], validate=True).decode("utf-8")
            if path not in sources:
                raise JavaProviderError("invalid Java helper response")
            if fields[0] == "F" and len(fields) == 4:
                count = int(fields[2])
                if path in results or count < 0:
                    raise JavaProviderError("invalid Java helper response")
                result: dict[str, Any] = {"path": path, "count": count, "candidates": []}
                if fields[3]:
                    result["error"] = base64.b64decode(fields[3], validate=True).decode("utf-8")
                results[path] = result
            elif fields[0] == "C" and len(fields) == 5:
                row, column = int(fields[2]), int(fields[3])
                api = fields[4]
                if (
                    path not in results or row < 1 or column < 1
                    or api not in {"unresolved-receiver." + name for name in JAVA_METHOD_FAMILIES}
                ):
                    raise JavaProviderError("invalid Java helper response")
                results[path]["candidates"].append({
                    "path": path, "line": row, "column": column, "api": api,
                })
                retained += 1
            else:
                raise JavaProviderError("invalid Java helper response")
        if (
            set(results) != set(sources) or retained > limit
            or any(
                len(result["candidates"]) > result["count"]
                or ("error" in result and (result["count"] or result["candidates"]))
                for result in results.values()
            )
        ):
            raise JavaProviderError("invalid Java helper response")
        return list(results.values())
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        raise JavaProviderError(f"Java provider failed or invalid response: {type(error).__name__}") from error
