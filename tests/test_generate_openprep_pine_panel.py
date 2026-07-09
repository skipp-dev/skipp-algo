"""Coverage for scripts/generate_openprep_pine_panel.py (plan Workstream B1).

Exercises the pure data reduction + Pine rendering against a synthetic
outcomes payload, plus the empty/stub path and the atomic write round-trip.
Does not compile the Pine on TradingView (no local Pine runtime); it asserts
the structural contract the panel must satisfy.
"""
from __future__ import annotations

import json

import pytest

gen = pytest.importorskip("scripts.generate_openprep_pine_panel")


_SAMPLE_ROWS = [
    {
        "date": "2026-07-04", "symbol": "mcd", "score": 6.17,
        "confidence_tier": "STANDARD", "regime": "ROTATION",
        "market_weather": "green", "market_efficiency_ratio": 0.25,
        "intraday_efficiency_ratio": 0.23, "cs_dispersion": 3.55,
        "avg_pair_correlation": 0.11, "direction": "long",
        "playbook_name": "GAP_FADE", "gap_pct": 0.0, "rvol": 1.38,
    },
    {
        "date": "2026-07-04", "symbol": "AAPL", "score": 5.73,
        "confidence_tier": "STANDARD", "regime": "ROTATION",
        "market_weather": "GREEN", "intraday_efficiency_ratio": 0.23,
        "direction": "short", "playbook_name": "GAP_AND_GO",
        "gap_pct": 1.2, "rvol": None,
    },
]


def test_extract_panel_reduces_and_sorts() -> None:
    panel = gen.extract_panel(_SAMPLE_ROWS)
    assert panel["date"] == "2026-07-04"
    assert panel["regime"] == "ROTATION"
    assert panel["weather"] == "GREEN"          # upper-cased
    assert panel["er_intraday"] == 0.23
    syms = [c["symbol"] for c in panel["candidates"]]
    assert syms == ["MCD", "AAPL"]              # upper-cased, score-sorted desc
    assert panel["candidates"][0]["score"] == 6.17
    assert panel["candidates"][1]["rvol"] is None


def test_extract_panel_tie_break_is_deterministic() -> None:
    """Equal scores must resolve by symbol ascending, regardless of the
    incoming row order, so the daily-published panel is reproducible."""
    tied = [
        {"date": "2026-07-04", "symbol": sym, "score": 5.0, "market_weather": "GREEN"}
        for sym in ("CCC", "AAA", "BBB")
    ]
    order_a = [c["symbol"] for c in gen.extract_panel(tied)["candidates"]]
    order_b = [c["symbol"] for c in gen.extract_panel(list(reversed(tied)))["candidates"]]
    assert order_a == ["AAA", "BBB", "CCC"]
    assert order_a == order_b  # input order must not change the output


def test_extract_panel_tie_break_respects_score_first() -> None:
    """Symbol only breaks ties — a higher score still wins over a lower one
    even when its symbol sorts later alphabetically."""
    rows = [
        {"date": "d", "symbol": "AAA", "score": 1.0, "market_weather": "GREEN"},
        {"date": "d", "symbol": "ZZZ", "score": 9.0, "market_weather": "GREEN"},
    ]
    syms = [c["symbol"] for c in gen.extract_panel(rows)["candidates"]]
    assert syms == ["ZZZ", "AAA"]


def test_extract_panel_truncates_long_strings() -> None:
    long_symbol = "A" * 1000
    long_playbook = "B" * 1000
    panel = gen.extract_panel(
        [
            {
                "date": "2026-07-04",
                "symbol": long_symbol,
                "score": 1.0,
                "confidence_tier": "STANDARD",
                "regime": "ROTATION",
                "market_weather": "GREEN",
                "playbook_name": long_playbook,
            }
        ]
    )
    row = panel["candidates"][0]
    assert len(row["symbol"]) == gen.MAX_SYMBOL_LEN
    assert len(row["playbook"]) == gen.MAX_NAME_LEN


def test_extract_panel_empty() -> None:
    panel = gen.extract_panel([])
    assert panel["candidates"] == []
    assert panel["date"] is None


def test_pine_float_never_emits_invalid_literals() -> None:
    """nan/inf/scientific notation are not Pine literals — must become na /
    fixed-point (a 'nan' in the panel is a TradingView compile error)."""
    assert gen._pine_float(float("nan")) == "na"
    assert gen._pine_float(float("inf")) == "na"
    assert gen._pine_float(1e16) == "10000000000000000.0000"
    assert "e" not in gen._pine_float(1e-7)
    # _safe_float filters non-finite ingress (json.loads accepts NaN tokens).
    assert gen._safe_float(float("nan")) is None
    assert gen._safe_float("inf") is None
    assert gen._safe_float("3.5") == 3.5


