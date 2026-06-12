"""Tests for scripts/render_shadow_step_summary.py."""

from __future__ import annotations

from scripts.render_shadow_step_summary import render_summary


def _row(
    family: str,
    auc: float,
    status: str = "PASS",
    role: str | None = None,
    date: str = "2025-01-01",
) -> dict:
    if role is None:
        role = "candidate" if family in {"BOS", "SWEEP"} else "control"
    return {
        "family": family,
        "magnitude_auc": auc,
        "status": status,
        "role": role,
        "date": date,
    }


class TestRenderSummaryEmpty:
    def test_empty_rows(self) -> None:
        md = render_summary([])
        assert "No shadow data yet" in md

    def test_empty_rows_no_table(self) -> None:
        md = render_summary([])
        assert "| Family" not in md


class TestRenderSummaryTable:
    def test_single_candidate_pass(self) -> None:
        rows = [_row("BOS", 0.62)]
        md = render_summary(rows, k=3, n=4)
        assert "| BOS" in md
        assert "candidate" in md
        assert "1/4" in md  # window size
        assert "need 2" in md  # 3-1 = 2 remaining

    def test_candidate_eligible(self) -> None:
        rows = [_row("SWEEP", 0.65, date=f"2025-01-0{i+1}") for i in range(3)]
        md = render_summary(rows, k=3, n=4)
        assert "3-of-4 met" in md

    def test_control_family_no_stage2(self) -> None:
        rows = [_row("FVG", 0.51, status="FAIL")]
        md = render_summary(rows, k=3, n=4)
        lines = [ln for ln in md.split("\n") if "| FVG" in ln]
        assert len(lines) == 1
        # Controls show em-dash, not progress
        assert "—" in lines[0]

    def test_window_truncation(self) -> None:
        # 6 rows for BOS but n=4 -> only last 4 shown
        rows = [_row("BOS", 0.60 + i * 0.01, date=f"2025-01-0{i+1}") for i in range(6)]
        md = render_summary(rows, k=3, n=4)
        assert "4/4" in md

    def test_sparkline_present(self) -> None:
        rows = [_row("BOS", 0.55), _row("BOS", 0.62), _row("BOS", 0.68)]
        md = render_summary(rows, k=3, n=4)
        # At least one sparkline block character should be present
        spark_chars = set("▁▂▃▄▅▆▇█·")
        lines = [ln for ln in md.split("\n") if "| BOS" in ln]
        assert len(lines) == 1
        assert any(c in lines[0] for c in spark_chars)

    def test_auc_format(self) -> None:
        rows = [_row("BOS", 0.6234)]
        md = render_summary(rows, k=3, n=4)
        assert "0.623" in md  # 3 decimal places

    def test_multiple_families_sorted(self) -> None:
        rows = [
            _row("SWEEP", 0.60),
            _row("BOS", 0.62),
            _row("OB", 0.51, status="FAIL"),
        ]
        md = render_summary(rows, k=3, n=4)
        lines = [ln for ln in md.split("\n") if ln.startswith("| ") and "Family" not in ln and "---" not in ln]
        families = [ln.split("|")[1].strip() for ln in lines]
        assert families == sorted(families)

    def test_footnote_present(self) -> None:
        rows = [_row("BOS", 0.60)]
        md = render_summary(rows, k=3, n=4)
        assert "coin-flip" in md
        assert "3-of-4" in md  # k-of-n in footnote


class TestRenderSummaryNoneAuc:
    def test_none_auc(self) -> None:
        rows = [{"family": "BOS", "magnitude_auc": None, "status": "INCONCLUSIVE", "date": "2025-01-01"}]
        md = render_summary(rows, k=3, n=4)
        assert "n/a" in md
