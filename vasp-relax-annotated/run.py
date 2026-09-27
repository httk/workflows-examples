#!/usr/bin/env python3
"""examples.vasp-relax-annotated: relax one structure with VASP, step by step.

What this example shows:

* a runner with several steps, and how a step decides what happens next:
  ``a.advance(step)`` runs another step, ``a.retry(reason)`` runs this step
  again, ``a.succeed()`` finishes the job, ``a.fail(code, message)`` stops it;
* job *state* (``a.state``), which survives retries and step changes;
* the difference between *parameters* (``a.parameter``: knobs of this job,
  fixed in its ``job.json`` when it was created; every parameter declared in
  ``httk_workflow.toml`` with a default already has its value there, so the
  runner reads it without a fallback of its own) and *settings*
  (``a.setting``: facts about the machine the job happens to run on, such as
  the VASP command, looked up when the step runs);
* the ``httk.workflow.codes.vasp`` primitives: prepare the inputs, run VASP under
  supervision, and plan and apply a remedy when VASP fails in a known way.

The flow is::

    prepare ──► run ──► publish ──► (succeeded)
                 │ ▲
                 └─┘  retry after one remedy, at most maximum_remedies times

Compared with the production ``vasp-relax`` of workflows-vasp, this runner
leaves out POTCAR assembly options, rattling, remedy policies, and the
transactional-data variant, so that every remaining line can be explained.

How the manager runs this file: once per *attempt*, as a separate process,
with the job's workdir (``<payload>/run``) as current directory. Nothing is
remembered between attempts except what is on disk: the workdir, the job
state, and the job definition.
"""

import shlex
import shutil

from httk.workflow import Attempt, Runner
from httk.workflow.codes.vasp import (
    VaspPreparationOptions,
    apply_vasp_remedy,
    clean_vasp_outputs,
    job_remedy_history_path,
    last_oszicar_energy,
    plan_vasp_remedy,
    prepare_vasp_inputs,
    run_vasp,
    validate_vasp_workdir,
)

# The name must equal `[workflow] name` in httk_workflow.toml, and the steps
# registered below must equal its `[workflow.runner] steps`.
run = Runner("examples.vasp-relax-annotated")


@run.step
def prepare(a: Attempt) -> None:
    """Copy the staged structure into the workdir and derive KPOINTS and INCAR."""

    # VASP truncates long paths; fail early and clearly instead.
    validate_vasp_workdir(a.workdir)

    # instantiate.py wrote files/POSCAR into the payload when the job was
    # created. a.payload is the job's directory; a.workdir is where VASP runs.
    shutil.copyfile(a.payload / "files" / "POSCAR", a.workdir / "POSCAR")

    # An optional POTCAR staged with the job (`--file POTCAR=...`) is used as is.
    # Otherwise, when this machine has a pseudopotential library configured,
    # prepare_vasp_inputs assembles one. Both are *machine* facts, which is why
    # the library is a setting and not a parameter.
    staged_potcar = a.payload / "files" / "POTCAR"
    library = None
    if staged_potcar.is_file():
        shutil.copyfile(staged_potcar, a.workdir / "POTCAR")
    else:
        library = a.setting("vasp.pseudo_library", None) or None

    # The INCAR starts empty; prepare_vasp_inputs derives EDIFF, EDIFFG, MAGMOM
    # (and NBANDS when a POTCAR exists). incar_tags are written first and are
    # never overwritten by a derived value, so the caller always has the last
    # word. ISPIN comes from the spin_polarized parameter: the caller's value,
    # instantiate.py's derived one, or the declared default, in that order of
    # precedence; an explicit incar_tags ISPIN wins over all three.
    (a.workdir / "INCAR").write_text("", encoding="utf-8")
    # No fallback defaults below: every declared default is already in
    # job.json by the time a runner starts (the framework applies them after
    # the instantiate hook). A missing name would raise KeyError, which is
    # what should happen.
    tags = {"ISPIN": 2 if a.parameter("spin_polarized") else 1}
    tags.update(a.parameter("incar_tags"))
    options = VaspPreparationOptions(
        kpoint_density=float(a.parameter("kpoint_density")),
        pseudopotential_library=library,
        incar_tags=tags,
    )
    prepare_vasp_inputs(options, directory=a.workdir)

    # The run log (logs/runlog.jsonl in the payload) is the job's own history.
    a.log.append("note", f"prepared a relaxation with ISPIN = {tags['ISPIN']}")
    a.advance("run")


