#!/usr/bin/env bash
# examples.two-step-bash: the most basic multi-step workflow, step for step the
# same as ../two-step/run.py.
#
# What this example shows:
#
#   * httk_workflow_advance STEP ends this step and asks the manager to run
#     STEP next. The manager starts this script again, as a new process, so no
#     shell variable survives from one step to the next;
#   * the two ways to hand something to the next step:
#       - files in the persistent workdir: every step of a job starts in the
#         same directory, so `count` writes words.txt and `report` reads it;
#       - job state: `advance --state NAME=VALUE` (or httk_workflow_state_set)
#         stores a small JSON value with the job, and httk_workflow_state_get
#         reads it back in a later step. It survives step changes, retries
#         and transfers, even for a job whose workdir is isolated.
#
# The flow is:
#
#     count --advance--> report --> (succeeded)
set -euo pipefail
source "$HTTK_WORKFLOW_BASH_API"

# Must match `[workflow] name` and `[workflow.runner] steps` in httk_workflow.toml.
httk_workflow_runner examples.two-step-bash count report

step_count() {
    local text
    local -a words
    # Declared with a default in httk_workflow.toml, so it is always set.
    text=$(httk_workflow_parameter text)
    # `read -ra` splits on whitespace without expanding globs such as `*`.
    read -ra words <<<"$text"
    # A file in the persistent workdir (a step starts in it).
    : >words.txt
    if [ "${#words[@]}" -gt 0 ]; then
        printf '%s\n' "${words[@]}" >words.txt
    fi
    # A value in job state, written together with the outcome. The value is
    # stored as JSON: 9 becomes the number 9, not the string "9". The
    # equivalent in two calls is
    #     httk_workflow_state_set word_count "${#words[@]}"
    #     httk_workflow_advance report
    httk_workflow_advance report --state word_count="${#words[@]}"
    # Outcome functions return: the step function simply ends here.
}

step_report() {
    local counted word longest= actual=0
    counted=$(httk_workflow_state_get word_count)
    # Read the file the previous step left in the workdir.
    while read -r word; do
        actual=$((actual + 1))
        if [ "${#word}" -gt "${#longest}" ]; then
            longest=$word
        fi
    done <words.txt
    # The two channels must agree; a mismatch would mean someone edited the
    # workdir between the steps.
    if [ "$counted" -ne "$actual" ]; then
        httk_workflow_fail examples.words_changed "count saw $counted words, but words.txt now holds $actual"
        return
    fi
    printf "%s words; the longest is '%s'\n" "$counted" "$longest" >report.txt
    # A note in the job's run log (<payload>/logs/runlog.jsonl).
    httk_workflow_runlog_note "reported on $counted words"
    httk_workflow_succeed
}

httk_workflow_main
