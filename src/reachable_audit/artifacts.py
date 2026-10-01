"""Content-addressed artifact storage."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import tempfile


class ArtifactIntegrityError(RuntimeError):
    """Raised when stored bytes do not match their content address."""


@dataclass(frozen=True)
class ArtifactRef:
    artifact_id: str
    relative_path: str
    size: int


class ArtifactStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def put_bytes(self, data: bytes) -> ArtifactRef:
        digest = hashlib.sha256(data).hexdigest()
        relative = Path(digest[:2]) / digest
        destination = self.root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            descriptor, temporary = tempfile.mkstemp(
                prefix=f".{digest}.", dir=destination.parent
            )
            try:
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(data)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, destination)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        return ArtifactRef(
            artifact_id=f"sha256:{digest}",
            relative_path=relative.as_posix(),
            size=len(data),
        )

    def put_text(self, text: str) -> ArtifactRef:
        return self.put_bytes(text.encode("utf-8"))

    def get_bytes(self, artifact_id: str) -> bytes:
        algorithm, separator, digest = artifact_id.partition(":")
        if separator != ":" or algorithm != "sha256" or len(digest) != 64:
            raise ValueError(f"unsupported artifact id: {artifact_id}")
        path = self.root / digest[:2] / digest
        data = path.read_bytes()
        actual = hashlib.sha256(data).hexdigest()
        if actual != digest:
            raise ArtifactIntegrityError(
                f"artifact digest mismatch: expected {digest}, got {actual}"
            )
        return data
