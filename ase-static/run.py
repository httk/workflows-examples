#!/usr/bin/env python3
"""ase.static: the energy and the forces of one structure with an ASE calculator.

What this example shows:

* an input with a ``destination`` arrives staged in the payload
  (``files/POSCAR``) without any instantiate hook;
* the code that computes is chosen by a parameter: any ASE calculator class,
  named ``module:Class``, with keyword arguments;
* the runner only writes ``results.json``; the collect hook turns it into
  httk records later, without ASE.

Try it:

.. code-block:: console

    httk job new --install --workflow-dir ase-static --input structure=POSCAR
    httk workflow run
    httk collect
"""

import importlib
import json

from httk.workflow import Attempt, Runner

run = Runner("ase.static")


@run.step
def evaluate(a: Attempt) -> None:
    """Evaluate the staged POSCAR and write ``results.json`` into the workdir."""

    spec = a.parameter("calculator")
    module, _, name = spec.partition(":")
    try:
        if not module or not name:
            raise ValueError("expected module:Class")
        calculator = getattr(importlib.import_module(module), name)
    except (ValueError, ImportError, AttributeError) as error:
        a.fail("ase.invalid_calculator", f"cannot load calculator {spec!r}: {error}")
        return

    # Imported here so the runner describes itself (`./run.py --describe`) without ASE.
    import ase.io

    # The format is explicit: ASE would otherwise guess it from the file name.
    atoms = ase.io.read(a.payload / "files" / "POSCAR", format="vasp")
    atoms.calc = calculator(**a.parameter("calculator_kwargs"))
    results = {
        "total_energy": float(atoms.get_potential_energy()),  # eV
        # eV/Angstrom, one row per atom in POSCAR order (ASE keeps the file's order).
        "cartesian_site_forces": atoms.get_forces().tolist(),
    }
    (a.workdir / "results.json").write_text(json.dumps(results) + "\n", encoding="utf-8")
    a.succeed()


if __name__ == "__main__":
    raise SystemExit(run.main())
