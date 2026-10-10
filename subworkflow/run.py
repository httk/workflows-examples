#!/usr/bin/env python3
"""examples.subworkflow: call another workflow as sub-workflows, gather, aggregate.

What this example shows:

* ``a.call("child", label=..., parameters=...)`` creates a child job of
  *another* workflow once per value. ``child`` is an alias this package
  declares in its manifest's ``[workflow.calls]`` table, for
  ``examples.subworkflow-child``. Each child
  runs that workflow's own runner with its own parameters, workdir and
  declaration, in parallel if the manager has room;
* ``a.gather`` waits for all of them, and ``a.children`` lists them in the
  step it resumes at: their labels, job keys, outcomes and directories;
* aggregating is reading each child's result file from its workdir.

``spawn`` or ``call``? ``a.spawn(ChildSpec(step=...))`` (../fan-out) starts a
child at a step of *this same runner*: use it when the children are part of
this workflow's own logic. ``a.call(workflow)`` starts a child of a
*different* workflow, a complete workflow with its own runner, parameters and
failure handling that could equally be submitted on its own: use it to build
on a workflow instead of copying its steps. Both kinds of child are gathered
and read back the same way.

Why declare what is called: the dependency is then known before anything
runs. Installing this workflow in a workspace (``httk workflow install``, or
``httk job new --install``) installs the declared calls too and records them by
id; a manager does not claim the job until the called workflow is installed,
and built if it is compiled, in its workspace (``httk job why`` and ``httk
workflow precheck`` say what is missing); and at run time the job may call only
what it declares, so a typo or a stray name in the code is refused rather than
silently fetched. The name is resolved on the machine where the workflow is
installed, so make the child known there (for example with ``httk plugin
install`` of this repository, which registers every package in it). To call a
workflow from a git repository, put its
commit-pinned git URI in ``[workflow.calls]`` instead of a name, never in the
code or a parameter::

    child = "git+https://github.com/httk/workflows-examples@<full commit>#subworkflow-child"

The code keeps calling ``"child"``. A called child
is created in this job's workspace, belongs to this job, and moves with it:
transferring the parent to another workspace moves its children along, and a
child cannot be transferred on its own.

Provenance: neither workflow has a collector or declared outputs, but
``httk collect --into results.sqlite --id-base my.campaign`` still
stores one run (an ``_httk_runs`` entry) per job: the parent's run names this
package's declaration, each child's run names the child's declaration, and the
parent's run links to each child's run by the call's label (``value-0``, ...).
``--no-bare-runs`` leaves such runs out.

The flow is::

    start ──call examples.subworkflow-child──► root (value=1) ─┐
          ──call examples.subworkflow-child──► root (value=4) ─┼─gather─► aggregate ──► (succeeded)
          ──call examples.subworkflow-child──► root (value=9) ─┘             └──────► report_failures
"""

import json

from httk.workflow import Attempt, Runner

run = Runner("examples.subworkflow")


@run.step
def start(a: Attempt) -> None:
    """Call the child workflow once per value, then wait for all the calls."""

    # Declared with a default in httk_workflow.toml.
    values = a.parameter("values")
    for index, value in enumerate(values):
        # parameters= are the child job's parameters, checked against the child
        # workflow's own manifest (its declared types and defaults) right here:
        # a bad value raises in this step, before any child exists. The label
        # names the child in a.children and becomes its job tag.
        # "child" is the alias from [workflow.calls], not a workflow name.
        a.call("child", label=f"value-{index}", parameters={"value": value})
    # The calls are registered with this attempt's outcome and created when it
    # is published, by gather() below. State survives the wait.
    a.state["called"] = len(values)
    # Resume at `aggregate` when every child succeeded; as soon as one fails
    # that is impossible, and the job resumes at `report_failures` instead.
    a.gather("aggregate", when="all_succeeded", on_impossible="report_failures")


@run.step
def aggregate(a: Attempt) -> None:
    """Read every child's root.txt and write summary.json."""

    children = {}
    for child in a.children.succeeded:
        # The child's workdir is a directory of its own job; read, never write.
        root = float((child.workdir / "root.txt").read_text(encoding="utf-8"))
        children[child.label] = {"job_key": child.job_key, "root": root}
    total = sum(child["root"] for child in children.values())
    summary = {"children": children, "sum_of_roots": total}
    (a.workdir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    a.log.append("note", f"aggregated {len(children)} of {a.state['called']} calls: sum of roots {total}")
    a.succeed()


@run.step
def report_failures(a: Attempt) -> None:
    """Reached through on_impossible: say which calls failed, and why."""

    failed = {child.label: child.failure.code if child.failure else child.kind for child in a.children.failed}
    a.fail("examples.calls_failed", f"{len(failed)} called workflow(s) failed", details={"failed": failed})


if __name__ == "__main__":
    raise SystemExit(run.main())
