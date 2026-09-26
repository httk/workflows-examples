"""Shared fixtures and helpers for the workflows-examples test suite.

The isolation fixtures and the normal/extended test-depth knob are those of
workflows-vasp's ``tests/conftest.py``. The helpers run jobs the way a user
does: :func:`httk.workflow.scaffold.new_job` on a package directory (what
``httk job new --workflow-dir`` calls) and a real
:class:`httk.workflow.TaskManager` until the workspace is idle.
"""

import json
import logging
import os
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from httk.workflow import TaskManager, Workspace
from httk.workflow.models import Marker
from httk.workflow.registry import register_workspace
from httk.workflow.scaffold import new_job

# Several tests import httk.atomistic (NumPy) while short-lived runner
# processes are spawned; one BLAS/OMP thread each keeps that cheap.
for _thread_limit in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_thread_limit, "1")

REPO_ROOT = Path(__file__).resolve().parent.parent
MOCK_VASP = Path(__file__).resolve().parent / "mock_vasp.py"
PACKAGES = ("hello", "hello-bash", "vasp-relax-annotated", "vasp-relax-bash-annotated", "fan-out", "compose")

SILICON = """silicon
1.0
2.0 0.0 0.0
0.0 2.0 0.0
0.0 0.0 2.0
Si
2
Direct
0.0000000000 0.0000000000 0.0000000000
0.5000000000 0.5000000000 0.5000000000
"""


@pytest.fixture(autouse=True)
def _isolated_httk_config(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    """Give every test its own httk config and data home, and no inherited VASP command."""

    monkeypatch.setenv("HTTK_CONFIG_HOME", str(tmp_path_factory.mktemp("httk-config")))
    monkeypatch.setenv("HTTK_DATA_HOME", str(tmp_path_factory.mktemp("httk-store")))
    # HTTK_VASP_COMMAND wins over the workspace setting; a machine exporting it
    # must never run a real VASP from these tests.
    monkeypatch.delenv("HTTK_VASP_COMMAND", raising=False)


@pytest.fixture(autouse=True)
def _isolated_workflow_logging() -> Iterator[None]:
    """Restore the ``httk.workflow`` logger after every test."""

    logger = logging.getLogger("httk.workflow")
    propagate, handlers, level = logger.propagate, list(logger.handlers), logger.level
    yield
    logger.propagate = propagate
    logger.handlers[:] = handlers
    logger.setLevel(level)


@dataclass(frozen=True)
class TestProfile:
    """Select normal or full-depth values without duplicating a test body."""

    name: str

    @property
    def extended(self) -> bool:
        return self.name == "extended"


@pytest.fixture(scope="session", autouse=True)
def test_profile() -> TestProfile:
    """``HTTK_TEST_PROFILE=extended`` selects the full-depth runs; normal is the default."""

    name = os.environ.get("HTTK_TEST_PROFILE", "normal")
    if name not in {"normal", "extended"}:
        raise pytest.UsageError("HTTK_TEST_PROFILE must be 'normal' or 'extended'")
    return TestProfile(name)


def register_ws(path: object, name: str = "ws") -> str:
    """Register *path* under *name* in the (isolated) machine registry and return the name."""

    register_workspace(name, str(path))
    return name


def mock_vasp_workspace(root: Path) -> Workspace:
    """A workspace whose ``vasp.command`` setting names the mock VASP beside this file."""

    workspace = Workspace.initialize(root)
    workspace.set_setting("vasp.command", f"{sys.executable} {MOCK_VASP}")
    return workspace


def run_one(workspace: Workspace, workflow: object, **job: Any) -> tuple[Marker, Path]:
    """Create one job with :func:`new_job`, run the workspace to idle, and return its marker and payload."""

    created = new_job(workspace, workflow, **job)
    run_idle(workspace)
    marker = workspace.find_marker_by_id(created.job_id)
    assert marker is not None
    return marker, workspace.payload_path(marker.placement, marker.job_key)


def run_idle(workspace: Workspace) -> None:
    """Run a real task manager until nothing is left to do."""

    with TaskManager(workspace, heartbeat_interval=0.01) as manager:
        manager.run_until_idle(timeout=300.0)


def job_state(payload: Path) -> dict[str, Any]:
    """The job state a runner wrote with ``a.state`` / ``advance(state=...)``."""

    path = payload / ".httk-job" / "state.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def job_parameters(payload: Path) -> dict[str, Any]:
    """The parameters recorded in the job's ``job.json``."""

    return json.loads((payload / "job.json").read_text(encoding="utf-8"))["parameters"]
