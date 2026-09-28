#!/usr/bin/env python3
"""examples.chain: a Python workflow calls a Rust workflow that calls a Python one.

What this example shows:

* calls nest, and they cross languages. This workflow calls
  ``examples.chain-rust`` by name; that compiled Rust workflow calls
  ``examples.chain-leaf`` by name. A call names a *workflow*, and each child
  runs its own workflow's runner, whatever it is written in;
* results travel up as files: the leaf writes ``trail.txt``, the Rust
  workflow reads it from its child's workdir and adds a line, and this step
  does the same, so the finished trail reads bottom to top::

      examples.chain-leaf (Python)
      examples.chain-rust (Rust)
      examples.chain (Python)

* a compiled workflow must be *built* where it runs: before running this
  chain, register the Rust binary in the workspace with
  ``httk workflow build --workspace WORKSPACE ./chain-rust`` (managers never
  build). All three names must resolve on the machine that runs the calling
  steps, e.g. after ``httk plugin install`` of this repository.

The three jobs form one tree (the leaf is a child of the Rust job, which is a
child of this job), stay in this job's workspace, and move together on
transfer. ``httk workflow collect --into STORE --id-base BASE`` stores one run
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

    a.call(a.parameter("middle_workflow"), label="middle")
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
