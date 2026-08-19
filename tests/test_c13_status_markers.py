"""Der Marker-Konsument (#4848 Review-Punkt #4): 10 Schreiber, jetzt 1 Leser-Kette.

Bis 19.8. war von zehn ``.<agent>_status_<DATE>``-Markern genau einer gelesen
(Flatten -> Reconcile, #4858); der DEGRADED-Reconcile vom 18.8. (TWS down,
Connection refused 7497) blieb unsichtbar. Diese Tests pinnen die neue Kette:
emit (Workstation, sanitisiert) -> data-branch -> check (Daily-Cron, rc ->
Issue-Opener). Beide Kasing-Konventionen der Schreiber sind Population
(SUCCESS/DEGRADED via _write_marker, ok:/degraded: im Push-Helper).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.c13_status_markers import check, collect_markers, emit, main

_TS = "2026-08-18T21:05:04Z"


def _write_marker(live_dir: Path, agent: str, date: str, content: str) -> None:
    (live_dir / f".{agent}_status_{date}").write_text(content, encoding="utf-8")


@pytest.fixture()
def live_dir(tmp_path: Path) -> Path:
    d = tmp_path / "live"
    d.mkdir()
    _write_marker(
        d,
        "reconcile",
        "2026-08-18",
        f"DEGRADED:portfolio-after-failed:path=/Users/op/x/cache/live/portfolio_after.json:{_TS}\n",
    )
    _write_marker(d, "eod_flatten", "2026-08-18", f"SUCCESS:flattened=5:{_TS}\n")
    _write_marker(d, "audit_push", "2026-08-18", f"degraded:no-audit-file:{_TS}\n")
    _write_marker(d, "audit_push", "2026-08-17", f"ok:pushed:{_TS}\n")
    _write_marker(d, "phase_a", "2026-08-10", f"SUCCESS:done:{_TS}\n")  # ausserhalb Fenster
    (d / "incubation_2026-08-18.jsonl").write_text("{}\n", encoding="utf-8")  # kein Marker
    return d


def test_collect_parses_both_conventions_and_windows(live_dir: Path) -> None:
    rows = collect_markers(live_dir, date="2026-08-18", days_back=3)

    assert [(r["agent"], r["date"], r["kind"]) for r in rows] == [
        ("audit_push", "2026-08-17", "ok"),
        ("audit_push", "2026-08-18", "degraded"),
        ("eod_flatten", "2026-08-18", "SUCCESS"),
        ("reconcile", "2026-08-18", "DEGRADED"),
    ]
    reconcile = rows[-1]
    assert reconcile["ts"] == _TS
    # Die Nachricht darf Doppelpunkte enthalten und wird pfad-sanitisiert:
    # absolute Pfade verlassen die Workstation nur als Basename.
    assert "/Users/" not in reconcile["message"]
    assert "portfolio_after.json" in reconcile["message"]


def test_emit_writes_schema_and_is_deterministic(live_dir: Path, tmp_path: Path) -> None:
    out = tmp_path / "summary.json"
    emit(live_dir, date="2026-08-18", days_back=3, output=out)
    first = out.read_bytes()
    emit(live_dir, date="2026-08-18", days_back=3, output=out)

    assert out.read_bytes() == first
    data = json.loads(first)
    assert data["schema_version"] == 1
    assert data["window_end"] == "2026-08-18"
    assert len(data["markers"]) == 4


def _summary(tmp_path: Path, markers: list[dict]) -> Path:
    p = tmp_path / "s.json"
    p.write_text(
        json.dumps({"schema_version": 1, "window_end": "x", "window_days": 3, "markers": markers}),
        encoding="utf-8",
    )
    return p


def test_check_alarms_on_any_non_green_marker(live_dir: Path, tmp_path: Path) -> None:
    out = tmp_path / "summary.json"
    emit(live_dir, date="2026-08-18", days_back=3, output=out)

    # 18.8. traegt DEGRADED (reconcile + audit_push) -> rot.
    assert check(out, date="2026-08-18") == 1
    # Am 19.8. zaehlt der Vortag mit -> immer noch rot: still ist maximal 1 Tag.
    assert check(out, date="2026-08-19") == 1
    # Am 20.8. liegt nichts mehr im Fenster -> weich gruen (Wochenend-Semantik).
    assert check(out, date="2026-08-20") == 0


def test_check_green_when_all_markers_ok(tmp_path: Path) -> None:
    p = _summary(
        tmp_path,
        [
            {"agent": "reconcile", "date": "2026-08-18", "kind": "SUCCESS", "message": "", "ts": _TS},
            {"agent": "audit_push", "date": "2026-08-18", "kind": "ok", "message": "", "ts": _TS},
        ],
    )
    assert check(p, date="2026-08-18") == 0


def test_check_fails_closed_on_unknown_kind(tmp_path: Path) -> None:
    p = _summary(
        tmp_path,
        [{"agent": "reconcile", "date": "2026-08-18", "kind": "PARTIAL", "message": "", "ts": _TS}],
    )
    assert check(p, date="2026-08-18") == 1


def test_check_missing_summary_is_soft(tmp_path: Path) -> None:
    assert check(tmp_path / "fehlt.json", date="2026-08-18") == 0


def test_cli_emit_then_check_roundtrip(live_dir: Path, tmp_path: Path) -> None:
    out = tmp_path / "summary.json"
    rc_emit = main(
        [
            "emit",
            "--live-dir", str(live_dir),
            "--date", "2026-08-18",
            "--days-back", "3",
            "--output", str(out),
        ]
    )
    rc_check = main(["check", "--summary", str(out), "--date", "2026-08-18"])

    assert rc_emit == 0
    assert rc_check == 1


def test_workflow_wires_check_into_the_issue_gate() -> None:
    """Der Konsument existiert nur, wenn der Cron ihn AUFRUFT und der
    Issue-Opener seinen rc liest — beide Kanten als Aufruf-Form gepinnt."""
    source = (
        Path(__file__).resolve().parents[1] / ".github" / "workflows" / "c13-daily-cron.yml"
    ).read_text(encoding="utf-8")

    assert "python -m scripts.c13_status_markers check" in source
    assert '--summary "${LIVE_DIR}/c13_status_markers.json"' in source
    # Anker ist die Step-DEFINITION, nicht die Phrase: sie steht wortgleich
    # auch in einem Kommentar des F-V3-15-Steps weiter oben (Kommentar-Falle,
    # dritter Treffer dieser Klasse in dieser Woche).
    gate = source.split("- name: Open issue if any required step failed", 1)[1]
    assert "steps.status_markers.outputs.rc != '0'" in gate.split("run:", 1)[0]


def test_audit_push_emits_and_ships_the_summary() -> None:
    source = (
        Path(__file__).resolve().parents[1] / "automation" / "launchd" / "run-c13-audit-push.sh"
    ).read_text(encoding="utf-8")

    assert "-m scripts.c13_status_markers emit" in source
    push_call = source.split("push_to_data_branch \\", 1)[1]
    assert '"${MARKERS_SUMMARY}"' in push_call
