# Copilot Code-Review Triage Protocol

> **Version:** 1.0 (2026-05-12)
> **Owner:** ops
> **Cadence:** consult before declaring any PR with Copilot review activity "done"
> **Related:** `docs/AUDIT_L1_REVIEW_RETROSPECTIVE_2026-05-12.md` §R14

This document is the **versioned, repo-resident** counterpart to the
operator-local memory file `copilot-review-comments.md`. It exists so that
any maintainer (not just the operator who carries Copilot memory) can run
the same triage and produce the same outcomes.

---

## 1. The failure mode this protocol prevents

`gh pr view <N>` shows the PR body and top-level reviews **but not the
inline review-comment threads**. Treating that view as authoritative
results in entire sweeps of new Copilot inline comments being missed.

We have observed this pattern repeatedly in `skipp-algo`. The fix is
mechanical and is described below.

## 2. Mandatory commands — run BOTH before declaring a PR "done"

```bash
# 1. Inline review comments (line-pinned) — paginated
# `gh api --paginate` concatenates JSON arrays into a stream of separate
# top-level arrays (NOT a single valid JSON document), so use --slurp to
# join them into one outer array before json.loads.
gh api repos/skippALGO/skipp-algo/pulls/<N>/comments --paginate --slurp \
  | python3 -c "
import sys, json
pages = json.loads(sys.stdin.read(), strict=False)
data = [c for page in pages for c in page]
copilot = [c for c in data if 'opilot' in (c.get('user',{}).get('login') or '').lower()]
for c in copilot:
    body = (c.get('body') or '').replace(chr(10), ' ')
    print(f\"{c['path']}:{c.get('line')} [{c['user']['login']}]\n  {body}\n---\")
"

# 2. Unresolved review threads (filters out already-resolved/outdated)
gh api graphql -f query='query{
  repository(owner:"skippALGO", name:"skipp-algo"){
    pullRequest(number: <N>){
      reviewThreads(first: 100){
        nodes{
          id isResolved isOutdated path line
          comments(first: 5){ nodes{ author{ login } body } }
        }
      }
    }
  }
}' | python3 -c "
import sys, json
d = json.loads(sys.stdin.read(), strict=False)
for n in d['data']['repository']['pullRequest']['reviewThreads']['nodes']:
    if n['isResolved'] or n['isOutdated']:
        continue
    if not n['comments']['nodes']:
        continue
    if 'opilot' not in n['comments']['nodes'][0]['author']['login'].lower():
        continue
    print(f\"{n['path']}:{n['line']} thread={n['id']}\")
    for c in n['comments']['nodes']:
        print(f\"  [{c['author']['login']}] {c['body'][:240]}\")
    print('---')
"
```

> Both commands together. **Step 2 alone is not enough** — an inline
> comment can exist as a top-level review reply that is not surfaced as a
> "review thread" in the GraphQL view.

## 3. The triage decision — every unresolved thread

For each unresolved thread surfaced by step 2 above:

1. **Read the cited file at the cited line on the current branch tip**
   (`read_file <path> #L<line>` in tools, or `git show HEAD:<path>` in CLI).
2. **Decide:**
   - **Stale (already implemented):** the suggestion was already addressed
     by a later commit on the branch (or a separate merged PR).
     Resolve via the GraphQL mutation in §4 — **no code change**.
   - **Actionable:** the code still does not match the suggestion.
     Write the fix, push to the branch, then resolve via §4.
3. **Move on.** Do not bundle resolutions across PRs unless there is a
   clear thematic group.

> **Empirical base rate (Audit L-1, 2026-05-12):** ~60% of unresolved
> threads were stale at retrospective time. Treat "unresolved" as
> "needs triage", not as "needs fix".

## 4. Resolve a thread (after the fix or after stale-confirmation)

```bash
gh api graphql -f query='mutation{
  resolveReviewThread(input: { threadId: "<THREAD_ID>" }){
    thread{ isResolved }
  }
}'
```

The `<THREAD_ID>` is the `id` field returned by the GraphQL query in §2
(an opaque base64 string starting with `PRRT_`).

## 5. Common pitfalls

### 5.1 `jq` chokes on Copilot bodies
Copilot inline comments often contain literal control characters
(newlines inside fenced code blocks). `jq` parses them strictly and will
fail. **Use `python3 -c "... json.loads(..., strict=False) ..."` instead.**

### 5.2 `gh pr view` is not authoritative
`gh pr view <N>` shows the PR body and the top-level review summary. It
does **not** show inline thread state. Never declare a PR "done" based on
`gh pr view` alone.

### 5.3 Whole-file grep before pushing header/comment edits
When editing a YAML, Markdown, or test file with header comments that
cite **values, line numbers, or constants**, the diff context only shows
the immediate surroundings. The file header / module docstring / other
comments often reference the OLD value and will silently lap the change.

> **Always** run the following before pushing such edits:
> ```bash
> grep -nE "<old-value-or-pattern>" <edited-file>
> ```
> on the **whole file**, not just the diff hunk. (R13 from
> `docs/AUDIT_L1_REVIEW_RETROSPECTIVE_2026-05-12.md`.)

If your edit cites a `CHANGELOG` section (e.g. "see F-V8-C4 in CHANGELOG"),
also grep `CHANGELOG.md` to confirm the section actually exists. Otherwise
the citation is a broken reference.

### 5.4 Concurrency / shared mutable state
Any module-level mutable dict/list/set touched from a `ThreadPoolExecutor`,
`asyncio.gather`, or background daemon **must**:

