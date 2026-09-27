"""The two annotated VASP relaxations, end to end against the mock VASP.

Both packages implement one declared workflow, so every test runs both: the
Python package with the in-process ``instantiate.py`` hook and the Bash
package with the executable ``instantiate`` hook.
"""

import json
from pathlib import Path
from typing import Any

import httk.core
import pytest
from httk.atomistic import UnitcellStructureView
from httk.core import DataRecord
from httk.core.cli import CLIContext
from httk.workflow import Workspace, collect
from httk.workflow.packages import load_workflow_package
from httk.workflow.postprocessing import run_postprocess_script
from httk.workflow.workflow_cli import command

from conftest import (
    REPO_ROOT,
    SILICON,
    job_parameters,
    job_state,
    mock_vasp_workspace,
    register_ws,
    run_idle,
    run_one,
)

PACKAGES = ("vasp-relax-annotated", "vasp-relax-bash-annotated")

# Two atoms 0.1 Angstrom apart: refused by both instantiate hooks.
OVERLAPPING = SILICON.replace("0.5000000000 0.5000000000 0.5000000000", "0.0500000000 0.0000000000 0.0000000000")
IRON = SILICON.replace("silicon", "iron").replace("\nSi\n", "\nFe\n")


def _structure(tmp_path: Path, text: str = SILICON) -> Path:
    path = tmp_path / "POSCAR"
    path.write_text(text, encoding="utf-8")
    return path


@pytest.mark.parametrize("directory", PACKAGES)
def test_relaxation_instantiates_runs_collects_and_postprocesses(tmp_path: Path, directory: str) -> None:
    workspace = mock_vasp_workspace(tmp_path / "workspace")
    marker, payload = run_one(workspace, REPO_ROOT / directory, inputs={"structure": str(_structure(tmp_path))})
    assert marker.kind == "succeeded", workspace.read_state(marker).get("failure")

    # The instantiate hook: tag from the reduced formula, POSCAR written with
    # the httk writer, spin_polarized derived and recorded with the defaults.
    assert marker.job_key.startswith("si--")
    staged = UnitcellStructureView(httk.core.load(str(payload / "files" / "POSCAR"), precision=5e-4))
    assert staged.chemical_formula_reduced == "Si"
    parameters = job_parameters(payload)
    assert parameters["spin_polarized"] is False
    assert parameters["kpoint_density"] == 20.0

    # The runner: ISPIN from the derived parameter, one completed VASP run.
    assert "ISPIN = 1" in (payload / "run" / "INCAR").read_text(encoding="utf-8")
    assert job_state(payload) == {"classification": "completed", "energy": -10.5}

    # The collect hook: role-keyed outputs, with the energy linked to the structure.
    (item,) = collect(workspace, fail_fast=True, allow_job_collector=True)
    assert set(item.outputs) == {"relaxed_structure", "total_energy"}
    assert not item.unfulfilled
    energy = item.outputs["total_energy"]
    assert isinstance(energy, DataRecord)
    assert energy.value == pytest.approx(-10.5)
    relaxed: Any = item.outputs["relaxed_structure"]
    assert float(relaxed.sites.reduced_coords[1][0]) == pytest.approx(0.51)
    assert [edge.label for edge in energy.product_of] == ["relaxed_structure"]
    assert item.run.workflow_declaration_uri == "https://example.org/httk/workflows-examples/declarations/vasp-relax"

    # The postprocess script.
    provider = load_workflow_package(REPO_ROOT / directory, register=False)
    result = run_postprocess_script(provider, "summary", item.record)
    assert result.returncode == 0, result.stderr
    summary = (result.output_dir / "summary.txt").read_text(encoding="utf-8")
    assert "Si2" in summary
    assert "-10.5" in summary


@pytest.mark.parametrize("directory", PACKAGES)
def test_a_caller_tag_and_spin_choice_win_over_the_derived_ones(tmp_path: Path, directory: str) -> None:
    workspace = mock_vasp_workspace(tmp_path / "workspace")
    marker, payload = run_one(
        workspace,
        REPO_ROOT / directory,
        inputs={"structure": str(_structure(tmp_path, IRON))},
        tag="my-iron",
        parameters={"spin_polarized": False},
    )
    assert marker.kind == "succeeded"
    assert marker.job_key.startswith("my-iron--")
    assert job_parameters(payload)["spin_polarized"] is False


@pytest.mark.parametrize("directory", PACKAGES)
def test_a_magnetic_element_turns_spin_polarization_on(tmp_path: Path, directory: str) -> None:
    workspace = mock_vasp_workspace(tmp_path / "workspace")
    marker, payload = run_one(workspace, REPO_ROOT / directory, inputs={"structure": str(_structure(tmp_path, IRON))})
    assert marker.kind == "succeeded"
    assert marker.job_key.startswith("fe--")
    assert job_parameters(payload)["spin_polarized"] is True
    assert "ISPIN = 2" in (payload / "run" / "INCAR").read_text(encoding="utf-8")


