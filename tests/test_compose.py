"""examples.compose: calls the hello package of this repository.

By default compose declares ``examples.hello`` by name, which resolves through
this working tree installed as a plugin (the ``installed_examples`` fixture).
A call may also name a commit-pinned git URI. The repository may not be
committed (or pushed) yet, so that test commits a snapshot of the working tree
into a temporary git repository and declares its pinned ``git+file://`` URI in
a copy of compose.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from httk.workflow import Workspace
from httk.workflow.introspection import iter_jobs

from conftest import PACKAGES, REPO_ROOT, failure, run_one


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
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repository, check=True, capture_output=True, text=True
    ).stdout.strip()
    return f"git+file://{repository}@{commit}#hello"


def _composed(workspace: Workspace, compose: Path) -> dict[str, object]:
    """Run compose to idle, check its composed greeting, and return the called child's ``job.json``."""

    ref, payload = run_one(workspace, compose, parameters={"name": "Grace"})
    assert ref.state == "succeeded", failure(ref)
    composed = (payload / "run" / "composed.txt").read_text(encoding="utf-8")
    assert composed == "The hello workflow said: Hello, Grace!\n"

    # The child is an ordinary job of the called workflow.
    (child,) = [found for found in iter_jobs(workspace) if found.job_key.startswith("hello--")]
    assert child.state == "succeeded"
    return json.loads((child.path / "job.json").read_text())


@pytest.mark.usefixtures("installed_examples")
def test_compose_calls_hello_and_uses_its_greeting(tmp_path: Path) -> None:
    workspace = Workspace.initialize(tmp_path / "workspace")
    assert _composed(workspace, REPO_ROOT / "compose")["workflow"] == {
        "id": "local:examples.hello",
        "name": "examples.hello",
    }


def test_compose_calls_hello_by_commit_pinned_git_uri(tmp_path: Path, snapshot_uri: str) -> None:
    compose = tmp_path / "compose"
    shutil.copytree(REPO_ROOT / "compose", compose, ignore=shutil.ignore_patterns("__pycache__"))
    manifest = compose / "httk_workflow.toml"
    text = manifest.read_text(encoding="utf-8")
    assert 'hello = "examples.hello"' in text
    manifest.write_text(text.replace('hello = "examples.hello"', f'hello = "{snapshot_uri}"'), encoding="utf-8")
    workspace = Workspace.initialize(tmp_path / "workspace")
    # Installing compose fetched and installed the called workflow under its pinned URI.
    workflow = _composed(workspace, compose)["workflow"]
    assert isinstance(workflow, dict)
    assert workflow["id"] == snapshot_uri
