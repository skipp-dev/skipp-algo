# ADR-0024: Allow `--force-with-lease` on `bot/*` snapshot branches (git push policy carve-out)

| Field   | Value |
|---------|-------|
| Status  | Accepted |
| Date    | 2026-06-10 |
| Refs    | Audit-R3 (Principal Review 2026-06-10); `scripts/publish_bot_snapshot.py`; `.github/workflows/smc-measurement-benchmark-rolling.yml` (bot/live-experiment-snapshot, added 2026-06-23); `.github/workflows/credential-health-check.yml` (bot/live-tv-credential-snapshot, added 2026-06-23); `.github/workflows/tv-save-consumer-source.yml` (bot/live-tradingview-bindings, added 2026-07-16); `scripts/publish_signals_snapshot.py` (bot/live-signals-snapshot host helper, added 2026-06-23); `tests/test_workflow_auth_pattern.py`; ADR-0010 (cron-workflow invariants) |

---

## Context

Repo policy (enforced by `tests/test_workflow_auth_pattern.py` since audit
F-02/F-05) prohibits bare `git push` in workflow `run:` blocks.  The
audit-R3 finding from 2026-06-10 additionally flags **any `--force*` flag**
as requiring explicit documentation, because the Principal Review prompt
lists `git push -f`, `git push --force`, and `--force-with-lease` in the same
"never" category without carve-outs.

The `smc-live-news-refresh.yml` workflow updates a rolling "live news
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
   `smc-live-news-refresh.yml:243`.

3. **The push is wrapped in `if git push ... ; then ... else ... fi`** — the
   existing `test_workflow_auth_pattern.py::test_workflow_git_push_is_safe`
   guard remains satisfied.

4. **The allowance is inventoried** — `tests/test_workflow_auth_pattern.py::test_workflow_force_push_is_allowlisted` (introduced alongside this ADR)
   asserts that every `--force-with-lease` occurrence in a workflow `run:`
   block appears in a explicit `_FORCE_LEASE_ALLOWLIST`.  Any new force-push
   must update the allowlist, which makes it discoverable at PR review time.

5. **Stateful and shared branches preserve the remote tree** — publishers
   that carry cumulative state or have more than one producer must seed from
   the fetched remote tip and replace only their owned paths. A fetch failure
   other than a confirmed missing branch is fatal. The shared
   `scripts/publish_bot_snapshot.py` helper enforces this contract and uses an
   explicit tip SHA (or zero SHA on first publish) in the lease. It retains the
   fetched snapshot tree in the index but re-parents each replacement commit to
   current `main`, keeping the cache branch to one snapshot commit beyond the
   base instead of accumulating a chain of historical snapshots.

---

## Consequences

* `smc-live-news-refresh.yml`, `run-open-prep-daily.yml`,
  `smc-measurement-benchmark-rolling.yml`, and `plan-2-8-evaluation.yml` use
  `scripts/publish_bot_snapshot.py`. The force-with-lease operation therefore
  lives in one tested helper rather than four workflow shell blocks. The helper
  seeds from the real branch tip, so a transient restore failure cannot replace
  cumulative state and the two experiment producers cannot delete each
  other's stable paths.
* The `smc-live-news-refresh.yml` snapshot mechanism continues to work
  without accumulating unbounded history on `bot/live-news-snapshot`.
* `run-open-prep-daily.yml` reuses the same carve-out to publish
  `latest_open_prep_run.json` to `bot/live-open-prep-snapshot` (2026-06-23,
  Task F-V8) so the realtime-signals producer can consume a stable,
  git-tracked snapshot path. The shared publisher builds the snapshot commit
  in an isolated temporary repository, so the workflow's later outcomes PR
  remains free of gitignored snapshot files.
* The same carve-out is reused by `smc-measurement-benchmark-rolling.yml`
  (added 2026-06-23), which publishes the daily experiment rollup +
  `plan_2_8_history.jsonl` to `bot/live-experiment-snapshot` so the
  live-overlay daemon (Grafana experiment panels) reads the freshest CI run
  via the GitHub Contents API instead of the stale Docker-baked seed. Both
  branches are pure cache cursors in the `bot/*` namespace and satisfy the
  constraints above.
