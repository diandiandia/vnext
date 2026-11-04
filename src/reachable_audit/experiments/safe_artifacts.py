"""POSIX directory-fd artifact transfer primitives.

The caller must stop and confirm every possible writer before promotion. The
metadata checks and byte limits below detect many races, but cannot make
concurrent mutation safe or prove that a writer has quiesced.
"""

from __future__ import annotations

import os
from pathlib import Path
import platform
import shutil
import stat
import subprocess
import threading
from typing import BinaryIO, Iterable


class SafeArtifactError(ValueError):
    """Artifact transfer failed a path, type, identity, or size check."""


class SafeArtifactCapabilityError(RuntimeError):
    """The host lacks a required safe-transfer or isolation capability."""


def host_isolation_status() -> dict[str, object]:
    """Return host capability results without running target code."""
    try:
        require_safe_transfer_support()
        transfer: dict[str, object] = {"available": True, "reason": None}
    except SafeArtifactCapabilityError as error:
        transfer = {"available": False, "reason": str(error)}
    try:
        require_linux_bwrap_isolation()
    except SafeArtifactCapabilityError as error:
        isolation: dict[str, object] = {
            "available": False,
            "reason": str(error),
        }
    else:
        isolation = {"available": True, "reason": None}
    return {
        "safe_artifact_transfer": transfer,
        "linux_bwrap_isolation": isolation,
        "target_execution_attempted": False,
    }


def require_safe_transfer_support() -> None:
    if os.name != "posix" or not all(
        hasattr(os, flag) for flag in ("O_NOFOLLOW", "O_DIRECTORY", "O_NONBLOCK", "O_CLOEXEC")
    ):
        raise SafeArtifactCapabilityError(
            "safe artifact transfer requires POSIX directory-fd and no-follow support"
        )
    if not all(
        (os.open in os.supports_dir_fd, os.stat in os.supports_dir_fd,
         os.unlink in os.supports_dir_fd)
    ) or os.stat not in os.supports_follow_symlinks:
        raise SafeArtifactCapabilityError(
            "safe artifact transfer requires openat/statat/unlinkat no-follow support"
        )