# `run` is also the name of the Runner object, so the function gets another
# Python name and the step name is given explicitly.
@run.step(name="run")
def run_step(a: Attempt) -> None:
    """Run VASP once; advance when it completed, remedy and retry when it failed in a known way."""

    # A setting is resolved at run time, most specific first: a `vasp.command`
    # job parameter, the HTTK_VASP_COMMAND environment variable on this
    # machine, then the workspace setting (`httk workspace settings set
    # --key vasp.command --value "srun vasp_std" WORKSPACE`). The same job can
    # therefore run on two clusters with two different VASP commands.
    argv = shlex.split(a.setting("vasp.command", None) or "")
    if not argv:
        # A failure has a stable code (for `retry_on` and for triage) and a
        # message for a human. Not retryable: retrying cannot configure VASP.
        a.fail("vasp.command_missing", "no VASP command: set the vasp.command workspace setting or HTTK_VASP_COMMAND")
        return  # a published outcome ends the step; always return right after

    # A retry reruns in the same (persistent) workdir: remove the previous
    # run's outputs so they cannot be mistaken for this run's. CONTCAR and the
    # run report are kept by default, since remedies read them.
    clean_vasp_outputs(a.workdir, keep=("WAVECAR", "CHGCAR"))
    try:
        report = run_vasp(argv, directory=a.workdir, timeout=float(a.parameter("timeout")))
    except OSError as exception:
        a.fail("vasp.failed", f"could not start VASP: {exception}")
        return

    # run_vasp classifies the run: completed, nonconverged, diagnosed_stop,
    # process_failure, or timeout. State is a small JSON dict that belongs to
    # the job; it is written together with the outcome.
    oszicar = a.workdir / "OSZICAR"
    energy = last_oszicar_energy(oszicar) if oszicar.is_file() else None
    state: dict[str, object] = {"classification": report.classification}
    if energy is not None:
        state["energy"] = energy
    if report.classification == "completed":
        a.advance("publish", state=state)
        return

    # VASP did not complete. plan_vasp_remedy matches the diagnostics against
    # a reviewed ladder of known problems (e.g. "ZPOTRF failed" -> scale the
    # lattice). The history of applied remedies is kept next to the job state,
    # so the ladder is climbed rung by rung across attempts.
    history = job_remedy_history_path(a.payload)
    decision = plan_vasp_remedy(report.diagnostics, directory=a.workdir, history_path=history)
    applied = int(a.state.get("remedies", 0))
    if decision.give_up or applied >= int(a.parameter("maximum_remedies")):
        a.state.merge(state)
        a.fail("vasp.failed", f"VASP {report.classification} after {applied} remedies", details=decision.as_mapping())
        return

    # Change the inputs in the workdir, count the remedy, and ask the manager
    # for another attempt of this same step. The attempt budget of the job
    # (set when it is created) bounds retries as well.
    apply_vasp_remedy(decision, directory=a.workdir, history_path=history)
    a.state.merge({**state, "remedies": applied + 1})
    a.log.append("note", f"applied a remedy for {decision.problem}")
    a.retry(f"applied a remedy for {decision.problem}")


@run.step
def publish(a: Attempt) -> None:
    """Finish the job; the workdir is the result."""

    # With data_mode = "none" the persistent workdir is the result, and
    # collect.py reads CONTCAR and OUTCAR from it. A transactional workflow
    # would publish curated files here instead, e.g. a.put("CONTCAR", "CONTCAR").
    a.log.append("note", f"relaxed; final energy {a.state.get('energy')} eV")
    a.succeed()


if __name__ == "__main__":
    raise SystemExit(run.main())
