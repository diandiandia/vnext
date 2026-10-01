from pathlib import Path
import sys

SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SOURCE_ROOT))

from reachable_audit.analysis_models import Applicability, AxisRun, DiscoveryAxis


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
) -> tuple[AxisRun, ...]:
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
		)
		for axis, refs in sorted(evidence.items())
	)