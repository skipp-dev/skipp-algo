"""Contract pins for the TEMPORARY f1-restart-drill workflow.

The drill exists for exactly one night (2026-07-23) to exercise the
lo-restart-data-loss-closed firing path with a real dead-zone restart.
These pins (a) un-orphan the workflow for the inventory guard and (b) make
sure nobody 'fixes' the date-pinned crons into a recurring nightly restart.
Remove this test together with .github/workflows/f1-restart-drill.yml once
the 2026-07-23 run is evaluated.
"""
from __future__ import annotations

from pathlib import Path

import yaml

_WF = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "f1-restart-drill.yml"


def test_drill_is_date_pinned_and_read_only_checks() -> None:
    doc = yaml.safe_load(_WF.read_text(encoding="utf-8"))
    crons = [entry["cron"] for entry in doc[True]["schedule"]]  # yaml parses bare `on` as True
    assert all(c.split()[2:4] == ["23", "7"] for c in crons), (
        f"drill crons must stay pinned to July 23 (one-night test), got {crons}"
    )
    text = _WF.read_text(encoding="utf-8")
    assert "grafana_alert_state" in text, "checks must use the read-only state reader"
    assert "deploy-live-overlay-daemon.yml" in text, (
        "restart must reuse the proven deploy workflow, not a second Railway path"
    )
    assert "REMOVE" in text, "the removal reminder comment must survive edits"
