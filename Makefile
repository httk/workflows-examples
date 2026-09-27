.PHONY: test test-extended lint

test:
	python3 -m pytest -q tests

test-extended:
	HTTK_TEST_PROFILE=extended python3 -m pytest -q tests

# ruff reaches the suffix-less executable instantiate hook through
# extend-include in pyproject.toml; the Bash runners and scripts are
# syntax-checked here.
BASH_EXECUTABLES = hello-bash/run.sh vasp-relax-bash-annotated/run.sh vasp-relax-bash-annotated/scripts/summary.sh

lint:
	python3 -m ruff format --check .
	python3 -m ruff check .
	for file in $(BASH_EXECUTABLES); do bash -n $$file || exit 1; done
