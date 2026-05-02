# Proactive PR Review Prompt — Lessons Learned 2026-05-02

> Use this prompt verbatim against any PR (or stack of PRs) that touches
> CI workflows, CHANGELOG/README/audit docs, defensive test guards, or
> small-surface code refactors. It is calibrated against the concrete
> issue classes that surfaced during the V8 audit cleanup sweep on
> 2026-05-02 — issues which all standard CI gates and the standard
> reviewer pass missed but which Copilot inline review caught.
>
> Goal: **catch every one of these classes proactively, before the PR
> is opened**, not after Copilot flags them post-merge-armed.

---

## How to use

1. Run this prompt against the **diff** of every PR in the queue.
2. Run it AGAIN against any file the rebase touched, even if your diff
   says "1 line changed" — rebases combining `--ours` with env blocks,
   import lists, or list-typed YAML keys are the #1 source of silent
   regressions.
3. Output a table per PR with: file, line, class (from §3 below),
   severity (BLOCKER / FACTUAL / COSMETIC), suggested patch.
4. If anything in §1 (CI structural) hits, treat as BLOCKER and stop —
   the workflow will silently disappear from required-checks and
   branch protection will lock the PR with no actionable error.

---

## §1 — CI / Workflow structural traps (BLOCKER class)

For every changed `.github/workflows/*.yml` and
`.github/actions/*/action.yml`:

1. **Duplicate YAML keys after rebase.** Pipe the file through
   `python3 -c "import sys,yaml; yaml.safe_load(open(sys.argv[1]))"`
   AND through `yamllint -d "{rules: {key-duplicates: enable}}"`. The
   stdlib loader silently last-wins; GitHub Actions REJECTS the file
   and the workflow vanishes from the checks rollup with no error
   surfaced in the PR UI. Specifically check `env:`, `permissions:`,
   `defaults:`, `jobs.<id>.env:`, `concurrency:`.
2. **Required-check disappearance.** For every workflow whose job name
   is in branch-protection required checks, confirm the trigger still
   matches `pull_request: branches: [main]` AND that `paths:` /
   `paths-ignore:` was not narrowed by the diff. A required check that
   simply doesn't run shows as "Expected — Waiting" forever.
3. **`workflow_run` cannot expose `outputs`.** A `workflow_run`
   trigger downstream of another workflow has no access to upstream
   step/job outputs. If a doc or workflow claims it does, flag it.
   Recommend artifacts, `workflow_call`, or `repository_dispatch`.
4. **GHA expression date math is forbidden.** Expressions like
   `${{ github.event.schedule == '...' && weekday(...) }}` do not
   exist. The expression language has no date arithmetic and no
   weekday function. Use a small composite/inline action with `date`.
5. **Runner label drift.** Standard runner is
   `${{ vars.SMC_GH_HOSTED_RUNNER || 'ubuntu-latest-l' }}`. Flag any
   `ubuntu-latest`, `ubuntu-latest-m`, `ubuntu-22.04` etc. unless
   the PR explicitly justifies the deviation in the description.
6. **`actions/setup-python` direct use.** Repo standard is the
   `setup-python-pinned` composite (Python 3.12 pinned). Any direct
   `setup-python@vX` invocation needs an explicit ADR-style note.
7. **`PYTHONUNBUFFERED` / `PYTHONPATH` / `FORCE_JAVASCRIPT_*`
   ordering.** When env blocks are merged from two branches, eyeball
   the resulting key set against `main` — duplicates are the silent
   killer (see §1.1).
8. **Mutation workflows lacking guard.** Any `gh pr create`, `gh pr
   merge`, `git push`, `gh release create` step needs the
   environment+permissions+conditional triad. If guard is missing or
   was stripped during rebase, BLOCKER.

## §2 — Documentation factual traps (FACTUAL class)

For every changed `CHANGELOG.md`, `README.md`,
`docs/audits/*.md`, `docs/ci-proposals/*.md`, `memories/repo/proposals/*.md`,
audit follow-ups (`*_FOLLOWUP.md`, `*_PLAN.md`, `*_GAP_ANALYSE.md`):

