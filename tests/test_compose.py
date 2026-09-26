"""examples.compose: calls the hello package of this repository by git URI.

The repository may not be committed (or pushed) yet, so the test commits a
snapshot of the working tree into a temporary git repository and hands the
compose workflow its ``git+file://`` URI instead of the default GitHub one.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from httk.workflow import Workspace

from conftest import PACKAGES, REPO_ROOT, run_one


@pytest.fixture
def snapshot_uri(tmp_path: Path) -> str:
    """Commit this working tree's packages into a fresh repository and return the hello URI."""

    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    repository = tmp_path / "workflows-examples"
    repository.mkdir()
    for directory in PACKAGES:
        shutil.copytree(REPO_ROOT / directory, repository / directory, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy2(REPO_ROOT / "httk_plugin.toml", repository)

    def git(*arguments: str) -> None:
        subprocess.run(
            ["git", "-c", "user.name=test", "-c", "user.email=test@example.org", *arguments],
            cwd=repository,
            check=True,
            capture_output=True,
        )

    git("init", "-q")
    git("add", ".")
    git("commit", "-q", "-m", "snapshot")
    return f"git+file://{repository}#hello"


def test_compose_calls_hello_by_git_uri_and_uses_its_greeting(tmp_path: Path, snapshot_uri: str) -> None:
    workspace = Workspace.initialize(tmp_path / "workspace")
    marker, payload = run_one(
        workspace, REPO_ROOT / "compose", parameters={"hello_workflow": snapshot_uri, "name": "Grace"}
    )
    assert marker.kind == "succeeded", workspace.read_state(marker).get("failure")
    composed = (payload / "run" / "composed.txt").read_text(encoding="utf-8")
    assert composed == "The hello workflow said: Hello, Grace!\n"

    # The child is an ordinary job of the called workflow, pinned to the commit.
    (child,) = [found for found in workspace.scan_markers() if found.job_key.startswith("hello--")]
    assert child.kind == "succeeded"
    child_job = json.loads((workspace.payload_path(child.placement, child.job_key) / "job.json").read_text())
    assert re.fullmatch(re.escape(snapshot_uri.split("#")[0]) + r"@[0-9a-f]{40}#hello", child_job["workflow"])
