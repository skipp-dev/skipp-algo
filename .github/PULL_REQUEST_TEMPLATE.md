<!--
PR template (audit-L-1 R3-regex, 2026-05-12).

Use this checklist before requesting review. Items are advisory unless
called out as MUST.
-->

## Summary

<!-- 1-3 sentences: what changed and why. -->

## Checklist

- [ ] Tests added or updated for new/changed behaviour.
- [ ] Pin tests run locally (`pytest tests/test_*_ledger.py tests/test_*_budget.py tests/test_*_pin*.py tests/test_*_tripwires.py -q`).
- [ ] If this PR changes config defaults in `newsstack_fmp/config.py`, run `python tools/check_defaults_table.py` and update `docs/CONFIG_DEFAULTS_TABLE.md` accordingly.
- [ ] If this PR adds a new probe under `scripts/probe_*.py`, every exception-formatting site is wrapped in `_redact_sensitive_error_text(...)` or carries a `# noqa: SECLEAK — <reason>` marker.
- [ ] If this PR changes a workflow cron/cap/timeout, the file header / module docstring / PR template references are updated to match.
- [ ] If this PR cites an audit retrospective section (e.g. `§R7`), the section actually exists in the cited doc.

## Linked work

<!-- e.g. "audit-L-1 R7", "issue #2169", "follow-up to PR #2167". -->
