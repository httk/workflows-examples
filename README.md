# workflows-examples

Teaching examples of *httk₂* workflow packages. Every package here is written
to be read: each runner and hook starts with a "what this example shows"
header, and the comments explain why each line is there. They are **not**
production workflows. For real VASP calculations, use
[workflows-vasp](https://github.com/httk/workflows-vasp) (a reviewed remedy
ladder, POTCAR provenance, transactional publishing, postprocess plots), or
copy one of these packages and grow it.

All examples need an installed *httk-workflow*; the two VASP examples also
need *httk-atomistic*, for reading and writing structures. None of them needs
VASP to try out: `tests/mock_vasp.py` stands in for it (see below).

## Learning path

Read them in this order. Each one adds a few ideas to the one before.

| Directory | Workflow name | What it shows |
| --- | --- | --- |
| [`hello`](hello) | `examples.hello` | The smallest workflow: a minimal manifest and a one-step Python runner that reads a parameter, writes a file, and succeeds. |
| [`hello-bash`](hello-bash) | `examples.hello-bash` | The same in Bash: sourcing the Bash runner API, `step_` functions, outcome functions that return. |
| [`two-step`](two-step) | `examples.two-step` | The most basic multi-step workflow: `initial_step`, `advance` to a second step, and the two ways to hand something on: a file in the persistent workdir and a value in job state (`a.state`). Carries its own workflow declaration. |
| [`two-step-bash`](two-step-bash) | `examples.two-step-bash` | The same in Bash: `httk_workflow_advance --state`, `httk_workflow_state_get`. |
| [`vasp-relax-annotated`](vasp-relax-annotated) | `examples.vasp-relax-annotated` | The centerpiece. A VASP relaxation with every hook real: an `instantiate.py` that reads, validates and stages the input structure, derives a tag and a parameter (telling a caller-supplied value from a declared default); a three-step runner on `httk.workflow.codes.vasp` with a short remedy loop; a `collect.py` that reads the energy and relaxed structure itself; a postprocess script; an external declaration; declared parameters. |
| [`vasp-relax-bash-annotated`](vasp-relax-bash-annotated) | `examples.vasp-relax-bash-annotated` | The same declared workflow with a Bash runner on the Bash VASP API and an *executable* instantiate hook speaking the JSON stdin/stdout contract. |
| [`fan-out`](fan-out) | `examples.fan-out` | One job spawns one child job per value (`ChildSpec` + `spawn`), gathers them, and aggregates their results; the children read a file from the parent's workdir in place through `a.parent`; a failing child routes the parent to a triage step. |
| [`compose`](compose) | `examples.compose` | A workflow that calls another workflow (`hello`, by git URI) with `Attempt.call`, waits for it, and builds on its result. Its default URI needs network access and the pushed repository (see below). |
| [`subworkflow-child`](subworkflow-child) | `examples.subworkflow-child` | A one-step workflow that writes the square root of a number to `root.txt`: the workflow the two subworkflow examples call. Nothing in it knows it is called. |
| [`subworkflow`](subworkflow) | `examples.subworkflow` | A parent that declares `examples.subworkflow-child` in `[workflow.calls]` and calls it by alias once per value (`a.call("child", ...)`), gathers the calls, and adds up their results through `a.children`; `spawn` versus `call`, why called workflows are declared (checked at creation, not claimed until installed or built, undeclared calls refused), commit-pinned git URIs in `[workflow.calls]`, children moving with their parent, and one declaration per workflow; `httk workflow collect --into` then stores one run per job, each naming its own declaration, with the parent's run linked to its children's runs. Needs the child installed (see below). |
| [`subworkflow-bash`](subworkflow-bash) | `examples.subworkflow-bash` | The same parent in Bash (`httk_workflow_parameter_items` iterating the same JSON-array `values`, `httk_workflow_call`, `httk_workflow_children`), calling the same Python child: a call names a workflow, not a language. |
| [`chain-leaf`](chain-leaf) | `examples.chain-leaf` | The bottom of a three-language chain: a one-step Python workflow that starts `trail.txt`. |
| [`chain-rust`](chain-rust) | `examples.chain-rust` | The middle, a compiled Rust workflow on the native Rust SDK: `Attempt::call` of its declared `leaf` (`examples.chain-leaf`), `gather`, reading the child's workdir; `[workflow.build]`, `command = ["{artifacts}/chain"]`, and a Makefile that stages the installed SDK crate. Needs `cargo` and `make`, and a one-time `httk workflow build`. |
| [`chain`](chain) | `examples.chain` | The top: a Python workflow calls the Rust one through its declared `middle`, which calls the Python leaf; its jobs wait unclaimed until chain-rust is built, and `httk workflow build examples.chain` builds it; the trail comes back up with one line per level. Calls nest and cross languages. |

