---
name: skipp-pr-flow
description: Land a code or doc change in the skipp-algo repo as a clean PR using the sibling-worktree + ledger-drift-guard workflow. Use whenever a change in skipp-algo needs its own branch and PR (e.g. the user says "fix X, eigener tree, pr" / "own tree + PR"), especially when editing production .py files that carry line-pinned security ledgers.
---

# skipp-algo PR flow

The skipp-algo repo has a strict pre-push gate (`scripts/run_ledger_drift_guard.sh`)
and dozens of guards that pin security-sensitive call sites by exact `(file, lineno)`.
Editing carelessly wastes a full ~2-min guard cycle per failed push. This skill is the
repeatable flow that avoids that.

## Instructions

### Step 1: Create a SIBLING worktree off origin/main
```bash
git fetch origin main
git worktree add /Users/spreuss/Documents/skipp-algo-wt-<name> -b <branch> origin/main
```
- **Sibling directory only** (next to the repo, e.g. `…/skipp-algo-wt-foo`). **Never** `.claude/worktrees/` and never a path nested *inside* the main checkout — the broad-except / budget guards discover files by walking the tree and a `.claude` ancestor (or nested worktree) produces **false positives** (`Frozen file(s) no longer contain…`, inflated urlopen/tempfile counts). See `references/gotchas.md`.
- Branch off `origin/main`, not local HEAD, so the PR diff is exactly your change.

### Step 2: Make the edits — net-zero near pinned files
- For production `.py` files, prefer **net-zero (1-for-1) edits**: change a line in place with a trailing `# comment`, not a comment block or `import` added *above* a pinned site. Adding even one line above a pinned call site shifts its lineno and fails the ledger.
- Keep sweep-discovered / non-essential edits **out of `open_prep/run_open_prep.py`** (~6k lines, many end-of-file pins — one top-of-file helper drifts them all). Document such edits for a focused follow-up instead.
- Test-only changes can also trip ledgers (`pytest.skip` budget, and `tests/` is not excluded). Don't assume `.sh`/test-only edits are guard-safe.

### Step 3: Verify — guard AND ruff, never piped
```bash
./scripts/run_ledger_drift_guard.sh > /tmp/guard.out 2>&1; echo "rc=$?"
grep FAILED /tmp/guard.out
ruff check .
```
- **Never pipe `git push` or the guard to `tail`** — the pipeline returns tail's `0` and masks a real failure. Redirect to a file and check `$?` / grep `FAILED`, or use `&&`.
- The guard **omits `ruff check .`** — run it separately (fast-gates runs a Ruff step the guard doesn't cover; I001 import-sorting and RUF012 mutable-default bite here).
- Run both from a **clean top-level checkout / your sibling worktree**, not from inside `.claude/worktrees/`.

### Step 4: On pin drift, update the ledger with a dated comment
The guard prints the new lineno for each drifted site. Update the pin in the **test-file constant** (or `pin_registry.toml` where that guard reads it) and add a dated comment: `# YYYY-MM-DD (context): OLD->NEW`. Re-run the guard until `rc=0`. The full pin catalog and which test owns each is in `references/ledger-pins.md`.

### Step 5: Commit, push, open the PR
```bash
git add -A && git commit -m "<type>(<scope>): <subject>

<body>

Co-Authored-By: Claude <noreply@anthropic.com>"
git push -u origin <branch> 2>&1 | tail -1   # OK to tail the PUSH LOG for display,
                                             # but confirm the branch actually moved
gh pr create --base main --head <branch> --title "…" --body "…"
```
- Do **not** use `--no-verify`. The pre-push hook re-runs the same guard — if it was green in Step 3 from a clean tree, it passes.
- End the commit body with the `Co-Authored-By:` trailer.

### Step 6: Clean up
```bash
git worktree remove /Users/spreuss/Documents/skipp-algo-wt-<name>
```
Remove the worktree after the push so stale sibling/nested trees don't pollute the next guard run.

## Recovery: diverged / squash-merged branch
If a push is rejected non-fast-forward (upstream rebased or the base PR squash-merged), don't force blindly. Rebuild the branch as `origin/main` + only your commit so the PR diff stays clean:
```bash
git fetch origin main <branch>
git reset --hard origin/main
git cherry-pick <your-commit-sha>     # re-runs guard-relevant pins on the fresh base
git push -f origin <branch>
```
Then re-check the PR's changed-file list is only yours.

## Critical rules (never violate)
- Sibling worktree off `origin/main`; never `.claude/worktrees/`, never nested in the main checkout.
- Pre-push = `run_ledger_drift_guard.sh` **and** `ruff check .`.
- Never pipe the guard (or a push whose success you're testing) to `tail`; check the real exit code.
- Net-zero edits near pinned `.py`; keep noise out of `run_open_prep.py`.
- Update drifted pins with dated comments; never `--no-verify`.
