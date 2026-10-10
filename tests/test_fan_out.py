"""examples.fan-out: children are spawned, gathered, and aggregated."""

import json
from pathlib import Path

from httk.workflow import Workspace
from httk.workflow.introspection import iter_jobs

from conftest import REPO_ROOT, failure, run_one


def _children(workspace: Workspace, parent: str) -> dict[str, str]:
    """Map each child's tag to its terminal kind."""

    return {ref.job_key.split("--")[0]: ref.state for ref in iter_jobs(workspace) if ref.job_key != parent}


def test_fan_out_spawns_one_child_per_value_and_sums_their_squares(tmp_path: Path) -> None:
    workspace = Workspace.initialize(tmp_path / "workspace")
    ref, payload = run_one(workspace, REPO_ROOT / "fan-out", parameters={"values": [2, 3, 4]})
    assert ref.state == "succeeded"
    summary = json.loads((payload / "run" / "summary.json").read_text(encoding="utf-8"))
    assert summary["sum_of_squares"] == 4 + 9 + 16
    assert summary["children"]["value-1"] == {"value": 3, "square": 9}
    assert _children(workspace, ref.job_key) == {
        "value-0": "succeeded",
        "value-1": "succeeded",
        "value-2": "succeeded",
    }


def test_children_read_the_parents_workdir_in_place(tmp_path: Path) -> None:
    workspace = Workspace.initialize(tmp_path / "workspace")
    ref, payload = run_one(workspace, REPO_ROOT / "fan-out", parameters={"values": [2, 3], "scale": 10})
    assert ref.state == "succeeded"
    # The parent wrote common.json once; each child read it through a.parent.
    assert json.loads((payload / "run" / "common.json").read_text(encoding="utf-8")) == {"scale": 10}
    summary = json.loads((payload / "run" / "summary.json").read_text(encoding="utf-8"))
    assert summary["sum_of_squares"] == 40 + 90


def test_a_failing_child_routes_the_parent_to_report_failures(tmp_path: Path) -> None:
    workspace = Workspace.initialize(tmp_path / "workspace")
    ref, _payload = run_one(workspace, REPO_ROOT / "fan-out", parameters={"values": [1, "two"]})
    assert ref.state == "failed"
    recorded = failure(ref)
    assert recorded["code"] == "examples.children_failed"
    assert recorded["details"]["failed"] == {"value-1": "examples.not_a_number"}
