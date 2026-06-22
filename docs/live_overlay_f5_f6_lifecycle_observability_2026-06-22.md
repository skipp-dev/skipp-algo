# F5/F6 Lifecycle & Observation Guide (2026-06-22)

This note captures the implementation and operating posture for:

- **F5 — Runtime Lock Invariant** (live overlay bridge cache paths)
- **F6 — Branch Divergence Observation** (developer lifecycle hygiene)

## Scope

This is intentionally **observation-first**:

- no behavior change in production data paths
- explicit tests for lock/error-path invariants
- branch guard prints divergence signals without blocking non-main commits

## F5: Runtime Lock Invariant

### Covered components

- `services/live_overlay_daemon/github_workflow_bridge.py`
- `services/live_overlay_daemon/uptimerobot_bridge.py`

### Invariants

1. **Parallel snapshot coalescing**: under concurrent calls, at most one fetch is executed while TTL cache is cold.
2. **Parallel error coalescing**: when fetch fails, all concurrent callers receive a consistent fallback payload (`ok=0`, error type), not mixed/partial states.
3. **No race exceptions**: snapshot readers do not raise under concurrent first-time insert/fetch paths.

### Regression tests

- `tests/test_github_workflow_bridge.py`
  - `test_snapshot_coalesces_parallel_fetches`
  - `test_snapshot_parallel_fetch_error_is_coalesced`
- `tests/test_uptimerobot_bridge.py`
  - `test_snapshot_coalesces_parallel_fetches`
  - `test_snapshot_parallel_fetch_error_is_coalesced`

## F6: Branch Divergence Observation

### Implemented signal

`scripts/check_branch_safety.py` now reads `git status --porcelain=2 --branch`
and reports branch lifecycle state against tracked upstream when available:

- `AHEAD` (`ahead>0, behind=0`)
- `BEHIND` (`ahead=0, behind>0`)
- `DIVERGED` (`ahead>0, behind>0`)

### Blocking behavior (unchanged)

- Commits on `main` / `master` are still hard-blocked (exit code `1`).
- Divergence is currently **advisory** (observation) and does **not** block feature/fix branch commits.

### Tests

- `tests/test_check_branch_safety.py`
  - main-branch hard block
  - feature-branch happy path
  - divergence message rendering
  - subprocess failure fallback

## Operator Notes

- If divergence is reported repeatedly, re-sync before merge housekeeping.
- Keep this as report-only until false-positive rate and team cadence are stable.
- If you later ratchet to blocking, do it behind a documented threshold policy.

## Validation commands

- `python -m pytest -q tests/test_check_branch_safety.py`
- `python -m pytest -q tests/test_github_workflow_bridge.py tests/test_uptimerobot_bridge.py`
