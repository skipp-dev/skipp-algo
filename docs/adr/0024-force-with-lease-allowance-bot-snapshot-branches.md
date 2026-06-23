# ADR-0024: Allow `--force-with-lease` on `bot/*` snapshot branches (git push policy carve-out)

| Field   | Value |
|---------|-------|
| Status  | Accepted |
| Date    | 2026-06-10 |
| Refs    | Audit-R3 (Principal Review 2026-06-10); `.github/workflows/smc-live-newsapi-refresh.yml:225`; `.github/workflows/smc-measurement-benchmark-rolling.yml` (bot/live-experiment-snapshot, added 2026-06-23); `.github/workflows/credential-health-check.yml` (bot/live-tv-credential-snapshot, added 2026-06-23); `scripts/publish_signals_snapshot.py` (bot/live-signals-snapshot host helper, added 2026-06-23); `tests/test_workflow_auth_pattern.py`; ADR-0010 (cron-workflow invariants) |

---

## Context

Repo policy (enforced by `tests/test_workflow_auth_pattern.py` since audit
F-02/F-05) prohibits bare `git push` in workflow `run:` blocks.  The
audit-R3 finding from 2026-06-10 additionally flags **any `--force*` flag**
as requiring explicit documentation, because the Principal Review prompt
lists `git push -f`, `git push --force`, and `--force-with-lease` in the same
"never" category without carve-outs.

The `smc-live-newsapi-refresh.yml` workflow updates a rolling "live news
snapshot" branch (`bot/live-news-snapshot`) with a lightweight JSON
microstructure file every cron tick.  The branch's sole purpose is to act
as a mutable cache cursor — there is intentionally no commit history worth
preserving across ticks.  The workflow has used `--force-with-lease` since
PR #2660's related consolidation.

---

## Problem

A `bot/*` snapshot branch accumulates one commit per cron tick.  Without
force-push the branch grows unboundedly (O(cron_ticks) commits, none of
which are useful after the next tick).  `git push --no-force` would work
only on the first push; after that the remote tip is always a different
commit than the local ancestor, causing every subsequent run to fail with a
non-fast-forward rejection — defeating the purpose of the branch entirely.

The alternatives are:

| Option | Rejection reason |
|--------|-----------------|
| Delete + recreate branch each run | Two atomic git operations with a race window; requires `git push origin --delete` which itself needs explicit carve-out and is harder to reason about than a force. |
| Squash-merge into a separate immutable history | Over-engineering for a pure cache cursor; creates unbounded main-branch churn. |
| Upload-artifact only (no branch) | Viable, but the branch is consumed by other steps in the same workflow that rely on a `git checkout` of the live state; switching would require a larger refactor out of scope here. |
| `--force` (no lease) | Would pass the carve-out bar but offers weaker safety: a concurrent manual fix-up commit on `bot/live-news-snapshot` would be silently overwritten. |

---

## Decision

**`--force-with-lease` is permitted exclusively on branches matching `bot/*`.**

Constraints that must hold for the allowance to remain valid:

1. **Branch is in the `bot/*` namespace** — the GitHub ruleset excludes
   `bot/*` from branch-protection, so the force-push reaches the remote
   without requiring admin override.

2. **Lease is populated before the push** — the workflow must execute
   `git fetch origin "+refs/heads/bot/...:refs/remotes/origin/bot/..."` (or
   equivalent) before the `--force-with-lease` call so the lease compares
   against the real remote tip rather than falling back to the "empty-lease"
   unconditional force.  This is already done at
   `smc-live-newsapi-refresh.yml:219-221`.

3. **The push is wrapped in `if git push ... ; then ... else ... fi`** — the
   existing `test_workflow_auth_pattern.py::test_workflow_git_push_is_safe`
   guard remains satisfied.

4. **The allowance is inventoried** — `tests/test_workflow_auth_pattern.py::test_workflow_force_push_is_allowlisted` (introduced alongside this ADR)
   asserts that every `--force-with-lease` occurrence in a workflow `run:`
   block appears in a explicit `_FORCE_LEASE_ALLOWLIST`.  Any new force-push
   must update the allowlist, which makes it discoverable at PR review time.

---

## Consequences

* The `smc-live-newsapi-refresh.yml` snapshot mechanism continues to work
  without accumulating unbounded history on `bot/live-news-snapshot`.
* The same carve-out is reused by `smc-measurement-benchmark-rolling.yml`
  (added 2026-06-23), which publishes the daily experiment rollup +
  `plan_2_8_history.jsonl` to `bot/live-experiment-snapshot` so the
  live-overlay daemon (Grafana experiment panels) reads the freshest CI run
  via the GitHub Contents API instead of the stale Docker-baked seed. Both
  branches are pure cache cursors in the `bot/*` namespace and satisfy the
  four constraints above.
* The carve-out is likewise reused by `credential-health-check.yml`
  (added 2026-06-23), which publishes the daily credential-health report
  (TradingView storage-state age probe) to `bot/live-tv-credential-snapshot`
  so the live-overlay daemon surfaces the cached-login age as a Grafana
  metric/panel before the 72h TTL expires.
* The same pattern is applied outside CI by
  `scripts/publish_signals_snapshot.py`, a host-run helper that force-updates
  `bot/live-signals-snapshot` with `latest_realtime_signals.json` (which has
  no CI producer — it is written only by `open_prep/realtime_signals.py` on
  the live trading host). It uses the identical fetch-then-`--force-with-lease`
  sequence against a `bot/*` cache branch. Because it runs outside a workflow
  `run:` block it is not covered by `_FORCE_LEASE_ALLOWLIST`, but it honours
  the same four constraints and pushes only to the `bot/*` namespace.
* A future `--force-with-lease` added outside `bot/*` or without a prior
  `git fetch` will be caught at PR time by the new allowlist test.
* The policy statement "never `--force*`" is now accurate as *"never outside
  the inventoried allowlist"*.
* R3 is closed; the audit trail is this ADR + the companion test.
