# ADR-0013: Atomic vs cross-cutting workflow PRs

| Field      | Value                                                                 |
|------------|-----------------------------------------------------------------------|
| Status     | Accepted (Option C)                                                   |
| Date       | 2026-05-30                                                            |
| Deciders   | skipp-dev                                                             |
| Related    | PR #2449 (4-concern bundle), PR #2450, PR #2445 (both BLOCKED by #2449 conflicts) |

## Context

PR #2449 ("upload-artifact v7 + SMC_GH_HOSTED_RUNNER selector for 2
new workflows") bundled four logically-separate concerns:

1. `actions/upload-artifact` SHA bump (v4 → v7) in two workflows
2. `SMC_GH_HOSTED_RUNNER` runner selector update
3. `concurrency:` block (F-V5-C2) for `credential-health-check.yml`
4. `# live-window: …` marker (F-V6-F2.1) for the same workflow

Because all four touch the same files, two in-flight PRs (#2450
"post-merge ledger sweep" and #2445 "close 11 structural-invariant
regressions") now have unresolvable merge conflicts. The cost of
"*small atomic PRs*" was paid here as cross-PR rebase pain.

This pattern recurred earlier: cross-cutting workflow PRs habitually
collide with parallel ledger-sweep PRs.

## Decision drivers

- **Mergeability**: a single PR touching 5+ workflows almost always
  conflicts with any other in-flight workflow PR.
- **Reviewability**: a 4-concern PR forces the reviewer to context-
  switch four times.
- **Velocity**: tiny atomic PRs require more CI runs (each its own
  ~7-min cycle) but unblock parallelism.
- **Rebase cost**: with 2 workflow PRs in flight, an N-workflow PR
  causes 2N rebase touchpoints; with 5 PRs, 5N.

## Options

### Option A — Status quo (cross-cutting allowed)
Pros: fewer PRs to track; bulk fixes feel efficient. Cons: blocked
parallel work; cascading rebases (today's #2450/#2445).

### Option B — One workflow per PR, hard rule
Enforce via PR template + a CI check that fails if a single PR
modifies > 1 file under `.github/workflows/`. Pros: trivial conflict
math; clear ownership per PR. Cons: a single "*v7 bump everywhere*"
becomes 12 PRs; mass workflow updates have high overhead.

### Option C — One *concern* per PR
A PR may touch N workflows if all changes are the **same concern**
(e.g. "*upload-artifact v7 in all 12 workflows*" is one PR; "*add
concurrency block to credential-health-check*" is a separate PR).
Enforced by convention + PR title regex.

Pros: keeps mass-update efficiency; eliminates cross-concern
collisions. Cons: requires discipline; "*same concern*" is judgement-
based.

### Option D — Stack PRs (stacked / Graphite-style)
Each PR depends on the previous one explicitly. Cons: requires tooling
(`gh stack`, Graphite, or manual rebase chains); over-engineering for
a solo committer.

## Decision

**Option C — One concern per PR.** Bundles like #2449 (concurrency
+ marker + SHA bump across 3 workflows) are split: one PR per
concern, even if it touches many workflows. PR titles use the
convention `concern(scope): …` to make the rule self-checking at
review time.

## Consequences

- B is the simplest rule but bites on mass-action updates.
- C is the right granularity for this repo's cadence; needs only PR
  hygiene discipline.
- D is the most rigorous but adds tooling weight ill-suited to a
  single-committer flow.
- Whichever path, after this ADR is accepted the practice becomes:
  no more 4-concern workflow PRs like #2449.
