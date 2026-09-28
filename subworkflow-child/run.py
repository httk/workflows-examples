#!/usr/bin/env python3
"""examples.subworkflow-child: the workflow the subworkflow examples call.

What this example shows:

* a called workflow is an ordinary workflow. This runner does not know, and
  does not need to know, whether a person submitted its job or another
  workflow's step called it; it reads its parameter, writes its result, and
  publishes one outcome, exactly like ../hello;
* its result is a small file in its own workdir, ``root.txt``. A caller reads
  it from there (``child.workdir / "root.txt"``); nothing is copied back;
* a failure with a code of its own (``examples.negative_value``) is what the
  caller sees in ``child.failure``.

Try it on its own:

.. code-block:: console

    httk job new --workflow-dir subworkflow-child --parameter value=2
    httk workflow run
    cat PAYLOAD/run/root.txt
"""

import math

from httk.workflow import Attempt, Runner

run = Runner("examples.subworkflow-child")


@run.step
def root(a: Attempt) -> None:
    """Write the square root of the ``value`` parameter to root.txt."""

    # Declared as a number with a default, so it is always a number here.
    value = a.parameter("value")
    if value < 0:
        a.fail("examples.negative_value", f"cannot take the square root of {value}")
        return
    (a.workdir / "root.txt").write_text(f"{math.sqrt(value)}\n", encoding="utf-8")
    a.succeed()


if __name__ == "__main__":
    raise SystemExit(run.main())
