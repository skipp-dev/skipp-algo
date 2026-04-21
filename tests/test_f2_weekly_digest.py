"""Tests for scripts/f2_weekly_digest.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.f2_weekly_digest import (
    build_digest,
    main,
    render_markdown,
)


def _write_report(
    reports_dir: Path, date: str, *,
    decision: str = "hold",
    brier_delta: float | None = -0.001,
    sprt_decision: str | None = "continue",
    sprt_n: int = 100, sprt_k: int = 55,
) -> Path:
    reports_dir.mkdir(parents=True, exist_ok=True)
    payload: dict = {"decision": decision}
    if sprt_decision is not None:
        payload["sprt"] = {"decision": sprt_decision, "n": sprt_n, "k": sprt_k}
    if brier_delta is not None:
        payload["kpi_metrics"] = [
            {"metric": "calibrated_brier", "delta": brier_delta},
            {"metric": "hit_rate_pct", "delta": 1.0},
        ]
    p = reports_dir / f"f2_promotion_gate_{date}.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# build_digest
# ---------------------------------------------------------------------------


def test_digest_collects_full_window(tmp_path: Path) -> None:
    rd = tmp_path / "reports"
    for d, decision in [
        ("2026-04-15", "hold"),
        ("2026-04-16", "hold"),
        ("2026-04-17", "hold"),
        ("2026-04-18", "promote"),
        ("2026-04-19", "rollback"),
        ("2026-04-20", "hold"),
        ("2026-04-21", "rollback"),
    ]:
        _write_report(rd, d, decision=decision)

    digest = build_digest(reports_dir=rd, window_days=7)
    assert digest["len"] == 7
    assert digest["date_range"] == ["2026-04-15", "2026-04-21"]
    assert digest["decisions"] == {"hold": 4, "promote": 1, "rollback": 2}
    assert len(digest["timeline"]) == 7
    assert digest["timeline"][0]["date"] == "2026-04-15"
    assert digest["timeline"][-1]["date"] == "2026-04-21"


def test_digest_trims_to_trailing_window(tmp_path: Path) -> None:
    rd = tmp_path / "reports"
    for i in range(10):
        _write_report(rd, f"2026-04-{i+10:02d}")
    digest = build_digest(reports_dir=rd, window_days=3)
    assert digest["len"] == 3
    assert digest["total_reports_seen"] == 10
    assert digest["date_range"] == ["2026-04-17", "2026-04-19"]


def test_digest_empty_when_no_reports(tmp_path: Path) -> None:
    rd = tmp_path / "reports"
    rd.mkdir()
    digest = build_digest(reports_dir=rd, window_days=7)
    assert digest["len"] == 0
    assert digest["date_range"] == [None, None]
    assert digest["decisions"] == {}
    assert digest["timeline"] == []


def test_digest_consecutive_worse_count(tmp_path: Path) -> None:
    rd = tmp_path / "reports"
    # First 2 better (negative), last 3 worse (positive) → consecutive_worse=3.
    for d, delta in [
        ("2026-04-17", -0.005),
        ("2026-04-18", -0.003),
        ("2026-04-19",  0.004),
        ("2026-04-20",  0.011),
        ("2026-04-21",  0.018),
    ]:
        _write_report(rd, d, brier_delta=delta)
    digest = build_digest(reports_dir=rd, window_days=7)
    assert digest["consecutive_worse"] == 3
    assert digest["consecutive_better"] == 0


def test_digest_consecutive_better_count(tmp_path: Path) -> None:
    rd = tmp_path / "reports"
    for d, delta in [
        ("2026-04-19",  0.005),
        ("2026-04-20", -0.001),
        ("2026-04-21", -0.002),
    ]:
        _write_report(rd, d, brier_delta=delta)
    digest = build_digest(reports_dir=rd, window_days=7)
    assert digest["consecutive_better"] == 2
    assert digest["consecutive_worse"] == 0


def test_digest_sprt_rollup(tmp_path: Path) -> None:
    rd = tmp_path / "reports"
    _write_report(rd, "2026-04-19", sprt_decision="continue")
    _write_report(rd, "2026-04-20", sprt_decision="continue")
    _write_report(rd, "2026-04-21", sprt_decision="accept_h0")
    digest = build_digest(reports_dir=rd, window_days=7)
    assert digest["sprt_decisions"] == {"continue": 2, "accept_h0": 1}


def test_digest_tolerates_missing_metric_block(tmp_path: Path) -> None:
    rd = tmp_path / "reports"
    _write_report(rd, "2026-04-21", brier_delta=None)
    digest = build_digest(reports_dir=rd, window_days=7)
    entry = digest["timeline"][0]
    assert entry["brier_delta"] is None
    assert digest["consecutive_worse"] == 0
    assert digest["consecutive_better"] == 0


def test_digest_tolerates_unreadable_file(tmp_path: Path) -> None:
    rd = tmp_path / "reports"
    rd.mkdir()
    (rd / "f2_promotion_gate_2026-04-21.json").write_text("not-json", encoding="utf-8")
    digest = build_digest(reports_dir=rd, window_days=7)
    assert digest["len"] == 1
    entry = digest["timeline"][0]
    assert entry["error"] == "unreadable"
    assert entry["decision"] is None


def test_digest_ignores_non_matching_filenames(tmp_path: Path) -> None:
    rd = tmp_path / "reports"
    rd.mkdir()
    (rd / "summary.json").write_text("{}", encoding="utf-8")
    (rd / "f2_promotion_gate_2026-04-21.json").write_text(
        json.dumps({"decision": "hold"}), encoding="utf-8")
    digest = build_digest(reports_dir=rd, window_days=7)
    assert digest["len"] == 1


def test_digest_raises_on_missing_dir(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="reports-dir does not exist"):
        build_digest(reports_dir=tmp_path / "nope", window_days=7)


def test_digest_raises_on_invalid_window(tmp_path: Path) -> None:
    rd = tmp_path / "reports"
    rd.mkdir()
    with pytest.raises(ValueError, match="window_days"):
        build_digest(reports_dir=rd, window_days=0)


# ---------------------------------------------------------------------------
# Markdown render
# ---------------------------------------------------------------------------


def test_render_markdown_full(tmp_path: Path) -> None:
    rd = tmp_path / "reports"
    _write_report(rd, "2026-04-20", decision="hold", brier_delta=-0.005)
    _write_report(rd, "2026-04-21", decision="rollback", brier_delta=0.012,
                  sprt_decision="accept_h0", sprt_n=120, sprt_k=70)
    md = render_markdown(build_digest(reports_dir=rd, window_days=7))
    assert "# F2 weekly digest" in md
    assert "## Timeline" in md
    assert "| date | decision | brier_delta | sprt | n | k |" in md
    assert "`2026-04-21`" in md
    assert "`rollback`" in md
    assert "+0.012000" in md
    assert "`accept_h0`" in md
    assert "`hold`=1" in md
    assert "`rollback`=1" in md


def test_render_markdown_empty(tmp_path: Path) -> None:
    rd = tmp_path / "reports"
    rd.mkdir()
    md = render_markdown(build_digest(reports_dir=rd, window_days=7))
    assert "# F2 weekly digest" in md
    assert "## Timeline" in md  # header always present, table empty


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_writes_output_returns_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rd = tmp_path / "reports"
    _write_report(rd, "2026-04-21")
    out = tmp_path / "digest.json"
    rc = main([
        "--reports-dir", str(rd),
        "--window-days", "7",
        "--output", str(out),
    ])
    assert rc == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["len"] == 1
    assert data["schema_version"] == 1


def test_cli_format_md_emits_markdown(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rd = tmp_path / "reports"
    _write_report(rd, "2026-04-21")
    rc = main(["--reports-dir", str(rd), "--format", "md"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "# F2 weekly digest" in out
    assert '"schema_version"' not in out


def test_cli_missing_reports_dir_returns_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(["--reports-dir", str(tmp_path / "nope")])
    assert rc == 1
    assert "does not exist" in capsys.readouterr().err
