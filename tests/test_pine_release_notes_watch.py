"""scripts/pine_release_notes_watch.py — the release-notes announcement bridge.

The fixture is REAL markup: a trimmed copy of the live page (2026-08-16)
prefixed with the page's actual pre-content junk (a template ``h2``, a script
block) and terminated by a footer, so the tests measure the parser against
the markup it will actually meet — not against a hand-idealized sample.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.pine_release_notes_watch import (
    Entry,
    diff_entries,
    extract_entries,
    grep_tokens,
    is_grep_token,
    live_pine_files,
    main,
    normalize_token,
    parse_snapshot,
    render_snapshot,
)

_FIXTURE = (
    Path(__file__).parent / "fixtures" / "pine_release_notes" / "release_notes_sample.html"
)


@pytest.fixture(scope="module")
def entries() -> list[Entry]:
    return extract_entries(_FIXTURE.read_text(encoding="utf-8"))


# -- extraction -------------------------------------------------------------
def test_extracts_the_fixture_entries_exactly(entries: list[Entry]) -> None:
    assert [(e.month, e.feature) for e in entries] == [
        ("August 2026", "Binary search in UDT arrays"),
        ("July 2026", "Strategy improvements"),
        ("July 2026", "Automatic parentheses"),
        ("April 2026", "Multiline strings"),
        ("April 2026", "Updated editor settings"),
        ("April 2026", "Sorting UDT collections"),
        ("January 2026", "Footprint requests"),
        ("December 2025", "Updated line wrapping"),
    ]


def test_tokens_come_from_code_and_reference_links(entries: list[Entry]) -> None:
    binary_search = entries[0]
    # array.binary_search* are <a href="…pine-script-reference…"> links,
    # sort_field is a <code> element — both sources must land.
    assert binary_search.tokens == (
        "array.binary_search",
        "array.binary_search_leftmost",
        "array.binary_search_rightmost",
        "sort_field",
    )


def test_pre_content_junk_and_footer_never_reach_entries(entries: list[Entry]) -> None:
    everything = "\n".join(e.body for e in entries)
    assert "navigation text" not in everything
    assert "fake heading" not in everything
    assert "footer text" not in everything


def test_month_direct_body_without_h4_becomes_a_dash_entry() -> None:
    html = (
        '<h2 id="y">2025</h2>'
        "<h3>November 2025</h3>"
        "<p>New variable <code>syminfo.isin</code> returns the ISIN.</p>"
        "<footer></footer>"
    )
    [entry] = extract_entries(html)
    assert entry.key == ("November 2025", "—")
    assert entry.tokens == ("syminfo.isin",)


def test_duplicate_keys_get_deterministic_suffixes() -> None:
    html = (
        '<h2 id="y">2014</h2>'
        "<h3>February 2014</h3>"
        "<p>first block</p>"
        "<h4>Some feature</h4>"
        "<p>feature body</p>"
        "<h3>February 2014</h3>"
        "<p>second block</p>"
        "<footer></footer>"
    )
    keys = [e.key for e in extract_entries(html)]
    assert keys == [
        ("February 2014", "—"),
        ("February 2014", "Some feature"),
        ("February 2014", "— (2)"),
    ]


# -- token rules ------------------------------------------------------------
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("array.sort()", "array.sort"),
        ('"PercentageLTP"', "PercentageLTP"),
        ("sort_field", "sort_field"),
        ("Alt + Z", None),  # prose, not an identifier
        ("ab", None),  # too short to grep meaningfully
    ],
)
def test_normalize_token(raw: str, expected: str | None) -> None:
    assert normalize_token(raw) == expected


def test_only_namespaced_tokens_are_grep_eligible() -> None:
    # Bare words like `true`/`high` match nearly every Pine file and would
    # fire the affected-gate on every delta.
    assert is_grep_token("array.sort")
    assert is_grep_token("sort_field")
    assert not is_grep_token("true")
    assert not is_grep_token("high")


# -- snapshot round-trip and diff -------------------------------------------
def test_snapshot_round_trip_is_lossless(entries: list[Entry]) -> None:
    parsed = parse_snapshot(render_snapshot(entries))
    assert parsed == {e.key: e.normalized_body for e in entries}


def test_identical_snapshot_yields_empty_delta(entries: list[Entry]) -> None:
    snapshot = parse_snapshot(render_snapshot(entries))
    assert diff_entries(snapshot, entries).empty


def test_missing_entry_is_reported_new(entries: list[Entry]) -> None:
    snapshot = parse_snapshot(render_snapshot(entries))
    del snapshot[("January 2026", "Footprint requests")]
    delta = diff_entries(snapshot, entries)
    assert [e.key for e in delta.new] == [("January 2026", "Footprint requests")]
    assert not delta.changed


def test_edited_body_is_reported_changed(entries: list[Entry]) -> None:
    snapshot = parse_snapshot(render_snapshot(entries))
    snapshot[("April 2026", "Multiline strings")] += " EDITED"
    delta = diff_entries(snapshot, entries)
    assert [e.key for e in delta.changed] == [("April 2026", "Multiline strings")]
    assert not delta.new


# -- live surface -----------------------------------------------------------
def test_live_pine_files_excludes_tests_and_legacy(tmp_path: Path) -> None:
    for rel in (
        "SMC_Root.pine",
        "SMC++/smc_utils.pine",
        "pine/skipp_math.pine",
        "pine/generated/gen.pine",
        "pine/legacy/old.pine",
        "tests/fixtures/pine/fixture.pine",
    ):
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("//@version=6\n", encoding="utf-8")
    assert [p.relative_to(tmp_path).as_posix() for p in live_pine_files(tmp_path)] == [
        "SMC++/smc_utils.pine",
        "SMC_Root.pine",
        "pine/generated/gen.pine",
        "pine/skipp_math.pine",
    ]


def test_grep_tokens_matches_word_boundaries_only(tmp_path: Path) -> None:
    pine = tmp_path / "a.pine"
    pine.write_text(
        "x = array.sort(values)\n"
        "y = myarray.sort(values)\n"  # prefixed — must NOT match
        "z = array.sorted\n",  # suffixed — must NOT match
        encoding="utf-8",
    )
    hits = grep_tokens({"array.sort"}, [pine], tmp_path)
    assert hits == {"array.sort": ["a.pine:1"]}


# -- CLI flow ---------------------------------------------------------------
def _run(tmp_path: Path, *extra: str) -> int:
    return main(
        [
            "--html",
            str(_FIXTURE),
            "--snapshot",
            str(tmp_path / "snapshot.md"),
            "--repo-root",
            str(tmp_path),
            "--min-entries",
            "3",
            *extra,
        ]
    )


def test_seed_then_noop(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert _run(tmp_path, "--seed") == 0
    assert "changed=false" in capsys.readouterr().out
    assert _run(tmp_path) == 0
    assert "changed=false" in capsys.readouterr().out
    leftovers = [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []


def test_missing_snapshot_without_seed_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run(tmp_path) == 1
    assert "snapshot missing" in capsys.readouterr().err


def test_delta_writes_report_updates_snapshot_and_greps_live_pine(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run(tmp_path, "--seed") == 0
    capsys.readouterr()
    # Drop one entry from the snapshot and plant a live file its token hits.
    snapshot_path = tmp_path / "snapshot.md"
    text = snapshot_path.read_text(encoding="utf-8")
    start = text.index("### Sorting UDT collections")
    # Cut to the next heading of EITHER level: this entry is the last of its
    # month, so cutting to the next "### " alone would swallow the month line.
    end = start + min(text.index(m, start + 1) - start for m in ("### ", "\n## "))
    snapshot_path.write_text(text[:start] + text[end:], encoding="utf-8")
    live = tmp_path / "SMC_Live.pine"
    live.write_text("//@version=6\narray.sort(weights)\n", encoding="utf-8")

    report = tmp_path / "report.md"
    assert _run(tmp_path, "--update", "--report", str(report)) == 0
    out = capsys.readouterr().out
    assert "changed=true" in out
    assert "new_entries=1" in out
    assert "affected_files=1" in out
    body = report.read_text(encoding="utf-8")
    assert "NEW — April 2026 — Sorting UDT collections" in body
    assert "`SMC_Live.pine:2`" in body
    # --update healed the snapshot: the next run is a no-op again.
    assert _run(tmp_path) == 0
    assert "changed=false" in capsys.readouterr().out


def test_broken_extraction_is_refused_not_diffed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stub = tmp_path / "broken.html"
    stub.write_text(
        '<h2 id="y">2026</h2><h3>May 2026</h3><p>only entry</p><footer></footer>',
        encoding="utf-8",
    )
    rc = main(
        [
            "--html",
            str(stub),
            "--snapshot",
            str(tmp_path / "snapshot.md"),
            "--repo-root",
            str(tmp_path),
            "--seed",
        ]
    )
    assert rc == 1
    assert "extraction sanity failed" in capsys.readouterr().err
    assert not (tmp_path / "snapshot.md").exists()
