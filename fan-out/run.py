#!/usr/bin/env python3
"""examples.fan-out: one job becomes many, then one again.

What this example shows:

* ``a.spawn(ChildSpec(...), label=...)`` registers a *child job* that runs a
  step of this same runner with its own parameters; the children are created
  when the spawning step publishes its outcome, and then run independently
  (in parallel, if the manager has room);
* ``a.gather(step, when=..., on_impossible=...)`` makes the parent wait: the
  manager resumes it at ``step`` once the children are done;
* in the gathering step, ``a.children`` lists the children with their
  outcome and their directories, so reading their results is a file read;
* the other direction: a child finds the job that spawned it through
  ``a.parent`` and reads a file the parent wrote *in place*, from the parent's
  workdir, instead of receiving its own copy.

The flow is::

    start ──spawn──► square (value=1)  ─┐
          ──spawn──► square (value=2)  ─┼─gather─► aggregate ──► (succeeded)
          ──spawn──► square (value=3)  ─┘              └──────► report_failures

Parent and children are ordinary jobs in the same workspace; ``httk job
list`` shows them all. This is also the building block of large campaigns
(see the campaigns guide of httk-workflow), where a campaign's partitions
each receive root jobs like this one.
"""

import json

from httk.workflow import Attempt, ChildSpec, Runner

run = Runner("examples.fan-out")


@run.step
def start(a: Attempt) -> None:
    """Spawn one child per value and wait for all of them."""

    # Declared in httk_workflow.toml with a default, so it is always in job.json.
    values = a.parameter("values")
    # A file every child reads in place (see `square`). A child may start the
    # moment this step's outcome is published, so write shared files before
    # that, and leave them alone until every child reading them has ended.
    # (Here `report_failures` can run while siblings still do; it leaves
    # common.json alone.)
    (a.workdir / "common.json").write_text(json.dumps({"scale": a.parameter("scale")}), encoding="utf-8")
    for index, value in enumerate(values):
        # A ChildSpec needs only the step the child starts at and its own
        # parameters; the runner, workflow, and scheduling follow the parent.
        # The child gets exactly these parameters: manifest defaults are
        # applied only when a job is created by `httk job new` / new_job, so a
        # child sees no `values`, only `value`.
        # The label names the child in a.children and becomes its job tag.
        a.spawn(ChildSpec(step="square", parameters={"value": value}), label=f"value-{index}")
    # Remember how many we asked for; state survives the wait.
    a.state["spawned"] = len(values)
    # all_succeeded (the default) resumes at `aggregate` when every child
    # succeeded; if one fails that can no longer happen, and the job goes to
    # `report_failures` instead. (all_terminal would wait for every child to
    # end and always resume at `aggregate`.)
    a.gather("aggregate", when="all_succeeded", on_impossible="report_failures")


@run.step
def square(a: Attempt) -> None:
    """The child's work: square one number, scale it, and write result.json."""

    value = a.parameter("value")
    if not isinstance(value, (int, float)):
        a.fail("examples.not_a_number", f"cannot square {value!r}")
        return
    # a.parent locates the spawning job in this workspace (None for a root job).
    # Reading its workdir in place avoids one copy per child. For a tiny file
    # like this one, copying it in at spawn time (or passing a parameter) is the
    # better habit: the child is then self-contained. Reading in place pays off
    # for large shared files, such as a WAVECAR every child starts from.
    parent = a.parent
    if parent is None or parent.workdir is None:
        # No reachable parent (e.g. this step was submitted as a root job), or a
        # parent with isolated workdirs, which a child cannot name.
        a.fail("examples.no_parent_workdir", "square must run as a child of a persistent-workdir parent")
        return
    common = json.loads((parent.workdir / "common.json").read_text(encoding="utf-8"))
    square = value * value * common["scale"]
    (a.workdir / "result.json").write_text(json.dumps({"value": value, "square": square}), encoding="utf-8")
    a.succeed()


@run.step
def aggregate(a: Attempt) -> None:
    """Read every child's result.json and write the combined summary.json."""

    results = {
        child.label: json.loads((child.workdir / "result.json").read_text(encoding="utf-8"))
        for child in a.children.succeeded
    }
    total = sum(result["square"] for result in results.values())
    summary = {"children": results, "sum_of_squares": total}
    (a.workdir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    a.log.append("note", f"aggregated {len(results)} of {a.state['spawned']} children: sum of squares {total}")
    a.succeed()


@run.step
def report_failures(a: Attempt) -> None:
    """Reached through on_impossible: say which children failed, and why."""

    failed = {child.label: child.failure.code if child.failure else child.kind for child in a.children.failed}
    a.fail("examples.children_failed", f"{len(failed)} child job(s) failed", details={"failed": failed})


if __name__ == "__main__":
    raise SystemExit(run.main())
