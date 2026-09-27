#!/usr/bin/env python3
"""examples.hello: the smallest possible Python workflow.

What this example shows:

* a runner is one executable file that registers its steps on a ``Runner``;
* the manager starts it once per *attempt* and tells it which step to run;
* a step reads what it needs (here one job parameter), does its work in the
  job's *workdir* (its current directory), and ends by publishing exactly one
  outcome (here ``a.succeed()``).

Try it:

.. code-block:: console

    httk job new --workflow-dir hello --parameter name=Ada   # prints KEY<tab>PAYLOAD
    httk workflow run                                          # runs until idle
    cat PAYLOAD/run/greeting.txt                               # run/ is the workdir
"""

from httk.workflow import Attempt, Runner

# The name must equal `[workflow] name` in httk_workflow.toml.
run = Runner("examples.hello")


@run.step
def greet(a: Attempt) -> None:
    """Write ``greeting.txt`` into the workdir and finish the job."""

    # Parameters are the job's opaque knobs, given with `--parameter name=...`
    # (or `parameters={...}` in Python). The second argument is the default.
    name = a.parameter("name", "world")
    # a.workdir is the job's working directory; the step also starts in it.
    (a.workdir / "greeting.txt").write_text(f"Hello, {name}!\n", encoding="utf-8")
    # One outcome per attempt: succeed, advance to another step, retry, or fail.
    a.succeed()


if __name__ == "__main__":
    # main() reads the attempt the manager prepared, runs the requested step,
    # and turns a step that forgot to publish into a clear `no_outcome` failure.
    raise SystemExit(run.main())
