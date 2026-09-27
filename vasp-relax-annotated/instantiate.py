"""Instantiate hook of examples.vasp-relax-annotated: turn the input into a ready payload.

What this example shows:

* a Python instantiate hook is a module with ``def instantiate(context)``; the
  framework imports it and calls it once per job, while ``httk job new`` (or
  ``new_job``) builds that job's payload, before anything is submitted;
* it *consumes* a declared input (``[workflow.inputs.structure]`` has no
  ``destination``): the hook receives the value exactly as the caller supplied
  it, and decides itself what lands in the payload;
* it can refuse a job by raising: the job is then never created, and the
  person submitting it sees the error immediately;
* it can fill in a job tag and record derived parameters in ``job.json``;
* it sees which parameters the *caller* supplied: ``context.parameters`` holds
  only those, while the declared defaults sit apart in ``context.defaults``
  and fill in every parameter still absent after the hook returns.

The framework has already done two things before this hook runs: it refused
the job if a required input (here ``structure``) was not supplied, so the hook
never has to check for it, and it type-checked the supplied parameters.

Why do this at submission rather than in the runner's first step? The hook
runs on the submitting machine, right away, with the caller watching. The
runner runs later, maybe on a cluster node, maybe after hours in a queue. So
the hook is the place for everything that is cheap and that the caller should
hear about *now*:

* reading the input format (the submitting machine is where httk-atomistic and
  its readers are sure to be installed, and the runner then only ever sees a
  plain POSCAR);
* rejecting nonsense (a structure with overlapping atoms should not wait in a
  queue only to fail on a compute node);
* choosing names and recording decisions (a tag and a derived parameter end up
  in ``job.json``, where they are part of the job's immutable, digest-pinned
  definition, so everyone can later see exactly what was decided).

What does *not* belong here: anything expensive, anything that needs the
machine the job runs on (the VASP command, the pseudopotential library,
parallelisation), and anything that reacts to how a run went. Those belong in
the runner, which reads machine-specific *settings* at run time.
"""

import math
import os
from itertools import product
from pathlib import Path

import httk.core
from httk.atomistic import UnitcellStructureView, atomic_number

# Elements for which this example turns on spin polarization when the caller
# did not decide. A deliberately crude heuristic, good enough to demonstrate a
# derived parameter; a real workflow would use a considered rule.
MAGNETIC_ELEMENTS = frozenset({"Cr", "Mn", "Fe", "Co", "Ni", "Gd"})


def instantiate(context):
    """Validate the input structure, stage it as ``files/POSCAR``, and derive a tag and a parameter.

    :param context: The ``httk.workflow.scaffold.InstantiateContext`` of the job being created.
        ``context.payload`` is the payload directory under construction,
        ``context.inputs`` the supplied inputs (read-only), ``context.parameters``
        the parameters the caller supplied (mutable), ``context.defaults`` the
        declared parameter defaults (read-only), and ``context.tag`` the
        caller's tag or ``None``.
    :raises ValueError: If the structure is unreadable or fails validation;
        the job is then not created.
    """

    # 1. Read the input. The input is declared required, and the framework
    #    refuses a job without it before calling this hook, so it is here.
    structure = _as_structure(context.inputs["structure"])

    # 2. Validate it. A parameter the caller did not supply is not yet in
    #    context.parameters (its default is applied after this hook), so the
    #    effective value is the caller's, else the declared default.
    minimum_distance = context.parameters.get("minimum_distance", context.defaults["minimum_distance"])
    _validate(structure, minimum_distance=float(minimum_distance))

    # 3. Write the structure into the payload with the httk writer registered
    #    for the name POSCAR. files/ is where payload inputs conventionally live;
    #    the runner's prepare step copies files/POSCAR into its workdir.
    poscar = context.payload / "files" / "POSCAR"
    poscar.parent.mkdir(parents=True, exist_ok=True)
    httk.core.save(structure, poscar)

    # 4. Suggest a tag. suggest_tag only takes effect when the caller gave no
    #    --tag, so an explicit choice always wins. Tags are lowercase letters,
    #    digits, '.', '_' and '-' (at most 48), so the formula is lowercased.
    formula = structure.chemical_formula_reduced
    tag = "".join(character for character in formula.lower() if character.isalnum())[:48]
    if tag:
        context.suggest_tag(tag)

    # 5. Derive a parameter the caller did not set. spin_polarized declares a
    #    default (false), yet "not given" is still distinguishable from "given
    #    as false": only a caller-supplied value is in context.parameters. When
    #    the caller said nothing and the structure has a magnetic element, the
    #    hook turns it on; otherwise it leaves the parameter absent and the
    #    declared default fills it in after the hook. Either way the value ends
    #    up in job.json, so the choice is recorded, not re-guessed later.
    if "spin_polarized" not in context.parameters and MAGNETIC_ELEMENTS & set(structure.elements):
        context.parameters["spin_polarized"] = True


def _as_structure(value):
    """Return the supplied input as a ``UnitcellStructureView``.

    ``httk job new --input structure=Si.cif`` passes the path as a string;
    ``--input-from structure Si.cif`` and ``new_job(inputs={"structure": obj})``
    pass an already loaded structure object. Both are accepted.
    """

    if isinstance(value, (str, os.PathLike)):
        path = Path(value).expanduser()
        if not path.is_file():
            raise ValueError(f"the structure file {path} does not exist")
        # httk recommends an explicit precision for VASP files, whose coordinates
        # carry no uncertainty of their own. Every structure reader accepts the
        # argument (a CIF states its own precision and ignores it), so the hook
        # passes it without caring which format it was given.
        try:
            value = httk.core.load(str(path), precision=5e-4)
        except Exception as exc:
            raise ValueError(f"cannot read the structure file {path}: {exc}") from exc
    try:
        # Constructing the view is how httk converts between representations:
        # a CIF's asymmetric unit, an ASE Atoms, or a pymatgen Structure all work.
        return UnitcellStructureView(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"the structure input is not a structure httk understands: {exc}") from exc


def _validate(structure, *, minimum_distance):
    """Refuse structures that could never make a sensible VASP relaxation.

    :raises ValueError: With a message naming what is wrong.
    """

    if structure.nsites < 1:
        raise ValueError("the structure has no atoms")
    for symbol in structure.elements:
        try:
            atomic_number(symbol)
        except ValueError as exc:
            raise ValueError(f"the structure contains {symbol!r}, which is not a chemical element") from exc
    shortest = _shortest_distance(structure)
    if shortest < minimum_distance:
        raise ValueError(
            f"two atoms are only {shortest:.3f} Angstrom apart, closer than minimum_distance = {minimum_distance}; "
            "check the structure, or lower the minimum_distance parameter if this is intended"
        )


def _shortest_distance(structure):
    """Return the shortest distance between two atoms, including periodic images.

    Only the 26 neighbouring cells are searched, which is exact for ordinary
    cells; a very skewed cell would need a Niggli-reduced cell first.
    """

    lattice = structure.lattice_vectors
    positions = structure.cartesian_site_positions
    shortest = math.inf
    for cell in product((-1, 0, 1), repeat=3):
        # The Cartesian translation to this neighbouring cell.
        shift = [sum(n * lattice[axis][k] for axis, n in enumerate(cell)) for k in range(3)]
        for i, first in enumerate(positions):
            for j, second in enumerate(positions):
                if i != j or cell != (0, 0, 0):  # skip an atom's distance to itself
                    shortest = min(shortest, math.dist(first, [second[k] + shift[k] for k in range(3)]))
    return shortest
