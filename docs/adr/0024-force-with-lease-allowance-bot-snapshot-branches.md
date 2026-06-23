# ADR-0024: Allow `--force-with-lease` on `bot/*` snapshot branches (git push policy carve-out)

| Field   | Value |
|---------|-------|
| Status  | Accepted |
| Date    | 2026-06-10 |
| Refs    | Audit-R3 (Principal Review 2026-06-10); `.github/workflows/smc-live-newsapi-refresh.yml:225`; `tests/test_workflow_auth_pattern.py`; ADR-0010 (cron-workflow invariants) |

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
* `run-open-prep-daily.yml` reuses the same carve-out to publish
  `latest_open_prep_run.json` to `bot/live-open-prep-snapshot` (2026-06-23,
  Task F-V8) so the realtime-signals producer can consume a stable,
  git-tracked snapshot path. The snapshot commit is built on a detached HEAD
  so the workflow's outcomes auto-merge PR diff stays free of the gitignored
  snapshot file; the lease is populated by a prior fetch and the push uses
  the `if git push ... ; then ... else ... fi` form. It is the second entry
  in `_FORCE_LEASE_ALLOWLIST`.
* A future `--force-with-lease` added outside `bot/*` or without a prior
  `git fetch` will be caught at PR time by the new allowlist test.
* The policy statement "never `--force*`" is now accurate as *"never outside
  the inventoried allowlist"*.
* R3 is closed; the audit trail is this ADR + the companion test.
