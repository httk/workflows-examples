#!/usr/bin/env python3
"""Postprocess script ``summary`` of examples.vasp-relax-annotated: write summary.txt.

What this example shows:

* a postprocess script is any executable listed under
  ``[workflow.postprocess.NAME]``; it runs only when asked for, after a job
  has been collected::

      httk workflow postprocess --workspace WS --workflow-dir vasp-relax-annotated --script summary

* it learns where things are from environment variables:
  ``HTTK_WORKFLOW_JOB_DIR`` (the job payload, to be treated as read-only),
  ``HTTK_WORKFLOW_WORKDIR`` (the job's workdir, when it has one), and
  ``HTTK_WORKFLOW_POSTPROCESS_DIR``, which is also its current directory and
  the only place it should write. Output never lands in the job itself, so
  even a sealed job can be postprocessed;
* it may use only the standard library: nothing here needs httk.

The collect hook is where results become httk entries; a postprocess script
is for everything else a person may want afterwards (reports, plots, copies).
"""

import json
import os
from pathlib import Path


def main() -> int:
    """Write ``summary.txt`` into the current (postprocess output) directory."""

    payload = Path(os.environ["HTTK_WORKFLOW_JOB_DIR"])
    workdir = Path(os.environ.get("HTTK_WORKFLOW_WORKDIR") or payload / "run")

    # The job definition: its parameters include those instantiate.py derived.
    job = json.loads((payload / "job.json").read_text(encoding="utf-8"))
    parameters = job.get("parameters", {})

    # The final energy from the calculation's own output: the last "F=" line
    # of OSZICAR, e.g. "   1 F= -.10500000E+02 E0= ...". Scripts read the
    # workdir's files, not httk's private job bookkeeping.
    energy = "unavailable"
    oszicar = workdir / "OSZICAR"
    if oszicar.is_file():
        for line in oszicar.read_text(encoding="utf-8").splitlines():
            fields = line.split()
            if "F=" in fields:
                energy = str(float(fields[fields.index("F=") + 1]))

    # The formula from the POSCAR the job ran (VASP 5 format: line 6 holds the
    # species, line 7 the counts).
    lines = (workdir / "POSCAR").read_text(encoding="utf-8").splitlines()
    formula = "".join(f"{symbol}{count}" for symbol, count in zip(lines[5].split(), lines[6].split()))

    summary = [
        f"job:             {payload.name}",
        f"formula:         {formula}",
        f"spin polarized:  {parameters.get('spin_polarized')}",
        f"k-point density: {parameters.get('kpoint_density')}",
        f"final energy:    {energy} eV",
    ]
    Path("summary.txt").write_text("\n".join(summary) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
