# Pre-Flight Lint & Hygiene Protocol

> **Version:** 1.0 (2026-05-13)
> **Owner:** ops
> **Cadence:** consult before pushing any branch that touches `docs/` or shell snippets in docs or `_progress`-style sibling functions or line-pinned ledger tests
> **Related:**
> - `docs/COPILOT_REVIEW_TRIAGE_PROTOCOL.md` §§5.6, 5.7, 5.8
> - Operator-local memory `~/.copilot/memories/copilot-review-comments.md`
>   (this file is the **repo-resident sibling** so non-operator maintainers
>   can run the same gates without operator-local context)

---

## 1. Why this exists

Three Copilot finding-classes recurred across PRs #2173–#2179 (P5.4
doc-train) and were eventually traced to absent pre-flight gates rather
than to author negligence:

1. **Cross-line inline-backtick spans** in Markdown that render as raw
   `` ` `` characters — caught by Copilot, never by local tools.
2. **Lex-sort surprises** in shell snippets that rank numeric / version
   tokens (`sort` defaults to lex) — `10 < 2 < 9`.
3. **Silent stderr/stdout buffering** in `_progress`-style functions
   when only one of N sibling implementations carries the canonical
   `sys.stderr.flush(); sys.stdout.flush()` pair after `logger.info(...)`.

This protocol gates each class.

---

## 2. Gate A — Markdown inline-backtick lint

Repo-resident lint: `scripts/lint_md_inline_backticks.py`.

```bash
# warn-only (current default; CI parity)
python scripts/lint_md_inline_backticks.py docs/

# fail-mode (run before pushing any docs/ edit)
python scripts/lint_md_inline_backticks.py --strict docs/

# GHA-annotated output (used by .github/workflows/docs-lint.yml)
python scripts/lint_md_inline_backticks.py --format github docs/
```

CI wiring: `.github/workflows/docs-lint.yml` runs warn-only on every PR
touching `docs/**` or the lint script itself. The `--strict` flip lands
once the existing corpus is clean (tracked separately).

**False-positive escape hatch:** the lint already special-cases
CommonMark §6.1 multi-line spans (warn, never fail without `--strict`).
If you hit a new false-positive class, add a fixture to
`tests/fixtures/md_lint/known_good/` and tighten the matcher rather than
silencing the lint.

---

## 3. Gate B — `sort -n` / `sort -V` enforcement in shell snippets

Plain `sort` is **lex-sort**: `10 < 2 < 9`. Forbidden in any shell
snippet (docs, scripts, CI YAML) that ranks numeric / version-tagged
values, unless an inline justification comment is present.

Pre-flight grep:

```bash
# Run on every changed file before push:
grep -nE 'sort\b' <edited-file> | grep -vE -- '-n|-V|lex-sort intentional'
# Zero hits required.
```

Common cases:

| Pipeline | Wrong | Right |
|---|---|---|
| Top-N PRs | <code>gh pr list ... &#124; sort &#124; head</code> | <code>... &#124; sort -n &#124; head</code> |
| Semver tags | <code>git tag &#124; sort &#124; tail</code> | <code>git tag &#124; sort -V &#124; tail</code> |
| Run IDs | <code>gh run list ... &#124; sort &#124; head</code> | <code>... &#124; sort -n &#124; head</code> |
| Alphabetical token list | <code>... &#124; sort &#124; uniq</code> | OK with comment: `# lex-sort intentional: alphabetical token list` |

---

## 4. Gate C — Dual-stream flush parity for `_progress` siblings

Canonical pattern (P5.3-A6, P5.4-A1):

```python
logger.info(message)        # writes to stderr (logger basicConfig)
sys.stderr.flush()          # CRITICAL: logger goes to stderr
sys.stdout.flush()          # defensive: progress_callback / stdout writers
if progress_callback is not None:
    progress_callback(message)
```

Whenever you touch ANY `_progress` (or analogous) function, grep the
**whole repo** for sibling implementations:

```bash
# `sort` here is lex-sort intentional: alphabetical file-path listing.
grep -nE 'def _progress\(' scripts/ tests/ | sort
```

For each result, read ±10 lines and confirm both `flush()` calls are
present immediately after the `logger.info(...)` (or equivalent log
call). The P5.4 deep-review found **3 of 4 siblings missing the
canonical flush** — whole-repo grep is the cheapest insurance.

**Why both streams:** logger writes to `sys.stderr` per
`scripts/_logging_init.py:62` `basicConfig(stream=sys.stderr)`. A bare
`sys.stdout.flush()` flushes the wrong stream. A bare
`sys.stderr.flush()` misses any caller that wraps `_progress` with a
stdout-targeted `progress_callback` (e.g. tee-to-pipe, or
streamlit/jupyter capture). Both flushes are required and cheap.

---

## 5. Gate D — Whole-file grep before pushing header / ledger edits

When editing a file with header comments, module docstrings, or
line-pinned ledger entries that cite specific values / line numbers /
constants:

```bash
# After your replace_string_in_file edits, before commit/push:
grep -nE "<old-value-or-pattern>" <edited-file>
```

The diff context only shows ±3 lines. Module docstrings, file headers,
concurrency-rationale comments, and other unrelated mentions of the
old value will silently lap the change. Confirmed in F-V8-C4 PR #2066
(4 stale references missed) and re-confirmed by the P5.4 deep-review.

For ledger tests, all three encodings must be checked:

```bash
# Combined regex covers tuple, positional, and frozenset forms:
grep -rnE '"<file>\.py"[:,]\s*(?:frozenset\(\{)?\d+' tests/
```

Run the FULL pytest sweep with `-n auto` (NOT a `-k` filter) before
declaring the ledger update complete.

---

## 6. PR-author checkpoint

Before pushing any branch:

1. Run **§2** if any `*.md` is in your diff.
2. Run **§3** if any shell snippet was touched (in docs, scripts, or CI).
3. Run **§4** if any `_progress`-style function was touched.
4. Run **§5** if any header / docstring / line-pinned ledger entry was
   touched.
5. Run **§6.1** below before arming `gh pr merge --auto` on any new PR.

Zero output from the pre-flight greps is required before commit. CI
will catch regressions but the goal is to never land them.

### 6.1 Auto-merge race wait

Copilot does not auto-re-review after a `git push`. Arming
`gh pr merge --auto` immediately after PR creation can race Copilot's
first review and silently drop actionable inline comments.

**Wait constant: 8 minutes** (p95 + 20% margin from a 30-PR latency
dataset; full derivation in `docs/COPILOT_REVIEW_TRIAGE_PROTOCOL.md`
§5.9).

```bash
# Preferred: helper script handles the wait + early-exit on first review.
scripts/pr_arm_after_copilot.sh <pr-number>

# Manual fallback:
gh pr create ...
sleep 480
gh pr merge --squash --delete-branch --auto
```

PRs armed without this wait must be re-checked post-merge for missed
Copilot inline comments using the `COPILOT_REVIEW_TRIAGE_PROTOCOL.md`
§1 query.

---

## 7. Relationship to `COPILOT_REVIEW_TRIAGE_PROTOCOL.md`

`COPILOT_REVIEW_TRIAGE_PROTOCOL.md` covers the **post-push** workflow
(reading Copilot inline comments, triaging stale threads, resolving
threads). This document covers the **pre-push** workflow. They are
complementary: gates here prevent the comment classes that the triage
protocol then has to handle when they slip through.
