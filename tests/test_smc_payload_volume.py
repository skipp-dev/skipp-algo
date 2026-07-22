"""Payload-volume measurement of the generated Pine library (ADR-0029).

These tests pin the property that made the 2026-07 empty-library incident
invisible: every existing check reads metadata *about* the payload
(``ASOF_DATE``, ``UNIVERSE_SIZE``, path consistency) and none reads the
payload. They also pin the sharding trap — ``UNIVERSE_TICKERS`` renders at
``max_chars=3900``, so a healthy 6929-symbol payload is emitted as a
concatenation expression, not a literal. A parser shaped like the existing
``ASOF_DATE`` regex would score that as 0 and invert the alert.
"""
from __future__ import annotations

import json
from pathlib import Path

from scripts.generate_smc_micro_profiles import (
    LIST_EXPORTS,
    LISTS,
    render_csv_export,
    write_manifest,
)
from scripts.smc_payload_volume import (
    MEMBERSHIP_LIST_EXPORTS,
    measure_payload_volume,
    parse_pine_csv_export,
    payload_blocking_reasons,
)


def test_list_exports_match_the_generator() -> None:
    """smc_payload_volume duplicates the names to stay pandas-free — pin them."""
    assert set(MEMBERSHIP_LIST_EXPORTS) == set(LIST_EXPORTS.values())


def test_parses_a_single_literal_export() -> None:
    text = 'export const string UNIVERSE_TICKERS = "AAPL,MSFT,NVDA"'

    assert parse_pine_csv_export(text, "UNIVERSE_TICKERS") == ["AAPL", "MSFT", "NVDA"]


def test_parses_an_empty_literal_export_as_empty_not_unknown() -> None:
    text = 'export const string UNIVERSE_TICKERS = ""'

    assert parse_pine_csv_export(text, "UNIVERSE_TICKERS") == []


def test_returns_none_when_the_export_is_absent() -> None:
    """Absent must not collapse to 0 — that is the ``payload_known`` distinction."""
    text = 'export const string SOMETHING_ELSE = "AAPL"'

    assert parse_pine_csv_export(text, "UNIVERSE_TICKERS") is None


def test_parses_the_sharded_concatenation_form() -> None:
    """The form a healthy 6929-symbol universe actually renders as."""
    symbols = [f"SYM{index:04d}" for index in range(900)]
    text = render_csv_export("UNIVERSE_TICKERS", symbols, max_chars=3900)

    assert "_PART_1" in text, "fixture must actually shard, else it proves nothing"
    assert parse_pine_csv_export(text, "UNIVERSE_TICKERS") == symbols


def test_measures_the_contradiction_that_shipped() -> None:
    """UNIVERSE_SIZE=6929 beside an empty ticker list — the state on origin/main."""
    text = "\n".join([
        "export const int UNIVERSE_SIZE = 6929",
        'export const string UNIVERSE_TICKERS = ""',
        'export const string CLEAN_RECLAIM_TICKERS = ""',
    ])

    volume = measure_payload_volume(text)

    assert volume.known is True
    assert volume.universe_size == 6929
    assert volume.universe_tickers_count == 0
    assert volume.list_total == 0


def test_unparseable_text_is_unknown_rather_than_empty() -> None:
    volume = measure_payload_volume("// nothing useful here")

    assert volume.known is False
    assert payload_blocking_reasons(volume) == []


def test_blocks_the_universe_contradiction() -> None:
    text = "\n".join([
        "export const int UNIVERSE_SIZE = 6929",
        'export const string UNIVERSE_TICKERS = ""',
        'export const string CLEAN_RECLAIM_TICKERS = "AAPL"',
    ])

    assert payload_blocking_reasons(measure_payload_volume(text)) == ["empty_universe_tickers"]


def test_blocks_the_membership_contradiction() -> None:
    text = "\n".join([
        "export const int UNIVERSE_SIZE = 3",
        'export const string UNIVERSE_TICKERS = "AAPL,MSFT,NVDA"',
        'export const string CLEAN_RECLAIM_TICKERS = ""',
        'export const string STOP_HUNT_PRONE_TICKERS = ""',
    ])

    assert payload_blocking_reasons(measure_payload_volume(text)) == ["empty_membership_lists"]


