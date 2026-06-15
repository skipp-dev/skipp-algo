"""Tests for scripts/g23_ab_watchdog.py — Q3/Q4 G2/G3 governance gate."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts import g23_ab_watchdog as wd
from scripts.smc_sprt_stop_rule import SPRTConfig

# ── helpers ────────────────────────────────────────────────────────────────


def _comparison(
    *,
    treatment_n: int,
    treatment_hr: float,
    control_n: int,
    control_hr: float,
    decision: str = "continue",
) -> dict:
    """Build a minimal `ab_comparison.json`-shaped dict."""
    return {
        "experiment": "test-exp",
        "sprt": {
            "decision": decision,
            "n": treatment_n,
            "k": round(treatment_n * treatment_hr),
            "hit_rate": round(treatment_hr, 4),
            "control_n": control_n,
            "control_hit_rate": round(control_hr, 4),
        },
    }


def _entry(*, treatment_underperformed: bool, treatment_n: int = 100,
           treatment_k: int = 60, control_n: int = 100, control_hr: float = 0.55) -> dict:
    return {
        "timestamp": "2026-01-01T00:00:00+00:00",
        "experiment": "test-exp",
        "control_n": control_n,
        "control_k": round(control_n * control_hr),
        "control_hit_rate": control_hr,
        "treatment_n": treatment_n,
        "treatment_k": treatment_k,
        "treatment_hit_rate": treatment_k / treatment_n if treatment_n else 0.0,
        "treatment_underperformed": treatment_underperformed,
        "sprt_decision_single_run": "continue",
        "source": {"path": None, "commit_sha": None, "workflow_run": None},
    }


# ── coercion / extraction ──────────────────────────────────────────────────


def test_coerce_int_handles_none_and_garbage():
    assert wd._coerce_int(None) == 0
    assert wd._coerce_int("nope") == 0
    assert wd._coerce_int("12") == 12


def test_coerce_float_returns_none_on_nan():
    assert wd._coerce_float(float("nan")) is None
    assert wd._coerce_float(None) is None
    assert wd._coerce_float("0.5") == 0.5


def test_extract_arm_totals_derives_control_k_from_hit_rate():
    comp = _comparison(treatment_n=200, treatment_hr=0.62,
                       control_n=180, control_hr=0.55)
    c_n, c_k, t_n, t_k = wd._extract_arm_totals(comp)
    assert (c_n, c_k, t_n, t_k) == (180, 99, 200, 124)


def test_extract_arm_totals_handles_missing_sprt_block():
    c_n, c_k, t_n, t_k = wd._extract_arm_totals({})
    assert (c_n, c_k, t_n, t_k) == (0, 0, 0, 0)


def test_treatment_underperformed_true_when_le_control():
    assert wd._treatment_underperformed(_comparison(
        treatment_n=100, treatment_hr=0.50, control_n=100, control_hr=0.55))
    # equal → also underperformed (≤)
    assert wd._treatment_underperformed(_comparison(
        treatment_n=100, treatment_hr=0.55, control_n=100, control_hr=0.55))


def test_treatment_underperformed_false_when_gt_control():
    assert not wd._treatment_underperformed(_comparison(
        treatment_n=100, treatment_hr=0.60, control_n=100, control_hr=0.55))


def test_treatment_underperformed_false_when_data_missing():
    # W9-2: must raise ValueError on missing data instead of returning False
    with pytest.raises(ValueError, match="cannot evaluate underperformance"):
        wd._treatment_underperformed({"sprt": {}})


# ── history I/O ────────────────────────────────────────────────────────────


def test_load_history_returns_empty_when_missing(tmp_path):
    assert wd.load_history(tmp_path / "missing.jsonl") == []


def test_load_history_raises_on_malformed_line_pre_existing(tmp_path):
    """W6-4: load_history must raise SystemExit on a malformed line.

    This test replaces the former ``test_load_history_skips_malformed_lines``
    which asserted silent-skip behaviour. That behaviour was a defect identified
    in stat-review wave 6 (W6-4): a corrupt entry was silently dropped, which
    could suppress a rollback streak. The function now fails closed.
    """
    p = tmp_path / "h.jsonl"
    p.write_text('{"a":1}\nNOT JSON\n{"b":2}\n', encoding="utf-8")
    with pytest.raises(SystemExit):
        wd.load_history(p)


def test_append_history_truncates_to_retention_window(tmp_path, monkeypatch):
    monkeypatch.setattr(wd, "HISTORY_RETENTION", 3)
    p = tmp_path / "h.jsonl"
    for i in range(5):
        wd.append_history(p, {"i": i})
    out = wd.load_history(p)
    assert [e["i"] for e in out] == [2, 3, 4]


def test_append_history_writes_atomically(tmp_path):
    p = tmp_path / "h.jsonl"
    wd.append_history(p, {"i": 1})
    # No leftover .tmp file.
    assert not p.with_suffix(".jsonl.tmp").exists()
    assert p.exists()


# ── streak detection (G2 rollback gate) ───────────────────────────────────


def test_streak_zero_when_history_empty():
    assert wd.consecutive_underperform_streak([]) == 0


def test_streak_counts_only_trailing_losses():
    history = [
        _entry(treatment_underperformed=True),
        _entry(treatment_underperformed=False),
        _entry(treatment_underperformed=True),
        _entry(treatment_underperformed=True),
    ]
    assert wd.consecutive_underperform_streak(history) == 2


def test_streak_resets_on_first_win_from_tail():
    history = [
        _entry(treatment_underperformed=True),
        _entry(treatment_underperformed=True),
        _entry(treatment_underperformed=False),
    ]
    assert wd.consecutive_underperform_streak(history) == 0


# ── aggregated SPRT (G3 stop rule) ────────────────────────────────────────


def test_aggregated_sprt_returns_no_data_when_history_empty():
    cfg = SPRTConfig(p0=0.544, p1=0.574, alpha=0.05, beta=0.20)
    out = wd.aggregated_sprt([], config=cfg)
    assert out["decision"] == "no_data"
    assert out["n"] == 0


def test_aggregated_sprt_uses_latest_entry():
    """W3-2: only the latest entry's (n, k) should be used — not the sum."""
    cfg = SPRTConfig(p0=0.544, p1=0.574, alpha=0.05, beta=0.20)
    # Build a strongly winning treatment that should accept_h1.
    history = [
        _entry(treatment_underperformed=False, treatment_n=500, treatment_k=350)
        for _ in range(10)
    ]
    out = wd.aggregated_sprt(history, config=cfg)
    # Latest entry only: n=500, k=350 — NOT 5000/3500.
    assert out["n"] == 500 and out["k"] == 350
    assert out["decision"] == "accept_h1"


