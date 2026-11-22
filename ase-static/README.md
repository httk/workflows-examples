# ase-static

`ase.static` evaluates one structure with an [ASE](https://wiki.fysik.dtu.dk/ase/)
calculator: a single point that returns the total energy and the force on
every site. The default calculator is ASE's built-in EMT, so it runs without
any external code (EMT only knows a few metals: Al, Cu, Ag, Au, Ni, Pd, Pt,
and H, C, N, O).

```console
httk job new --install ./ase-static --input structure=POSCAR
httk run
httk collect
```

The input is staged to `files/POSCAR` by the framework: a file is copied as
it is, so it must be a POSCAR; a structure object is written there with the
httk POSCAR writer. The runner reads it with `ase.io.read(..., format="vasp")`
and writes `results.json` into the workdir; the collect hook turns that file
into records without ASE.

## Choosing a calculator

`calculator` names any ASE calculator class as `module:Class`, and
`calculator_kwargs` is a JSON object of keyword arguments for it. For example,
a machine-learned potential's ASE calculator:

```console
httk job new --install ./ase-static --input structure=POSCAR \
    --parameter calculator=some_mlip.ase:Calculator --parameter calculator_kwargs=@kwargs.json
```

The class must be importable where the job runs. A malformed or unimportable
`calculator` fails the job with the code `ase.invalid_calculator`.

## Outputs

| Role | Record | Unit |
| --- | --- | --- |
| `total_energy` | `TotalEnergyRecord` | eV |
| `cartesian_site_forces` | `CartesianSiteForcesRecord`, one 3-vector per site | eV/Å |

Both are products of the `initial_structure` input. The forces are in the
Cartesian frame of the POSCAR and in its site order (ASE keeps the order the
file lists the atoms in).

Its declared input and outputs make it a "structure → energy and forces"
workflow that can be bound into a call slot of another workflow; call slots
are documented in *httk-workflow*.
