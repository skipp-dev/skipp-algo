from __future__ import annotations

from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parents[1] / "scripts" / "grafana_dashboard_pullback.sh"
)


def test_pullback_updates_both_live_overlay_dashboards() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "smc-live-overlay-v1|services/live_overlay_daemon/infra/grafana/dashboard.json" in source
    assert (
        "smc-live-overlay-signals-v1|"
        "services/live_overlay_daemon/infra/grafana/dashboard-signals-experiments.json"
        in source
    )
    assert 'TMP_TARGET="$(mktemp "${TARGET}.tmp.XXXXXX")"' in source
    assert 'python scripts/update_overlay_dashboard.py "${TMP_TARGET}"' in source
    assert 'mv "${TMP_TARGET}" "${TARGET}"' in source
    assert 'rm -f "${TMP_TARGET}"' in source
    assert "for dashboard in" in source