def test_pine_string_literal_escaping() -> None:
    # Double-quotes escaped; emoji kept literal (not \\uXXXX).
    assert gen._q('a"b') == '"a\\"b"'
    assert gen._q("\U0001F7E2") == '"\U0001F7E2"'


def test_build_pine_structure_and_freshness() -> None:
    panel = gen.extract_panel(_SAMPLE_ROWS)
    pine = gen.build_pine(panel, generated_at="2026-07-04T00:00:00+00:00",
                          source="x.json", commit_sha=None)
    assert pine.startswith("//@version=6")
    assert 'indicator("Open-Prep Daily Panel"' in pine
    assert "table.new(position.top_right" in pine
    # Baked constants + candidate data present.
    assert 'PANEL_WEATHER = "GREEN"' in pine
    assert "PANEL_YEAR    = 2026" in pine
    assert '"MCD"' in pine and '"AAPL"' in pine
    # Freshness guard + chart-symbol highlight wired.
    assert "is_stale = age_days > 3.0" in pine
    assert "syminfo.ticker == array.get(P_SYM, i)" in pine
    # Emoji weather badge is a literal char, not a surrogate escape.
    assert "\\ud83d" not in pine
    assert "\U0001F7E2" in pine


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2025-07-03", (2025, 7, 3)),
        ("2025-07-03T12:00:00Z", (2025, 7, 3)),
        ("2025-99-99", (0, 0, 0)),
        ("garbage", (0, 0, 0)),
    ],
)
def test_parse_date_ymd(raw: str, expected: tuple[int, int, int]) -> None:
    assert gen._parse_date_ymd(raw) == expected


def test_build_pine_empty_is_valid_stub() -> None:
    pine = gen.build_pine(gen.extract_panel([]), generated_at="t",
                          source="none", commit_sha=None)
    assert pine.startswith("//@version=6")
    assert "array.new<string>()" in pine       # empty candidate arrays
    assert "keine Kandidaten heute" in pine     # stub row rendered


def test_write_outputs_roundtrip(tmp_path) -> None:
    panel = gen.extract_panel(_SAMPLE_ROWS)
    out = tmp_path / "sub" / "panel.pine"
    pine = gen.build_pine(panel, generated_at="t", source="x", commit_sha=None)
    sidecar = gen.write_outputs(pine, panel, out)
    assert out.read_text(encoding="utf-8").startswith("//@version=6")
    loaded = json.loads(sidecar.read_text(encoding="utf-8"))
    assert loaded["weather"] == "GREEN"
    assert [c["symbol"] for c in loaded["candidates"]] == ["MCD", "AAPL"]


def test_main_generates_from_explicit_file(tmp_path) -> None:
    src = tmp_path / "outcomes_2026-07-04.json"
    src.write_text(json.dumps(_SAMPLE_ROWS), encoding="utf-8")
    out = tmp_path / "panel.pine"
    rc = gen.main(["--outcomes-json", str(src), "--output", str(out)])
    assert rc == 0
    assert out.is_file()
    assert 'PANEL_WEATHER = "GREEN"' in out.read_text(encoding="utf-8")


def test_main_stub_when_no_input(tmp_path) -> None:
    out = tmp_path / "panel.pine"
    rc = gen.main(["--outcomes-dir", str(tmp_path / "missing"), "--output", str(out)])
    assert rc == 0
    assert out.read_text(encoding="utf-8").startswith("//@version=6")


# ── C13 setups join (official daily levels) ─────────────────────────────────

_SETUPS = [
    {"symbol": "NVDA", "entry": 196.93, "stop_loss": 186.5818, "take_profit": 217.6264,
     "quantity": 1, "trade_date": "2026-07-04", "variant": "smc_orb_vwap_hold"},
    {"symbol": "OTHERDAY", "entry": 1.0, "stop_loss": 0.9, "take_profit": 1.2,
     "quantity": 1, "trade_date": "2026-07-03", "variant": "smc_orb_vwap_hold"},
]


