from __future__ import annotations

import os
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from reachable_audit.campaign import CampaignManager
from reachable_audit.experiments import safe_artifacts
from reachable_audit.experiments.safe_artifacts import (
    SafeArtifactCapabilityError,
    SafeArtifactError,
    SafeArtifactPromoter,
)


pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX directory-fd API required")


def _promoter(source: Path, destination: Path, **kwargs: object) -> SafeArtifactPromoter:
    return SafeArtifactPromoter(
        source,
        destination,
        allowed_paths=kwargs.pop("allowed_paths", ["nested/item.bin"]),
        max_file_bytes=kwargs.pop("max_file_bytes", 32),
        max_total_bytes=kwargs.pop("max_total_bytes", 64),
        **kwargs,
    )


def test_promotes_allowlisted_regular_file_with_noninheritable_roots(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    (source / "nested").mkdir(parents=True)
    (destination / "nested").mkdir(parents=True)
    (source / "nested/item.bin").write_bytes(b"evidence")

    with _promoter(source, destination) as promoter:
        assert all(not os.get_inheritable(fd) for fd in promoter.root_descriptors)
        assert promoter.promote("nested/item.bin") == 8
        assert promoter.total_bytes == 8
    assert (destination / "nested/item.bin").read_bytes() == b"evidence"


@pytest.mark.parametrize("kind", ["parent", "leaf"])
def test_rejects_symlink_parent_or_leaf_without_creating_destination(
    tmp_path: Path, kind: str,
) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    outside = tmp_path / "outside"
    (source / "nested").mkdir(parents=True)
    (destination / "nested").mkdir(parents=True)
    outside.mkdir()
    (outside / "item.bin").write_bytes(b"outside")
    if kind == "parent":
        (source / "nested").rmdir()
        (source / "nested").symlink_to(outside, target_is_directory=True)
    else:
        (source / "nested/item.bin").symlink_to(outside / "item.bin")

    with _promoter(source, destination) as promoter, pytest.raises(OSError):
        promoter.promote("nested/item.bin")
    assert not (destination / "nested/item.bin").exists()


def test_fifo_is_opened_nonblocking_then_rejected(tmp_path: Path) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    (source / "nested").mkdir(parents=True)
    (destination / "nested").mkdir(parents=True)
    os.mkfifo(source / "nested/item.bin")

    with _promoter(source, destination) as promoter:
        with pytest.raises(SafeArtifactError, match="regular file"):
            promoter.promote("nested/item.bin")
    assert not (destination / "nested/item.bin").exists()


def test_rejects_hardlinked_source(tmp_path: Path) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    (source / "nested").mkdir(parents=True)
    (destination / "nested").mkdir(parents=True)
    item = source / "nested/item.bin"
    item.write_bytes(b"linked")
    os.link(item, source / "second-link")

    with _promoter(source, destination) as promoter:
        with pytest.raises(SafeArtifactError, match="exactly one link"):
            promoter.promote("nested/item.bin")
    assert not (destination / "nested/item.bin").exists()


def test_per_file_and_cumulative_limits_are_enforced(tmp_path: Path) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    (source / "nested").mkdir(parents=True)
    (destination / "nested").mkdir(parents=True)
    (source / "nested/item.bin").write_bytes(b"12345")
    (source / "nested/next.bin").write_bytes(b"1234")

    with _promoter(
        source,
        destination,
        allowed_paths=["nested/item.bin", "nested/next.bin"],
        max_file_bytes=4,
        max_total_bytes=6,
    ) as promoter:
        with pytest.raises(SafeArtifactError, match="per-file"):
            promoter.promote("nested/item.bin")
        (source / "nested/item.bin").write_bytes(b"123")
        assert promoter.promote("nested/item.bin") == 3
        with pytest.raises(SafeArtifactError, match="cumulative"):
            promoter.promote("nested/next.bin")
        assert promoter.total_bytes == 3
    assert not (destination / "nested/next.bin").exists()


def test_growth_during_copy_is_bounded_and_partial_destination_is_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    (source / "nested").mkdir(parents=True)
    (destination / "nested").mkdir(parents=True)
    item = source / "nested/item.bin"
    item.write_bytes(b"abc")
    original_read = safe_artifacts.os.read
    changed = False

    def grow_before_read(descriptor: int, count: int) -> bytes:
        nonlocal changed
        if not changed:
            changed = True
            with item.open("ab") as writer:
                writer.write(b"de")
        return original_read(descriptor, count)

    monkeypatch.setattr(safe_artifacts.os, "read", grow_before_read)
    with _promoter(source, destination, max_file_bytes=4, max_total_bytes=4) as promoter:
        with pytest.raises(SafeArtifactError, match="grew"):
            promoter.promote("nested/item.bin")
        assert promoter.total_bytes == 0
    assert not (destination / "nested/item.bin").exists()


def test_destination_conflict_is_never_overwritten_or_removed(tmp_path: Path) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    (source / "nested").mkdir(parents=True)
    (destination / "nested").mkdir(parents=True)
    (source / "nested/item.bin").write_bytes(b"source")
    existing = destination / "nested/item.bin"
    existing.write_bytes(b"keep")

    with _promoter(source, destination) as promoter:
        with pytest.raises(FileExistsError):
            promoter.promote("nested/item.bin")
    assert existing.read_bytes() == b"keep"


@pytest.mark.parametrize("kind", ["parent", "leaf"])
def test_destination_symlinks_are_not_followed(
    tmp_path: Path, kind: str,
) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    outside = tmp_path / "outside"
    (source / "nested").mkdir(parents=True)
    (destination / "nested").mkdir(parents=True)
    outside.mkdir()
    (source / "nested/item.bin").write_bytes(b"source")
    (outside / "item.bin").write_bytes(b"preserve")
    if kind == "parent":
        (destination / "nested").rmdir()
        (destination / "nested").symlink_to(outside, target_is_directory=True)
    else:
        (destination / "nested/item.bin").symlink_to(outside / "item.bin")

    with _promoter(source, destination) as promoter, pytest.raises(OSError):
        promoter.promote("nested/item.bin")
    assert (outside / "item.bin").read_bytes() == b"preserve"


def test_rejects_nonallowlisted_and_unsafe_relative_paths(tmp_path: Path) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    (source / "nested").mkdir(parents=True)
    (destination / "nested").mkdir(parents=True)

    with _promoter(source, destination) as promoter:
        for path in ("other.bin", "../escape", "/absolute", "nested//item.bin"):
            with pytest.raises(SafeArtifactError):
                promoter.promote(path)


def test_unsupported_isolation_platform_fails_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(safe_artifacts.platform, "system", lambda: "Darwin")
    with pytest.raises(SafeArtifactCapabilityError, match="unavailable on this platform"):
        safe_artifacts.require_linux_bwrap_isolation()


def test_unsupported_safe_transfer_platform_fails_explicitly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(safe_artifacts, "os", SimpleNamespace(name="nt"))
    with pytest.raises(SafeArtifactCapabilityError, match="requires POSIX"):
        safe_artifacts.require_safe_transfer_support()


def test_available_bwrap_probe_still_blocks_until_complete_policy_is_qualified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ProbeResult:
        returncode = 0
        stderr = b""

    calls: list[list[str]] = []

    def trusted_probe(command: list[str], **_: object) -> ProbeResult:
        calls.append(command)
        return ProbeResult()

    monkeypatch.setattr(safe_artifacts.platform, "system", lambda: "Linux")
    monkeypatch.setattr(safe_artifacts.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(safe_artifacts.subprocess, "run", trusted_probe)
    with pytest.raises(SafeArtifactCapabilityError, match="no qualified complete host policy"):
        safe_artifacts.require_linux_bwrap_isolation()
    assert calls == [[
        "/usr/bin/bwrap", "--unshare-all", "--die-with-parent",
        "--", "/usr/bin/true",
    ]]


def test_runner_explicit_isolation_blocker_never_runs_requested_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from reachable_audit.campaign import CampaignManager
    from reachable_audit.experiments.runner import run_harness
    from reachable_audit.resource_cleanup import cleanup_campaign_resources

    target = tmp_path / "target"
    target.mkdir()
    manager = CampaignManager(target)
    manager.create_campaign(campaign_id="CMP-isolation-blocked", snapshot_id="fixture:isolation")
    marker = target / "should-not-exist"

    def blocked() -> None:
        raise SafeArtifactCapabilityError("fixture capability blocker; no command was executed")

    monkeypatch.setattr(
        "reachable_audit.experiments.runner.require_linux_bwrap_isolation", blocked
    )
    try:
        with pytest.raises(SafeArtifactCapabilityError, match="fixture capability blocker"):
            run_harness(
                manager,
                "CMP-isolation-blocked",
                command=[sys.executable, "-c", f"open({str(marker)!r}, 'w').close()"],
                isolation="linux-bwrap",
            )
        assert not marker.exists()
    finally:
        cleanup_campaign_resources(manager, "CMP-isolation-blocked")
        manager.close()


def test_host_capability_status_is_explicit_and_never_runs_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def blocked() -> None:
        raise SafeArtifactCapabilityError("host validation unavailable")

    monkeypatch.setattr(safe_artifacts, "require_linux_bwrap_isolation", blocked)
    status = safe_artifacts.host_isolation_status()
    assert status["linux_bwrap_isolation"] == {
        "available": False,
        "reason": "host validation unavailable",
    }
    assert status["target_execution_attempted"] is False


def test_host_capabilities_cli_needs_no_target_or_state(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from reachable_audit.cli import main

    assert main(["host-capabilities"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert set(status) == {
        "safe_artifact_transfer",
        "linux_bwrap_isolation",
        "target_execution_attempted",
    }
    assert status["target_execution_attempted"] is False
    assert isinstance(status["safe_artifact_transfer"]["available"], bool)
    assert isinstance(status["linux_bwrap_isolation"]["available"], bool)


def test_cli_isolation_flag_reports_capability_block_without_execution(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from reachable_audit.cli import main

    target = tmp_path / "target"
    target.mkdir()
    with CampaignManager(target) as manager:
        manager.create_campaign(
            campaign_id="CMP-cli-isolation", snapshot_id="fixture:cli-isolation"
        )
    marker = target / "should-not-exist"
    input_path = tmp_path / "harness.json"
    input_path.write_text(
        json.dumps({
            "command": [sys.executable, "-c", f"open({str(marker)!r}, 'w').close()"],
        }),
        encoding="utf-8",
    )

    def blocked() -> None:
        raise SafeArtifactCapabilityError("host validation unavailable")

    monkeypatch.setattr(
        "reachable_audit.experiments.runner.require_linux_bwrap_isolation", blocked
    )
    assert main([
        "harness-run", str(target), "CMP-cli-isolation",
        "--input", str(input_path), "--isolation", "linux-bwrap",
    ]) == 2
    assert "host validation unavailable" in capsys.readouterr().err
    assert not marker.exists()


def test_runner_uses_private_capture_even_when_runtime_paths_are_fifo(
    tmp_path: Path,
) -> None:
    from reachable_audit.campaign import CampaignManager
    from reachable_audit.experiments.runner import run_harness
    from reachable_audit.resource_cleanup import cleanup_campaign_resources

    target = tmp_path / "target"
    target.mkdir()
    manager = CampaignManager(target)
    manager.create_campaign(campaign_id="CMP-safe-capture", snapshot_id="fixture:safe-capture")
    try:
        result = run_harness(
            manager,
            "CMP-safe-capture",
            command=[
                sys.executable,
                "-c",
                "import os, pathlib, sys; "
                "root = pathlib.Path(os.environ['VNA_HARNESS_TMP']); "
                "(root / 'stdout.bin').unlink(missing_ok=True); "
                "(root / 'stderr.bin').unlink(missing_ok=True); "
                "(root / 'outside.bin').write_bytes(b'not stdout'); "
                "os.symlink(root / 'outside.bin', root / 'stdout.bin'); "
                "os.mkfifo(root / 'stderr.bin'); "
                "print('captured'); print('captured error', file=sys.stderr)",
            ],
        )
        assert manager.artifacts.get_bytes(str(result["stdout_artifact_id"])) == b"captured\n"
        assert manager.artifacts.get_bytes(str(result["stderr_artifact_id"])) == b"captured error\n"
        assert result["exit_code"] == 0
    finally:
        cleanup_campaign_resources(manager, "CMP-safe-capture")
        manager.close()