1. **PR-number provenance.** Every `(#NNNN)` reference must point at
   a real PR whose merge commit actually contains the claimed
   functionality. Run `gh pr view <n> --json title,mergedAt,files`
   and confirm. Common failure: copy-paste from a sibling PR.
2. **Endpoint / function name typos.** Cross-check every cited
   function name against `grep -RIn "def <name>"`. Common failure:
   `get_insider_trade_statistics` vs the real
   `get_insider_trading_statistics`.
3. **Provider attribution.** When a doc says "X covers Y", verify by
   reading the provider client file. Today's failure: F&G claimed
   covered by Unusual Whales — actually covered by CNN +
   alternative.me. Short-interest provider-precedence claims are
   especially error-prone.
4. **Required-vs-optional env-var status.** README env-table rows
   must say "required for X feature, optional otherwise". Don't mark
   things "REQUIRED" globally if half the codebase has fallbacks.
   Today's failure: `BENZINGA_API_KEY` marked required when Benzinga
   OR FMP satisfies the news lane.
5. **Hardcoded-vs-env-driven IDs.** When a doc lists a UUID/client-id
   as configurable, verify the call sites — if it's a constant in
   code, the doc must say "hardcoded; do not override unless …".
6. **HTTP status-code claims.** Don't assert `401 Unauthorized` when
   the code path actually returns `404 Not Found` or `400 Bad
   Request`. Pull the most recent run's `provider_failures.jsonl` if
   in doubt; otherwise hedge ("expected per docs / may be enforced").
7. **Section / heading numbering.** When inserting sections into a
   numbered doc, confirm the renumbered indices end at the correct
   value. Today's failure: 8 → 11/12 instead of 8 → 9/10.
8. **Markdown table integrity.** After any table edit, check that
   header `|` count, separator `|---|` count, and each row's `|`
   count are identical. A single mismatch breaks the whole table
   silently in GitHub rendering.
9. **PR-range claims.** Avoid `(#1951..#1969)` style ranges if not
   every number in the range is on-topic. List the actual PR numbers.
10. **German Umlaute transliteration.** In any German prose doc
    (`*.md` containing "und", "die", "wir"), search for `ae`, `oe`,
    `ue`, `Ae`, `Oe`, `Ue`, `ss` patterns inside German words and
    flag transliterations like `aendern → ändern`, `klaeren →
    klären`, `koennen → können`, `muessen → müssen`, `groesse →
    größe`. Skip code identifiers and English words.
11. **Doc-path mismatch in PR description.** PR description's "see
    docs/foo/bar.md" must match the actual added file location. Today
    `docs/ci-proposals/` vs `memories/repo/proposals/` mixed up.

## §3 — Test-guard quality (DEFENSIVE class)

For every changed `tests/test_*.py` (esp. workflow / lint guards):

1. **`yaml.safe_load` over text matching.** Workflow assertions
   should `yaml.safe_load` and traverse the dict, NOT regex/text
   search. Text matching produces false positives on commented-out
   lines and false negatives on quoted/aliased values. Watch the
   YAML 1.1 quirk: bare `on:` parses as Python `True` — use
   `data.get(True) or data.get("on")`.
2. **Non-empty discovery assert.** Every `for path in WORKFLOWS:`
   loop must `assert WORKFLOWS, "no workflows discovered"` first —
   otherwise an empty glob silently passes the test.
3. **`encoding="utf-8"` on `read_text`.** Locale-dependent reads
   bite on Windows CI runners and on macOS in C locale. Always pass
   `encoding="utf-8"`.
4. **Fail-loud on YAML parse errors.** `try: yaml.safe_load(...)
   except yaml.YAMLError: continue` masks exactly the bug we want
   to catch. Re-raise (or `pytest.fail`) with the file path.
5. **Subset/superset checks for cron specs.** `_is_pure_cron(events)`
   returning True on `["push","schedule"]` is wrong. Require the
   trigger set to equal `{"schedule"}` (or be a subset of an
   explicit allowlist).
6. **Strong assertions over presence checks.** `assert "concurrency"
   in data` is weak. Also assert the `group` and `cancel-in-progress`
   values are what you claim.
