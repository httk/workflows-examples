#!/usr/bin/env python3
"""examples.compose: call another workflow and build on its result.

What this example shows:

* ``a.call(alias, label=...)`` creates a child job of a *different*
  workflow, which runs that workflow's own runner. The alias is declared in
  ``[workflow.calls]`` of httk_workflow.toml, and the called workflow is
  installed in the workspace together with this one;
* the caller waits with ``a.gather`` exactly as for spawned children (see
  ../fan-out), and reads the child's files through ``a.children``;
* results move between workflows explicitly: this step reads the child's
  greeting.txt. Nothing matches one workflow's outputs to another's inputs
  automatically.

``a.spawn(ChildSpec(...))`` (../fan-out) runs a step of *this* runner in the
child; ``a.call`` runs *another* workflow. Reach for ``call`` when the stage
is a complete workflow of its own, with its own inputs and failure handling.

The flow is::

    start ──call examples.hello──► (child: greet) ──gather──► finish ──► (succeeded)
                                                       └────► dependency_failed
"""

from httk.workflow import Attempt, Runner

run = Runner("examples.compose")


@run.step
def start(a: Attempt) -> None:
    """Call the hello workflow as a child job, then wait for it."""

    # "hello" is the alias [workflow.calls] declares; name is declared with a
    # default in httk_workflow.toml, so it is always in job.json.
    # parameters= are the child's job parameters, exactly as `--parameter`.
    a.call("hello", label="hello", parameters={"name": a.parameter("name")})
    a.gather("finish", when="all_succeeded", on_impossible="dependency_failed")


@run.step
def finish(a: Attempt) -> None:
    """Read the child's greeting and write our own answer next to it."""

    hello = a.children["hello"]  # by label
    # hello leaves its result in its workdir.
    greeting = (hello.workdir / "greeting.txt").read_text(encoding="utf-8").strip()
    (a.workdir / "composed.txt").write_text(f"The hello workflow said: {greeting}\n", encoding="utf-8")
    a.log.append("note", f"child {hello.job_key} said {greeting!r}")
    a.succeed()


@run.step
def dependency_failed(a: Attempt) -> None:
    """Reached through on_impossible when the called workflow did not succeed."""

    hello = a.children["hello"]
    reason = hello.failure.message if hello.failure else hello.kind
    a.fail("examples.dependency_failed", f"the called hello workflow did not succeed: {reason}")


if __name__ == "__main__":
    raise SystemExit(run.main())