## Running an example

### From this repository by URI

A workflow package in a git repository is referenced by a git URI: the
repository, optionally `@<ref>` (branch, tag or commit), and `#<directory>`.
The first reference fetches and installs it; the job records the URI pinned
to the full commit.

```console
httk job new --workflow 'git+https://github.com/httk/workflows-examples#hello' --parameter name=Ada
httk workflow run
```

`httk job new` prints the job key and its payload directory; the greeting is
in `<payload>/run/greeting.txt` (`run/` is the job's workdir). Once
referenced, the short name works too: `httk job new --workflow examples.hello`.

The VASP examples take a structure file in any format httk reads, and need
the VASP command as a workspace setting (or `HTTK_VASP_COMMAND`):

```console
httk workspace settings set --key vasp.command --value "srun -n 16 vasp_std" default
httk job new --workflow 'git+https://github.com/httk/workflows-examples#vasp-relax-annotated' \
    --input structure=Si.cif
httk workflow run
httk workflow collect
httk workflow postprocess --script summary --workflow-dir ./vasp-relax-annotated   # from a checkout
```

Without VASP, name the mock instead:
`--value "python3 $PWD/tests/mock_vasp.py"`.

### From a local checkout

`--workflow-dir` uses a package directory directly, which is what you want
while editing one:

```console
httk workflow describe ./vasp-relax-annotated
httk job new --workflow-dir ./fan-out --parameter 'values=[1, 2, 3, 4]'
httk workflow run
```

A runner describes itself without running anything: `./hello/run.py --describe`.

`compose` calls `hello` by its default URI,
`git+https://github.com/httk/workflows-examples#hello`, which needs network
access and the pushed repository. To stay local, point it at a clone with a
`git+file://` URI (the clone must be a committed git repository):

```console
httk job new --workflow-dir ./compose \
    --parameter 'hello_workflow=git+file:///path/to/workflows-examples#hello'
```

### As a plugin

```console
httk plugin install 'git+https://github.com/httk/workflows-examples'
```

installs all fourteen packages listed in `httk_plugin.toml` at once; their
workflow names then resolve directly. The subworkflow and chain examples rely
on that: they declare the workflows they call in `[workflow.calls]` by name,
and a name is resolved on the machine where the job runs. `httk job new`
refuses a job whose declared calls do not resolve, so install the plugin (or
the called packages) there before creating one:

```console
httk plugin install 'git+https://github.com/httk/workflows-examples'
httk job new --workflow examples.subworkflow --parameter 'values=[1, 4, 9]'
httk workflow run
```

The chain examples also need the Rust middle built once per workspace and
machine (managers never build). Building a workflow by name builds every
workflow it declares it calls, transitively, so one command covers the
installed plugin; until then a chain job waits unclaimed, and `httk job why`
names chain-rust as not built:

```console
httk workflow build examples.chain
httk job new --workflow examples.chain
httk workflow run
```

## Anatomy of a package

A package is a directory with an `httk_workflow.toml` manifest and the files
it names. Each manifest table maps to a file (or to nothing, for pure
metadata):

| Manifest table | File | When it runs | Example |
| --- | --- | --- | --- |
| `[workflow]` (`name`, `description`, `requires`) | — | `requires` is checked at submission and at claim | all |
| `[workflow] declaration_uri`, `declaration_file` | `declaration.json` | carried into every job | `vasp-relax-annotated`, `two-step`, `subworkflow`, `subworkflow-child` |
| `[workflow.runner]` (`entry`, `steps`, `initial_step`, `data_mode`) | the `entry` member, here `run.py` or `run.sh` (any executable; `run` when `entry` is omitted) | once per attempt, by a manager | all |
| `[workflow.inputs.NAME]` | — (staged to `destination`, or consumed by the instantiate hook) | at submission | `vasp-relax-annotated` |
| `[workflow.parameters.NAME]` | — (read by hooks and runner) | type-checked at submission; defaults applied after the instantiate hook | `vasp-relax-annotated`, `two-step`, `fan-out`, `subworkflow` |
| `[workflow.outputs.NAME]` | — (produced by the collect hook) | at collection | `vasp-relax-annotated` |
| `[workflow.calls]` (alias = workflow name or commit-pinned git URI) | — (the runner calls the alias) | checked at submission and at claim; at run time only declared calls are allowed | `subworkflow`, `chain`, `chain-rust` |
| `[workflow.build]` (`command`, `platform`, `artifacts`) | `Makefile`, `Cargo.toml`, `src/main.rs` | once per machine, by `httk workflow build`; the runner is then `command = ["{artifacts}/chain"]` | `chain-rust` |
| `[workflow.instantiate] file` | `instantiate.py` (in-process) or `instantiate` (executable, JSON; any name without `.py`) | at submission, on the submitting machine, after the required-input check | both VASP examples |
| `[workflow.collect] file` | `collect.py` (in-process) or an executable (JSON lines) | at `httk workflow collect` | both VASP examples |
| `[workflow.postprocess.NAME]` | any executable (`scripts/summary.py`, `scripts/summary.sh`) | on request, after collection | both VASP examples |

A few distinctions the examples keep coming back to:

- **Inputs, parameters, settings.** An *input* is what the workflow operates
  on (a structure); it is part of the declaration and of the provenance. A
  *parameter* is a knob of this implementation (a k-point density); it is
  recorded in the job's `job.json` but does not change what the workflow is.
  A *setting* is a fact about the machine a job runs on (the VASP command, the
  pseudopotential library); a step looks it up when it runs, so the same job
  can run on different machines.
- **Submission time vs run time.** The instantiate hook runs immediately, on
  the submitting machine, with the user watching: read input formats,
  validate, name the job, record decisions there. The runner runs later,
  wherever a manager claims it: put machine-specific and expensive work there.
- **Declaration URI vs git URI.** `declaration_uri` is the `$id` of the
  declaration document, which says *what* the workflow is (inputs and outputs
  in OPTIMADE vocabulary). The git URI a job is created from names the
  *definition*, the code that ran. Both VASP examples are two definitions of
  one declaration, so they share its `$id`. The two-step and subworkflow
  packages each declare their own `$id`, and a called child job carries the
  declaration of the workflow it runs, not its caller's. The examples use an `example.org`
  `$id` because they are not a published declaration; a real workflow uses a
  URI its authors control.
- **Collect vs postprocess.** The collect hook turns a finished job into httk
  entries (a structure, a `DataRecord`) under declared roles, which
  `httk workflow collect --into results.sqlite` can store. A postprocess
  script is for anything else a person wants afterwards (a report, a plot); it
  writes only to its own output directory.

The full reference is the *httk-workflow* documentation: *Workflow packages in
detail*, *Workflows by URI*, *Composing workflows*, *Native runner helpers*,
and the *Native Bash runner API*.

## Testing

```console
make test                    # or: python3 -m pytest -q tests
make test-extended           # also the alternative input forms
make lint                    # ruff format/check (including the suffix-less instantiate hook) and bash -n
```

The tests drive every package end to end through the real APIs: they create
jobs with `httk.workflow.scaffold.new_job` (what `httk job new --workflow-dir`
calls), run a real `TaskManager` until idle, and collect with
`httk.workflow.collect`. The VASP examples run against `tests/mock_vasp.py`,
which computes nothing: it writes plausible OUTCAR, OSZICAR and CONTCAR files
(final energy -10.5 eV), and with `HTTK_MOCK_VASP_FAIL_ONCE=1` fails once with
a diagnosable error so the remedy loop runs. The `compose` test commits a
snapshot of this working tree into a temporary git repository and calls
`hello` through its `git+file://` URI, so it works before anything is pushed.
The subworkflow tests install this working tree as a plugin into the test's
isolated data home first, so the child resolves by name, offline, and then
collect the tree into a SQLite store to check its linked runs.
The chain test checks that a chain job stays unclaimed (and precheck names
chain-rust as not built) until `httk workflow build examples.chain` has built
chain-rust, and is skipped when `cargo` or `make` is not on `PATH`.