7. **Per-file failure messages.** When a guard test iterates over N
   files, the assertion message must include the file path, else
   debug time explodes.

## §4 — Small-surface code traps (CODE class)

For every changed `.py` outside `tests/`:

1. **`s.strip()` on possibly-None.** Any `value.strip()` /
   `.upper()` / `.lower()` chain whose `value` came from a dict /
   request / DataFrame cell / env var must be `str(value).strip()`
   or guarded with `if value is None: ...`. Today: `open_prep/macro.py`
   3 spots.
2. **Wrapper duplication.** Two functions whose body differs only by
   a flag value should consolidate via the flag. Flag if you see
   `def get_stock_news(...): return _stock_news_impl(latest=False)`
   alongside `def get_stock_latest_news(...): return
   _stock_news_impl(latest=True)` is fine; flag if both bodies are
   copy-pasted.
3. **Missing test assertions for new params.** When a function gains
   a new optional parameter (`include_articles`, `include_events`),
   the corresponding test must assert that the parameter is
   propagated to the underlying client call (use `mock.assert_called_with`
   or `mock.call_args.kwargs[...]`).
4. **Magic-string repetition.** If the same param name string
   appears > 3 times across new code, flag for const extraction —
   but DO NOT block on this for queued PRs; defer to a follow-up.

## §5 — Process / merge-state traps

1. **`mergeable=true` + `mergeStateStatus=BLOCKED` + no failing
   check.** Means a required check is silently absent (see §1.1 /
   §1.2). Run `gh pr checks <n> | wc -l` and compare to expected
   count from branch protection.
2. **`UNSTABLE` ≠ failing.** A non-required check in progress will
   show UNSTABLE; do not retry the workflow, just wait.
3. **Race-prone files.** When N PRs in flight all touch
   `CHANGELOG.md` / `open_prep/macro.py` / `requirements*.txt` /
   any single-source-of-truth file, expect that the second-to-merge
   will go BLOCKED needing rebase + force-push. Sequence merges to
   minimize this.

---

## Output format expected from the reviewer

```
PR #NNNN  <branch-name>
─────────────────────────────────────
[BLOCKER §1.1] .github/workflows/foo.yml:18  duplicate PYTHONUNBUFFERED key
   → delete line 18 (kept on line 23)
[FACTUAL §2.2] docs/FMP_GAP.md:412  typo get_insider_trade_statistics
   → s/trade/trading/
[DEFENSIVE §3.1] tests/test_workflow_x.py:24  text-match instead of yaml.safe_load
   → load yaml; traverse data["jobs"]["fast-gates"]["env"]
[CODE §4.1] open_prep/macro.py:1248  s.strip() on possibly-None
   → str(s).strip()
[COSMETIC §2.10] docs/PROVIDER.md:137  "aendern" → "ändern"

Summary: 1 BLOCKER, 2 FACTUAL, 1 DEFENSIVE, 1 CODE, 1 COSMETIC
Recommendation: hold merge until BLOCKER fixed; rest can ship as a
follow-up commit on this branch.
```

---

## Self-test rubric

Before submitting your review, confirm you actually checked:

- [ ] Ran `python3 -c "import yaml; yaml.safe_load(open(<wf>))"` on
      every changed workflow file
- [ ] Cross-checked every `(#NNNN)` PR ref via `gh pr view`
- [ ] grep'd for `'ubuntu-latest'` exact match in every workflow diff
- [ ] grep'd for `setup-python@` (not the composite) in every diff
- [ ] grep'd for `aendern\|oeffnen\|muessen\|koennen\|groesser`
      in every German doc diff
- [ ] Re-counted markdown table `|` per row in every changed table
- [ ] Re-numbered every renumbered section
- [ ] For every test guard: confirmed `yaml.safe_load` + non-empty
      assert + utf-8 + per-file message
- [ ] For every `.strip()` on a non-literal: confirmed source is
      provably non-None or wrapped in `str(...)`
- [ ] Compared `gh pr checks <n>` count to branch-protection
      expected required-check count