def test_aggregated_sprt_accepts_h0_on_strong_loss():
    cfg = SPRTConfig(p0=0.544, p1=0.574, alpha=0.05, beta=0.20)
    history = [
        _entry(treatment_underperformed=True, treatment_n=500, treatment_k=200)
        for _ in range(10)
    ]
    out = wd.aggregated_sprt(history, config=cfg)
    # Latest entry only: n=500, k=200.
    assert out["n"] == 500 and out["k"] == 200
    assert out["decision"] == "accept_h0"


# ── evaluate_signals composition ──────────────────────────────────────────


def test_evaluate_signals_flags_rollback_on_streak():
    cfg = SPRTConfig(p0=0.544, p1=0.574, alpha=0.05, beta=0.20)
    history = [
        _entry(treatment_underperformed=True, treatment_n=10, treatment_k=2),
        _entry(treatment_underperformed=True, treatment_n=10, treatment_k=2),
    ]
    sig = wd.evaluate_signals(history, rollback_streak=2, config=cfg)
    assert sig["rollback_required"] is True
    assert sig["underperform_streak"] == 2
    assert wd.select_exit_code(sig) == wd.EXIT_ROLLBACK


def test_evaluate_signals_does_not_flag_rollback_below_threshold():
    cfg = SPRTConfig(p0=0.544, p1=0.574, alpha=0.05, beta=0.20)
    history = [_entry(treatment_underperformed=True, treatment_n=10, treatment_k=2)]
    sig = wd.evaluate_signals(history, rollback_streak=2, config=cfg)
    assert sig["rollback_required"] is False
    assert wd.select_exit_code(sig) == wd.EXIT_OK


def test_evaluate_signals_promotion_ready_emits_exit_3():
    cfg = SPRTConfig(p0=0.544, p1=0.574, alpha=0.05, beta=0.20)
    history = [
        _entry(treatment_underperformed=False, treatment_n=500, treatment_k=350)
        for _ in range(10)
    ]
    sig = wd.evaluate_signals(history, rollback_streak=2, config=cfg)
    assert sig["promotion_ready"] is True
    assert wd.select_exit_code(sig) == wd.EXIT_PROMOTION_READY


def test_evaluate_signals_futility_emits_exit_4():
    cfg = SPRTConfig(p0=0.544, p1=0.574, alpha=0.05, beta=0.20)
    history = [
        _entry(treatment_underperformed=True, treatment_n=500, treatment_k=200)
        for _ in range(10)
    ]
    sig = wd.evaluate_signals(history, rollback_streak=99, config=cfg)
    # rollback_streak set high so only futility fires.
    assert sig["stop_for_futility"] is True
    assert wd.select_exit_code(sig) == wd.EXIT_FUTILITY


