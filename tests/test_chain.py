"""examples.chain: Python calls Rust calls Python, through declared calls.

The Rust middle is a compiled package. Each package declares what it calls in
``[workflow.calls]``, and installing the top workflow installs the whole chain.
A chain job is left unclaimed until chain-rust is built: ``httk workflow
install`` builds it unless told not to (``--no-build``), and ``httk workflow
build`` builds it later (what a user runs once per machine). The test skips
when cargo or make is missing. All three names resolve through this working
tree installed as a plugin (the ``installed_examples`` fixture).
"""

import json
from pathlib import Path

import pytest
from httk.core.cli import CLIContext
from httk.workflow import Workspace
from httk.workflow.introspection import iter_jobs, resolve_job
from httk.workflow.precheck import precheck_jobs
from httk.workflow.scaffold import new_job
from httk.workflow.workflow_cli import command

from conftest import failure, register_ws, require_toolchain, run_idle

DECLARATIONS = "https://example.org/httk/workflows-examples/declarations"


@pytest.mark.usefixtures("installed_examples")
def test_the_trail_propagates_up_a_python_rust_python_chain(tmp_path: Path) -> None:
    require_toolchain("chain-rust")
    workspace = Workspace.initialize(tmp_path / "workspace")
    name = register_ws(workspace.root)
    context = CLIContext("httk", tmp_path)
    # Installing the top workflow installs what it declares it calls, transitively.
    assert command(["install", "--no-build", "--workspace", name, "examples.chain"], context) == 0
    created = new_job(workspace, "examples.chain")

    # chain-rust is installed but not built here: the job is never claimed, and
    # precheck (what `httk job why` / `httk workflow precheck` report) says why.
    run_idle(workspace)
    assert resolve_job(workspace, created.job_id).state == "ready"
    (finding,) = [item for item in precheck_jobs(workspace) if item["job_id"] == created.job_id]
    assert "not built" in str(finding["calls"]) and "examples.chain-rust" in str(finding["calls"])

    assert command(["build", "--workspace", name, "examples.chain-rust"], context) == 0
    run_idle(workspace)

    ref = resolve_job(workspace, created.job_id)
    assert ref.state == "succeeded", failure(ref)
    assert (ref.path / "run" / "trail.txt").read_text(encoding="utf-8") == (
        "examples.chain-leaf (Python)\nexamples.chain-rust (Rust)\nexamples.chain (Python)\n"
    )

    # Three jobs, one tree: the leaf is the Rust job's child, the Rust job ours.
    jobs = {}
    for found in iter_jobs(workspace):
        assert found.state == "succeeded", failure(found)
        job = json.loads((found.path / "job.json").read_text())
        jobs[job["workflow"]["name"]] = job
    assert set(jobs) == {"examples.chain", "examples.chain-rust", "examples.chain-leaf"}
    assert jobs["examples.chain-rust"]["parent"]["job_id"] == jobs["examples.chain"]["id"]
    assert jobs["examples.chain-leaf"]["parent"]["job_id"] == jobs["examples.chain-rust"]["id"]
    for workflow, job in jobs.items():
        short = workflow.removeprefix("examples.")
        assert job["declarations"]["workflow"]["$id"] == f"{DECLARATIONS}/{short}"
