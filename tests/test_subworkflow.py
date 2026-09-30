"""The two subworkflow packages call examples.subworkflow-child by name.

The child is resolved by name inside the parent's runner process, so these
tests install this working tree as a plugin first (the ``installed_examples``
fixture), exactly as ``httk plugin install`` would; nothing uses the network.
Collecting the finished tree into a store (``httk collect --into``)
then leaves one linked run per job; that needs *httk-store* and is skipped
without it.
"""

import json
from pathlib import Path

import pytest
from httk.core import Run
from httk.core.cli import CLIContext
from httk.workflow import Workspace
from httk.workflow.models import Marker
from httk.workflow.workflow_cli import command

from conftest import REPO_ROOT, register_ws, run_one

PARENTS = ("subworkflow", "subworkflow-bash")
CHILD = "examples.subworkflow-child"
DECLARATIONS = "https://example.org/httk/workflows-examples/declarations"


def _children(workspace: Workspace, parent: Marker) -> dict[str, Marker]:
    """Every job in the workspace other than *parent*, by its tag (the call's label)."""

    return {
        marker.job_key.split("--")[0]: marker for marker in workspace.scan_markers() if marker.job_key != parent.job_key
    }


def _job(workspace: Workspace, marker: Marker) -> dict[str, object]:
    return json.loads((workspace.payload_path(marker.placement, marker.job_key) / "job.json").read_text())


def _aggregated(directory: str, payload: Path) -> tuple[dict[str, tuple[str, float]], float]:
    """The parent's aggregate output: ``{label: (job_key, root)}`` and the sum of roots."""

    run = payload / "run"
    if directory == "subworkflow":
        summary = json.loads((run / "summary.json").read_text(encoding="utf-8"))
        children = {label: (child["job_key"], child["root"]) for label, child in summary["children"].items()}
        return children, summary["sum_of_roots"]
    rows = [line.split("\t") for line in (run / "summary.tsv").read_text(encoding="utf-8").splitlines()]
    children = {label: (job_key, float(root)) for label, job_key, root in rows}
    return children, float((run / "sum_of_roots.txt").read_text(encoding="utf-8"))


@pytest.mark.usefixtures("installed_examples")
@pytest.mark.parametrize("directory", PARENTS)
def test_parent_calls_the_child_workflow_per_value_and_sums_their_roots(tmp_path: Path, directory: str) -> None:
    workspace = Workspace.initialize(tmp_path / "workspace")
    marker, payload = run_one(workspace, REPO_ROOT / directory, parameters={"values": [4, 9, 16]})
    assert marker.kind == "succeeded", workspace.read_state(marker).get("failure")

    # Each call is an ordinary job of the *called* workflow, carrying that
    # workflow's own declaration, not the parent's.
    children = _children(workspace, marker)
    assert set(children) == {"value-0", "value-1", "value-2"}
    for child in children.values():
        assert child.kind == "succeeded"
        job = _job(workspace, child)
        assert job["workflow"] == CHILD
        declarations = job["declarations"]
        assert isinstance(declarations, dict)
        assert declarations["workflow"]["$id"] == (
            "https://example.org/httk/workflows-examples/declarations/subworkflow-child"
        )
    # The parent's job recorded its declared calls at creation.
    assert _job(workspace, marker)["calls"] == {"child": CHILD}
    parent_declarations = _job(workspace, marker)["declarations"]
    assert isinstance(parent_declarations, dict)
    assert parent_declarations["workflow"]["$id"] == (
        f"https://example.org/httk/workflows-examples/declarations/{directory}"
    )

    # The aggregate step listed exactly those children through a.children /
    # httk_workflow_children, with their job keys, and read their results.
    aggregated, total = _aggregated(directory, payload)
    assert {label: job_key for label, (job_key, _root) in aggregated.items()} == {
        label: child.job_key for label, child in children.items()
    }
    assert {label: root for label, (_key, root) in aggregated.items()} == {
        "value-0": 2.0,
        "value-1": 3.0,
        "value-2": 4.0,
    }
    assert total == 9.0


