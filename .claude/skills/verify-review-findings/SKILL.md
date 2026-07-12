---
name: verify-review-findings
description: Verify external review / bug-hunt findings against CURRENT origin/main and every OPEN PR before writing any fix, so you reject false positives with evidence and never duplicate in-flight work. Use whenever someone hands over a review report or says "analysiere die Findings, fixe, eigener tree, pr" in skipp-algo (a repo with a very active parallel bug-hunt on the same account).
---

# Verify review findings before fixing

skipp-algo has a fast parallel bug-hunt running on the same `skipp-dev` account, so
handed-over findings are frequently **already fixed on main**, **already covered by an
open PR**, or **cited against a SHA that isn't in the repo**. Fixing before verifying
duplicates merged work, reverts better implementations, or fixes a non-bug. Do this pass
first; only then hand the real, unique remainders to the **skipp-pr-flow** skill.

## Instructions

### Step 1: Verify each finding against CURRENT origin/main
```bash
git fetch origin
```
- Reproduce every finding **empirically on a worktree at `origin/main`** — not stale local `main` (it lags), and not the SHA quoted in the report (reports cite SHAs like `30a9eb3` that don't exist here — a fork/mirror).
- Label each: **VALID (still present)** vs **already-fixed**. Read the actual code at the cited `file:line`; don't trust the report's description.

### Step 2: Distrust a handed-over "main" worktree or branch
A branch/worktree *named* after main may not be main. Cheap checks before trusting it:
```bash
git merge-base --is-ancestor <base-sha> origin/main && echo "is ancestor" || echo "NOT main"
git rev-parse origin/main:<file>            # compare blob vs the handed-over base
```
Real case: a pre-made `audit-origin-main @ 0b1e28c34` claimed "entspricht origin/main" with two "fixed" bugs — both were **already fixed on current origin/main with dedicated tests**, and committing the stale-base patch would have reverted the better implementations.

### Step 3: Check every OPEN PR, not just merged ones
```bash
gh pr list --state open
```
Diff the candidate files/functions against **each open PR**. Overlaps are the norm (one active bug-hunt, not separate colleagues). If a finding already lives in an open PR, **defer to the incumbent** — don't open a competing PR. Hand any genuinely-unique delta to the incumbent as a concrete code comment.

### Step 4: Re-fetch PR/merge state right before you branch
PR state is volatile mid-task. A finding can flip from "lives only in an open PR → defer" to "merged on main → now a legitimate direct fix" within one session (origin/main advanced 3× in one task; a targeted PR merged *during* it). Decide fix-vs-defer against the state **at branch time**, not at task start.

### Step 5: Before deferring, verify the incumbent is actually CORRECT
Trace the incumbent's logic — don't just confirm a guard exists. Deferring to a PR whose `if bars_since < 0: continue` was **dead code** (because `bars_since = max(0, …)` ran first) let its bug reach main. Also: two contradictory tests can coexist on main (one asserting correct behavior and FAILING, one asserting the bug and passing) when neither is in the fast-gate list — run the **full** suite (`pytest -q -n auto`), not just the ledger guard, to catch a red main.

### Step 6: Fix only the real, unique, unfixed remainders
Everything that survives Steps 1–5 (VALID + not-in-any-open-PR + incumbent-absent-or-wrong) is a legitimate fix. Base it on **current origin/main** and land it via the **skipp-pr-flow** skill. For rejected findings, write a one-line verdict with a code citation (`file:line` + why) so the same false positive isn't re-reported.

## Output discipline
- Every rejection cites evidence (blob compare, merge-base, or the exact contradicting code).
- Every deferral names the incumbent PR.
- Every fix states it was reproduced on current origin/main and is absent from all open PRs.