# ── markdown render ───────────────────────────────────────────────────────


def test_render_status_markdown_handles_empty_history():
    cfg = SPRTConfig(p0=0.544, p1=0.574, alpha=0.05, beta=0.20)
    sig = wd.evaluate_signals([], rollback_streak=2, config=cfg)
    md = wd.render_status_markdown(sig, history=[], generated_at="2026-01-01T00:00:00+00:00", source_commit_sha=None)
    assert "awaiting_first_run" in md
    assert "G2/G3 A/B Watchdog" in md


def test_render_status_markdown_reports_rollback_yes():
    cfg = SPRTConfig(p0=0.544, p1=0.574, alpha=0.05, beta=0.20)
    history = [
        _entry(treatment_underperformed=True, treatment_n=10, treatment_k=2),
        _entry(treatment_underperformed=True, treatment_n=10, treatment_k=2),
    ]
    sig = wd.evaluate_signals(history, rollback_streak=2, config=cfg)
    md = wd.render_status_markdown(sig, history=history, generated_at="t", source_commit_sha="abc1234567")
    assert "rollback required" in md
    assert "**YES**" in md


# ── CLI / main ────────────────────────────────────────────────────────────


def test_main_without_input_evaluates_existing_history(tmp_path, monkeypatch):
    history_path = tmp_path / "h.jsonl"
    status_md = tmp_path / "s.md"
    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.write_text(json.dumps(_entry(treatment_underperformed=False)) + "\n",
                            encoding="utf-8")
    rc = wd.main([
        "--history", str(history_path),
        "--status-md", str(status_md),
    ])
    assert rc == wd.EXIT_OK
    assert status_md.exists()


def test_main_with_input_appends_and_returns_rollback_when_streak_met(tmp_path):
    history_path = tmp_path / "h.jsonl"
    status_md = tmp_path / "s.md"
    # Seed one losing entry already.
    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.write_text(json.dumps(_entry(treatment_underperformed=True,
                                              treatment_n=10, treatment_k=2)) + "\n",
                            encoding="utf-8")
    # Provide a fresh losing comparison as input → second loss → streak = 2.
    inp = tmp_path / "comp.json"
    inp.write_text(json.dumps(_comparison(
        treatment_n=10, treatment_hr=0.20, control_n=10, control_hr=0.55)),
        encoding="utf-8")
    rc = wd.main([
        "--input", str(inp),
        "--history", str(history_path),
        "--status-md", str(status_md),
        "--rollback-streak", "2",
    ])
    assert rc == wd.EXIT_ROLLBACK


def test_main_handles_unreadable_input(tmp_path):
    rc = wd.main([
        "--input", str(tmp_path / "missing.json"),
        "--history", str(tmp_path / "h.jsonl"),
        "--status-md", str(tmp_path / "s.md"),
    ])
    assert rc == wd.EXIT_FATAL


def test_main_handles_malformed_input_json(tmp_path):
    inp = tmp_path / "bad.json"
    inp.write_text("not json", encoding="utf-8")
    rc = wd.main([
        "--input", str(inp),
        "--history", str(tmp_path / "h.jsonl"),
        "--status-md", str(tmp_path / "s.md"),
    ])
    assert rc == wd.EXIT_FATAL


# ---------------------------------------------------------------------------
# W6-4 — malformed history JSONL must fail closed (stat-review wave 6)
# ---------------------------------------------------------------------------


