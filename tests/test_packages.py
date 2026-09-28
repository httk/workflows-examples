"""Every package directory loads, matches its own runner, and is listed by the plugin."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import httk.workflow
import pytest
from httk.core.plugins.manifest import parse_plugin_manifest
from httk.workflow.packages import load_workflow_package
from httk.workflow.scaffold import describe_package_runner, describe_runner

from conftest import COMPILED, PACKAGES, REPO_ROOT, require_toolchain

SCRIPTED = tuple(directory for directory in PACKAGES if directory not in COMPILED)


@pytest.mark.parametrize("directory", SCRIPTED)
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


@pytest.mark.parametrize("directory", sorted(COMPILED))
def test_compiled_package_builds_and_its_steps_equal_the_binarys_own_description(
    tmp_path: Path, directory: str
) -> None:
    require_toolchain(directory)
    provider = load_workflow_package(REPO_ROOT / directory, register=False)
    # Build a copy in place, as `httk workflow build` does in its own copy.
    build = tmp_path / directory
    shutil.copytree(REPO_ROOT / directory, build, ignore=shutil.ignore_patterns("target", "Cargo.lock"))
    languages = Path(httk.workflow.__file__).parent / "languages"
    environment = {**os.environ, "HTTK_WORKFLOW_LANGUAGES_DIR": str(languages)}
    completed = subprocess.run(["make"], cwd=build, env=environment, capture_output=True, text=True, check=False)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    described = describe_package_runner(build, artifacts=build)
    assert set(described["steps"]) == set(provider.steps)
    assert described["workflow"] == provider.workflow_id == f"examples.{directory}"


def test_plugin_manifest_lists_every_package() -> None:
    assert set(parse_plugin_manifest(REPO_ROOT).workflows) == set(PACKAGES)


@pytest.mark.parametrize(
    "directory",
    (
        "two-step",
        "two-step-bash",
        "subworkflow",
        "subworkflow-bash",
        "subworkflow-child",
        "chain",
        "chain-rust",
        "chain-leaf",
    ),
)
def test_package_carries_its_own_declaration(directory: str) -> None:
    # Each of these packages declares itself under its own $id, so a parent
    # job and the jobs it calls each reference their own workflow declaration.
    provider = load_workflow_package(REPO_ROOT / directory, register=False)
    declared = json.loads((REPO_ROOT / directory / "declaration.json").read_text(encoding="utf-8"))
    assert declared["$id"] == f"https://example.org/httk/workflows-examples/declarations/{directory}"
    assert provider.declaration_uri == declared["$id"]
    assert provider.declarations["workflow"] == declared
