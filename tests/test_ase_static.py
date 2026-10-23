"""The ase.static package: EMT energy and forces end to end, and its declared outputs."""

import json
from pathlib import Path

import pytest
from httk.core.data_records import TotalEnergyRecord
from httk.core.property_records import CartesianSiteForcesRecord
from httk.workflow import Workspace, collect
from httk.workflow.packages import load_workflow_package

from conftest import REPO_ROOT, failure, run_one

PACKAGE = REPO_ROOT / "ase-static"
STRUCTURE_REF = "https://schemas.optimade.org/defs/v1.3/entrytypes/optimade/structures"
REFS = {
    "total_energy": "https://schemas.httk.org/defs/v0.1/properties/core/total_energy",
    "cartesian_site_forces": "https://schemas.httk.org/defs/v0.1/properties/core/cartesian_site_forces",
}

# The conventional fcc Cu cell with one atom displaced, so the forces are not zero.
COPPER = """copper
1.0
3.6 0.0 0.0
0.0 3.6 0.0
0.0 0.0 3.6
Cu
4
Direct
0.02 0.01 0.0
0.0 0.5 0.5
0.5 0.0 0.5
0.5 0.5 0.0
"""


def test_declared_input_and_outputs_fit_a_structure_to_forces_slot() -> None:
    provider = load_workflow_package(PACKAGE, register=False)
    assert provider.workflow_id == "ase.static"
    assert provider.inputs == {"structure": "POSCAR"}
    (declared_input,) = provider.declarations["workflow"]["inputs"]
    assert (declared_input["name"], declared_input["entry_type"], declared_input["ref"]) == (
        "initial_structure",
        "structures",
        STRUCTURE_REF,
    )
    declared = {item["name"]: item for item in provider.declarations["workflow"]["outputs"]}
    assert {name: (item["entry_type"], item["ref"]) for name, item in declared.items()} == {
        name: ("records", ref) for name, ref in REFS.items()
    }
    assert {name: output["product_of"] for name, output in provider.outputs.items()} == dict.fromkeys(
        REFS, "initial_structure"
    )


def test_emt_energy_and_forces_match_direct_ase(tmp_path: Path) -> None:
    ase_io = pytest.importorskip("ase.io")
    from ase.calculators.emt import EMT

    poscar = tmp_path / "POSCAR"
    poscar.write_text(COPPER, encoding="utf-8")
    workspace = Workspace.initialize(tmp_path / "workspace")
    ref, payload = run_one(workspace, PACKAGE, inputs={"structure": str(poscar)})
    assert ref.state == "succeeded", failure(ref)
    assert set(json.loads((payload / "run" / "results.json").read_text(encoding="utf-8"))) == set(REFS)

    atoms = ase_io.read(poscar, format="vasp")
    atoms.calc = EMT()
    expected_forces = atoms.get_forces()
    assert abs(expected_forces).max() > 1e-3

    (item,) = collect(workspace, fail_fast=True, allow_job_collector=True)
    assert not item.unfulfilled
    energy, forces = item.outputs["total_energy"], item.outputs["cartesian_site_forces"]
    assert isinstance(energy, TotalEnergyRecord)
    assert isinstance(forces, CartesianSiteForcesRecord)
    assert energy.total_energy == pytest.approx(atoms.get_potential_energy(), abs=1e-10)
    assert len(forces.value) == len(atoms) == 4
    assert abs(expected_forces - forces.value).max() <= 1e-10  # one row per site, in POSCAR order
    assert [edge.label for edge in energy.product_of] == ["initial_structure"]
    assert [edge.label for edge in forces.product_of] == ["initial_structure"]


@pytest.mark.parametrize("spec", ("ase.calculators.emt", "ase.calculators.emt:NoSuchCalculator", "no_such_module:X"))
def test_a_malformed_calculator_fails_the_job(tmp_path: Path, spec: str) -> None:
    pytest.importorskip("ase")
    poscar = tmp_path / "POSCAR"
    poscar.write_text(COPPER, encoding="utf-8")
    workspace = Workspace.initialize(tmp_path / "workspace")
    ref, _payload = run_one(workspace, PACKAGE, inputs={"structure": str(poscar)}, parameters={"calculator": spec})
    assert ref.state == "failed"
    assert failure(ref)["code"] == "ase.invalid_calculator"
