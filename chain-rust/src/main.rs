//! examples.chain-rust: the middle of the three-language chain, in Rust.
//!
//! What this example shows:
//!
//! * a compiled runner on the native Rust SDK (`httk_workflow`, copied in from
//!   the installed *httk-workflow* by the Makefile). Every `Attempt` method runs
//!   the same bridge the Python and Bash SDKs use, so a Rust step calls,
//!   gathers and reads children exactly as they do;
//! * `attempt.call(label, workflow, args)` calls another workflow *by name*,
//!   here the Python workflow examples.chain-leaf. `args` are the options of
//!   `httk_workflow_call` (`--parameter NAME=VALUE`, `--file NAME=PATH`, ...);
//! * `attempt.gather(...)` waits, and in the resumed step
//!   `attempt.child(label, "workdir")` locates the child's workdir, so its
//!   result is a plain file read;
//! * this workflow is itself called, by the Python workflow examples.chain.
//!   Neither caller nor callee knows the other's language.
//!
//! The flow is:
//!
//!     start --call examples.chain-leaf--> (child) --gather--> finish --> (succeeded)
//!                                                     \-----> leaf_failed
//!
//! Build it with `httk workflow build` (see httk_workflow.toml); a bare
//! `cargo build` lacks the SDK crate the Makefile stages under target/sdk.

use std::fs;
use std::path::Path;

use httk_workflow::{Attempt, Gather, Runner, StepError};

/// This workflow's line in the trail.
const LINE: &str = "examples.chain-rust (Rust)\n";

fn step_start(attempt: &Attempt) -> Result<(), StepError> {
    // Declared with a default in httk_workflow.toml, so it is always set.
    let leaf = attempt.parameter("leaf_workflow", None)?.unwrap_or_default();
    // The name resolves on the machine where this step runs. `?` turns a
    // refused call (e.g. an unknown workflow) into an aborted attempt.
    attempt.call("leaf", &leaf, &[])?;
    attempt.gather(
        "finish",
        &Gather {
            when: Some("all_succeeded"),
            on_impossible: Some("leaf_failed"),
            ..Gather::default()
        },
    )?;
    Ok(())
}

fn step_finish(attempt: &Attempt) -> Result<(), StepError> {
    // `Ok(None)` would mean "no such child observed"; after the gather it is there.
    let workdir = attempt
        .child("leaf", "workdir")?
        .ok_or_else(|| StepError::with_message(1, "the gathered leaf child has no workdir"))?;
    let trail = fs::read_to_string(Path::new(&workdir).join("trail.txt"))
        .map_err(|error| StepError::with_message(1, format!("cannot read the leaf's trail.txt: {error}")))?;
    // A step starts in its own workdir, so a relative path lands there.
    fs::write("trail.txt", trail + LINE)
        .map_err(|error| StepError::with_message(1, format!("cannot write trail.txt: {error}")))?;
    attempt.succeed()?;
    Ok(())
}

fn step_leaf_failed(attempt: &Attempt) -> Result<(), StepError> {
    let code = attempt.child("leaf", "failure_code")?.unwrap_or_default();
    attempt.fail("examples.leaf_failed", &format!("the called leaf workflow failed: {code}"), false)?;
    Ok(())
}

fn main() {
    // Must match `[workflow] name` and `[workflow.runner] steps` in httk_workflow.toml.
    Runner::new("examples.chain-rust", &["start", "finish", "leaf_failed"])
        .step("start", step_start)
        .step("finish", step_finish)
        .step("leaf_failed", step_leaf_failed)
        .main();
}
