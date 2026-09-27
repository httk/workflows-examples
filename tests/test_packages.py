"""Every package directory loads, matches its own runner, and is listed by the plugin."""

import json
import os

import pytest
from httk.core.plugins.manifest import parse_plugin_manifest
from httk.workflow.packages import load_workflow_package
from httk.workflow.scaffold import describe_runner

from conftest import PACKAGES, REPO_ROOT


@pytest.mark.parametrize("directory", PACKAGES)
def test_package_loads_and_its_steps_equal_the_runners_own_description(directory: str) -> None:
    provider = load_workflow_package(REPO_ROOT / directory, register=False)
    # Every package names a descriptive entry (run.py or run.sh), which the
    # manifest records as the one-element runner command; no bare `run` remains.
    (command,) = provider.command
    entry = REPO_ROOT / directory / command.removeprefix("{package}/")
    assert entry.suffix in {".py", ".sh"}
    assert not (REPO_ROOT / directory / "run").exists()
    assert os.access(entry, os.X_OK)
    described = describe_runner(entry)
    assert set(described["steps"]) == set(provider.steps)
    assert described["workflow"] == provider.workflow_id == f"examples.{directory}"


@pytest.mark.parametrize("directory", PACKAGES)
def test_package_members_are_executable_where_they_must_be(directory: str) -> None:
    provider = load_workflow_package(REPO_ROOT / directory, register=False)
    for script in provider.postprocess_scripts.values():
        assert os.access(REPO_ROOT / directory / script["file"], os.X_OK)
    instantiate = REPO_ROOT / directory / "instantiate"
    assert not instantiate.exists() or os.access(instantiate, os.X_OK)


@pytest.mark.parametrize("directory", ("vasp-relax-annotated", "vasp-relax-bash-annotated"))
def test_the_two_vasp_definitions_share_one_declaration(directory: str) -> None:
    provider = load_workflow_package(REPO_ROOT / directory, register=False)
    declared = json.loads((REPO_ROOT / directory / "declaration.json").read_text(encoding="utf-8"))
    assert provider.declarations["workflow"] == declared
    assert declared == json.loads((REPO_ROOT / "vasp-relax-annotated" / "declaration.json").read_text(encoding="utf-8"))
    assert provider.inputs == {"structure": None}  # consumed by the instantiate hook
    assert set(provider.outputs) == {"relaxed_structure", "total_energy"}


def test_plugin_manifest_lists_every_package() -> None:
    assert set(parse_plugin_manifest(REPO_ROOT).workflows) == set(PACKAGES)
