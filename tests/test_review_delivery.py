import json
from pathlib import Path

import pytest

from reachable_audit.analysis_models import Adjudication, AdjudicationActor, VerdictKind
from reachable_audit.deferred_review import (
    batch_review_queue, record_review_delivery, validate_review_delivery,
)
from reachable_audit.models import ModelError
from test_deferred_review import _workflow, _refute


def _delivery():
    return {
        "blockers": ["The identity scope of the external owner policy is not observed."],
        "validation_plan": {"owner": "Observe the bound identity and policy on the declared deployment without sending test traffic."},
        "investigation_urgency": "P2",
        "priority_rationale": "The source path exists but current authority and reachability are not established.",
    }


@pytest.mark.parametrize("change", [
    {"severity": "HIGH"}, {"blockers": []}, {"blockers": [" "]},
    {"validation_plan": {}}, {"validation_plan": {"local": None}},
    {"validation_plan": {"remote": "probe production"}},
    {"investigation_urgency": "HIGH"}, {"priority_rationale": ""},
])
def test_review_delivery_rejects_empty_or_severity_shaped_input(change):
    with pytest.raises(ModelError):
        validate_review_delivery({**_delivery(), **change})


def test_delivery_is_bound_to_current_unresolved_evidence(tmp_path: Path):
    manager, workflow, _ = _workflow(tmp_path, deferred=True)
    try:
        _refute(workflow)
        workflow.record_adjudication(Adjudication(
            "ADJ-delivery", "HYP-split", ("REF-call", "REF-premise"),
            VerdictKind.NEEDS_REVIEW, AdjudicationActor.AUTO, None,
            "the external owner premise remains unobserved",
        ))
        packet, = batch_review_queue(workflow)
        assert packet["delivery_status"] == "NOT_RECORDED"
        ref = record_review_delivery(workflow, "HYP-split", _delivery(), actor="operator")
        assert record_review_delivery(workflow, "HYP-split", _delivery(), actor="operator") == ref
        current, = batch_review_queue(workflow)
        assert current["delivery"] == _delivery()
        assert "severity" not in current["delivery"]
        assert current["r3_verdict"] == packet["r3_verdict"]
        assert json.loads(manager.artifacts.get_bytes(ref)) == _delivery()
        with pytest.raises(ModelError, match="current unresolved"):
            record_review_delivery(workflow, "absent", _delivery(), actor="operator")
    finally:
        manager.close()
