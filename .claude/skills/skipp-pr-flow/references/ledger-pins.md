# Line-pinned ledger catalog (skipp-algo)

These guard tests pin security-sensitive call sites by **exact `(file, lineno)`**. They
use git-tracked-file discovery, so they fire on your **real diff** (robust to worktree
location — unlike the budget guards in `gotchas.md`). Adding even one line above a
pinned site shifts its lineno and fails **both** halves (`no_new_sites` + `no_stale_ledger`).

| Guard test | What it pins | Where the pin lives |
| --- | --- | --- |
| `test_random_tempfile_ledger_pin` | `tempfile.mkstemp` | test-file constant `_TEMPFILE_LEDGER` |
| `test_mutable_defaults_and_loads_pins` | `json.load` + `os.environ[...]` subscripts | test-file constants |
| `test_os_unlink_remove_ledger` | `os.unlink` / `os.remove` | `OS_DELETE_LEDGER` |
| `test_silent_security_and_boundary_bundle` | `logging.basicConfig` + `sys.path` mutation | test-file constants |
| `test_sys_exit_ledger_pin` | `sys.exit` | test-file constant |
| `test_hashlib_weak_hash_ledger` | `hashlib.md5` | `_FROZEN_SITES` |
| `test_time_sleep_budget` | `time.sleep` | test-file `_FROZEN_SITES` |
| `test_http_client_discipline` / `test_urllib_urlopen_ledger` | `urllib` `urlopen` | test-file + `pin_registry.toml` (both) |
| `test_http_post_egress_ledger` | outbound `.post(...)` / POST `Request` | `HTTP_POST_LEDGER` / `URLLIB_REQUEST_POST_LEDGER` |
| `test_global_statement_budget` | `global` statements | `_FROZEN_SITES` `(file, line, sorted-names)` |
| `test_noqa_budget` | `# noqa` suppressions | `pin_registry.toml` noqa_budget.sites |
| `test_pytest_skip_budget` | `pytest.skip()` count **per test file** (`tests/` NOT excluded) | `pin_registry.toml` pytest_skip_budget.file_counts |
| `test_workflow_set_plus_e_inventory` | `set +e` per workflow | `pin_registry.toml` workflow_set_plus_e_inventory.allowed |

## How drift cascades (real examples)
- One `import math` + a 6-line guard near the top of a file drifted **4 separate ledgers**
  at once (urlopen in both `pin_registry.toml` and `test_http_client_discipline`, POST-Request,
  and two `global` anchors).
- A `+15`-line helper near the top of `run_open_prep.py` drifts **every** end-of-file pin
  (sys.exit, os.unlink, time.sleep, basicConfig, os.environ, field-preference count).

## Fixing drift cleanly
1. Run the guard to get the printed new linenos. Re-run **without** `--maxfail` to see the
   full failure set at once (the pre-push guard uses `--maxfail=1` under xdist).
2. For each drifted pin, edit the **test-file constant** (or the `pin_registry.toml` slice the
   guard reads) to the new lineno and append a dated comment:
   `# YYYY-MM-DD (context): OLD->NEW`.
3. Verify the actual new lineno in the source before editing the pin — recompute with a quick
   `grep -n` / a one-off `enumerate` script rather than trusting a mental offset.
4. Re-run `run_ledger_drift_guard.sh` until `rc=0`.

## Guard exemption mechanisms differ per guard — check before "fixing"
- **Zero-tolerance** (no allowlist → fix the code): `requests`→httpx, eager-logger format,
  naive-datetime, `yaml.load`.
- **File allowlists**: `_ALLOWED_RAW_WRITE_FILES`, `_FROZEN_FILE_COUNTS`, `ALLOWED_ORPHANS`
  in `pin_registry.toml`.
- **Inline markers**: e.g. `# ATOMIC-WRITE-EXEMPT:`.

## Prefer avoiding drift entirely
- Net-zero 1-for-1 edits with a **trailing** comment shift nothing (this fully avoided all 6
  `realtime_signals.py` ledger updates for one clamp fix).
- Import an alias **locally inside the function** that needs it (below all frozen sites), instead
  of adding a top-level aliased import that shifts every pin below it. Matches the `_ct_eq`
  local-import precedent.
- Rework a test to not need a new `pytest.skip` (e.g. force an ENOTDIR write-failure by dropping
  a *file* where a dir is expected, instead of `chmod 0o555` + a root-guard skip).
