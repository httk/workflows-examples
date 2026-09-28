"""The two two-step packages: a file through the workdir, a value through job state."""

from pathlib import Path

import pytest
from httk.workflow import Workspace

from conftest import REPO_ROOT, job_state, run_one


@pytest.mark.parametrize("directory", ("two-step", "two-step-bash"))
def test_two_step_hands_a_file_and_a_state_value_to_the_second_step(tmp_path: Path, directory: str) -> None:
    workspace = Workspace.initialize(tmp_path / "workspace")
    marker, payload = run_one(workspace, REPO_ROOT / directory, parameters={"text": "to be or not to be"})
    assert marker.kind == "succeeded", workspace.read_state(marker).get("failure")
    # Step one's file, still in the persistent workdir ...
    assert (payload / "run" / "words.txt").read_text(encoding="utf-8") == "to\nbe\nor\nnot\nto\nbe\n"
    # ... and its value in job state, stored as a JSON number.
    assert job_state(payload) == {"word_count": 6}
    # Step two read both.
    assert (payload / "run" / "report.txt").read_text(encoding="utf-8") == "6 words; the longest is 'not'\n"


@pytest.mark.parametrize("directory", ("two-step", "two-step-bash"))
def test_two_step_runs_with_its_default_text(tmp_path: Path, directory: str) -> None:
    workspace = Workspace.initialize(tmp_path / "workspace")
    marker, payload = run_one(workspace, REPO_ROOT / directory)
    assert marker.kind == "succeeded", workspace.read_state(marker).get("failure")
    assert (payload / "run" / "report.txt").read_text(encoding="utf-8") == "9 words; the longest is 'quick'\n"
