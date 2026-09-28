#!/usr/bin/env python3
"""examples.chain-leaf: the bottom of the three-language chain.

What this example shows: nothing new on its own. It is an ordinary one-step
Python workflow that writes ``trail.txt`` with one line naming itself. Its
caller, the Rust workflow ../chain-rust, reads that file from this job's
workdir, adds its own line, and so on up to ../chain. The runner never learns
that it was called, let alone by a Rust program.
"""

from httk.workflow import Attempt, Runner

run = Runner("examples.chain-leaf")


@run.step
def start_trail(a: Attempt) -> None:
    """Write the first line of the trail."""

    (a.workdir / "trail.txt").write_text("examples.chain-leaf (Python)\n", encoding="utf-8")
    a.succeed()


if __name__ == "__main__":
    raise SystemExit(run.main())
