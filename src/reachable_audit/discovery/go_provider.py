"""Offline, bounded stdlib Go parser bridge; no target code is built or loaded.

The helper is compiled once per host Python process, not once per source file.
Its private build cache and executable are removed at process exit. The bundled
``go_hotspots.go`` resource must be included in distribution package data.
"""

from __future__ import annotations

import atexit
import base64
import json
import os
from pathlib import Path
import selectors
import shutil
import signal
import subprocess
import threading
import time
import uuid
from typing import Any

if os.name == "posix":
    import resource


GO_HOTSPOT_PROVIDER_ID = "go-ast-hotspots-v1"
MAX_GO_FILES = 128
MAX_GO_FILE_BYTES = 1024 * 1024
MAX_GO_TOTAL_BYTES = 4 * MAX_GO_FILE_BYTES
MAX_GO_CANDIDATES = 200
_BUILD_TIMEOUT = 90
_PARSE_TIMEOUT = 15
_OUTPUT_LIMIT = 2 * 1024 * 1024
_LOCK = threading.Lock()
_WORKSPACE: Path | None = None
_BINARY: Path | None = None


class GoProviderError(Exception):
    """A provider failure, not evidence of a clean scan."""


def _cleanup() -> None:
    global _WORKSPACE, _BINARY
    if _WORKSPACE is not None:
        shutil.rmtree(_WORKSPACE, ignore_errors=True)
    _WORKSPACE = _BINARY = None


atexit.register(_cleanup)


def _child_limits() -> None:
    for kind, limit in (
        (resource.RLIMIT_CPU, 60),
        (resource.RLIMIT_AS, 4 * 1024**3),
        (resource.RLIMIT_FSIZE, 64 * 1024**2),
        (resource.RLIMIT_NOFILE, 128),
    ):
        soft, hard = resource.getrlimit(kind)
        if soft != resource.RLIM_INFINITY:
            limit = min(limit, soft)
        if hard != resource.RLIM_INFINITY:
            limit = min(limit, hard)
        resource.setrlimit(kind, (limit, limit))


def _environment(workspace: Path) -> dict[str, str]:
    return {
        "PATH": os.defpath,
        "HOME": str(workspace),
        "TMPDIR": str(workspace),
        "GOENV": "off",
        "GO111MODULE": "off",
        "GOWORK": "off",
        "GOTOOLCHAIN": "local",
        "GOPROXY": "off",
        "GOSUMDB": "off",
        "GOFLAGS": "",
        "CGO_ENABLED": "0",
        "GOCACHE": str(workspace / "cache"),
        "GOPATH": str(workspace / "gopath"),
        "GOMAXPROCS": "2",
        "GOMEMLIMIT": "256MiB",
    }


def _run_bounded(
    command: list[str], workspace: Path, input_bytes: bytes, timeout: int,
) -> bytes:
    """Drain both pipes with a shared hard output cap and kill the process group."""
    input_path = workspace / f"request-{uuid.uuid4().hex}.json"
    try:
        input_path.write_bytes(input_bytes)
        with input_path.open("rb") as stdin:
            process = subprocess.Popen(
                command, cwd=workspace, env=_environment(workspace),
                stdin=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                shell=False, start_new_session=True, preexec_fn=_child_limits,
            )
        output = bytearray()
        size = 0
        deadline = time.monotonic() + timeout
        try:
            with selectors.DefaultSelector() as selector:
                assert process.stdout is not None and process.stderr is not None
                selector.register(process.stdout, selectors.EVENT_READ, True)
                selector.register(process.stderr, selectors.EVENT_READ, False)
                while selector.get_map():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise GoProviderError("Go helper timed out")
                    for key, _ in selector.select(min(remaining, 0.1)):
                        chunk = os.read(key.fd, 65536)
                        if not chunk:
                            selector.unregister(key.fileobj)
                            continue
                        size += len(chunk)
                        if size > _OUTPUT_LIMIT:
                            raise GoProviderError("Go helper output limit exceeded")
                        if key.data:
                            output.extend(chunk)
                try:
                    status = process.wait(timeout=max(0.001, deadline - time.monotonic()))
                except subprocess.TimeoutExpired as error:
                    raise GoProviderError("Go helper timed out") from error
                if status:
                    raise GoProviderError(f"Go helper exited with status {status}")
        finally:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
            if process.stdout is not None:
                process.stdout.close()
            if process.stderr is not None:
                process.stderr.close()
        return bytes(output)
    finally:
        input_path.unlink(missing_ok=True)


