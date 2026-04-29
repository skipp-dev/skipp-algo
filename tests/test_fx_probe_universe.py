"""Tests for scripts/fx_probe_universe.py — Q3/Q4 §3.3 scaffold."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts import fx_probe_universe as fx

# ── universe contract (pinned by repo memory) ─────────────────────────────


def test_fx_majors_contains_exactly_four_pairs():
    assert len(fx.FX_MAJORS) == 4


def test_fx_majors_spot_symbols_match_plan():
    assert {p.spot_symbol for p in fx.FX_MAJORS} == {
        "EURUSD", "GBPUSD", "USDJPY", "AUDUSD"}


def test_fx_majors_cme_mapping_is_canonical():
    """Pinned by /memories/repo/fx-probe-databento-glbx-mdp3.md."""
    mapping = {p.spot_symbol: p.cme_symbol for p in fx.FX_MAJORS}
    assert mapping == {
        "EURUSD": "6E.c.0",
        "GBPUSD": "6B.c.0",
        "AUDUSD": "6A.c.0",
        "USDJPY": "6J.c.0",
    }


def test_only_usdjpy_is_inverse():
    inverses = {p.spot_symbol for p in fx.FX_MAJORS if p.invert}
    assert inverses == {"USDJPY"}


def test_databento_symbols_returns_canonical_order():
    assert fx.databento_symbols() == ["6E.c.0", "6B.c.0", "6A.c.0", "6J.c.0"]


def test_fx_timeframes_match_plan():
    assert fx.FX_TIMEFRAMES == ("15m", "1H")


def test_fx_sessions_cover_three_global_blocks():
    assert set(fx.FX_SESSIONS) == {"TOKYO", "LONDON", "NY"}


# ── inverse-pair conversion ───────────────────────────────────────────────


def test_to_spot_price_direct_pair_is_identity():
    eur = fx.get_pair_by_spot("EURUSD")
    assert eur.to_spot_price(1.0825) == 1.0825


def test_to_spot_price_inverse_pair_inverts():
    jpy = fx.get_pair_by_spot("USDJPY")
    # 6J quotes JPY/USD ~ 0.0067 → spot USDJPY ~ 149.25
    spot = jpy.to_spot_price(0.0067)
    assert abs(spot - (1 / 0.0067)) < 1e-9


def test_to_spot_price_rejects_zero():
    with pytest.raises(ValueError):
        fx.get_pair_by_spot("USDJPY").to_spot_price(0.0)


def test_to_spot_price_rejects_negative():
    with pytest.raises(ValueError):
        fx.get_pair_by_spot("EURUSD").to_spot_price(-1.0)


def test_to_spot_price_rejects_non_numeric():
    with pytest.raises(ValueError):
        fx.get_pair_by_spot("EURUSD").to_spot_price("nope")  # type: ignore[arg-type]


# ── lookups ───────────────────────────────────────────────────────────────


def test_get_pair_by_spot_case_insensitive():
    assert fx.get_pair_by_spot("eurusd").cme_symbol == "6E.c.0"
    assert fx.get_pair_by_spot("  USDJPY  ").invert is True


def test_get_pair_by_spot_unknown_raises():
    with pytest.raises(KeyError):
        fx.get_pair_by_spot("XAUUSD")


def test_get_pair_by_cme_round_trip():
    p = fx.get_pair_by_cme("6E.c.0")
    assert p.spot_symbol == "EURUSD"


def test_get_pair_by_cme_unknown_raises():
    with pytest.raises(KeyError):
        fx.get_pair_by_cme("NQ.c.0")


# ── _safe_fetch fail-soft ────────────────────────────────────────────────


def test_safe_fetch_swallows_exceptions():
    def bad(_a, _b):
        raise RuntimeError("boom")
    bars, err = fx._safe_fetch(bad, "6E.c.0", "15m")
    assert bars == []
    assert "boom" in err


def test_safe_fetch_rejects_non_list_return():
    def weird(_a, _b):
        return "oops"
    bars, err = fx._safe_fetch(weird, "6E.c.0", "15m")
    assert bars == []
    assert "expected list" in err


def test_safe_fetch_passes_through_valid_list():
    def good(_a, _b):
        return [{"close": 1.0}]
    bars, err = fx._safe_fetch(good, "6E.c.0", "15m")
    assert err is None
    assert bars == [{"close": 1.0}]


# ── run_probe ────────────────────────────────────────────────────────────


def _ok_callback(prices: dict[str, float]):
    """Helper: every (cme,tf) returns a single-bar list with the mapped price."""
    def cb(cme, tf):
        if cme in prices:
            return [{"close": prices[cme]}]
        return []
    return cb


def test_run_probe_status_ok_when_all_cells_succeed():
    cb = _ok_callback({
        "6E.c.0": 1.08, "6B.c.0": 1.27, "6A.c.0": 0.66, "6J.c.0": 0.0067,
    })
    rep = fx.run_probe(cb)
    assert rep.status == "OK"
    assert len(rep.pairs) == 8  # 4 pairs × 2 timeframes


def test_run_probe_inverts_usdjpy_correctly():
    cb = _ok_callback({"6J.c.0": 0.0067, "6E.c.0": 1.08, "6B.c.0": 1.27, "6A.c.0": 0.66})
    rep = fx.run_probe(cb, timeframes=["15m"])
    jpy = next(r for r in rep.pairs if r.spot_symbol == "USDJPY")
    eur = next(r for r in rep.pairs if r.spot_symbol == "EURUSD")
    assert abs(jpy.last_spot_price - (1 / 0.0067)) < 1e-3
    assert eur.last_spot_price == 1.08  # not inverted


def test_run_probe_status_partial_on_mixed_failure():
    cb = _ok_callback({"6E.c.0": 1.08})  # only EURUSD has data
    rep = fx.run_probe(cb, timeframes=["15m"])
    assert rep.status == "PARTIAL"


def test_run_probe_status_fail_when_no_cells_succeed():
    rep = fx.run_probe(lambda _a, _b: [], timeframes=["15m"])
    assert rep.status == "FAIL"


def test_run_probe_records_per_cell_errors_without_aborting():
    def cb(cme, _tf):
        if cme == "6J.c.0":
            raise ValueError("no entitlement for 6J")
        return [{"close": 1.0}]
    rep = fx.run_probe(cb, timeframes=["15m"])
    jpy = next(r for r in rep.pairs if r.spot_symbol == "USDJPY")
    eur = next(r for r in rep.pairs if r.spot_symbol == "EURUSD")
    assert "no entitlement" in jpy.error
    assert eur.error is None
    assert rep.status == "PARTIAL"


def test_run_probe_handles_bad_close_field():
    def cb(_cme, _tf):
        return [{"close": "not a number"}]
    rep = fx.run_probe(cb, timeframes=["15m"])
    assert all("bad close" in r.error for r in rep.pairs)
    assert rep.status == "FAIL"


def test_run_probe_awaiting_data_when_universe_empty():
    rep = fx.run_probe(lambda _a, _b: [], pairs=[], timeframes=[])
    assert rep.status == "AWAITING_DATA"
    assert rep.pairs == []


# ── render_markdown ──────────────────────────────────────────────────────


def test_render_markdown_lists_universe_and_inverse_flag():
    rep = fx.ProbeReport(generated_at="t")
    md = fx.render_markdown(rep)
    assert "EURUSD" in md and "USDJPY" in md
    assert "| YES |" in md  # USDJPY inverse marker
    assert "AWAITING_DATA" in md


def test_render_markdown_renders_probe_results():
    cb = _ok_callback({"6E.c.0": 1.08, "6B.c.0": 1.27, "6A.c.0": 0.66, "6J.c.0": 0.0067})
    rep = fx.run_probe(cb, timeframes=["15m"])
    md = fx.render_markdown(rep)
    assert "1.08" in md
    # USDJPY's spot conversion should appear (~149)
    assert "149" in md


# ── CLI / main ───────────────────────────────────────────────────────────


def test_main_writes_outputs_with_default_callback(tmp_path):
    out_json = tmp_path / "p.json"
    out_md = tmp_path / "p.md"
    rc = fx.main([
        "--output-json", str(out_json),
        "--output-md", str(out_md),
    ])
    assert rc == 0
    payload = json.loads(out_json.read_text())
    # Default callback returns empty; main() downgrades FAIL → AWAITING_DATA.
    assert payload["status"] == "AWAITING_DATA"
    # Every cell still records error="empty" so the surface is honest.
    assert all(p["error"] == "empty" for p in payload["pairs"])


def test_main_accepts_injected_callback(tmp_path):
    out_json = tmp_path / "p.json"
    out_md = tmp_path / "p.md"
    cb = _ok_callback({"6E.c.0": 1.08, "6B.c.0": 1.27, "6A.c.0": 0.66, "6J.c.0": 0.0067})
    rc = fx.main(
        ["--output-json", str(out_json), "--output-md", str(out_md)],
        callback=cb,
    )
    assert rc == 0
    payload = json.loads(out_json.read_text())
    assert payload["status"] == "OK"


def test_main_writes_atomically(tmp_path):
    out_json = tmp_path / "p.json"
    out_md = tmp_path / "p.md"
    fx.main(["--output-json", str(out_json), "--output-md", str(out_md)])
    assert not out_json.with_suffix(".json.tmp").exists()
    assert not out_md.with_suffix(".md.tmp").exists()
