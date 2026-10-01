from pathlib import Path

import pytest

from reachable_audit.artifacts import ArtifactIntegrityError, ArtifactStore


def test_artifacts_are_content_addressed_and_deduplicated(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    first = store.put_text("edge proof\n")
    second = store.put_text("edge proof\n")

    assert first == second
    assert store.get_bytes(first.artifact_id) == b"edge proof\n"
    assert len(list((tmp_path / "artifacts").glob("*/*"))) == 1


def test_artifact_corruption_is_detected(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    artifact = store.put_bytes(b"original")
    (tmp_path / "artifacts" / artifact.relative_path).write_bytes(b"modified")

    with pytest.raises(ArtifactIntegrityError):
        store.get_bytes(artifact.artifact_id)
