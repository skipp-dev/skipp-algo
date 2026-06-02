# ADR-0011: Auto-merge + admin-bypass pattern for single-developer PRs

| Field      | Value                                                                 |
|------------|-----------------------------------------------------------------------|
| Status     | Accepted (Option C)                                                   |
| Date       | 2026-05-30                                                            |
| Deciders   | skipp-dev                                                             |
| Related    | branch protection on `main`, `gh pr merge --auto`, `gh api -X PUT pulls/{n}/merge` |

## Context

The repository operates with a single human committer (`skipp-dev`).
Branch protection on `main` currently requires:
- `fast-gates` status check (`strict=true`, must be up-to-date with main)
- *no* required reviews (today)

PRs are routinely opened by `skipp-dev` and armed with `--auto` to
squash-merge once CI is green. When required-review is enabled, GitHub
blocks **self-approval** — the author cannot approve their own PR.
The current workaround is `gh api -X PUT pulls/{n}/merge`, which the
admin role bypasses branch protection with.

This works but has an auditability gap: the merge does not show a
review trail in the PR timeline. For a solo committer this is
acceptable; for a future second contributor it is not.

## Decision drivers

- **Velocity**: each PR is small (often a pin-ledger bump). Manual
  approvals would dominate the cycle time.
- **Audit**: admin-merge silently bypasses any rule attached to
  required-reviews; no record of *why* the bypass happened.
- **Future-proofing**: a second contributor would inherit the bypass
  pattern unless an alternative is in place.

## Options

### Option A — Status quo (admin-merge bypass when blocked)
Pros: zero friction; works today. Cons: no audit trail; if reviews
become required, the bypass undermines them silently.

### Option B — Configure a CI-bot account that approves PRs
A separate GitHub account or App (e.g. `github-actions[bot]` via a
custom workflow with `pull_request_review` write permission) issues
the approval after `fast-gates` succeeds. Required-reviews stays on;
audit trail is honest.

Pros: real review trail, future-proof for second contributor.
Cons: needs a bot account / app installation; the bot becomes a
trusted principal that must be hardened (no rogue approvals).

### Option C — Drop required-reviews entirely
Codify the solo-committer reality. Branch protection requires only CI;
self-merge via `gh pr merge --auto` works without admin bypass.

Pros: removes the lie; no bypass needed. Cons: re-enabling reviews
later requires explicit policy work; second contributor onboarding has
a moment of "*everyone could merge anything*".

### Option D — Two-account discipline
Operate from a second GitHub account (`skipp-reviewer`) for reviews.
Pros: cheapest "real" review. Cons: account hygiene burden; same
human, so no genuine second pair of eyes.

## Decision

**Option C — Drop required-reviews on `main`.** Repository is single-
committer; the actual safety net is the `fast-gates` required status
check, not the review approval. Removing reviews ends the admin-API
bypass habit and restores a normal audit log. When a second
maintainer joins, this ADR is reopened and Option B (dedicated CI
bot) is adopted immediately.

## Consequences

- A is fine until day-N when a second contributor lands; then it
  becomes technical debt.
- B is the highest-quality solution but adds infrastructure surface.
- C is the most honest small-team choice and keeps the door open for B
  later.
- D is the worst of both worlds for a solo committer.

## Implementation

The decision is reflected in the live `main` branch-protection config
(required reviews absent; only the `fast-gates` status check required) and
in the audit tooling that verifies it:

- `scripts/verify_branch_protection.py` treats **absence of a required-review
  block (or a block with 0 required approvals) as the expected Option-C
  baseline**, reported informationally (`warn`). A **non-zero approval
  requirement is a hard `error`**, not "stricter": a positive approval count
  recreates the exact self-approval / admin-bypass failure mode this ADR
  eliminates. The single hard merge gate remains the required `fast-gates`
  status check.
- `tests/test_verify_branch_protection.py` pins all three shapes: required
  reviews absent (baseline — passes, `warn`), present with 0 approvals
  (passes, `warn`), and present with a positive approval count (fails,
  `error`).

When a second maintainer joins, reopen this ADR and adopt Option B (a
dedicated CI bot that approves after `fast-gates` is green); the verifier's
review check then tightens back to a hard requirement.
