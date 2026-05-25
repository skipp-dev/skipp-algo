# Repository conventions

Repo-wide conventions that are enforced by CI guards but were not
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

## 4. Source-pin ledgers (frozen call-site inventories)

**Guards:** every `tests/test_*_ledger.py` / `tests/test_*_ledger_pin.py`
file (~18 ledgers as of 2026-05-25), plus
[tests/test_pytest_skip_budget.py](../tests/test_pytest_skip_budget.py).

Repo policy freezes the **inventory of certain risky or audit-relevant
call sites** so any new use is a forced, reviewed decision. Examples
currently pinned:

| Ledger                                          | What it freezes                                                                |
| ----------------------------------------------- | ------------------------------------------------------------------------------ |
| `test_hashlib_weak_hash_ledger.py`              | `hashlib.md5/sha1` direct calls (non-security fingerprints only).              |
| `test_random_tempfile_ledger_pin.py`            | `tempfile.mkstemp` / random-temp call sites.                                   |
| `test_urllib_urlopen_ledger.py`                 | `urllib.request.urlopen` call sites (HTTP egress audit).                       |
| `test_http_post_egress_ledger.py`               | HTTP POST sites that leave the repo boundary.                                  |
| `test_os_environ_mutation_ledger.py`            | `os.environ[...] = ...` subscript writes (process-global side effects).        |
| `test_os_unlink_remove_ledger.py`               | `os.unlink` / `os.remove` (destructive filesystem ops).                        |
| `test_subprocess_spawn_sites_ledger.py`         | `subprocess.run/Popen` spawn sites.                                            |
| `test_sys_exit_ledger_pin.py`                   | `sys.exit` call sites (CLI exit-code contracts).                               |
| `test_sys_path_mutation_ledger.py`              | `sys.path` mutations (import-graph rewrites).                                  |
| `test_warnings_simplefilter_ledger.py`          | `warnings.simplefilter/filterwarnings` overrides.                              |
| `test_builtin_open_encoding_ledger.py`          | `open(...)` without explicit `encoding=`.                                      |
| `test_path_text_io_encoding_ledger.py`          | `Path.read_text/write_text` without explicit `encoding=`.                      |
| `test_dynamic_getattr_ledger.py`                | `getattr(obj, dynamic_str, ...)` (audit dynamic dispatch).                     |
| `test_bare_type_ignore_ledger.py`               | `# type: ignore` without an error-code suffix.                                 |
| `test_noqa_suppression_ledger.py`               | `# noqa` without an error-code suffix.                                         |
| `test_while_true_termination_ledger.py`         | `while True:` loop sites (must declare a termination path).                    |
| `test_prod_print_ledger.py`                     | Production `print(...)` (vs structured logging).                               |
| `test_nonlocal_budget.py`                       | `nonlocal` closure-state mutations.                                            |
| `test_mutable_defaults_and_loads_pins.py`       | Mutable default arguments + `json.loads` audit sites.                          |
| `test_http_client_discipline.py`                | HTTP-client `timeout=` / `headers=` pinning.                                   |
| `test_pytest_skip_budget.py`                    | Per-file `pytest.skip` / `@pytest.mark.skip` counts.                           |

### How a ledger fails

Each ledger declares a frozen inventory, typically `_FROZEN_SITES` or
`_FROZEN_FILE_COUNTS`, and runs three families of assertions:

1. **`test_no_new_*_files`** — a new file appears in the live inventory
   that the ledger doesn't know about. Forces the contributor to either
   refactor away the new use OR add it to the ledger with a justifying
   comment.
2. **`test_no_removed_*_files`** — a file in the ledger no longer
   contains any pinned site (good — migrated away — but the entry must
   shrink to keep the ledger truthful).
3. **`test_frozen_*_linenos_still_match`** — line-number drift in an
   existing file (someone inserted/removed code above a pinned call).
   The call itself is unchanged, but the cached line number is stale.
4. Often a fourth **`test_total_count_pinned`** — sum-of-counts didn't
   match `_FROZEN_TOTAL`; catches additions/removals that happen to
   leave individual file counts unchanged.

### How to update a ledger correctly

When a ledger test fails, decide which case applies:

**Case A — pure line drift (no new/removed call site).**
You moved code above a pinned line. The call's *semantics* are unchanged.
Fix: open the ledger file, update the frozen `lineno` set / file count
to the new live value, add a one-line comment explaining the shift, e.g.

```python
# #2334: cache-version comment block above CACHE_VERSION_BY_CATEGORY
# shifted sha1 call by 3 lines (85 -> 88); semantics unchanged.
"databento_utils.py": {"sha1": frozenset({88})},
```

The comment must reference the PR / issue causing the shift so future
auditors can reconstruct the drift history.

**Case B — new call site you intentionally added.**
The pinned category is opt-in for new uses. First decide whether the
new use is justified (the ledger docstring lists the criteria — e.g.
weak-hash ledger explicitly allows non-security fingerprints). If yes,
add the file + line(s) to the frozen inventory with a justifying
comment. If no, refactor (e.g. switch `sha1` → `sha256`).

**Case C — call site you removed (migration).**
Either delete the entry entirely (file no longer has any pinned call)
or shrink it (some lines removed, others remain). Update the comment.

### Skip-budget ledger specifics

`test_pytest_skip_budget.py` pins per-file counts of `pytest.skip(...)`
and `@pytest.mark.skip`. **Reductions are encouraged** — when a skip
goes away, drop or decrement the entry. **Increases require justification
in the PR description** (typically: optional dependency missing on a
runner, sparse-checkout artifact gap).

### Drift-comment hygiene

