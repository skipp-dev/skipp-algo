# Worktree / guard false-positive gotchas (skipp-algo)

The **budget/discovery** guards (distinct from the line-pinned ledgers in `ledger-pins.md`)
walk the filesystem instead of git-tracked files, so their file discovery breaks when the
checkout has a `.` ancestor or when other sessions' worktrees/scratch files sit inside the tree.
These are **false positives** — the same commit passes on a clean top-level checkout. Do NOT
"fix" them by editing the frozen counts.

## Affected guards
`test_broad_except_silent_budget`, `test_socket_bind_loopback_pin`,
`test_assert_in_production_budget`, `test_global_statement_budget`,
`test_urllib_urlopen_ledger`, `test_random_tempfile_ledger_pin`, `test_pine_var_budget_pin`,
`test_loopback_and_baseimage_pin`, `test_no_new_syspath_mutation_sites`.

## Four manifestations seen
1. **Checkout under a dot-dir** (`.claude/worktrees/<name>/`): `test_broad_except_silent_budget`
   skips any path whose parts start with `.`, so **every** file is excluded → frozen files look
   "gone" → `Frozen file(s) no longer contain any broad-except`.
2. **Clean main checkout containing nested `.claude/worktrees/<name>/`** (left by other sessions):
   the budget/ledger guards' `_DIR_EXCLUDE` lists `.git/.github/.venv` but **not `.claude`**, so
   `rglob("*.py")` descends into the nested worktrees and counts their files as **NEW** sites
   (e.g. urlopen live=78 vs frozen=26; delta = 2 nested worktrees × ~26 each).
3. **Untracked scratch `.py` in the working tree** (e.g. `tmp/fuzz_*.py` from a parallel session;
   `tmp/` not excluded, file not gitignored) trips `test_no_new_syspath_mutation_sites`.
4. Same nested-worktree inflation on `test_urllib_urlopen_ledger` (PR #3201).

## Remedies (in order of safety)
- **Best — detached sibling worktree of YOUR branch, then push from there:**
  ```bash
  git worktree add --detach /Users/spreuss/Documents/skipp-algo-wt-push <your-branch>
  # push with a generous Bash timeout (guard is ~90s); NEVER --no-verify
  git -C /Users/spreuss/Documents/skipp-algo-wt-push push origin <branch>   # timeout: 300000
  git worktree remove --force /Users/spreuss/Documents/skipp-algo-wt-push
  ```
  This validates YOUR real diff (the detached tree checks out your commit) and never touches the
  mutating shared tree.
- **Push the shared branch ref from any clean sibling top-level checkout** that has no nested
  `.claude/worktrees/`: `git -C <clean-sibling> push origin <branch>`.
- **Parking `.claude/worktrees/` aside** only if the nested worktrees are `git status`-clean and
  idle (no parallel session regenerating them). A racing session rewrites the file mid-push and a
  foreground push that exceeds the ~2-min Bash timeout gets SIGTERM'd — the restore `trap` may not
  fire, leaving other sessions' worktrees un-restored. Prefer the detached-worktree remedy.

## Hard rules
- Never `--no-verify` — the pre-push hook running the guard is the whole point.
- Never delete or move **other** sessions' nested worktrees.
- Before fixing a "new site" finding, prove the flagged paths are under `.claude/worktrees/` or
  `tmp/` (not in your diff) — if so it's a false positive, not a regression.
- Check `git worktree list` + branch names before starting: parallel work can live in an
  uncommitted worktree, not just an open PR.
