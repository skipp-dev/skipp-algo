"""Tests for the ADR-0019 paired-A/B on-ramp.

Covers the on-ramp pieces that sit on top of the harness (#2528):

* the adapter RECORDS ``relative_volume`` on family events (record-only);
* :func:`extract_family_ab_samples` pairs the v1 score against a recorded
  candidate feature for a given ``feature_key``;
* ``scripts/run_feature_ab`` turns recorded events into a per-family verdict
  and maps that verdict onto a process exit code.

Everything is SHADOW-ONLY: no test wires a feature into a gate or score.
"""

from __future__ import annotations

import json

from governance.family_event_adapter import family_events_from_structure
from governance.family_event_score import ATR_PERIOD
from governance.family_returns import extract_family_ab_samples
from scripts import run_feature_ab

_T0 = 1_700_000_000.0
_STEP = 86_400.0


def _bars_with_volume(n: int, anchor_bar: int) -> list[dict[str, float]]:
    closes = [100.0 + i for i in range(n)]
    volumes = [100.0] * n
    volumes[anchor_bar] = 300.0
    return [
        {
            "timestamp": _T0 + i * _STEP,
            "high": closes[i] + 1.0,
            "low": closes[i] - 1.0,
            "close": closes[i],
            "volume": volumes[i],
        }
        for i in range(n)
    ]


def _bars_without_volume(n: int) -> list[dict[str, float]]:
    closes = [100.0 + i for i in range(n)]
    return [
        {
            "timestamp": _T0 + i * _STEP,
            "high": closes[i] + 1.0,
            "low": closes[i] - 1.0,
            "close": closes[i],
        }
        for i in range(n)
    ]


# --------------------------------------------------------------------------- #
# adapter records the candidate feature
# --------------------------------------------------------------------------- #
def test_adapter_records_relative_volume() -> None:
    n = ATR_PERIOD + 12
    anchor_bar = ATR_PERIOD + 2  # >= ATR_PERIOD warmup for relative_volume
    bars = _bars_with_volume(n, anchor_bar)
    anchor_ts = _T0 + anchor_bar * _STEP
    structure = {
        "bos": [
            {"id": "b1", "time": anchor_ts, "price": bars[anchor_bar]["close"], "dir": "UP"}
        ]
    }

    events = family_events_from_structure(structure, bars)

    assert len(events) == 1
    assert "relative_volume" in events[0]
    assert isinstance(events[0]["relative_volume"], float)


def test_adapter_omits_relative_volume_without_volume() -> None:
    # Bars without a volume column -> relative_volume honestly absent, but the
    # event is still built from price/structure alone.
    n = ATR_PERIOD + 12
    anchor_bar = ATR_PERIOD + 2
    bars = _bars_without_volume(n)
    anchor_ts = _T0 + anchor_bar * _STEP
    structure = {
        "bos": [
            {"id": "b1", "time": anchor_ts, "price": bars[anchor_bar]["close"], "dir": "UP"}
        ]
    }

    events = family_events_from_structure(structure, bars)

    assert events == [] or "relative_volume" not in events[0]


# --------------------------------------------------------------------------- #
# extract pairs against the candidate feature_key
# --------------------------------------------------------------------------- #
def test_extract_pairs_relative_volume_feature_key() -> None:
    n = ATR_PERIOD + 12
    anchor_bar = ATR_PERIOD + 2
    bars = _bars_with_volume(n, anchor_bar)
    anchor_ts = _T0 + anchor_bar * _STEP
    structure = {
        "bos": [
            {"id": "b1", "time": anchor_ts, "price": bars[anchor_bar]["close"], "dir": "UP"}
        ]
    }

    events = family_events_from_structure(structure, bars)
    samples = extract_family_ab_samples(events, feature_key="relative_volume")

    assert "BOS" in samples
    assert len(samples["BOS"]["features"]) == 1
    assert len(samples["BOS"]["scores"]) == 1


