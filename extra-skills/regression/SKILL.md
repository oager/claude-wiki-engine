---
name: regression
description: Run this project's regression test suite, report results, block deploys on failure
---

# /regression — Run Regression Test Suite

Run the project's test suite and report clearly. No environment assumptions here —
the session context (CLAUDE.md, project notes) tells you how to reach the machine.
This skill only knows what to run and how to report it.

## Step 1 — Detect the test framework

Check the project root in order:

| Signal | Framework | Default command |
|--------|-----------|-----------------|
| `pyproject.toml` / `pytest.ini` / `setup.cfg` with pytest config, or `tests/` dir | pytest | `python3 -m pytest <test_dir> -v --tb=short` |
| `package.json` with `"test"` script | jest / vitest / mocha | `npm test` or `npx vitest run` |
| `Cargo.toml` | cargo | `cargo test 2>&1` |
| `go.mod` | Go | `go test ./... -v 2>&1` |
| `Makefile` with `test` target | make | `make test` |
| Project CLAUDE.md specifies a test command | use that verbatim |

For pytest projects: prefer the most specific directory that contains regression tests
(e.g. `tests/agents/`, `tests/regression/`) over running the entire suite if a
regression subfolder exists.

## Step 2 — Run

Execute the detected command in the project root. If the project uses a virtual
environment or requires activation, do that first per the project's convention.
Capture stdout and stderr together.

## Step 3 — Report

```
✅  21 passed in 0.38s
❌  3 failed, 18 passed in 1.2s

FAILED tests/agents/test_foo.py::TestBar::test_baz
  AssertionError: expected warning, got info
```

Always report: pass count, fail count, elapsed time.
On failure: list each FAILED test name + the one-line assertion or error that caused it.
On collection error (import error, syntax error, missing dep): flag as
**collection failure** — distinct from a test failure — and quote the error.

## Step 4 — State the verdict

All pass:
> ✅ Regression suite clean — safe to restart / deploy.

Any failure:
> ❌ Regression suite has failures — resolve before restarting the loop / deploying.

## When to invoke

- After every bug fix (auto-invoked alongside `/error-harden`)
- Before restarting or deploying any live process
- After pulling commits from a collaborator
- Any time you are unsure whether recent changes broke existing behavior

## Adding regression tests

When a bug fix is written, add a test for it in the same session:

- **File naming:** `tests/<dir>/test_session_regression_YYYY_MM_DD.py` for Python;
  equivalent convention for other languages
- **One test class per bug fixed** — class name describes the component,
  method name describes the failure mode prevented
- **The test must fail on the unfixed code** and pass on the fixed code
- **Commit with the fix** or in an immediate follow-up labeled clearly
- **Not every fix needs a test** — focus on: silent failures, live-process crashes,
  edge cases with no other error signal. Skip for: config/log tweaks, already-covered paths.