def _helper() -> tuple[Path, Path]:
    global _WORKSPACE, _BINARY
    if os.name != "posix":
        raise GoProviderError("bounded Go provider requires a POSIX host")
    tool = shutil.which("go")
    if tool is None:
        raise GoProviderError("optional Go toolchain is unavailable")
    with _LOCK:
        if _BINARY is not None and _WORKSPACE is not None:
            return _BINARY, _WORKSPACE
        # Never use target modules, ambient Go configuration, or shared binaries.
        workspace = Path(f".reachable-audit-go-{uuid.uuid4().hex}")
        workspace.mkdir(mode=0o700)
        workspace = workspace.resolve()
        try:
            source = workspace / "helper.go"
            source.write_bytes(Path(__file__).with_name("go_hotspots.go").read_bytes())
            binary = workspace / "helper"
            _run_bounded(
                [str(Path(tool).resolve()), "build", "-trimpath", "-o", str(binary), str(source)],
                workspace, b"", _BUILD_TIMEOUT,
            )
        except Exception:
            shutil.rmtree(workspace, ignore_errors=True)
            raise
        _WORKSPACE, _BINARY = workspace, binary
        return binary, workspace


def scan_go_bytes(
    sources: dict[str, bytes], *, max_candidates: int,
) -> list[dict[str, Any]]:
    """Parse a single verified, bounded Work Unit batch in one helper process."""
    if (
        max_candidates < 1 or len(sources) > MAX_GO_FILES
        or any(len(source) > MAX_GO_FILE_BYTES for source in sources.values())
        or sum(map(len, sources.values())) > MAX_GO_TOTAL_BYTES
        or any(len(path.encode("utf-8")) > 4096 for path in sources)
    ):
        raise GoProviderError("Go parser input limit exceeded")
    try:
        binary, workspace = _helper()
        payload = json.dumps({
            "files": [
                {"path": path, "source": base64.b64encode(source).decode("ascii")}
                for path, source in sorted(sources.items())
            ],
            "limit": min(max_candidates, MAX_GO_CANDIDATES),
        }).encode("utf-8")
        output = _run_bounded([str(binary)], workspace, payload, _PARSE_TIMEOUT)
        results = json.loads(output)
        if not isinstance(results, list) or len(results) != len(sources):
            raise GoProviderError("invalid Go helper response")
        seen = set()
        retained = 0
        for result in results:
            if not isinstance(result, dict) or result.get("path") not in sources:
                raise GoProviderError("invalid Go helper response")
            path = result["path"]
            count = result.get("count")
            candidates = result.get("candidates")
            if (
                path in seen or type(count) is not int or count < 0
                or not isinstance(candidates, list) or len(candidates) > count
                or ("error" in result and not isinstance(result["error"], str))
            ):
                raise GoProviderError("invalid Go helper response")
            seen.add(path)
            for candidate in candidates:
                if (
                    not isinstance(candidate, dict) or candidate.get("path") != path
                    or type(candidate.get("line")) is not int or candidate["line"] < 1
                    or type(candidate.get("column")) is not int or candidate["column"] < 1
                    or candidate.get("api") not in {
                        "os/exec.Command", "os/exec.CommandContext", "io.ReadAll",
                        "io/ioutil.ReadAll", "path.Join", "path.Clean",
                        "path/filepath.Join", "path/filepath.Clean",
                        "path/filepath.Abs", "path/filepath.Rel",
                    }
                ):
                    raise GoProviderError("invalid Go helper response")
            retained += len(candidates)
        if retained > min(max_candidates, MAX_GO_CANDIDATES):
            raise GoProviderError("invalid Go helper response")
        return results
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        raise GoProviderError(f"Go provider failed: {type(error).__name__}") from error
