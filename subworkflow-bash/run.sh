#!/usr/bin/env bash
# examples.subworkflow-bash: call another workflow as sub-workflows, gather,
# and aggregate; step for step the same as ../subworkflow/run.py.
#
# What this example shows:
#
#   * httk_workflow_call LABEL WORKFLOW --parameter NAME=VALUE creates a child
#     job of *another* workflow (here examples.subworkflow-child, a Python
#     workflow) and prints its job key;
#   * httk_workflow_gather waits for the calls, and httk_workflow_children
#     lists them, one tab-separated row each, in the step it resumes at;
#   * aggregating is reading each child's root.txt from its workdir.
#
# spawn or call? httk_workflow_spawn --step STEP (see the Bash runner API)
# starts a child at a step of *this same runner*; httk_workflow_call starts a
# child of a *different*, complete workflow with its own runner, parameters,
# declaration and failure handling. Both are gathered and read the same way.
#
# The called name is resolved when `start` runs, on the machine where the
# manager runs this step, as `httk job new --workflow NAME` would resolve it
# there: the child workflow must be registered or installed on that machine
# (e.g. `httk plugin install` of this repository). A git URI pinned to a
# commit works as well, and is fetched on first use:
#
#     git+https://github.com/httk/workflows-examples@<full commit>#subworkflow-child
#
# Called children live in this job's workspace, belong to this job, and move
# with it when it is transferred; a child cannot be transferred on its own.
#
# Provenance: `httk workflow collect --into results.sqlite --id-base BASE`
# stores one run per job even though neither workflow collects anything else;
# each run names its own workflow's declaration, and the parent's run links to
# every child's run by call label. `--no-bare-runs` leaves such runs out.
#
# The flow is:
#
#     start --call x3--> root (in each child) --gather--> aggregate --> (succeeded)
#                                                  \----> report_failures
set -euo pipefail
source "$HTTK_WORKFLOW_BASH_API"

# Must match `[workflow] name` and `[workflow.runner] steps` in httk_workflow.toml.
httk_workflow_runner examples.subworkflow-bash start aggregate report_failures

step_start() {
    local child_workflow value index=0
    local -a values
    child_workflow=$(httk_workflow_parameter child_workflow)
    read -ra values <<<"$(httk_workflow_parameter values)"
    for value in "${values[@]}"; do
        # --parameter NAME=VALUE: VALUE is stored as JSON when it parses as
        # JSON, so `value=4` is the number 4 the child's manifest asks for. The
        # parameters are checked against the child workflow's manifest right
        # here. The label names the child in httk_workflow_children and becomes
        # its job tag; the printed job key is not needed now.
        httk_workflow_call "value-$index" "$child_workflow" --parameter value="$value" >/dev/null
        index=$((index + 1))
    done
    # Job state survives the wait; gather itself takes no state.
    httk_workflow_state_set called "$index"
    httk_workflow_gather aggregate --when all_succeeded --on-impossible report_failures
}

step_aggregate() {
    local label state job_key workdir data root count=0
    # One row per succeeded child: label, terminal state, job key, workdir,
    # data directory (empty here: the child has no transactional data).
    : >summary.tsv
    while IFS=$'\t' read -r label state job_key workdir data; do
        root=$(<"$workdir/root.txt")
        printf '%s\t%s\t%s\n' "$label" "$job_key" "$root" >>summary.tsv
        count=$((count + 1))
    done < <(httk_workflow_children --succeeded)
    # Bash arithmetic is integer-only; awk adds up the (fractional) roots.
    awk -F '\t' '{ sum += $3 } END { printf "%g\n", sum }' summary.tsv >sum_of_roots.txt
    httk_workflow_runlog_note "aggregated $count of $(httk_workflow_state_get called) calls: sum of roots $(<sum_of_roots.txt)"
    httk_workflow_succeed
}

step_report_failures() {
    local label state job_key workdir data failed=
    while IFS=$'\t' read -r label state job_key workdir data; do
        # One field of one child: its published failure code.
        failed="${failed:+$failed, }$label: $(httk_workflow_child "$label" failure_code)"
    done < <(httk_workflow_children --failed)
    httk_workflow_fail examples.calls_failed "called workflow(s) failed: $failed"
}

httk_workflow_main
