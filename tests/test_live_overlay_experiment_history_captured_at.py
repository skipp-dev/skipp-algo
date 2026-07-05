"""Regression test for ``metrics._experiment_history`` numeric ``captured_at``.

Readonly-review finding: ``_experiment_history`` derived each row's
``run_date`` with ``str(captured_at)[:10] if isinstance(captured_at, str)``,
so a snapshot whose ``captured_at`` was a numeric Unix timestamp (rather than
the ISO-8601 string the Plan 2.8 archive normally writes) fell through to an
empty ``run_date`` and the whole row was silently dropped — even though
``compute._parse_history_lines`` already tolerates numeric ``captured_at``.

The two sibling findings from the same review are handled separately:
``metrics._sanitize_name`` (leading digit) in PR #3191, and
``compute._signals_service_url_to_full`` (double endpoint) on the dedicated
branch ``fix/signals-service-url-idempotent-endpoint``.
"""
from __future__ import annotations

from typing import Any

import pytest


def _snapshot(captured_at: object) -> dict[str, Any]:
    return {
        "captured_at": captured_at,
        "per_tf": {
            "5m": {
                "n_events": 10,
                "hit_rate": 0.5,
                "families": {"fvg": {"n_events": 10, "hit_rate": 0.5}},
            }
        },
    }


def test_experiment_history_keeps_numeric_captured_at(monkeypatch: pytest.MonkeyPatch) -> None:
    import services.live_overlay_daemon.compute as compute_mod
    from services.live_overlay_daemon.metrics import _experiment_history

    monkeypatch.setattr(
        compute_mod, "_load_experiment_history", lambda: [_snapshot(1700000000)]
    )
    rows = _experiment_history()
    assert len(rows) == 1, f"numeric captured_at produced {len(rows)} rows: {rows}"
    assert rows[0]["run_date"] == "2023-11-14"


def test_experiment_history_keeps_iso_captured_at(monkeypatch: pytest.MonkeyPatch) -> None:
    import services.live_overlay_daemon.compute as compute_mod
    from services.live_overlay_daemon.metrics import _experiment_history

    monkeypatch.setattr(
        compute_mod,
        "_load_experiment_history",
        lambda: [_snapshot("2026-04-21T07:35:12Z")],
    )
    rows = _experiment_history()
    assert len(rows) == 1
    assert rows[0]["run_date"] == "2026-04-21"


def test_experiment_history_run_date_helper() -> None:
    from services.live_overlay_daemon.metrics import _experiment_history_run_date

    assert _experiment_history_run_date("2026-04-21T00:00:00Z") == "2026-04-21"
    assert _experiment_history_run_date(1700000000) == "2023-11-14"
    # Out-of-contract / junk inputs never raise and never yield a bogus date.
    assert _experiment_history_run_date(True) == ""
    assert _experiment_history_run_date(float("nan")) == ""
    assert _experiment_history_run_date(-1) == ""
    assert _experiment_history_run_date(None) == ""