* The carve-out is likewise reused by `credential-health-check.yml`
  (added 2026-06-23), which publishes the daily credential-health report
  (TradingView storage-state age probe) to `bot/live-tv-credential-snapshot`
  so the live-overlay daemon surfaces the cached-login age as a Grafana
  metric/panel before the 72h TTL expires.
* The same pattern is reused by `sweep-trap-shadow-daily.yml` (WS4a, added
  2026-07-11), which publishes the daily sweep-trap shadow monitoring snapshot
  to `bot/live-sweep-trap-shadow` so the live-overlay daemon fetches the
  freshest snapshot for the `lo-sweep-trap-shadow-stale` gauge. Same rolling
  `bot/*` cache-cursor pattern; force-with-lease with prior fetch.
* `tv-save-consumer-source.yml` (added 2026-07-16) publishes the latest
  saved-source SHA-256 comparisons and measured TradingView `input.source`
  dropdown assignments on the dedicated
  `bot/live-tradingview-bindings` cache branch. The workflow fetches
  the current tip and uses an explicit lease; the branch remains a pure
  machine-generated cache cursor consumed by the live-overlay daemon.
* `smc-r4-context-readback.yml` (added 2026-08-03) became a SECOND producer
  on `bot/live-tradingview-bindings`, publishing its own R4 rebind snapshot
  to `artifacts/monitoring/latest/tradingview_r4_context_bindings.json`
  alongside `tv-save-consumer-source.yml`'s `tradingview_consumer_bindings.json`
  in the same directory. This is the constraint #5 case: a bare `git add -f`
  of only its own file, committed on top of a fresh checkout (which does not
  carry that bot-branch-only directory at all), would silently delete the
  other producer's file the moment the commit became the new tip. Its
  publish step fetches first, seeds `artifacts/monitoring/latest/` from the
  fetched tip (`git checkout <tip-sha> -- artifacts/monitoring/latest`)
  before adding its own file, then stages the whole directory — replacing
  only its own path while carrying the sibling producer's file forward.
  `tv-save-consumer-source.yml` was not modified to seed symmetrically (it
  predates having a second producer on this branch and is intentionally
  left as the reference implementation for the single-producer case
  elsewhere in this ADR); the residual asymmetric risk — that workflow's
  next run can still overwrite the R4 path — is accepted for now and noted
  in the fix's PR description rather than silently left undocumented.
* The same pattern is applied outside CI by
  `scripts/publish_signals_snapshot.py`, a host-run helper that updates
  `bot/live-signals-snapshot` with `latest_realtime_signals.json` (which has
  no CI producer — it is written only by `open_prep/realtime_signals.py` on
  the live trading host). It uses the identical fetch-then-`--force-with-lease`
  sequence against a `bot/*` cache branch, plus a race-safe first-publish
  lease
  (`refs/heads/<branch>:0000000000000000000000000000000000000000`) so a
  concurrently created branch is never overwritten silently. Because it runs
  outside a workflow `run:` block
  it is not covered by `_FORCE_LEASE_ALLOWLIST`, but it honours the same four
  constraints, validates branch names defensively, and pushes only to the
  `bot/*` namespace.
* The same pattern is reused by `scripts/publish_universe_snapshots.py`
  (truth-audit #5, added 2026-07-11), which makes the point-in-time universe
  snapshot store durable across ephemeral CI runs by publishing
  `artifacts/universe/*.json` to `bot/live-universe-snapshot`. Unlike the
  single-file cursors this store **accumulates** (one file per trade date), so
  each publish seeds the work tree from the branch tip and copies the local
  snapshots on top before the `--force-with-lease` push, keeping prior days.
  It is invoked from `smc-databento-production-export.yml` (restore before the
  export, publish after) but the push itself lives in the script — like
  `publish_signals_snapshot.py` it is therefore outside `_FORCE_LEASE_ALLOWLIST`
  yet honours the same four constraints and `bot/*`-only namespace.
* A future `--force-with-lease` added outside `bot/*` or without a prior
  `git fetch` will be caught at PR time by the new allowlist test.
* The policy statement "never `--force*`" is now accurate as *"never outside
  the inventoried allowlist"*.
* R3 is closed; the audit trail is this ADR + the companion test.