@pytest.mark.parametrize("directory", PACKAGES)
def test_a_structure_object_and_a_cif_file_are_accepted(tmp_path: Path, directory: str, test_profile) -> None:
    if not test_profile.extended:
        pytest.skip("the alternative input forms only run under HTTK_TEST_PROFILE=extended")
    structure = UnitcellStructureView(httk.core.load(str(_structure(tmp_path)), precision=5e-4))
    cif = tmp_path / "silicon.cif"
    httk.core.save(structure, cif)
    workspace = mock_vasp_workspace(tmp_path / "workspace")
    for value in (structure, str(cif)):
        marker, payload = run_one(workspace, REPO_ROOT / directory, inputs={"structure": value})
        assert marker.kind == "succeeded"
        assert (payload / "files" / "POSCAR").read_text(encoding="utf-8").splitlines()[5].split() == ["Si"]


@pytest.mark.parametrize("directory", PACKAGES)
def test_overlapping_atoms_are_refused_at_submission(tmp_path: Path, directory: str) -> None:
    workspace = mock_vasp_workspace(tmp_path / "workspace")
    with pytest.raises(ValueError, match=r"only 0\.100 Angstrom apart"):
        run_one(workspace, REPO_ROOT / directory, inputs={"structure": str(_structure(tmp_path, OVERLAPPING))})
    assert list(workspace.scan_markers()) == []  # no job was created


@pytest.mark.parametrize("directory", PACKAGES)
def test_a_missing_structure_is_refused_at_submission(tmp_path: Path, directory: str) -> None:
    workspace = mock_vasp_workspace(tmp_path / "workspace")
    # The framework refuses a missing required input before any hook runs.
    with pytest.raises(ValueError, match="'structure' is required and was not supplied"):
        run_one(workspace, REPO_ROOT / directory)


@pytest.mark.parametrize("directory", PACKAGES)
def test_a_diagnosed_vasp_failure_is_remedied_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, directory: str
) -> None:
    monkeypatch.setenv("HTTK_MOCK_VASP_FAIL_ONCE", "1")
    workspace = mock_vasp_workspace(tmp_path / "workspace")
    marker, payload = run_one(workspace, REPO_ROOT / directory, inputs={"structure": str(_structure(tmp_path))})
    assert marker.kind == "succeeded"
    assert job_state(payload)["remedies"] == 1
    # The first rung of the ZPOTRF ladder scales the lattice by five percent.
    assert (payload / "run" / "POSCAR").read_text(encoding="utf-8").splitlines()[1].strip() == "1.05"


@pytest.mark.parametrize("directory", PACKAGES)
def test_the_remedy_budget_is_respected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, directory: str) -> None:
    monkeypatch.setenv("HTTK_MOCK_VASP_FAIL_ONCE", "1")
    workspace = mock_vasp_workspace(tmp_path / "workspace")
    marker, _payload = run_one(
        workspace,
        REPO_ROOT / directory,
        inputs={"structure": str(_structure(tmp_path))},
        parameters={"maximum_remedies": 0},
    )
    assert marker.kind == "failed"
    failure = workspace.read_state(marker)["failure"]
    assert failure["code"] == "vasp.failed"
    assert "after 0 remedies" in failure["message"]


@pytest.mark.parametrize("directory", PACKAGES)
def test_no_vasp_command_fails_by_name(tmp_path: Path, directory: str) -> None:
    workspace = Workspace.initialize(tmp_path / "workspace")
    marker, _payload = run_one(workspace, REPO_ROOT / directory, inputs={"structure": str(_structure(tmp_path))})
    assert marker.kind == "failed"
    assert workspace.read_state(marker)["failure"]["code"] == "vasp.command_missing"


def test_the_command_line_passes_a_structure_path_to_the_hook(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = mock_vasp_workspace(tmp_path / "workspace")
    name = register_ws(workspace.root)
    arguments = [
        "job",
        "new",
        "--workspace",
        name,
        "--workflow-dir",
        str(REPO_ROOT / "vasp-relax-annotated"),
        "--input",
        f"structure={_structure(tmp_path)}",
        "--parameter",
        "kpoint_density=30",
    ]
    assert command(arguments, CLIContext("httk", tmp_path)) == 0
    key, payload = capsys.readouterr().out.strip().split("\t")
    assert key.startswith("si--")
    run_idle(workspace)
    assert json.loads((Path(payload) / "job.json").read_text(encoding="utf-8"))["parameters"]["kpoint_density"] == 30
    assert job_state(Path(payload))["classification"] == "completed"
