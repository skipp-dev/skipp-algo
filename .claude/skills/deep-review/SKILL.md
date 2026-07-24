---
name: deep-review
description: Systematic semantic/logic deep-review of a skipp-algo module or subsystem — reconstruct the spec, prove reachability EMPIRICALLY for every finding, separate real bugs from deliberate design, verify against fresh origin/main + the (stale) PRODUCTION_BUG_REPORT + open PRs, then land only the real+reachable+unique fixes via skipp-pr-flow. Use whenever asked to deep-review / audit code for trade-affecting bugs, e.g. "deep-review services/", "nächstes target", "review X bis keines mehr übrig ist".
---

# Deep-review a skipp-algo subsystem for real, reachable bugs

The goal is a SHORT list of **real, reachable, trade-affecting** findings plus **confident, evidenced refutations** — not a pile of "maybe" findings. In this repo a refutation-with-evidence is worth as much as a fix: a fast parallel bug-hunt runs on the same account, so most handed-over or freshly-found issues are **already fixed on main**, **already in an open PR**, **by-design**, or **not reachable**. Empirical reachability and by-design discrimination are what separate this from a linter.

Sibling skills — invoke them, don't reinvent: **verify-review-findings** (Step 1), **skipp-pr-flow** (Step 7), **truth-audit** (for name/doc-vs-behavior sweeps).

## Instructions

### Step 1 — Orient (before any expensive run)
- Invoke **verify-review-findings** first. `git fetch origin` and work against **fresh `origin/main`** — the local checkout usually LAGS. Read target code via `git show origin/main:<file>` or a worktree off `origin/main`; use the main-repo `.venv` (3.12) for empirical checks.
- Read the memory note `skipp-open-prep-deep-review-sweep` and the refutation notes first, so you don't re-chase already-settled items.
- Reconstruct the target's spec + **consumer map**: grep who consumes each output and whether it is WIRED to production vs shadow/dead. In skipp-algo, `a0_*`/`pre_a0_*` are shadow workers (mandatory `A0_FAST_MODE=shadow`), many modules are offline CLIs, and some are dead re-export shims — bugs there are not live. Confirm wired-ness before spending effort.
- Report the plan (target, consumers, candidate areas) BEFORE the expensive runs.

### Step 2 — Parallelize the recon, verify every lead yourself
- Fan out subagents (general-purpose) to scout modules for leads — each reconstructs its module's spec, greps consumers, proposes candidate findings with a reachability assessment, and cross-checks the stale `PRODUCTION_BUG_REPORT.md`. Give each a precise prompt: "prefer refutation-with-evidence; label trade-affecting vs display and reachable vs not; note by-design patterns."
- Treat subagent output as **leads, not conclusions**. Re-verify every real lead at the code yourself before acting on it.

### Step 3 — Prove reachability EMPIRICALLY, per finding
- For each candidate: construct an input that triggers it with the real code (the `.venv` interpreter), OR prove it cannot reach the production path. **No constructed trigger ⇒ "uncertain", never "confirmed".**
- Trace end-to-end: does the bad value actually flow into a decision (scoring / gating / signal firing / macro-regime / alerts / playbook / outcomes), or is it neutralized upstream (e.g. symbols upper-cased at ingestion, scores sanitized to finite, universe deduped)? An "unreachable" finding is a refutation, not a fix.

### Step 4 — Separate real bugs from DELIBERATE design
These are NOT bugs — flag as by-design WITH evidence (a named code, a test, an ADR, a docstring) and do NOT "fix" them:
- fail-open / warn-only data-quality handling (data issues warn, only *strength* demotes);
- asymmetric upside/downside weight knobs (e.g. `macro` reward vs a separate `risk_off_penalty_multiplier`);
- sign-gates / long-only triggers; documented dormancy; `None`→neutral(0.5) and missing-rvol (`has_rvol = ratio > 0`) discipline;
- named reason codes for a waiver (e.g. `CORE_*_LARGE_MOVE` granting a tier on price-move alone); deliberately non-iterated caps / pre-cap denominators.
Fighting a deliberate, tested design is the failure mode — surface it for the human, don't ship it as a fix.

### Step 5 — Cross-check the report + open PRs
- `open_prep/PRODUCTION_BUG_REPORT.md` is **massively stale** — verify every relevant entry against CURRENT code; many HIGH/MEDIUM are already fixed (wrong line/method names are a tell). Report stale entries; only mark one RESOLVED (or NOT REACHABLE) when you have PROVEN it.
- `gh pr list --state open` and diff the candidate files/functions against each open PR before writing a fix. If a finding already lives in an open PR, defer to the incumbent. Re-check PR/merge state right before you branch (it moves fast).

### Step 6 — Report with discipline
- Label each finding: **trade-affecting | alert/operator-facing | pure-display**; **reachable | not-reachable | uncertain**; **by-design?** — each with a one-line evidence citation (`file:line` + command output).
- Rank the actionable ones first; state refutations with the code citation that kills them.

### Step 7 — Land ONLY real+reachable+unique+not-by-design fixes (one PR each)
Hand each to **skipp-pr-flow**. Key mechanics that bite here:
- Sibling worktree off `origin/main`. **TDD red-first**; if the logic is duplicated (e.g. `open_prep/macro.py` ↔ `scripts/smc_macro_bias.py`), fix and test **both copies**.
- Prefer **net-zero (1-for-1 line)** edits near line-pinned files (trailing comment, not an added line). If you add lines, reconcile the drifted ledger pins with a **dated comment**: global-statement budget, `time.sleep`/`urlopen`/http-post-egress ledgers.
- Verify: `PYTEST_XDIST_AUTO_NUM_WORKERS=4 ./scripts/run_ledger_drift_guard.sh` must be **rc=0**. Do NOT use the default `-n auto` (12 workers on 16 GB → OOM/SIGKILL 137, truncated log with phantom `F`s); `PYTEST_ADDOPTS="-n N"` does NOT cap the workers. Run `ruff check` separately. Restore the `artifacts/monitoring/provider_usage.json` test side-effect before committing.
- Push **backgrounded** with `PYTEST_XDIST_AUTO_NUM_WORKERS=4` in the env (a foreground push orphans the pre-push hook and flakes); wait for the branch on the remote before `gh pr create`. Never `--no-verify`.
- **Never merge without the human's explicit signal.** Surface every by-design / strategy / behavioral-surface decision for the human's call — never ship one as a bug fix.

## Critical rules (never violate)
- No unverified assumptions (CLAUDE.md): every checkable claim resolved TRUE/FALSE/→follow-up with concrete evidence.
- Empirical reachability per finding — "looks wrong" is not "confirmed".
- Don't fight deliberate, tested design; don't build speculative hardening for an unreachable path.
- Verify against fresh `origin/main` + open PRs; the local tree lags and the bug-report is stale.
- Report faithfully — refutations are first-class deliverables.