class SafeArtifactPromoter:
    """Copy allowlisted files between trusted roots without following links.

    Both roots must be created and controlled by the trusted coordinator.
    Destination parents must already exist and must not be writable by the
    untrusted worker. Existing destination leaves are never overwritten.
    """

    def __init__(
        self,
        source_root: str | os.PathLike[str],
        destination_root: str | os.PathLike[str],
        *,
        allowed_paths: Iterable[str],
        max_file_bytes: int,
        max_total_bytes: int,
    ) -> None:
        require_safe_transfer_support()
        if type(max_file_bytes) is not int or max_file_bytes <= 0:
            raise SafeArtifactError("max_file_bytes must be a positive integer")
        if type(max_total_bytes) is not int or max_total_bytes <= 0:
            raise SafeArtifactError("max_total_bytes must be a positive integer")
        paths = frozenset(_validate_relative_path(path) for path in allowed_paths)
        if not paths:
            raise SafeArtifactError("at least one allowlisted relative path is required")
        self._allowed_paths = paths
        self._max_file_bytes = max_file_bytes
        self._max_total_bytes = max_total_bytes
        self._total_bytes = 0
        self._lock = threading.Lock()
        self._source_fd = _open_root(source_root)
        try:
            self._destination_fd = _open_root(destination_root)
        except BaseException:
            os.close(self._source_fd)
            raise
        self._closed = False

    @property
    def total_bytes(self) -> int:
        with self._lock:
            return self._total_bytes

    @property
    def root_descriptors(self) -> tuple[int, int]:
        """Return the retained descriptors for diagnostics and capability tests."""
        with self._lock:
            self._ensure_open()
            return self._source_fd, self._destination_fd

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._closed = True
                os.close(self._source_fd)
                os.close(self._destination_fd)

    def __enter__(self) -> SafeArtifactPromoter:
        self._ensure_open()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def promote(
        self,
        relative_path: str,
        *,
        destination_path: str | None = None,
    ) -> int:
        """Promote one regular, single-link file and return its copied size."""
        with self._lock:
            return self._promote_locked(
                relative_path, destination_path=destination_path
            )

    def _promote_locked(
        self,
        relative_path: str,
        *,
        destination_path: str | None,
    ) -> int:
        self._ensure_open()
        source_name = _validate_relative_path(relative_path)
        if source_name not in self._allowed_paths:
            raise SafeArtifactError("source path is not allowlisted")
        destination_name = _validate_relative_path(destination_path or source_name)

        source_parent, source_leaf = _open_parent(self._source_fd, source_name)
        try:
            destination_parent, destination_leaf = _open_parent(
                self._destination_fd, destination_name
            )
        except BaseException:
            os.close(source_parent)
            raise
        source_fd = -1
        destination_fd = -1
        created_identity: tuple[int, int] | None = None
        created = False
        try:
            source_fd = _open_leaf(source_parent, source_leaf, os.O_RDONLY)
            initial = os.fstat(source_fd)
            _check_regular_single_link(initial)
            remaining_total = self._max_total_bytes - self._total_bytes
            if initial.st_size > self._max_file_bytes:
                raise SafeArtifactError("source exceeds the per-file byte limit")
            if initial.st_size > remaining_total:
                raise SafeArtifactError("source exceeds the cumulative byte limit")

            destination_fd = os.open(
                destination_leaf,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
                | os.O_CLOEXEC,
                0o600,
                dir_fd=destination_parent,
            )
            os.set_inheritable(destination_fd, False)
            destination_stat = os.fstat(destination_fd)
            _check_regular_single_link(destination_stat)
            created_identity = (destination_stat.st_dev, destination_stat.st_ino)
            created = True

            copied = 0
            while True:
                allowance = min(
                    self._max_file_bytes - copied,
                    remaining_total - copied,
                )
                chunk = os.read(source_fd, min(64 * 1024, allowance + 1))
                if not chunk:
                    break
                if len(chunk) > allowance:
                    raise SafeArtifactError("source grew beyond an artifact byte limit")
                _write_all(destination_fd, chunk)
                copied += len(chunk)

            final_source = os.fstat(source_fd)
            _check_regular_single_link(final_source)
            if copied != initial.st_size or _source_identity(initial) != _source_identity(final_source):
                raise SafeArtifactError("source changed while it was being copied")
            final_destination = os.fstat(destination_fd)
            _check_regular_single_link(final_destination)
            if (
                final_destination.st_dev != created_identity[0]
                or final_destination.st_ino != created_identity[1]
                or final_destination.st_size != copied
            ):
                raise SafeArtifactError("destination changed while it was being written")
            named_destination = os.stat(
                destination_leaf,
                dir_fd=destination_parent,
                follow_symlinks=False,
            )
            _check_regular_single_link(named_destination)
            if (
                named_destination.st_dev != created_identity[0]
                or named_destination.st_ino != created_identity[1]
                or named_destination.st_size != copied
            ):
                raise SafeArtifactError("destination name no longer identifies the created file")
            self._total_bytes += copied
            return copied
        except BaseException:
            if created and created_identity is not None:
                _unlink_if_same(destination_parent, destination_leaf, created_identity)
            raise
        finally:
            for descriptor in (source_fd, destination_fd, source_parent, destination_parent):
                if descriptor >= 0:
                    os.close(descriptor)

    def _ensure_open(self) -> None:
        if self._closed:
            raise SafeArtifactError("artifact promoter is closed")


def read_bounded_capture(stream: BinaryIO, limit_bytes: int) -> tuple[bytes, bool]:
    """Read an anonymous/pre-opened capture by descriptor, never by its pathname."""
    if type(limit_bytes) is not int or limit_bytes <= 0:
        raise SafeArtifactError("capture limit must be a positive integer")
    descriptor = stream.fileno()
    before = os.fstat(descriptor)
    if not stat.S_ISREG(before.st_mode):
        raise SafeArtifactError("captured output is not a regular file")
    stream.seek(0)
    data = stream.read(limit_bytes + 1)
    after = os.fstat(descriptor)
    if (
        not stat.S_ISREG(after.st_mode)
        or after.st_ino != before.st_ino
        or after.st_dev != before.st_dev
    ):
        raise SafeArtifactError("captured output changed identity while being read")
    if (
        after.st_size != before.st_size
        or after.st_mtime_ns != before.st_mtime_ns
        or after.st_ctime_ns != before.st_ctime_ns
    ):
        raise SafeArtifactError("captured output changed while being read")
    return data[:limit_bytes], len(data) > limit_bytes or after.st_size > limit_bytes


