"""Collect hook of ase.static: turn ``results.json`` into httk records.

It only reads the JSON the runner wrote; it needs neither ASE nor the
calculator. The framework adds the ``product_of`` edges the manifest declares.
"""

import json

from httk.core.data_records import TotalEnergyRecord
from httk.core.property_records import CartesianSiteForcesRecord


def collect(record):
    """Return the total energy and the site forces of one job.

    :param record: The ``JobRecord`` of one finished job.
    :return: ``{"total_energy": TotalEnergyRecord, "cartesian_site_forces": CartesianSiteForcesRecord}``.
    :raises ValueError: If ``results.json`` is missing.
    """

    results = json.loads(record.result_file("results.json").read_text(encoding="utf-8"))
    return {
        "total_energy": TotalEnergyRecord(total_energy=results["total_energy"]),
        "cartesian_site_forces": CartesianSiteForcesRecord.from_value(results["cartesian_site_forces"]),
    }
