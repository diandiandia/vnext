"""Optional real-project acceptance; the signed manifest stays outside the repo."""

import os
import json
from pathlib import Path

import pytest

from reachable_audit.evaluation import evaluate_release


def test_external_heldout_bundle_passes_implemented_checks() -> None:
    manifest_value = os.environ.get("VNA_HELDOUT_SIGNED_MANIFEST")
    signing_key = os.environ.get("VNA_EVALUATION_HMAC_KEY")
    if not manifest_value:
        pytest.skip("protected real held-out manifest is not configured")
    if not signing_key:
        pytest.fail("VNA_EVALUATION_HMAC_KEY is required with a held-out manifest")

    manifest_path = Path(manifest_value).resolve()
    repository_root = Path(__file__).resolve().parents[1]
    if repository_root == manifest_path or repository_root in manifest_path.parents:
        pytest.fail("held-out manifest must remain outside the vNext runtime repository")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    report = evaluate_release(manifest, signing_key=signing_key.encode("utf-8"))

    assert report["implemented_subset_status"] == "PASS", report["gates"]
    assert report["status"] == "BLOCKED"
    assert report["eligible_for_promotion"] is False
    assert report["unimplemented_gates"] == ["RG12", "RG13", "RG14", "RG15"]