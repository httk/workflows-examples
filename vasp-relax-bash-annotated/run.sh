#!/usr/bin/env bash
# examples.vasp-relax-bash-annotated: relax one structure with VASP, in Bash.
#
# What this example shows:
#
#   * the Bash runner library ($HTTK_WORKFLOW_BASH_API) plus the Bash VASP API
#     ($HTTK_WORKFLOW_VASP_BASH_API): every httk_workflow_* / httk_vasp_*
#     function is a thin call into the same implementation the Python runner
#     ../vasp-relax-annotated/run.py uses, so the two publish the same results;
#   * how a Bash step reads parameters (httk_workflow_parameter), settings
#     (httk_workflow_setting) and job state (httk_workflow_state_get), and how
#     it ends with exactly one outcome (advance / retry / succeed / fail);
#   * exit statuses as answers: httk_vasp_run reports how VASP ended through
#     its exit status, and a function that finds nothing returns 1.
#
# The flow is the same as the Python twin:
#
#     prepare --> run --> publish --> (succeeded)
#                 | ^
#                 +-+  retry after one remedy, at most maximum_remedies times
#
# The manager runs this script once per attempt, in the job's workdir
# (<payload>/run), and sets HTTK_WORKFLOW_JOB_DIR to the payload.
set -euo pipefail
source "$HTTK_WORKFLOW_BASH_API"
source "$HTTK_WORKFLOW_VASP_BASH_API"

# Must match `[workflow] name` and `[workflow.runner] steps` in httk_workflow.toml.
httk_workflow_runner examples.vasp-relax-bash-annotated prepare run publish

# Copy the staged structure into the workdir and derive KPOINTS and INCAR.
step_prepare() {
    local library ispin options
    # The executable instantiate hook wrote files/POSCAR into the payload.
    cp "$HTTK_WORKFLOW_JOB_DIR/files/POSCAR" POSCAR

    # A POTCAR staged with the job wins; otherwise a pseudopotential library
    # configured on this machine (a *setting*, not a parameter) is used.
    library=
    if [ -f "$HTTK_WORKFLOW_JOB_DIR/files/POTCAR" ]; then
        cp "$HTTK_WORKFLOW_JOB_DIR/files/POTCAR" POTCAR
    else
        # With the '' default an unset setting prints ''. It prints `null` only
        # when a value was stored as JSON null (e.g. --parameter
        # vasp.pseudo_library=null), which means "none" as well.
        library=$(httk_workflow_setting vasp.pseudo_library '')
        [ "$library" = null ] && library=
    fi

    # Start from an empty INCAR with ISPIN from the spin_polarized parameter
    # (the caller's value, the instantiate hook's derived one, or the declared
    # default). Parameters are read without defaults: every parameter declared
    # with a default in httk_workflow.toml is already in job.json, so a
    # fallback here would only be a second copy that can drift. ISPIN goes
    # in first because the NBANDS estimate reads it; incar_tags are applied
    # by httk_vasp_prepare afterwards, so an explicit ISPIN there still wins.
    : >INCAR
    ispin=1
    if [ "$(httk_workflow_parameter spin_polarized)" = true ]; then
        ispin=2
    fi
    httk_vasp_set_tag ISPIN "$ispin"

    # httk_vasp_prepare takes its options as a JSON file: the same fields as
    # Python's VaspPreparationOptions. The control directory is private to
    # this attempt, so the workdir holds only the calculation.
    options=$HTTK_WORKFLOW_CONTROL_DIR/vasp-options.json
    {
        printf '{"kpoint_density": %s, "incar_tags": %s' \
            "$(httk_workflow_parameter kpoint_density)" "$(httk_workflow_parameter incar_tags)"
        if [ -n "$library" ]; then
            printf ', "pseudopotential_library": "%s"' "$library"
        fi
        printf '}\n'
    } >"$options"
    httk_vasp_prepare --directory . --options "$options" >/dev/null

    httk_workflow_runlog_note "prepared a relaxation with ISPIN = $ispin"
    httk_workflow_advance run
}

# Run VASP once; advance when it completed, remedy and retry when it failed in
# a known way, fail otherwise.
step_run() {
    local command status classification energy applied decision problem
    # Resolved at run time: a vasp.command job parameter, HTTK_VASP_COMMAND on
    # this machine, then the workspace setting.
    command=$(httk_workflow_setting vasp.command '')
    # `null`: a vasp.command stored as JSON null, as for the library above.
    if [ -z "$command" ] || [ "$command" = null ]; then
        httk_workflow_fail vasp.command_missing \
            "no VASP command: set the vasp.command workspace setting or HTTK_VASP_COMMAND"
        return # outcome functions return; end the step right after one
    fi

    # Remove the previous attempt's outputs (CONTCAR and the run report stay).
    httk_vasp_preclean --directory . --keep WAVECAR --keep CHGCAR >/dev/null
    # httk_vasp_run supervises VASP and answers with its exit status. `|| status=$?`
    # keeps `set -e` from ending the step on a nonzero status we want to read.
    status=0
    # The command is one argv string (e.g. "vasp_std"; the parallel start comes
    # from the launch prefix HTTK_WORKFLOW_LAUNCH), so it is
    # deliberately unquoted and split into words.
    # shellcheck disable=SC2086
    httk_vasp_run --directory . --timeout "$(httk_workflow_parameter timeout)" \
        --report vasp-run-report.json -- $command || status=$?
    case $status in
        0) classification=completed ;;
        20) classification=diagnosed_stop ;;
        21) classification=nonconverged ;;
        22) classification=process_failure ;;
        124) classification=timeout ;;
        *)
            httk_workflow_fail vasp.failed "could not start VASP (status $status)"
            return
            ;;
    esac
    energy=$(httk_vasp_energy OSZICAR || true)

    if [ "$classification" = completed ]; then
        # --state writes job state together with the outcome.
        if [ -n "$energy" ]; then
            httk_workflow_advance publish --state classification="$classification" --state energy="$energy"
        else
            httk_workflow_advance publish --state classification="$classification"
        fi
        return
    fi

    # Plan one remedy from the reviewed ladder. Exit status 3 means "nothing
    # safe left to try"; the planned decision is written to a JSON file.
    applied=$(httk_workflow_state_get remedies || echo 0)
    decision=$HTTK_WORKFLOW_CONTROL_DIR/vasp-remedy-decision.json
    status=0
    problem=$(httk_vasp_remedy_plan vasp-run-report.json --directory . --output "$decision") || status=$?
    if [ "$status" -ne 0 ] && [ "$status" -ne 3 ]; then
        httk_workflow_fail vasp.failed "planning a VASP remedy failed with status $status"
        return
    fi
    if [ "$status" -eq 3 ] || [ "$applied" -ge "$(httk_workflow_parameter maximum_remedies)" ]; then
        httk_workflow_state_merge classification="$classification"
        httk_workflow_fail vasp.failed "VASP $classification after $applied remedies" --details "@$decision"
        return
    fi

    # Change the inputs, count the remedy, and ask for another attempt.
    httk_vasp_remedy_apply "$decision" --directory .
    httk_workflow_state_merge classification="$classification" remedies="$((applied + 1))"
    httk_workflow_runlog_note "applied a remedy for $problem"
    httk_workflow_retry "applied a remedy for $problem"
}

# Finish the job; the workdir is the result.
step_publish() {
    httk_workflow_runlog_note "relaxed; final energy $(httk_workflow_state_get energy || echo unknown) eV"
    httk_workflow_succeed
}

httk_workflow_main
