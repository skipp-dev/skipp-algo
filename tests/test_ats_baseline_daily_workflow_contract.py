"""Contract pins for the ats-baseline-daily workflow (WP-J daily producer).

The workflow exists because ``scripts/build_ats_20d_baseline.py`` promised a
daily job since PR #2613 that was never wired: the committed baseline stayed
the 1970 seed with ``symbols={}`` and the WP-K /smc_live overlay fail-closed on
every lookup. These pins keep the wiring honest:

* the schedule stays AFTER Databento same-day finalization in BOTH halves
  of the year (winter close is 21:00 UTC + ~1h finalization => >= 22:00
  UTC), otherwise the trailing window silently excludes today's session
  every day of the EST half — the old >= 21:00 pin encoded the EDT close
  only and would have gone stale on 2026-11-01 (Grenzgaenger A5);
* the empty-baseline publish gate stays in place — without it a provider
  outage would replace a good baseline with an empty one and re-kill exactly
  the fields the job exists to feed;
* the publish path keeps the GH_PAT auto-merge discipline and targets the
  committed artifact path the WP-K consumer reads.
"""
from __future__ import annotations

import re
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ats-baseline-daily.yml"


def _source() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_schedule_runs_after_databento_finalization() -> None:
    # 2026-08-18 (Grenzgaenger A5): repinned 21 -> 22. GitHub cron is UTC-only
    # while the US close is ET, so the bound must encode the WINTER (EST)
    # close: 21:00 UTC + ~1h Databento finalization. The old >= 21 bound was
    # true only during EDT and would have let the job run pre-finalization
    # every day from 2026-11-01 on.
    match = re.search(r'cron:\s*"(\d+) (\d+) \* \* 1-5"', _source())
    assert match, "weekday cron missing"
    hour = int(match.group(2))
    assert hour >= 22, (
        f"cron hour {hour} runs before Databento same-day finalization in the "
        "EST half of the year (winter close 21:00 UTC + ~1h finalization)"
    )


def test_empty_baseline_publish_gate_present() -> None:
    src = _source()
    assert "Refuse to publish an empty baseline" in src
    assert "0 symbols" in src


def test_builds_via_the_module_and_publishes_the_committed_artifact() -> None:
    src = _source()
    assert "scripts.build_ats_20d_baseline" in src
    assert "reports/ats_baseline_20d.json" in src
    # Same GH_PAT rationale as run-open-prep-daily: GITHUB_TOKEN events leave
    # required checks "expected" forever.
    assert "secrets.GH_PAT" in src
    assert "--auto --squash" in src


def test_uses_the_20_symbol_benchmark_universe() -> None:
    match = re.search(r'SYMBOLS="([A-Z,]+)"', _source())
    assert match, "inline SYMBOLS pin missing"
    symbols = match.group(1).split(",")
    assert len(symbols) == 20
    assert symbols == sorted(set(symbols), key=symbols.index), "duplicates"
