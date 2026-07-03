"""Freshness guard for the hand-authored Pine libraries (``pine/skipp_*.pine``).

Why this exists
---------------
The five hand-authored shared libraries under ``pine/skipp_*.pine`` ship to
TradingView and are imported by the active suite via
``import preuss_steffen/<lib>/1``. Unlike the code-generated libraries under
``pine/generated/`` (kept fresh by ``smc-library-refresh.yml``), the shared
libraries had **no** scheduled freshness/validation mechanism — they could
silently rot for months without anyone noticing (last touched 2026-03-27
before this guard landed).

``scripts/pine_library_freshness.py`` stamps a machine-readable
``// Last refreshed: YYYY-MM-DD`` marker into each shared library and can
report when a library exceeds a maximum age. The scheduled
``pine-library-freshness`` workflow runs the age check on a cadence so a
stale library turns the build red and forces a review/refresh PR.

This test pins two things:

* the pure marker/stamp/staleness helpers behave deterministically, and
* every shared library in the repo currently carries a **well-formed**
  freshness marker (presence + parseable ISO date). Recency itself is
  enforced at runtime by the scheduled workflow using the real ``today``;
  pinning a hard age here would make the suite drift-fail on a fixed date.
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

import pytest

from scripts import pine_library_freshness as plf

REPO_ROOT = Path(__file__).resolve().parents[1]

_EXPECTED_LIBRARIES = {
    "pine/skipp_calibration.pine",
    "pine/skipp_indicators.pine",
    "pine/skipp_labels.pine",
    "pine/skipp_math.pine",
    "pine/skipp_scoring.pine",
}


def test_shared_library_scope_matches_repo() -> None:
    """The guarded set must match exactly the five active shared libraries.

    Mirrors the scope guard in ``test_pine_version_directive.py`` so a moved
    or renamed library fails loudly instead of silently dropping coverage.
    """
    assert set(plf.SHARED_LIBRARIES) == _EXPECTED_LIBRARIES
    for rel in plf.SHARED_LIBRARIES:
        assert (REPO_ROOT / rel).is_file(), f"missing shared library: {rel}"


def test_find_marker_date_parses_iso() -> None:
    text = 'library("skipp_math", overlay = true)\n// Last refreshed: 2026-07-03\n'
    assert plf.find_marker_date(text) == _dt.date(2026, 7, 3)


def test_find_marker_date_absent_returns_none() -> None:
    assert plf.find_marker_date('library("skipp_math", overlay = true)\n') is None


def test_find_marker_date_ignores_malformed() -> None:
    # Missing zero-padding / wrong shape must not parse as a valid marker.
    text = "// Last refreshed: 2026-7-3\n"
    assert plf.find_marker_date(text) is None


def test_stamp_inserts_marker_after_library_declaration() -> None:
    src = (
        "// license\n"
        "// © preuss_steffen\n"
        "\n"
        "//@version=6\n"
        'library("skipp_math", overlay = true)\n'
        "\n"
        "export FOO() => 1\n"
    )
    today = _dt.date(2026, 7, 3)
    out = plf.stamp_marker(src, today)
    lines = out.splitlines()
    lib_idx = lines.index('library("skipp_math", overlay = true)')
    assert lines[lib_idx + 1] == "// Last refreshed: 2026-07-03"
    # The version directive must still be detectable and untouched.
    assert "//@version=6" in lines
    assert plf.find_marker_date(out) == today


def test_stamp_marker_is_idempotent_and_updates_date() -> None:
    src = (
        "//@version=6\n"
        'library("skipp_scoring", overlay = true)\n'
        "// Last refreshed: 2026-01-01\n"
        "export BAR() => 2\n"
    )
    out = plf.stamp_marker(src, _dt.date(2026, 7, 3))
    # Exactly one marker line, carrying the new date.
    marker_lines = [ln for ln in out.splitlines() if ln.startswith(plf.MARKER_PREFIX)]
    assert marker_lines == ["// Last refreshed: 2026-07-03"]
    # Stamping again with the same date is a no-op.
    assert plf.stamp_marker(out, _dt.date(2026, 7, 3)) == out


def test_library_status_reports_staleness() -> None:
    today = _dt.date(2026, 7, 3)
    fresh = plf.marker_is_stale(_dt.date(2026, 6, 1), today, max_age_days=120)
    stale = plf.marker_is_stale(_dt.date(2026, 1, 1), today, max_age_days=120)
    assert fresh is False
    assert stale is True


def test_missing_marker_counts_as_stale() -> None:
    assert plf.marker_is_stale(None, _dt.date(2026, 7, 3), max_age_days=120) is True


def test_update_writes_marker_atomically(tmp_path: Path) -> None:
    lib = tmp_path / "skipp_math.pine"
    lib.write_text(
        "//@version=6\n" 'library("skipp_math", overlay = true)\n' "export FOO() => 1\n",
        encoding="utf-8",
    )
    changed = plf.update_file(lib, _dt.date(2026, 7, 3))
    assert changed is True
    assert plf.find_marker_date(lib.read_text(encoding="utf-8")) == _dt.date(2026, 7, 3)
    # Second run with same date changes nothing.
    assert plf.update_file(lib, _dt.date(2026, 7, 3)) is False


@pytest.mark.parametrize("rel", sorted(_EXPECTED_LIBRARIES))
def test_repo_libraries_carry_wellformed_marker(rel: str) -> None:
    """Repo invariant: every shared library has a parseable freshness marker."""
    text = (REPO_ROOT / rel).read_text(encoding="utf-8")
    marker = plf.find_marker_date(text)
    assert marker is not None, (
        f"{rel} is missing a well-formed '// Last refreshed: YYYY-MM-DD' "
        f"marker. Run `python scripts/pine_library_freshness.py --update`."
    )


def test_check_returns_problems_for_stale(tmp_path: Path) -> None:
    lib = tmp_path / "skipp_math.pine"
    lib.write_text(
        "//@version=6\n"
        'library("skipp_math", overlay = true)\n'
        "// Last refreshed: 2026-01-01\n",
        encoding="utf-8",
    )
    problems = plf.check([lib], today=_dt.date(2026, 7, 3), max_age_days=120)
    assert len(problems) == 1
    assert "skipp_math" in problems[0]