1. Be guarded by an explicit `threading.Lock()` (or appropriate
   `contextvars`/thread-local for read paths).
2. Have a regression test that hammers it from ≥ 32 threads × ≥ 1000 ops
   with **sleep-injection** between read-modify-write to manufacture
   contention (a naive test may pass under the GIL even without the lock).
3. Snapshot reads must defensive-copy under the lock
   (`{k: dict(v) for k, v in d.items()}` rather than returning `d`).

Process-global env-var mutation (e.g. `os.environ["FOO"] = ...`) is
**never** an acceptable transport between caller and callee.

### 5.5 Feature-flag defaults
A single `ENABLE_*` env var must have **one** default-source-of-truth
(see `feature_flags.py` once R4 lands). Do not write
`os.environ.get("ENABLE_*", "<default>")` in business-logic modules; use
the typed flag.

### 5.6 Pre-flight Markdown lint (inline-backtick spans)

Cross-line inline-backtick spans render as raw `` ` `` characters and were
the dominant Copilot finding-class in the P5.4 doc-train (PRs #2173–#2179).
The repo-resident lint catches them before push:

```bash
python scripts/lint_md_inline_backticks.py docs/                # warn
python scripts/lint_md_inline_backticks.py --strict docs/       # fail
python scripts/lint_md_inline_backticks.py --format github docs/  # GHA annotations
```

CI runs the warn-only mode on every PR touching `docs/**` via
`.github/workflows/docs-lint.yml`. Whenever you edit Markdown, run
`--strict` locally before pushing.

### 5.7 Pre-flight `sort` ordering check (shell snippets in docs)

Plain `sort` is **lex-sort**: `10 < 2 < 9`. In any shell snippet that
ranks numeric / version-tagged values (PR numbers, run IDs, line
numbers, semver tags, byte counts), use one of:

- `sort -n` — numeric sort
- `sort -V` — version sort (handles `v1.10.0 > v1.9.0`)
- explicit `# lex-sort intentional: <reason>` comment

Forbidden in docs / CI / scripts unless justified inline:

```bash
... | sort | head    # ⛔ lex-sort surprise
```

Required:

```bash
... | sort -n | head   # ✅ numeric
... | sort -V | head   # ✅ semver
... | sort | head      # ✅ with comment: "# lex-sort intentional: alphabetical token list"
```

Pre-flight grep before pushing any docs / shell-script edit:

```bash
grep -nE 'sort\b' <edited-file> | grep -vE -- '-n|-V|lex-sort intentional'
```

Zero hits required.

### 5.8 Pre-flight dual-stream-flush check (sibling `_progress` functions)

The canonical `_progress` flush pattern (P5.3-A6, P5.4-A1) is:

```python
logger.info(message)        # writes to stderr (logger basicConfig)
sys.stderr.flush()          # CRITICAL: logger goes to stderr
sys.stdout.flush()          # defensive: progress_callback / stdout writers
```

Whenever you touch ANY `_progress` (or analogous) function, grep the
**whole repo** for sibling implementations and verify they all carry the
dual-stream flush:

```bash
# `sort` here is lex-sort intentional: alphabetical file-path listing.
grep -nE 'def _progress\(' scripts/ tests/ | sort
# For each result, read ±10 lines and confirm both flushes are present.
```

The P5.4 deep-review found 4 sibling implementations
(`databento_production_export.py`, `databento_preopen_fast.py`,
`generate_smc_micro_base_from_databento.py`,
`smc_microstructure_base_runtime.py`) — only one had the canonical
flush pair. Whole-repo grep is the lowest-cost insurance.

### 5.9 Auto-merge race wait constant

Copilot does not auto-re-review after a `git push`. When you arm
`gh pr merge --auto` immediately after PR creation, the PR can squash
before Copilot has emitted its first review — and any actionable
inline comment Copilot would have left is silently lost.

**Wait constant: `8 minutes`** between PR creation and arming
auto-merge. Derived from the last 30 merged PRs in this repo:

- N = 30 PRs with at least one Copilot review.
- p50 latency (PR created → first Copilot review): ~155s (2.6min).
- p95 latency: 399s (6.7min).
- p95 + 20% safety margin: 479s (8.0min) → rounded to **8 minutes**.

The +20% margin absorbs Copilot review-queue spikes. If Copilot has
not emitted a review after 8 minutes, the auto-merge is safe to arm
(in practice the queue rarely exceeds 7min).

Mechanism options:

```bash
# Option A — manual: open PR, wait, then arm
gh pr create ...
sleep 480
gh pr merge --squash --delete-branch --auto

# Option B — script for batch work (preferred)
./scripts/pr_arm_after_copilot.sh <pr-number>
```

PRs armed without this wait MUST be re-checked post-merge for missed
Copilot comments using the §1 query.

## 6. PR-author checkpoint (before declaring "done")

Before saying "PR #N done":

1. Re-run **both** commands in §2.
2. Verify zero unresolved Copilot threads remain (or every remaining
   thread has been triaged + resolved per §3).
3. CI passes (or auto-merge gate is in `BLOCKED→READY` only because of
   merge-state, not failing checks).
4. Only then commit/push/move on.

## 7. Reviewer / second-pair checkpoint

When reviewing a colleague's PR, run §2 yourself (do **not** trust the
PR-author's claim that no comments are unresolved). Then walk §3 for any
remaining items.
