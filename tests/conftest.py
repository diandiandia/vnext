from pathlib import Path
import sys

SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SOURCE_ROOT))

from reachable_audit.analysis_models import (
	Applicability,
	AxisRun,
	DiscoveryAxis,
	ReviewAltitude,
)


def execution_configuration_fixture() -> dict[str, str]:
	return {
		"model_id": "test-model",
		"runtime_version": "test-runtime/1",
		"host_tool_policy_digest": "sha256:" + "a" * 64,
	}


def axis_runs_from_evidence(
	evidence: dict[str, tuple[str, ...]],
	*,
	not_applicable: tuple[str, ...] = (),
	review_altitudes: dict[str, str] | None = None,
) -> tuple[AxisRun, ...]:
	review_altitudes = review_altitudes or {}
	return tuple(
		AxisRun(
			axis=DiscoveryAxis(axis),
			applicability=(
				Applicability.NOT_APPLICABLE
				if axis in not_applicable else Applicability.APPLICABLE
			),
			evidence_refs=refs,
			rationale=(
				"axis is not applicable to this fixture"
				if axis in not_applicable else "axis was explicitly reviewed"
			),
			review_altitude=ReviewAltitude(
				review_altitudes.get(axis, ReviewAltitude.NOT_RECORDED.value)
			),
		)
		for axis, refs in sorted(evidence.items())
	)