<!--
PR template (audit-L-1 R3-regex, 2026-05-12).

Use this checklist before requesting review. Items are advisory unless
called out as MUST.
-->

## Summary

<!-- 1-3 sentences: what changed and why. -->

## Checklist

- [ ] Tests added or updated for new/changed behaviour.
- [ ] **New test file? Wire it into the gate — a test that runs nowhere gates nothing (#3946, #3960, #3967).** `fast-gates` is the only merge-gating job.
      - **Python** that must gate → add to the `Run pin / ledger drift guard` step in `smc-fast-pr-gates.yml` **and** `FAST_TEST_FILES` in `tests/_fast_inventory.py` **and** `FULL_REQUIRED_PATH_TRIPWIRES` in `tests/test_fast_gates_silent_skip_coverage.py`. The meta-guards there name the exact list to touch and fail if you miss one.
      - **TypeScript** (`automation/tradingview/tests/*.test.ts`) → add an `npx tsx --test …` step **and** both `paths:` filters in `tv-onboarding-packages.yml`, **plus the source the test scans** (else a change there won't trigger the run). Or exempt it in `_TS_TESTS_INTENTIONALLY_UNGATED` with a reason. `test_every_ts_test_is_gated_or_exempt` enforces this.
- [ ] Pin tests run locally (`pytest tests/test_*_ledger.py tests/test_*_budget.py tests/test_*_pin*.py tests/test_*_tripwires.py -q`).
- [ ] If this PR changes config defaults in `newsstack_fmp/config.py`, run `python tools/check_defaults_table.py` and update `docs/CONFIG_DEFAULTS_TABLE.md` accordingly.
- [ ] If this PR adds a new probe under `scripts/probe_*.py`, every exception-formatting site is wrapped in `_redact_sensitive_error_text(...)` or carries a `# noqa: SECLEAK — <reason>` marker.
- [ ] If this PR changes a workflow cron/cap/timeout, the file header / module docstring / PR template references are updated to match.
- [ ] If this PR cites an audit retrospective section (e.g. `§R7`), the section actually exists in the cited doc.

## Linked work

<!-- e.g. "audit-L-1 R7", "issue #2169", "follow-up to PR #2167". -->
