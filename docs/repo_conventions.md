# Repository conventions

Three repo-wide conventions that are enforced by CI guards but were not
previously documented in a single place. New code, new workflows, and new
tests must follow them or CI will block.

## 1. Workflow posture marker (`# live-window: <posture>`)

**Guard:** [tests/test_workflow_live_window_posture.py](../tests/test_workflow_live_window_posture.py)

Every file in `.github/workflows/*.yml` / `*.yaml` MUST declare its
operational posture as the first comment line, within the first 10 lines,
matching the regex `^# live-window: (\S+)`.

Accepted vocabulary (7 values):

| Posture                                  | Use when                                                                                  |
| ---------------------------------------- | ----------------------------------------------------------------------------------------- |
| `off-hours-only`                         | Schedule-only AND no `contents` / `pull-requests` / `issues` write permission.            |
| `mutating-on-cron`                       | Schedule-triggered AND at least one write permission (commits artifacts, opens PRs).      |
| `live-cron`                              | Schedule-triggered, intentionally inside the live trading handoff window.                 |
| `any-trigger`                            | Fires on `push` / `pull_request` (CI gates, ephemeral).                                   |
| `manual-only`                            | `workflow_dispatch` / `workflow_call` only.                                               |
| `deprecated-workflow_dispatch-only`      | Legacy manual-only workflow kept temporarily for rollback / compat until cutover lands.   |
| `release-driven`                         | Fires on `release` events.                                                                |

Example:

```yaml
# live-window: off-hours-only
name: weekly-dashboard
on:
  schedule:
    - cron: "0 6 * * 0"
```

The marker also gates `permissions:` audits — switching a workflow from
`off-hours-only` to `mutating-on-cron` is a posture change that must be
called out in the PR.

## 2. Atomic-write discipline in `scripts/` (`# ATOMIC-WRITE-EXEMPT: <reason>`)

**Guard:** [tests/test_no_direct_to_csv_in_production.py](../tests/test_no_direct_to_csv_in_production.py)

Production-flavoured code in `scripts/` MUST NOT call non-atomic writers
directly. Forbidden patterns include:

- `DataFrame.to_csv(...)` / `DataFrame.to_parquet(...)` / `DataFrame.to_json(...)`
- `Path.write_text(...)` / `Path.write_bytes(...)`
- `json.dump(...)` to a final destination path

Use the helpers in [`scripts/smc_atomic_write.py`](../scripts/smc_atomic_write.py)
instead: `atomic_write_csv`, `atomic_write_json`, `atomic_write_text`,
`atomic_write_bytes`. They write to a unique temp file and `os.replace`
to the final path so a torn write can never produce a half-written
artifact consumed by CI / tests.

If the call site is genuinely exempt (one-shot operator CLI, CI-only
scratch under `/tmp`, etc.), add a single-line marker **on the same line
or immediately above** the write:

```python
# ATOMIC-WRITE-EXEMPT: one-shot dev CLI (--apply regen of golden fixture); operator-supervised, no concurrent writers, not pipeline-consumed.
actual[cols].to_csv(expected_path, index=False)
```

The CI guard will then accept the call. Marker rules:

- One short line. State **why** (concurrent-writer risk absent, throwaway
  scratch, etc.) — not what.
- Keep within the function body, not on a separate doc-block.
- Do not abuse the marker to silence a real production write — those
  must use the atomic helpers.

## 3. Pytest-xdist parametrize determinism (`sorted(...)`)

**Guard:** [tests/test_pytest_xdist_parametrize_determinism.py](../tests/test_pytest_xdist_parametrize_determinism.py)

`@pytest.mark.parametrize` arguments whose source has a non-deterministic
iteration order under pytest-xdist MUST be wrapped in `sorted(...)` so
worker processes assemble the same parameter list in the same order.
Otherwise the suite is flaky under `-n auto`.

Non-deterministic call sources the guard rejects:

- `set(...)` / `frozenset(...)` / set literal `{a, b, c}`
- `os.listdir(...)` / `glob.glob(...)` / `Path.iterdir()` / `os.scandir(...)`
- `dict.keys()` / `dict.values()` / `dict.items()`

Fix pattern:

```python
# BAD — dict.items() iteration order is implementation-defined under xdist
@pytest.mark.parametrize("regime, score", _VOL_REGIME_BASE_SCORES.items())
def test_score_present(regime, score): ...

# GOOD — sorted enforces a stable parameter order on every worker
@pytest.mark.parametrize("regime, score", sorted(_VOL_REGIME_BASE_SCORES.items()))
def test_score_present(regime, score): ...
```

The same rule applies to set literals used as parameter sources — replace
`{1, 2}` with `(1, 2)` (tuple) or wrap as `sorted({1, 2})` if dedup is
intentional.

## Verifying locally

Before opening a PR that touches workflows, scripts, or tests:

```powershell
..\.venv\Scripts\python.exe -m pytest `
  tests/test_workflow_live_window_posture.py `
  tests/test_no_direct_to_csv_in_production.py `
  tests/test_pytest_xdist_parametrize_determinism.py `
  -q
```

All three are pure-stdlib / fast (~5 s combined) and run on every CI
job — failing any of them blocks merge.
