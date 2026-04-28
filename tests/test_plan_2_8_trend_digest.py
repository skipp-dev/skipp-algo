"""Tests for ``scripts/plan_2_8_trend_digest.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


digest_mod = _load(
    "plan_2_8_trend_digest",
    REPO / "scripts" / "plan_2_8_trend_digest.py",
)
arch_mod = _load(
    "plan_2_8_history_archive",
    REPO / "scripts" / "plan_2_8_history_archive.py",
)


def _snap(captured_at: str, scoring_root: str,
          fvg_5m_hr: float, fvg_5m_n: int = 100) -> dict:
    return {
        "captured_at": captured_at,
        "scoring_root": scoring_root,
        "files_scanned": 4,
        "per_tf": {
            "5m": {
                "n_events": fvg_5m_n,
                "hit_rate": fvg_5m_hr,
                "families": {
                    "FVG": {"n_events": fvg_5m_n, "hit_rate": fvg_5m_hr},
                },
            },
        },
    }


def test_build_digest_empty_history() -> None:
    out = digest_mod.build_digest(snapshots=[])
    assert out["status"] == "empty"


def test_build_digest_warmup_when_window_too_young() -> None:
    snaps = [_snap("2026-04-21T07:00:00Z", "out/a", 0.45)]
    out = digest_mod.build_digest(snapshots=snaps, lookback_days=7)
    assert out["status"] == "warmup"
    assert out["coverage"]["latest_captured_at"] == "2026-04-21T07:00:00Z"


def test_build_digest_picks_oldest_snapshot_satisfying_lookback() -> None:
    snaps = [
        _snap("2026-04-14T07:00:00Z", "out/a", 0.45),  # exactly 7d before
        _snap("2026-04-15T07:00:00Z", "out/b", 0.46),  # within window
        _snap("2026-04-21T07:00:00Z", "out/c", 0.50),  # latest
    ]
    out = digest_mod.build_digest(snapshots=snaps, lookback_days=7)
    assert out["status"] == "ok"
    assert out["coverage"]["previous_captured_at"] == "2026-04-14T07:00:00Z"


def test_build_digest_per_tf_and_per_family_drift() -> None:
    snaps = [
        _snap("2026-04-14T07:00:00Z", "out/a", 0.45, fvg_5m_n=100),
        _snap("2026-04-21T07:00:00Z", "out/b", 0.50, fvg_5m_n=100),
    ]
    out = digest_mod.build_digest(snapshots=snaps, lookback_days=7)
    assert out["status"] == "ok"
    tf_row = next(r for r in out["per_tf"] if r["tf"] == "5m")
    assert tf_row["delta_pp"] == pytest.approx(0.05)
    assert tf_row["comparable"] is True
    fam_row = next(r for r in out["per_family"] if r["tf"] == "5m" and r["family"] == "FVG")
    assert fam_row["delta_pp"] == pytest.approx(0.05)
    assert fam_row["comparable"] is True


def test_build_digest_alert_emitted_when_threshold_exceeded() -> None:
    snaps = [
        _snap("2026-04-14T07:00:00Z", "out/a", 0.40, fvg_5m_n=100),
        _snap("2026-04-21T07:00:00Z", "out/b", 0.50, fvg_5m_n=100),  # +10pp
    ]
    out = digest_mod.build_digest(
        snapshots=snaps, lookback_days=7, alert_threshold_pp=0.05,
    )
    assert any(a["family"] == "FVG" and a["tf"] == "5m" for a in out["alerts"])


def test_build_digest_no_alert_below_threshold() -> None:
    snaps = [
        _snap("2026-04-14T07:00:00Z", "out/a", 0.45),
        _snap("2026-04-21T07:00:00Z", "out/b", 0.46),  # +1pp
    ]
    out = digest_mod.build_digest(
        snapshots=snaps, lookback_days=7, alert_threshold_pp=0.05,
    )
    assert out["alerts"] == []


def test_build_digest_marks_uncomparable_when_min_events_unmet() -> None:
    snaps = [
        _snap("2026-04-14T07:00:00Z", "out/a", 0.45, fvg_5m_n=10),
        _snap("2026-04-21T07:00:00Z", "out/b", 0.55, fvg_5m_n=10),
    ]
    out = digest_mod.build_digest(snapshots=snaps, lookback_days=7, min_events=30)
    fam_row = next(r for r in out["per_family"] if r["family"] == "FVG")
    assert fam_row["comparable"] is False
    # Big delta but uncomparable -> no alert.
    assert out["alerts"] == []


def test_render_markdown_warmup_skips_tables() -> None:
    out = digest_mod.build_digest(
        snapshots=[_snap("2026-04-21T07:00:00Z", "out/a", 0.45)],
        lookback_days=7,
    )
    md = digest_mod.render_markdown(out)
    assert "warmup" in md
    assert "## Per-TF drift" not in md
    assert md.endswith("\n")


def test_render_markdown_ok_includes_all_sections() -> None:
    snaps = [
        _snap("2026-04-14T07:00:00Z", "out/a", 0.45),
        _snap("2026-04-21T07:00:00Z", "out/b", 0.50),
    ]
    md = digest_mod.render_markdown(digest_mod.build_digest(snapshots=snaps))
    for section in ("## Per-TF drift", "## Per-TF x family drift", "## Alerts"):
        assert section in md


def test_end_to_end_archive_then_digest(tmp_path: Path) -> None:
    """Snapshots written by the archiver must feed the digest cleanly."""
    history = tmp_path / "hist.jsonl"

    def _rollup(scoring_root: str, hr: float) -> dict:
        return {
            "schema_version": 1,
            "scoring_root": scoring_root,
            "files_scanned": 1,
            "per_tf": {
                "5m": {
                    "n_events": 100, "hit_rate": hr, "symbols": ["A"],
                    "families": {"FVG": {"n_events": 100, "hit_rate": hr}},
                },
            },
        }

    arch_mod.append_snapshot(
        rollup=_rollup("out/a", 0.45), history_path=history,
        captured_at="2026-04-14T07:00:00Z",
    )
    arch_mod.append_snapshot(
        rollup=_rollup("out/b", 0.50), history_path=history,
        captured_at="2026-04-21T07:00:00Z",
    )
    snapshots = digest_mod._read_jsonl(history)
    out = digest_mod.build_digest(snapshots=snapshots)
    assert out["status"] == "ok"
    assert out["coverage"]["snapshots_total"] == 2
    fam_row = next(r for r in out["per_family"] if r["family"] == "FVG")
    assert fam_row["delta_pp"] == pytest.approx(0.05)


def test_cli_writes_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    history = tmp_path / "hist.jsonl"
    history.write_text(
        "\n".join(
            json.dumps(s) for s in [
                _snap("2026-04-14T07:00:00Z", "out/a", 0.45),
                _snap("2026-04-21T07:00:00Z", "out/b", 0.50),
            ]
        ) + "\n", encoding="utf-8",
    )
    out_path = tmp_path / "digest.md"
    rc = digest_mod.main([
        "--history", str(history),
        "--output", str(out_path),
    ])
    assert rc == 0
    body = out_path.read_text(encoding="utf-8")
    assert "Plan 2.8 weekly trend digest" in body
    assert "## Per-TF drift" in body
    assert "Plan 2.8 weekly trend digest" in capsys.readouterr().out


def test_cli_error_on_missing_history(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = digest_mod.main([
        "--history", str(tmp_path / "nope.jsonl"),
    ])
    assert rc == 1
    assert "history not found" in capsys.readouterr().err
