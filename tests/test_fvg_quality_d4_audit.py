"""Smoke test for ``scripts/fvg_quality_d4_audit.py``.

Builds a tiny synthetic ``events_*.jsonl`` fixture matching the v3
benchmark schema, then verifies the audit helpers produce the expected
buckets and rollups. Locks in the schema contract so an evolving FVG
event payload (see ``smc_integration/measurement_evidence.py``) cannot
silently break the D4 audit pipeline.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "fvg_quality_d4_audit.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("fvg_quality_d4_audit", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _make_event(
    *,
    symbol: str = "AAPL",
    timeframe: str = "1H",
    family: str = "FVG",
    outcome: bool = True,
    label_partial_50: bool = True,
    htf_aligned: bool = True,
    is_full_body: bool = True,
    gap_size_atr: float | None = 0.5,
    distance_to_price_atr: float | None = 0.1,
    hurst_50: float | None = 0.5,
) -> dict:
    return {
        "event_id": f"{symbol}-{timeframe}-{outcome}",
        "family": family,
        "symbol": symbol,
        "timeframe": timeframe,
        "outcome": outcome,
        "context": {},
        "features": {
            "label_partial_50": label_partial_50,
            "htf_aligned": htf_aligned,
            "is_full_body": is_full_body,
            "gap_size_atr": gap_size_atr,
            "distance_to_price_atr": distance_to_price_atr,
            "hurst_50": hurst_50,
        },
    }


@pytest.fixture
def fixture_root(tmp_path: Path) -> Path:
    """Build a minimal SYMBOL/TF/events_*.jsonl tree with FVG + non-FVG rows.

    The audit script's quartile sections (gap_size_atr, distance_to_price_atr,
    hurst_50) and the per-symbol robustness check require ``n >= 4``
    non-null entries to compute. We seed 8 FVG rows plus one OB filter
    decoy across two symbols / two TFs.
    """
    rows: list[dict] = []
    for i, sym in enumerate(("AAPL", "MSFT")):
        for j, tf in enumerate(("1H", "5m")):
            sym_tf = tmp_path / sym / tf
            sym_tf.mkdir(parents=True)
            # Two FVG events per (sym, tf) with varying feature values so
            # quantile bucketing produces non-empty Q1/Q4.
            base = i * 4 + j * 2
            local = [
                _make_event(
                    symbol=sym,
                    timeframe=tf,
                    outcome=True,
                    label_partial_50=True,
                    htf_aligned=True,
                    is_full_body=True,
                    gap_size_atr=0.1 + base * 0.5,
                    distance_to_price_atr=0.1 + base * 0.5,
                    hurst_50=0.45 + base * 0.02,
                ),
                _make_event(
                    symbol=sym,
                    timeframe=tf,
                    outcome=False,
                    label_partial_50=False,
                    htf_aligned=False,
                    is_full_body=False,
                    gap_size_atr=0.2 + base * 0.5,
                    distance_to_price_atr=0.2 + base * 0.5,
                    hurst_50=0.55 + base * 0.02,
                ),
            ]
            rows.extend(local)
            with (sym_tf / f"events_{sym}_{tf}.jsonl").open("w", encoding="utf-8") as fh:
                for r in local:
                    fh.write(json.dumps(r) + "\n")
                # Non-FVG decoy must be filtered out.
                fh.write(json.dumps(_make_event(family="OB", symbol=sym, timeframe=tf)) + "\n")
    return tmp_path


def test_load_fvg_events_filters_family_and_walks_glob(fixture_root: Path) -> None:
    mod = _load_module()
    events = mod._load_fvg_events(fixture_root)
    assert len(events) == 8
    assert all(e["family"] == "FVG" for e in events)


def test_hit_strict_uses_features_label_partial_50(fixture_root: Path) -> None:
    mod = _load_module()
    events = mod._load_fvg_events(fixture_root)
    strict = [e for e in events if mod._hit(e, "strict")]
    lenient = [e for e in events if mod._hit(e, "lenient")]
    # Half the events have both flags True, the other half have both False.
    assert len(strict) == 4
    assert len(lenient) == 4


def test_rollup_returns_none_for_empty_bucket() -> None:
    mod = _load_module()
    hr, n = mod._rollup([], "strict")
    assert hr is None
    assert n == 0


def test_rollup_computes_hit_rate(fixture_root: Path) -> None:
    mod = _load_module()
    events = mod._load_fvg_events(fixture_root)
    hr, n = mod._rollup(events, "strict")
    assert n == 8
    assert hr == 0.5


def test_main_runs_end_to_end_on_fixture(
    fixture_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """End-to-end smoke: the CLI must not raise on a minimal fixture
    and must emit the section headers the audit doc references."""
    mod = _load_module()
    monkey_argv = ["fvg_quality_d4_audit", "--root", str(fixture_root)]
    old_argv = sys.argv
    try:
        sys.argv = monkey_argv
        rc = mod.main()
    finally:
        sys.argv = old_argv
    assert rc == 0
    out = capsys.readouterr().out
    # Section pins — these are referenced by docs/FVG_QUALITY_D4_AUDIT.md.
    for section in (
        "htf_aligned (bool)",
        "is_full_body (bool)",
        "distance_to_price_atr (quartiles)",
        "hurst_50 (quartiles)",
        "× symbol (robustness check)",
    ):
        assert section in out, f"missing section: {section!r}"