@pytest.mark.usefixtures("installed_examples")
@pytest.mark.parametrize("directory", PARENTS)
def test_a_failing_call_routes_the_parent_to_report_failures(tmp_path: Path, directory: str) -> None:
    workspace = Workspace.initialize(tmp_path / "workspace")
    marker, _payload = run_one(workspace, REPO_ROOT / directory, parameters={"values": [1, -1]})
    assert marker.kind == "failed"
    failure = workspace.read_state(marker)["failure"]
    assert failure["code"] == "examples.calls_failed"
    if directory == "subworkflow":
        assert failure["details"]["failed"] == {"value-1": "examples.negative_value"}
    else:
        assert failure["message"] == "called workflow(s) failed: value-1: examples.negative_value"
    kinds = {label: child.kind for label, child in _children(workspace, marker).items()}
    assert kinds == {"value-0": "succeeded", "value-1": "failed"}


@pytest.mark.usefixtures("installed_examples")
def test_the_child_runs_on_its_own_by_name(tmp_path: Path) -> None:
    workspace = Workspace.initialize(tmp_path / "workspace")
    marker, payload = run_one(workspace, CHILD, parameters={"value": 2.25})
    assert marker.kind == "succeeded", workspace.read_state(marker).get("failure")
    assert (payload / "run" / "root.txt").read_text(encoding="utf-8") == "1.5\n"


def _collect_runs(tmp_path: Path, workspace: Workspace, *extra: str) -> list[Run]:
    """Run ``httk collect --into`` on the workspace and read the stored runs back."""

    from httk.store import Backend, SqlStore

    context = CLIContext("httk", tmp_path)
    store = tmp_path / "runs.sqlite"
    arguments = ["collect", "--workspace", register_ws(workspace.root), "--into", str(store)]
    # --no-id-ledger: store-minted ids are fine for a throwaway store.
    arguments += ["--id-base", "examples.test", "--no-id-ledger", *extra]
    assert command(arguments, context) == 0
    with Backend.sqlite(store) as database:
        searcher = SqlStore(database).searcher()
        return [row.run for row in searcher.results(run=searcher.variable(Run))]


@pytest.mark.usefixtures("installed_examples")
@pytest.mark.parametrize("directory", PARENTS)
def test_collecting_stores_one_linked_run_per_job(tmp_path: Path, directory: str) -> None:
    pytest.importorskip("httk.store")
    workspace = Workspace.initialize(tmp_path / "workspace")
    marker, _payload = run_one(workspace, REPO_ROOT / directory, parameters={"values": [1, 4]})
    assert marker.kind == "succeeded", workspace.read_state(marker).get("failure")

    runs = _collect_runs(tmp_path, workspace)
    # One run per job, each naming the declaration of the workflow it ran.
    assert len(runs) == 3
    (parent,) = [run for run in runs if run.workflow_declaration_uri == f"{DECLARATIONS}/{directory}"]
    children = [run for run in runs if run.workflow_declaration_uri == f"{DECLARATIONS}/subworkflow-child"]
    assert len(children) == 2
    # The parent's run names each child's run, labelled by the call's label.
    assert sorted((edge.label, edge.entry_type) for edge in parent.artifacts) == [
        ("value-0", "runs"),
        ("value-1", "runs"),
    ]
    assert {edge.entry_id for edge in parent.artifacts} == {child.id for child in children}


@pytest.mark.usefixtures("installed_examples")
@pytest.mark.parametrize("directory", PARENTS)
def test_bare_runs_can_be_opted_out_of(tmp_path: Path, directory: str) -> None:
    pytest.importorskip("httk.store")
    workspace = Workspace.initialize(tmp_path / "workspace")
    marker, _payload = run_one(workspace, REPO_ROOT / directory, parameters={"values": [1]})
    assert marker.kind == "succeeded", workspace.read_state(marker).get("failure")
    # Neither workflow has a collector or declared outputs: nothing else to store.
    assert _collect_runs(tmp_path, workspace, "--no-bare-runs") == []