def test_load_history_raises_on_malformed_line(tmp_path):
    """W6-4: a corrupt history line must cause SystemExit, not silent skip."""
    history_path = tmp_path / "h.jsonl"
    good = json.dumps(_entry(treatment_underperformed=True))
    history_path.write_text(f"{good}\nnot_valid_json\n{good}\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        wd.load_history(history_path)


def test_main_exits_fatal_on_corrupt_history(tmp_path):
    """W6-4: main must exit fatally if history JSONL is corrupt."""
    history_path = tmp_path / "h.jsonl"
    good = json.dumps(_entry(treatment_underperformed=True))
    history_path.write_text(f"{good}\nbad_json_line\n", encoding="utf-8")
    with pytest.raises(SystemExit) as exc_info:
        wd.main([
            "--history", str(history_path),
            "--status-md", str(tmp_path / "s.md"),
        ])
    assert exc_info.value.code == wd.EXIT_FATAL


# ---------------------------------------------------------------------------
# W6-5 — SPRT max_n constant + CLI wiring (stat-review wave 6)
# ---------------------------------------------------------------------------


def test_sprt_max_n_constant_matches_live_spec():
    """W6-5: SPRT_MAX_N must match artifacts/experiments/f2_contextual_promotion.json."""
    import json as _json
    from pathlib import Path as _Path

    spec_path = _Path(__file__).resolve().parent.parent / "artifacts" / "experiments" / "f2_contextual_promotion.json"
    live_max_n = _json.loads(spec_path.read_text(encoding="utf-8"))["sprt"]["max_n"]
    assert live_max_n == wd.SPRT_MAX_N, (
        f"SPRT_MAX_N={wd.SPRT_MAX_N} != live spec max_n={live_max_n}; "
        "update SPRT_MAX_N in g23_ab_watchdog.py"
    )


def test_sprt_config_uses_max_n(tmp_path):
    """W6-5: main must wire --max-n into SPRTConfig (and thus into aggregated_sprt)."""
    history_path = tmp_path / "h.jsonl"
    # Write a history entry with enough observations to potentially trigger max_n.
    entry = _entry(treatment_underperformed=False, treatment_n=2000, treatment_k=1200)
    history_path.write_text(json.dumps(entry) + "\n", encoding="utf-8")
    rc = wd.main([
        "--history", str(history_path),
        "--status-md", str(tmp_path / "s.md"),
        "--max-n", "1200",
    ])
    assert rc in (wd.EXIT_OK, wd.EXIT_PROMOTION_READY, wd.EXIT_FUTILITY, wd.EXIT_ROLLBACK)


def test_max_n_default_equals_constant():
    """W6-5: default --max-n must equal SPRT_MAX_N."""
    ns = wd._parse_args([
        "--history", "/dev/null",
        "--status-md", "/dev/null",
    ])
    assert ns.max_n == wd.SPRT_MAX_N


# ---------------------------------------------------------------------------
# Additional coverage to kill surviving mutants
# ---------------------------------------------------------------------------


def test_aggregated_sprt_returns_no_data_when_treatment_n_is_zero():
    cfg = SPRTConfig(p0=0.544, p1=0.574, alpha=0.05, beta=0.20)
    history = [
        _entry(treatment_underperformed=False, treatment_n=0, treatment_k=0)
    ]
    out = wd.aggregated_sprt(history, config=cfg)
    assert out["decision"] == "no_data"
    assert out["n"] == 0


def test_append_history_sorts_keys(tmp_path):
    p = tmp_path / "h.jsonl"
    entry = {"z": 1, "a": 2}
    wd.append_history(p, entry)
    line = p.read_text(encoding="utf-8").strip()
    assert line.startswith('{"a": 2')


def test_append_history_creates_deep_nested_parents(tmp_path):
    p = tmp_path / "deep" / "nested" / "dir" / "h.jsonl"
    wd.append_history(p, {"i": 1})
    assert p.exists()


def test_write_status_creates_deep_nested_parents(tmp_path):
    p = tmp_path / "deep" / "nested" / "dir" / "status.md"
    wd.write_status(p, "test status")
    assert p.exists()


def test_treatment_underperformed_false_when_treatment_hr_is_none():
    # W9-2: must raise ValueError on missing data instead of returning False
    with pytest.raises(ValueError, match="cannot evaluate underperformance"):
        wd._treatment_underperformed({
            "sprt": {"control_hit_rate": 0.55}
        })


def test_treatment_underperformed_false_when_control_hr_is_none():
    # W9-2: must raise ValueError on missing data instead of returning False
    with pytest.raises(ValueError, match="cannot evaluate underperformance"):
        wd._treatment_underperformed({
            "sprt": {"hit_rate": 0.55}
        })


def test_make_history_entry_populates_all_fields():
    comp = {
        "experiment": "test-exp",
        "sprt": {
            "decision": "continue",
            "n": 100,
            "k": 60,
            "hit_rate": 0.60,
            "control_n": 100,
            "control_hit_rate": 0.55,
        }
    }
    entry = wd._make_history_entry(
        comp,
        timestamp="2026-01-01T00:00:00Z",
        source_path=Path("docs/ab_comparison.json"),
        source_commit_sha="abcdef123",
        source_workflow_run="12345",
    )
    assert entry["timestamp"] == "2026-01-01T00:00:00Z"
    assert entry["experiment"] == "test-exp"
    assert entry["control_n"] == 100
    assert entry["control_k"] == 55
    assert entry["control_hit_rate"] == 0.55
    assert entry["treatment_n"] == 100
    assert entry["treatment_k"] == 60
    assert entry["treatment_hit_rate"] == 0.60
    assert entry["treatment_underperformed"] is False
    assert entry["sprt_decision_single_run"] == "continue"
    assert entry["source"]["path"] == "docs/ab_comparison.json"
    assert entry["source"]["commit_sha"] == "abcdef123"
    assert entry["source"]["workflow_run"] == "12345"