def test_load_setup_levels_joins_and_date_guards(tmp_path) -> None:
    path = tmp_path / "setups_2026-07-04.jsonl"
    path.write_text(json.dumps(_SETUPS), encoding="utf-8")
    levels = gen.load_setup_levels(path, "2026-07-04")
    assert levels["NVDA"] == {"entry": 196.93, "stop": 186.5818, "target": 217.6264}
    # The 2026-07-03 row is dropped by the date guard — stale levels never join.
    assert "OTHERDAY" not in levels


def test_load_setup_levels_tolerates_jsonl_and_garbage(tmp_path) -> None:
    path = tmp_path / "setups_x.jsonl"
    path.write_text(
        '{"symbol": "aapl", "entry": 100.0, "stop_loss": 95.0, "take_profit": 110.0}\n'
        'not-json\n'
        '{"entry": 1.0}\n'  # no symbol -> skipped
        '{"symbol": "BAD", "entry": "n/a", "stop_loss": null, "take_profit": 1e999}\n',
        encoding="utf-8",
    )
    levels = gen.load_setup_levels(path, None)
    assert levels["AAPL"]["entry"] == 100.0  # symbol upper-cased
    # Unusable numbers degrade to None (never raise, never emit bad Pine).
    assert levels["BAD"] == {"entry": None, "stop": None, "target": None}


def test_discover_setups_for_date(tmp_path) -> None:
    (tmp_path / "setups_2026-07-04.jsonl").write_text("[]", encoding="utf-8")
    assert gen.discover_setups_for_date(tmp_path, "2026-07-04") is not None
    assert gen.discover_setups_for_date(tmp_path, "2026-07-05") is None
    assert gen.discover_setups_for_date(tmp_path, None) is None


def test_extract_panel_levels_join_and_absence() -> None:
    levels = {"MCD": {"entry": 10.0, "stop": 9.5, "target": 11.0}}
    panel = gen.extract_panel(_SAMPLE_ROWS, levels=levels)
    by_sym = {c["symbol"]: c for c in panel["candidates"]}
    assert by_sym["MCD"]["entry"] == 10.0 and by_sym["MCD"]["target"] == 11.0
    # Candidates without a setup keep None (rendered as "–" in Pine).
    others = [c for s, c in by_sym.items() if s != "MCD"]
    assert all(c["entry"] is None and c["stop"] is None for c in others)


def test_build_pine_emits_level_arrays_and_column() -> None:
    levels = {"MCD": {"entry": 10.0, "stop": 9.5, "target": 11.0}}
    panel = gen.extract_panel(_SAMPLE_ROWS, levels=levels)
    pine = gen.build_pine(panel, generated_at="t", source="x", commit_sha=None,
                          source_setups="cache/live/setups_2026-07-04.jsonl")
    assert "P_ENTRY" in pine and "P_STOP" in pine and "P_TGT" in pine
    assert '"L1 e/s/t"' in pine
    assert "// source_setups: cache/live/setups_2026-07-04.jsonl" in pine
    assert "table.new(position.top_right, 8, rows" in pine
    # Missing levels are na literals, present ones fixed-point.
    assert "10.0000" in pine and "na" in pine


def test_main_with_setups_json(tmp_path) -> None:
    src = tmp_path / "outcomes_2026-07-04.json"
    src.write_text(json.dumps(_SAMPLE_ROWS), encoding="utf-8")
    setups = tmp_path / "setups_2026-07-04.jsonl"
    setups.write_text(json.dumps(
        [{"symbol": "MCD", "entry": 10.0, "stop_loss": 9.5, "take_profit": 11.0,
          "trade_date": "2026-07-04"}]), encoding="utf-8")
    out = tmp_path / "panel.pine"
    rc = gen.main(["--outcomes-json", str(src), "--setups-json", str(setups),
                   "--output", str(out)])
    assert rc == 0
    text = out.read_text(encoding="utf-8")
    assert "P_ENTRY" in text and "10.0000" in text
    sidecar = json.loads((tmp_path / "panel.json").read_text(encoding="utf-8"))
    mcd = next(c for c in sidecar["candidates"] if c["symbol"] == "MCD")
    assert mcd["entry"] == 10.0 and mcd["stop"] == 9.5 and mcd["target"] == 11.0


def test_main_errors_on_missing_explicit_setups(tmp_path) -> None:
    src = tmp_path / "outcomes_2026-07-04.json"
    src.write_text(json.dumps(_SAMPLE_ROWS), encoding="utf-8")
    rc = gen.main(["--outcomes-json", str(src),
                   "--setups-json", str(tmp_path / "missing.jsonl"),
                   "--output", str(tmp_path / "p.pine")])
    assert rc == 1
