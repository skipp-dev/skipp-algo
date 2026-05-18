# pytest-testmon PR fast-feedback lane

Status: **opt-in, default OFF.**

## What

[pytest-testmon](https://testmon.org/) records per-test execution
fingerprints in `.testmondata` and, on subsequent runs, selects only the
tests whose imported code has changed. On a PR that only touches a handful
of files this can collapse the validate-job test phase from full-suite
duration down to a few seconds.

This optimization is **only** applied to PR / non-main pushes. The
`main`-push validate run always executes the full suite (with coverage),
so stale-DB risk is bounded — any test that testmon incorrectly skipped on
a PR will run on the merge commit and fail there.

## Enable

```bash
gh variable set SMC_TESTMON_PR_LANE --body "true" --repo skippALGO/skipp-algo
```

While the variable is `true`:

- PR / non-main pushes run `pytest -q --maxfail=1 --testmon` (serial,
  testmon needs to see every test for selection).
- `.testmondata` is restored from and saved to `actions/cache`, keyed on
  `${{ runner.os }}-${{ github.base_ref || github.ref_name }}-${{ github.run_id }}`
  with restore-key fallback to the matching base ref then `main`.
- `main`-push runs are unchanged (full suite, coverage, xdist).

## Disable / roll back

```bash
gh variable delete SMC_TESTMON_PR_LANE --repo skippALGO/skipp-algo
```

PR / non-main pushes immediately revert to the no-coverage xdist path.

## Caveats

- **First PR run after enabling**: `.testmondata` cache is empty → testmon
  runs the full suite once to build it (no speedup yet).
- **Implicit dependencies**: tests that load data files / templates /
  generated artifacts without `import`ing them are not tracked by
  testmon. If you see a PR pass on the fast lane but fail on the main
  push, the fix is usually to convert the implicit dep into an explicit
  import (or fall back to the full xdist path while investigating).
- **Coverage and testmon do not compose**: the main-push coverage run is
  unaffected and remains the source of truth for coverage metrics.

## Manual local use

```bash
pip install pytest-testmon
pytest --testmon            # selects only affected tests
pytest --testmon-noselect   # rebuilds DB without skipping anything
rm .testmondata             # full reset
```