When you update a ledger, the explanatory comment is the audit trail.
Two recurring failure modes seen in review:

- **Wrong PR number** — copy-pasting an old comment block referencing
  a closed PR. Always update to the current PR number before pushing.
- **Stale line-shift math** — comment says `489 → 575` but the new
  pinned line is actually `587`. Recompute the actual delta from the
  diff before committing.

### Verifying a ledger update locally

```powershell
..\.venv\Scripts\python.exe -m pytest tests/test_<ledger_name>.py -q
```

Each ledger test is pure-AST / pure-regex and runs in well under 1 s,
so iterate freely until green.

## 5. `scripts/smc_atomic_write` — helper API

**Module:** [scripts/smc_atomic_write.py](../scripts/smc_atomic_write.py)

The four public helpers below replace the forbidden direct-write calls
listed in §2. All four follow the same contract: write to a unique
`tempfile.mkstemp` in the destination directory, set the file mode to
match the existing target (or a sane default for a new file), then
`os.replace` to the final path. Reader processes either see the prior
version or the new version — never a torn write.

| Helper                 | Signature                                                                                                | Replaces                                              |
| ---------------------- | -------------------------------------------------------------------------------------------------------- | ----------------------------------------------------- |
| `atomic_write_parquet` | `(df: pd.DataFrame, target: str \| PathLike, **kwargs) -> None`                                          | `df.to_parquet(target, ...)`                          |
| `atomic_write_csv`     | `(df: pd.DataFrame, target: str \| PathLike, **kwargs) -> None`                                          | `df.to_csv(target, ...)`                              |
| `atomic_write_text`    | `(text: str, target: str \| PathLike, *, encoding="utf-8", newline=None) -> None`                        | `Path(target).write_text(text)`                       |
| `atomic_write_json`    | `(payload: Any, target: str \| PathLike, *, indent=2, sort_keys=False, ensure_ascii=True, default=None) -> None` | `json.dump(payload, open(target, "w"))`        |

Notes:

- `**kwargs` on the DataFrame helpers are forwarded verbatim to the
  underlying pandas `to_parquet` / `to_csv` writer — pass `index=False`,
  `compression="zstd"`, etc. as you normally would.
- `atomic_write_json` is a thin wrapper over `atomic_write_text` + a
  preconfigured `json.dumps`. Defaults match the repo's serialization
  style (2-space indent, key order preserved, ASCII-safe). For
  byte-identical comparisons across runs set `sort_keys=True`.
- Parent directories are created (`mkdir(parents=True, exist_ok=True)`)
  before the temp file is opened — callers don't need to `mkdir` first.
- Any exception raised during the write deletes the temp file before
  re-raising. The destination is never left half-written.

Typical migration pattern:

```python
# BEFORE — flagged by tests/test_no_direct_to_csv_in_production.py
import json
from pathlib import Path

Path(out_path).write_text(json.dumps(report, indent=2), encoding="utf-8")

# AFTER — atomic, mode-preserving, parent-creating
from scripts.smc_atomic_write import atomic_write_json

atomic_write_json(report, out_path)
```

The helpers themselves live in `scripts/` and are exempt from the
guard (registered in the guard's `_FILE_LEVEL_EXEMPT`). Importing them
from production modules outside `scripts/` is fine.

## 6. Workflow → GitHub label contract (`PINNED_KNOWN_LABELS`)

**Guard:** [tests/test_workflow_issue_labels_exist.py](../tests/test_workflow_issue_labels_exist.py)

Every literal `--label <name>` argument passed to `gh issue create` (or
any other `gh` subcommand) from a workflow in `.github/workflows/*.yml`
MUST reference a label that actually exists in the repository. If `gh`
is handed an unknown label it exits non-zero, the alerter step fails,
and the alert that prompted the issue creation is silently lost — the
exact failure-mode of Bug-Hunt 2026-05-01 Finding F-04 (workflows were
posting to `c13`, `critical`, `drift`, `drift-alert`, `plan-2.8`,
`f2-rollback`, none of which existed).

The guard parses every workflow file, extracts each `--label` argument
(quoted, unquoted, comma-separated, `=`-form all supported), and
asserts each literal token is present in `PINNED_KNOWN_LABELS` — a
frozenset snapshot of `gh label list --json name` taken on 2026-05-01.
Dynamic labels (`${{ ... }}`, `$(...)`, `$VAR`) are skipped on purpose;
static guards cannot prove their runtime values.

### When you add a new label

The label and its pin MUST land in the **same PR** as the workflow that
first references it. Two-PR splits will fail CI on the workflow PR.

1. Create the label in the repo:

   ```powershell
   gh label create <name> --description "<purpose>" --color <hex>
   ```

2. Add `"<name>"` to the `PINNED_KNOWN_LABELS` frozenset in
   [tests/test_workflow_issue_labels_exist.py](../tests/test_workflow_issue_labels_exist.py),
   keeping the set alphabetically sorted.
3. Commit both changes together with the workflow edit.

### When you remove a label

Mirror the addition: remove every workflow reference, remove the entry
from `PINNED_KNOWN_LABELS`, then `gh label delete <name>`. The guard
will catch any stray workflow reference left behind.

### Out of scope

- Dynamic label expressions (`--label ${{ matrix.severity }}`) — the
  guard cannot evaluate them. Reviewer must confirm by hand that every
  possible runtime value is a known label.
- Labels applied via the REST API (`gh api -X POST .../labels`) — not
  parsed. Stick to `--label` on `gh issue create` / `gh issue edit` so
  the guard sees them.

### Verifying locally

```powershell
..\.venv\Scripts\python.exe -m pytest tests/test_workflow_issue_labels_exist.py -q
```