def require_linux_bwrap_isolation() -> None:
    """Fail closed until the complete host isolation profile is qualified.

    A trusted ``true`` probe distinguishes unavailable user namespaces from a
    missing executable. Even a successful probe is not a guarantee of
    filesystem, network, environment, or aggregate resource containment.
    """
    if platform.system() != "Linux":
        raise SafeArtifactCapabilityError(
            "linux-bwrap isolation is unavailable on this platform; no command was executed"
        )
    bwrap = shutil.which("bwrap")
    trusted_true = shutil.which("true")
    if bwrap is None or trusted_true is None:
        raise SafeArtifactCapabilityError(
            "linux-bwrap isolation requires bubblewrap and a trusted true executable; "
            "no command was executed"
        )
    try:
        probe = subprocess.run(
            [bwrap, "--unshare-all", "--die-with-parent", "--", trusted_true],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            env={"PATH": os.defpath},
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise SafeArtifactCapabilityError(
            f"linux-bwrap namespace capability probe failed: {error}; no target command was executed"
        ) from error
    if probe.returncode != 0:
        detail = probe.stderr.decode("utf-8", errors="replace").strip()
        raise SafeArtifactCapabilityError(
            "linux-bwrap namespace capability is unavailable"
            + (f": {detail}" if detail else "")
            + "; no target command was executed"
        )
    raise SafeArtifactCapabilityError(
        "linux-bwrap is present, but this runner has no qualified complete host policy "
        "for filesystem, network, environment, and aggregate resource isolation; "
        "no target command was executed"
    )


def _validate_relative_path(value: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise SafeArtifactError("artifact path must be a non-empty relative path")
    path = Path(value)
    if path.is_absolute():
        raise SafeArtifactError("artifact path must be relative")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise SafeArtifactError("artifact path contains an unsafe component")
    return "/".join(parts)


def _open_root(path: str | os.PathLike[str]) -> int:
    descriptor = os.open(
        os.fspath(path),
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    try:
        os.set_inheritable(descriptor, False)
        if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise SafeArtifactError("trusted artifact root is not a directory")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _open_parent(root_fd: int, relative_path: str) -> tuple[int, str]:
    parts = relative_path.split("/")
    descriptor = os.dup(root_fd)
    os.set_inheritable(descriptor, False)
    try:
        for component in parts[:-1]:
            next_descriptor = os.open(
                component,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=descriptor,
            )
            os.set_inheritable(next_descriptor, False)
            if not stat.S_ISDIR(os.fstat(next_descriptor).st_mode):
                os.close(next_descriptor)
                raise SafeArtifactError("artifact parent is not a directory")
            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor, parts[-1]
    except BaseException:
        os.close(descriptor)
        raise


def _open_leaf(parent_fd: int, leaf: str, access: int) -> int:
    descriptor = os.open(
        leaf,
        access | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
        dir_fd=parent_fd,
    )
    os.set_inheritable(descriptor, False)
    return descriptor


def _check_regular_single_link(value: os.stat_result) -> None:
    if not stat.S_ISREG(value.st_mode) or value.st_nlink != 1:
        raise SafeArtifactError("artifact must be a regular file with exactly one link")


def _source_identity(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        stat.S_IFMT(value.st_mode),
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _write_all(descriptor: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise SafeArtifactError("could not complete artifact write")
        view = view[written:]


def _unlink_if_same(parent_fd: int, leaf: str, identity: tuple[int, int]) -> None:
    try:
        current = os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
        if (current.st_dev, current.st_ino) == identity:
            os.unlink(leaf, dir_fd=parent_fd)
    except FileNotFoundError:
        pass
