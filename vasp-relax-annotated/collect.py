"""Collect hook of examples.vasp-relax-annotated: read the results out of a finished job.

What this example shows:

* a Python collect hook is a module with ``def collect(record)``; it runs
  when someone collects the workspace (``httk workflow collect``, or
  ``httk.workflow.collect(workspace)`` in Python), long after the job ran;
* ``record`` is a ``httk.workflow.JobRecord``: a read-only description of one
  finished job, with absolute paths such as ``record.workdir``;
* the hook returns a mapping from output *role* to an httk object. The roles
  must be the ones declared in ``[workflow.outputs.*]``; a declared role the
  hook leaves out is reported as unfulfilled. The framework then links each
  output into the collected provenance ``Run`` and adds the ``product_of``
  edges the manifest declares, so the hook only has to produce values.

The production workflows delegate to ``httk.workflow.codes.vasp.collect``; this
hook does the reading itself with the httk file readers, to show that there
is nothing more to it.
"""

import httk.core
from httk.atomistic import UnitcellStructureView

# The property definition the total_energy output declares (`ref` in the
# manifest) and the property name httk stores it under.
TOTAL_ENERGY = "https://schemas.httk.org/defs/v0.1/properties/core/total_energy"
TOTAL_ENERGY_NAME = "_httk_total_energy"


def collect(record):
    """Return the relaxed structure and the final total energy of one job.

    :param record: The ``JobRecord`` of one finished job.
    :return: ``{"relaxed_structure": UnitcellStructureView, "total_energy": DataRecord}``.
    :raises ValueError: If the job's files are missing or unreadable.
    """

    # This workflow runs with data_mode = "none", so its results are in the
    # persistent workdir. (A transactional job would read record.data.)
    workdir = record.workdir
    if workdir is None:
        raise ValueError(f"job {record.job_id} has no workdir to collect from")
    contcar = workdir / "CONTCAR"
    outcar = workdir / "OUTCAR"
    for path in (contcar, outcar):
        if not path.is_file():
            raise ValueError(f"job {record.job_id} did not leave {path.name} in {workdir}")

    # CONTCAR is the geometry after the last ionic step. httk.core.load picks
    # the reader registered for the name; the view turns the loaded file into
    # the structure type httk stores. The precision is the coordinate
    # uncertainty httk assumes for this file (VASP writes no such number).
    relaxed = UnitcellStructureView(httk.core.load(str(contcar), precision=5e-4))

    # raw=True returns the reader's own objects instead of an adapted httk
    # type; for an OUTCAR that is an OutcarFile with the parsed final energies.
    final = httk.core.load(str(outcar), raw=True)["outcar"].final_energies
    # Only a succeeded job is collected by default, and the runner only
    # succeeds after VASP completed, so the OUTCAR should have a final energy
    # block; a missing one means the file is damaged.
    if final is None:
        raise ValueError(f"job {record.job_id}: {outcar} has no final energies")
    # The energy extrapolated to zero smearing. The reader keeps the exact
    # decimal text VASP wrote; float() is the only conversion.
    energy = float(final.energy_sigma0)

    # A DataRecord is httk's entry for one property value; it knows which
    # property definition gives the number its meaning (and unit, eV).
    return {
        "relaxed_structure": relaxed,
        "total_energy": httk.core.DataRecord.from_value(TOTAL_ENERGY, TOTAL_ENERGY_NAME, energy),
    }