def test_a_consistently_empty_universe_reports_only_the_universe_reason() -> None:
    """Both zero -> the first blocker already fires; no coverage is lost."""
    text = "\n".join([
        "export const int UNIVERSE_SIZE = 0",
        'export const string UNIVERSE_TICKERS = ""',
        'export const string CLEAN_RECLAIM_TICKERS = ""',
    ])

    assert payload_blocking_reasons(measure_payload_volume(text)) == []


def test_a_healthy_payload_blocks_nothing() -> None:
    text = "\n".join([
        "export const int UNIVERSE_SIZE = 3",
        'export const string UNIVERSE_TICKERS = "AAPL,MSFT,NVDA"',
        'export const string CLEAN_RECLAIM_TICKERS = "AAPL"',
    ])

    assert payload_blocking_reasons(measure_payload_volume(text)) == []


# ── Productivity gate wiring ────────────────────────────────────

INCIDENT_PINE = "\n".join([
    "export const int UNIVERSE_SIZE = 6929",
    'export const string UNIVERSE_TICKERS = ""',
    *[f'export const string {export} = ""' for export in LIST_EXPORTS.values()],
])

HEALTHY_PINE = "\n".join([
    "export const int UNIVERSE_SIZE = 3",
    'export const string UNIVERSE_TICKERS = "AAPL,MSFT,NVDA"',
    'export const string CLEAN_RECLAIM_TICKERS = "AAPL"',
    *[
        f'export const string {export} = ""'
        for export in LIST_EXPORTS.values()
        if export != "CLEAN_RECLAIM_TICKERS"
    ],
])


def _write_manifest_for(tmp_path: Path, pine_text: str | None, **kwargs: object) -> dict:
    pine_path = tmp_path / "lib.pine"
    if pine_text is not None:
        pine_path.write_text(pine_text, encoding="utf-8")
    manifest_path = tmp_path / "manifest.json"
    write_manifest(
        manifest_path,
        asof_date="2026-07-21",
        input_path=tmp_path / "in.csv",
        schema_path=tmp_path / "schema.json",
        features_path=tmp_path / "features.csv",
        lists_path=tmp_path / "lists.csv",
        state_path=tmp_path / "state.csv",
        diff_report_path=tmp_path / "diff.md",
        pine_path=pine_path,
        core_import_snippet_path=tmp_path / "snippet.pine",
        universe_size=6929,
        lists={name: [] for name in LISTS},
        library_owner="test",
        library_version=1,
        recommended_import_path="test/path",
        **kwargs,  # type: ignore[arg-type]
    )
    return json.loads(manifest_path.read_text())


def test_gate_blocks_the_artifact_that_actually_shipped(tmp_path: Path) -> None:
    """The exact signature on origin/main: 6929 scanned, nothing in the payload."""
    gate = _write_manifest_for(tmp_path, INCIDENT_PINE)["productivity_gate"]

    assert gate["publish_ready"] is False
    assert "empty_universe_tickers" in gate["blocking_reasons"]


def test_gate_records_the_measured_counts(tmp_path: Path) -> None:
    gate = _write_manifest_for(tmp_path, HEALTHY_PINE)["productivity_gate"]

    assert gate["payload_known"] is True
    assert gate["universe_tickers_count"] == 3
    assert gate["list_total"] == 1


# Real event-risk enrichment isolates the payload dimension: without it the
# pre-existing default_event_risk blocker fires on a stub enrichment.
_EVENT_RISK_ENRICHMENT = {"event_risk": {"EVENT_WINDOW_STATE": "CLEAR"}}


def test_a_healthy_payload_stays_publishable(tmp_path: Path) -> None:
    gate = _write_manifest_for(
        tmp_path, HEALTHY_PINE, enrichment=_EVENT_RISK_ENRICHMENT
    )["productivity_gate"]

    assert gate["publish_ready"] is True
    assert gate["blocking_reasons"] == []


def test_an_unreadable_library_is_unknown_not_blocked(tmp_path: Path) -> None:
    """Unknown must not read as empty — and must not read as green either."""
    gate = _write_manifest_for(
        tmp_path, None, enrichment=_EVENT_RISK_ENRICHMENT
    )["productivity_gate"]

    assert gate["payload_known"] is False
    assert gate["universe_tickers_count"] is None
    assert gate["blocking_reasons"] == []
