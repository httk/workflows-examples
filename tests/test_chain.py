"""examples.chain: Python calls Rust calls Python, all by name.

The Rust middle is a compiled package: the test builds and registers it in the
workspace with ``httk workflow build`` (what a user runs once per machine) and
skips when cargo or make is missing. All three names resolve through this
working tree installed as a plugin (the ``installed_examples`` fixture).
"""

import json
from pathlib import Path

import pytest
from httk.core.cli import CLIContext
from httk.workflow import Workspace
from httk.workflow.workflow_cli import command

from conftest import REPO_ROOT, register_ws, require_toolchain, run_one

DECLARATIONS = "https://example.org/httk/workflows-examples/declarations"


@pytest.mark.usefixtures("installed_examples")
def test_the_trail_propagates_up_a_python_rust_python_chain(tmp_path: Path) -> None:
    require_toolchain("chain-rust")
    workspace = Workspace.initialize(tmp_path / "workspace")
    name = register_ws(workspace.root)
    # Register the Rust binary; the registration is keyed by the source
    # digest, so it serves the plugin's installed copy of the same sources.
    assert command(["build", "--workspace", name, str(REPO_ROOT / "chain-rust")], CLIContext("httk", tmp_path)) == 0

    marker, payload = run_one(workspace, REPO_ROOT / "chain")
    assert marker.kind == "succeeded", workspace.read_state(marker).get("failure")
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
