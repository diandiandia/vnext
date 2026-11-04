import json
from pathlib import Path

import pytest

from reachable_audit.domain_guidance import POLICY, domain_context, record_domain_selection
from reachable_audit.execution import DiscoveryCoordinator, ManualExecutionBackend
from reachable_audit.models import ModelError
from test_batch_workflow import _workflow


def test_guidance_selected_by_explicit_evidence_and_bounded_task_input(tmp_path: Path):
    manager, workflow, plan = _workflow(tmp_path, constraints=(POLICY,))
    try:
        unit = plan.work_units[0].work_unit_id
        assert domain_context(workflow, unit)["selection_status"] == "not_assessed"
        selection = {"domain_id": "ai_agent", "work_unit_id": unit,
                     "reason": "inspect context-to-tool boundary", "evidence_refs": ["LOC-app.py:1"]}
        ref = record_domain_selection(workflow, selection)
        assert record_domain_selection(workflow, selection) == ref
        assert set(domain_context(workflow, unit)["blocks"]) == {"ai_agent"}
        workflow.run_r0()
        coordinator = DiscoveryCoordinator(workflow, ManualExecutionBackend(manager, workflow.campaign_id))
        view, = coordinator.schedule_r1()
        value = json.loads(manager.artifacts.get_bytes(view.task.input_refs[0]))
        assert set(value["domain_guidance"][unit]["blocks"]) == {"ai_agent"}
        assert "data_lifecycle" not in value["domain_guidance"][unit]["blocks"]
        record_domain_selection(workflow, {**selection, "domain_id": "data_lifecycle"})
        assert set(domain_context(workflow, unit)["blocks"]) == {"ai_agent", "data_lifecycle"}
        # R1 task is immutable even though later R2 can receive the refined selection.
        assert coordinator.schedule_r1()[0].task == view.task
    finally:
        manager.close()


@pytest.mark.parametrize("field,value", [
    ("domain_id", "unknown"), ("work_unit_id", "WU-absent"), ("reason", ""),
    ("evidence_refs", ["LOC-app.py:99999"]), ("evidence_refs", ["symbolic"]),
])
def test_domain_selection_rejects_missing_or_invalid_evidence(tmp_path: Path, field, value):
    manager, workflow, plan = _workflow(tmp_path, constraints=(POLICY,))
    try:
        selection = {"domain_id": "ai_agent", "work_unit_id": plan.work_units[0].work_unit_id,
                     "reason": "source-evidenced boundary", "evidence_refs": ["LOC-app.py:1"]}
        with pytest.raises(ModelError):
            record_domain_selection(workflow, {**selection, field: value})
    finally:
        manager.close()
