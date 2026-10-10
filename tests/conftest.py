"""Shared fixtures and helpers for the workflows-examples test suite.

The isolation fixtures and the normal/extended test-depth knob are those of
workflows-vasp's ``tests/conftest.py``. The helpers run jobs the way a user
does: :func:`httk.workflow.scaffold.new_job` on a package directory, installing
it into the workspace first (what ``httk job new --install --workflow-dir``
calls), and a real
:class:`httk.workflow.TaskManager` until the workspace is idle.
"""

import json
import logging
import os
import shutil
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from httk.workflow import TaskManager, Workspace
from httk.workflow.introspection import read_state, resolve_job
from httk.workflow.protocol import JobRef
from httk.workflow.registry import register_workspace
from httk.workflow.scaffold import new_job

# Several tests import httk.atomistic (NumPy) while short-lived runner
# processes are spawned; one BLAS/OMP thread each keeps that cheap.
for _thread_limit in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_thread_limit, "1")

REPO_ROOT = Path(__file__).resolve().parent.parent
MOCK_VASP = Path(__file__).resolve().parent / "mock_vasp.py"
PACKAGES = (
    "hello",
    "hello-bash",
    "two-step",
    "two-step-bash",
    "vasp-relax-annotated",
    "vasp-relax-bash-annotated",
    "fan-out",
    "compose",
    "subworkflow",
    "subworkflow-bash",
    "subworkflow-child",
    "chain",
    "chain-rust",
    "chain-leaf",
)
# Packages whose runner is a compiled binary built by `httk workflow build`,
# with the executables their build needs.
COMPILED = {"chain-rust": ("cargo", "make")}

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


def run_one(workspace: Workspace, workflow: Any, **job: Any) -> tuple[JobRef, Path]:
    """Install *workflow*, create one job of it, run the workspace to idle, and return the job and its payload."""

    created = new_job(workspace, workflow, install=True, **job)
    run_idle(workspace)
    ref = resolve_job(workspace, created.job_id)
    return ref, ref.path


def failure(ref: JobRef) -> Any:
    """The job's recorded failure (``code``, ``message``, ``details``), or ``None``."""

    state, damaged = read_state(ref)
    assert damaged is None, damaged
    return None if state is None else state.failure


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


@pytest.fixture
def installed_examples(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    """Install this working tree as the ``workflows-examples`` plugin in the isolated data home.

    That is what ``httk plugin install`` of this repository does, and it makes
    every package's workflow name resolve on this machine, including inside the
    runner processes a manager starts (they inherit ``HTTK_DATA_HOME``). Only
    the packages and the plugin manifest are copied, not tests or caches.
    This test process caches plugin discovery, so the cache is cleared around
    the test (with the helper httk-workflow provides for tests).
    """

    from httk.core.plugins import install_plugin
    from httk.workflow.packages import _reset_plugin_workflow_cache

    source = tmp_path_factory.mktemp("plugin-source") / "workflows-examples"
    source.mkdir()
    for directory in PACKAGES:
        ignore = shutil.ignore_patterns("__pycache__", "target", "Cargo.lock")
        shutil.copytree(REPO_ROOT / directory, source / directory, ignore=ignore)
    shutil.copy2(REPO_ROOT / "httk_plugin.toml", source)
    install_plugin(source)
    _reset_plugin_workflow_cache()
    yield
    _reset_plugin_workflow_cache()


def require_toolchain(directory: str) -> None:
    """Skip the calling test when the compiled package *directory* cannot be built here."""

    missing = [tool for tool in COMPILED[directory] if shutil.which(tool) is None]
    if missing:
        pytest.skip(f"{directory} needs {', '.join(missing)}")
