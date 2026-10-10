"""The two hello packages, from the command line and from Python."""

from pathlib import Path

import pytest
from httk.core.cli import CLIContext
from httk.workflow import Workspace
from httk.workflow.introspection import resolve_job
from httk.workflow.workflow_cli import command

from conftest import REPO_ROOT, register_ws, run_idle, run_one


@pytest.mark.parametrize("directory", ("hello", "hello-bash"))
def test_hello_greets_the_named_parameter(tmp_path: Path, directory: str) -> None:
    workspace = Workspace.initialize(tmp_path / "workspace")
    ref, payload = run_one(workspace, REPO_ROOT / directory, parameters={"name": "Ada"})
    assert ref.state == "succeeded"
    assert (payload / "run" / "greeting.txt").read_text(encoding="utf-8") == "Hello, Ada!\n"


@pytest.mark.parametrize("directory", ("hello", "hello-bash"))
def test_hello_runs_from_the_command_line_with_its_default(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], directory: str
) -> None:
    workspace = Workspace.initialize(tmp_path / "workspace")
    name = register_ws(workspace.root)
    arguments = ["job", "new", "--install", "--workspace", name, "--workflow-dir", str(REPO_ROOT / directory)]
    assert command(arguments, CLIContext("httk", tmp_path)) == 0
    key, _ready = capsys.readouterr().out.strip().split("\t")
    run_idle(workspace)
    # The printed path is where the job was submitted; it moves as it runs.
    assert (resolve_job(workspace, key).path / "run" / "greeting.txt").read_text(encoding="utf-8") == "Hello, world!\n"