def test_extract_excludes_event_missing_feature() -> None:
    # An event carrying a score but no relative_volume is excluded for that key.
    event = {
        "family": "BOS",
        "direction": "UP",
        "entry_mode": "immediate",
        "entry_price": 100.0,
        "anchor_ts": _T0,
        "forward_highs": [101.0, 102.0],
        "forward_lows": [99.0, 100.0],
        "forward_closes": [100.5, 101.5],
        "forward_timestamps": [_T0 + _STEP, _T0 + 2 * _STEP],
        "score": 0.5,
    }
    samples = extract_family_ab_samples([event], feature_key="relative_volume")
    assert samples == {}


# --------------------------------------------------------------------------- #
# driver exit-code mapping
# --------------------------------------------------------------------------- #
def _report(*, results: dict, lifted: list[str]) -> dict:
    return {
        "feature_key": "relative_volume",
        "cost_bps": 5.0,
        "families_measured": sorted(results),
        "families_lifted": lifted,
        "results": results,
    }


def test_exit_code_no_measurable_family_is_3() -> None:
    assert run_feature_ab._verdict_exit_code(_report(results={}, lifted=[])) == 3


def test_exit_code_measured_but_no_lift_is_2() -> None:
    report = _report(results={"BOS": {"verdict": "no_lift"}}, lifted=[])
    assert run_feature_ab._verdict_exit_code(report) == 2


def test_exit_code_lift_is_0() -> None:
    report = _report(
        results={"BOS": {"verdict": "candidate_lifts_resolution"}}, lifted=["BOS"]
    )
    assert run_feature_ab._verdict_exit_code(report) == 0


# --------------------------------------------------------------------------- #
# driver build_report + main round trip
# --------------------------------------------------------------------------- #
def test_build_report_thin_sample_yields_empty_results() -> None:
    n = ATR_PERIOD + 12
    anchor_bar = ATR_PERIOD + 2
    bars = _bars_with_volume(n, anchor_bar)
    anchor_ts = _T0 + anchor_bar * _STEP
    structure = {
        "bos": [
            {"id": "b1", "time": anchor_ts, "price": bars[anchor_bar]["close"], "dir": "UP"}
        ]
    }
    events = family_events_from_structure(structure, bars)

    report = run_feature_ab.build_report(
        events, feature_key="relative_volume", cost_bps=5.0
    )

    assert report["feature_key"] == "relative_volume"
    assert report["results"] == {}  # one event is far below MIN_OOS
    assert report["families_lifted"] == []


def test_main_writes_report_and_returns_thin_exit(tmp_path) -> None:
    n = ATR_PERIOD + 12
    anchor_bar = ATR_PERIOD + 2
    bars = _bars_with_volume(n, anchor_bar)
    anchor_ts = _T0 + anchor_bar * _STEP
    structure = {
        "bos": [
            {"id": "b1", "time": anchor_ts, "price": bars[anchor_bar]["close"], "dir": "UP"}
        ]
    }
    events = family_events_from_structure(structure, bars)

    events_path = tmp_path / "events.json"
    events_path.write_text(json.dumps(events), encoding="utf-8")
    out_path = tmp_path / "report.json"

    code = run_feature_ab.main(
        [str(events_path), "--feature-key", "relative_volume", "--out", str(out_path)]
    )

    assert code == 3  # measurable families: none (thin)
    written = json.loads(out_path.read_text(encoding="utf-8"))
    assert written["feature_key"] == "relative_volume"


def test_main_rejects_non_list_payload(tmp_path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"not": "a list"}), encoding="utf-8")
    assert run_feature_ab.main([str(bad)]) == 1


def test_main_rejects_empty_event_list(tmp_path) -> None:
    empty = tmp_path / "empty.json"
    empty.write_text("[]", encoding="utf-8")
    assert run_feature_ab.main([str(empty)]) == 1


def test_main_rejects_missing_file(tmp_path) -> None:
    assert run_feature_ab.main([str(tmp_path / "nope.json")]) == 1
