"""examples.chain: Python calls Rust calls Python, through declared calls.

The Rust middle is a compiled package. Each package declares what it calls in
``[workflow.calls]``, so a chain job is left unclaimed until chain-rust is
built, and ``httk workflow build examples.chain`` builds it transitively (what
a user runs once per machine). The test skips when cargo or make is missing.
All three names resolve through this working tree installed as a plugin (the
``installed_examples`` fixture).
"""

import json
from pathlib import Path

import pytest
from httk.core.cli import CLIContext
from httk.workflow import Workspace
from httk.workflow._calls import reset_call_readiness
from httk.workflow.precheck import precheck_jobs
from httk.workflow.scaffold import new_job
from httk.workflow.workflow_cli import command

from conftest import register_ws, require_toolchain, run_idle

DECLARATIONS = "https://example.org/httk/workflows-examples/declarations"


@pytest.mark.usefixtures("installed_examples")
def test_the_trail_propagates_up_a_python_rust_python_chain(tmp_path: Path) -> None:
    require_toolchain("chain-rust")
    workspace = Workspace.initialize(tmp_path / "workspace")
    name = register_ws(workspace.root)
    # Managers cache which declared calls are ready; start from a clean slate.
    reset_call_readiness()
    created = new_job(workspace, "examples.chain")
    job = json.loads((created.payload / "job.json").read_text(encoding="utf-8"))
    assert job["calls"] == {"middle": "examples.chain-rust"}

    # chain-rust is declared but not built here: the job is never claimed, and
    # precheck (what `httk job why` / `httk workflow precheck` report) says why.
    run_idle(workspace)
    marker = workspace.find_marker_by_id(created.job_id)
    assert marker is not None and marker.kind in {"submitted", "ready"}
    (finding,) = [item for item in precheck_jobs(workspace) if item["job_id"] == created.job_id]
    assert "not built" in str(finding["calls"]) and "examples.chain-rust" in str(finding["calls"])

    # Building the top workflow by name builds everything it declares it calls.
    assert command(["build", "--workspace", name, "examples.chain"], CLIContext("httk", tmp_path)) == 0
    reset_call_readiness()
    run_idle(workspace)

    marker = workspace.find_marker_by_id(created.job_id)
    assert marker is not None and marker.kind == "succeeded", workspace.read_state(marker).get("failure")
    payload = workspace.payload_path(marker.placement, marker.job_key)
    assert (payload / "run" / "trail.txt").read_text(encoding="utf-8") == (
        "examples.chain-leaf (Python)\nexamples.chain-rust (Rust)\nexamples.chain (Python)\n"
    )

    # Three jobs, one tree: the leaf is the Rust job's child, the Rust job ours.
    jobs = {}
    for found in workspace.scan_markers():
        assert found.kind == "succeeded", workspace.read_state(found).get("failure")
        job = json.loads((workspace.payload_path(found.placement, found.job_key) / "job.json").read_text())
        jobs[job["workflow"]] = job
    assert set(jobs) == {"examples.chain", "examples.chain-rust", "examples.chain-leaf"}
    assert jobs["examples.chain-rust"]["parent"]["job_id"] == jobs["examples.chain"]["id"]
    assert jobs["examples.chain-leaf"]["parent"]["job_id"] == jobs["examples.chain-rust"]["id"]
    for workflow, job in jobs.items():
        short = workflow.removeprefix("examples.")
        assert job["declarations"]["workflow"]["$id"] == f"{DECLARATIONS}/{short}"
