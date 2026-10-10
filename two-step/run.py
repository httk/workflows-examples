#!/usr/bin/env python3
"""examples.two-step: the most basic multi-step workflow.

What this example shows:

* a job runs one step per *activation*: ``a.advance("report")`` ends this step
  and asks the manager to run step ``report`` next, as a fresh attempt in a
  fresh process. Nothing in Python memory survives from one step to the next;
* the two ways to hand something to the next step:

  - **files in the persistent workdir.** Every step of a job starts in the same
    directory (``a.workdir``, ``<payload>/run``), so ``count`` writes
    ``words.txt`` and ``report`` reads it. Use files for results: anything
    large, anything a person wants to look at, anything another program reads;
  - **job state.** ``a.state`` is a small JSON object that belongs to the job
    (stored below ``<payload>/.httk-job/``). It survives step changes, retries
    and transfers, and also works for a job whose workdir is *isolated* (a
    fresh directory per attempt). Use it for small bookkeeping values: a
    count, a flag, how many retries were spent.

The flow is::

    count ──advance──► report ──► (succeeded)

Try it:

.. code-block:: console

    httk job new --install --workflow-dir two-step --parameter 'text=to be or not to be'
    httk workflow run
    httk job show KEY    # then read report.txt in the workdir it names
"""

from httk.workflow import Attempt, Runner

run = Runner("examples.two-step")


@run.step
def count(a: Attempt) -> None:
    """Split the text into words, write one per line to words.txt, and advance."""

    # Declared with a default in httk_workflow.toml, so it is always in
    # job.json and needs no fallback here.
    words = a.parameter("text").split()
    # A file in the persistent workdir: the next step finds it where we left it.
    (a.workdir / "words.txt").write_text("".join(f"{word}\n" for word in words), encoding="utf-8")
    # A value in job state. advance(state=...) writes it *before* publishing the
    # outcome, so `report` always sees the state that decided to run it. (The
    # same as `a.state["word_count"] = len(words)` followed by
    # `a.advance("report")`.)
    a.advance("report", state={"word_count": len(words)})
    # advance() is this attempt's one outcome: the step simply ends here. The
    # manager later starts this runner again with step `report`.


@run.step
def report(a: Attempt) -> None:
    """Read words.txt and the count from job state, write report.txt, and succeed."""

    words = (a.workdir / "words.txt").read_text(encoding="utf-8").split()
    counted = a.state["word_count"]
    # The two channels must agree; a mismatch would mean someone edited the
    # workdir between the steps. Failing with a code of our own says so clearly.
    if counted != len(words):
        a.fail("examples.words_changed", f"count saw {counted} words, but words.txt now holds {len(words)}")
        return
    longest = max(words, key=len) if words else ""
    (a.workdir / "report.txt").write_text(f"{counted} words; the longest is {longest!r}\n", encoding="utf-8")
    # The run log (<payload>/logs/runlog.jsonl) is for notes a person reads later.
    a.log.append("note", f"reported on {counted} words")
    a.succeed()


if __name__ == "__main__":
    raise SystemExit(run.main())
