# ADR-0009: Pin-ledger consolidation vs. per-domain ledger files

| Field      | Value                                                                 |
|------------|-----------------------------------------------------------------------|
| Status     | Proposed                                                              |
| Date       | 2026-05-30                                                            |
| Deciders   | skipp-dev                                                             |
| Related    | `tests/test_pytest_skip_budget.py`, `tests/test_urllib_urlopen_ledger.py`, `tests/test_noqa_budget.py`, `tests/test_workflow_orphan_inventory.py`, `tests/test_workflow_set_plus_e_inventory.py`, `tests/test_subprocess_shell_injection_pin.py`, `tests/test_workflow_upload_artifact_uniform_version.py` |

## Context

The repo currently maintains ≥7 independent "frozen ledger" test files,
each pinning a different drift surface (skip count per file, urlopen
sites, noqa suppressions, workflow orphans, `set +e` inventory,
subprocess shell injection sites, upload-artifact SHA allow-list).

Each ledger is hand-edited and lives in its own module with its own
`_FROZEN_*` constant, its own scanning logic, and its own error
message. Any non-trivial PR touches 1–3 of them; CI failures of the
class "*ledger drift*" account for a large share of the recent BLOCKED
PRs (#2450, #2447, #2445, #2421, #2448, #2451, #2452, #2453).

## Decision drivers

- **Discoverability**: a contributor adding a new `urlopen` cannot easily
  find which ledger they need to bump.
- **Atomicity**: a single PR that adds a new test + script + noqa needs
  three coordinated ledger edits in three files.
- **CI signal**: today the failure surface reads "*one of seven ledgers
  drifted*" rather than "*one logical pin drifted*". Cross-ledger
  conflicts (e.g. test-file added → both `test_pytest_skip_budget` and
  `test_no_pytest_skip_count_increases` need bumps) are easy to miss.

## Options

### Option A — Status quo (per-domain ledger files)
Each domain owns its own `_FROZEN_*` constant. Pros: minimal change,
each ledger reads in isolation. Cons: current pain (see above).

### Option B — Single canonical `pin_registry.toml`
All frozen state lives in one TOML registry under
`tests/_pin_registry.toml`. Each ledger test loads its slice. Pros:
one diff per PR, mechanical merge conflicts, no Python edits for data
bumps. Cons: TOML loader needed; per-domain test logic still lives in
seven modules; loses inline comments/justifications.

### Option C — `pyproject.toml` `[tool.skipp.pins]` section
Same as B but reuses an existing config root. Pros: no new file. Cons:
mixes data with build config; large diffs are visible in every
`pyproject` view.

### Option D — Generated ledger from source-of-truth scan
A `scripts/refresh_pins.py` regenerates all ledger files from the live
codebase; ledger tests then assert `live == frozen`. Operator runs the
script as part of any drift PR. Pros: eliminates hand-editing. Cons:
weakens the "*every drift is a deliberate review decision*" property —
the whole point of the ledgers is to force a human to look at the new
site before approving.

## Decision

*(pending operator)*

## Consequences

- B and C reduce CI reruns for purely-mechanical bumps but require a
  migration of all 7 ledgers in one PR.
- D is the highest-leverage but lowest-rigor option; only viable if
  paired with a separate "*new-site review*" gate.
- A is the cheapest path forward; the pain stays constant but is bounded.
