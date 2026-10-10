#!/usr/bin/env python3
"""examples.chain: a Python workflow calls a Rust workflow that calls a Python one.

What this example shows:

* calls nest, and they cross languages. This workflow calls
  ``examples.chain-rust``; that compiled Rust workflow calls
  ``examples.chain-leaf``. Each package declares what it calls in its
  manifest's ``[workflow.calls]`` table and calls it by alias (``"middle"``
  here, ``"leaf"`` in the Rust runner). A call names a *workflow*, and each
  child runs its own workflow's runner, whatever it is written in;
* results travel up as files: the leaf writes ``trail.txt``, the Rust
  workflow reads it from its child's workdir and adds a line, and this step
  does the same, so the finished trail reads bottom to top::

      examples.chain-leaf (Python)
      examples.chain-rust (Rust)
      examples.chain (Python)

* declared dependencies are checked before anything runs. Installing this
  workflow in a workspace (``httk workflow install examples.chain``, or
  ``httk job new --install``) installs every workflow it declares it calls,
  transitively, so all three names must resolve where it is installed, e.g.
  after ``httk plugin install`` of this repository. The Rust workflow is
  compiled and must be *built* (managers never build): the install builds it
  unless given ``--no-build``, and until it is built a manager leaves a job of
  this workflow unclaimed, ``httk job why`` / ``httk workflow precheck`` name
  chain-rust as not built, and ``httk workflow build examples.chain-rust``
  builds it.

The three jobs form one tree (the leaf is a child of the Rust job, which is a
child of this job), stay in this job's workspace, and move together on
transfer. ``httk collect --into STORE --id-base BASE`` stores one run
per job, each naming its own declaration, with every parent's run linked to
its child's.

The flow is::

    start ──call examples.chain-rust──► [start ──call examples.chain-leaf──► (leaf) ─► finish]
          ◄─────────────────────────────────────────gather──────────────────────────────┘
    finish ──► (succeeded)          (middle_failed when the Rust job did not succeed)
"""

from httk.workflow import Attempt, Runner

run = Runner("examples.chain")

LINE = "examples.chain (Python)\n"


@run.step
def start(a: Attempt) -> None:
    """Call the Rust workflow and wait for it (and, through it, for the leaf)."""

    # "middle" (the first argument) is the alias declared in [workflow.calls];
    # the label happens to be the same word.
    a.call("middle", label="middle")
    a.gather("finish", when="all_succeeded", on_impossible="middle_failed")


@run.step
def finish(a: Attempt) -> None:
    """Read the Rust job's trail and add our own line to it."""

    middle = a.children["middle"]
    trail = (middle.workdir / "trail.txt").read_text(encoding="utf-8")
    (a.workdir / "trail.txt").write_text(trail + LINE, encoding="utf-8")
    a.log.append("note", f"the chain left {trail.count(chr(10)) + 1} lines")
    a.succeed()


@run.step
def middle_failed(a: Attempt) -> None:
    """Reached through on_impossible when the Rust job did not succeed."""

    middle = a.children["middle"]
    reason = middle.failure.code if middle.failure else middle.kind
    a.fail("examples.middle_failed", f"the called Rust workflow did not succeed: {reason}")


if __name__ == "__main__":
    raise SystemExit(run.main())
