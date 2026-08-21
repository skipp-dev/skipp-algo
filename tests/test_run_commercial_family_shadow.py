"""Tests for the broker-free commercial-family shadow orchestrator."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from scripts.run_commercial_family_shadow import main, run_shadow_once

_ANCHOR = 1_800_000_000.0
_BAR_CLOSE = _ANCHOR + 900.0  # 2026-08-19: source_asof_ts = Bar-CLOSE; now-Fixtures leben in der Close-Welt, relative Alter bleiben identisch
_NOW = datetime.fromtimestamp(_BAR_CLOSE, UTC)


def _payload() -> dict:
    return {
        "as_of": _ANCHOR,
        "bars": [
            {
                "timestamp": _ANCHOR,
                "open": 100.0,
                "high": 103.0,
                "low": 98.0,
                "close": 102.0,
            }
        ],
        "structure": {
            "bos": [
                {
                    "id": "bos-1",
                    "time": _ANCHOR,
                    "price": 102.0,
                    "dir": "UP",
                }
            ],
            "orderblocks": [
                {
                    "id": "ob-1",
                    "anchor_ts": _ANCHOR,
                    "low": 98.0,
                    "high": 100.0,
                    "dir": "BULL",
                    "valid": True,
                }
            ],
            "fvg": [
                {
                    "id": "fvg-1",
                    "anchor_ts": _ANCHOR,
                    "low": 100.0,
                    "high": 101.0,
                    "dir": "BULL",
                    "valid": True,
                }
            ],
            "liquidity_sweeps": [
                {
                    "id": "sweep-1",
                    "time": _ANCHOR,
                    "price": 99.0,
                    "side": "SELL_SIDE",
                }
            ],
        },
        "provenance": {
            "symbol": "AAPL",
            "timeframe": "15m",
            "source": "databento",
            "dataset": "XNAS.ITCH",
        },
    }


def _paths(tmp_path: Path) -> dict:
    return {
        "setups_path": tmp_path / "setups.json",
        "gate_status_path": tmp_path / "gates.json",
        "diagnostics_path": tmp_path / "diagnostics.json",
        "audit_path": tmp_path / "audit.jsonl",
        "manifest_path": tmp_path / "manifest.json",
    }


def _audit(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _payload_spanning_midnight() -> tuple[dict, float, float]:
    """Ein 15-Minuten-Bar quer ueber die UTC-Datumsgrenze: OPEN 23:52Z, CLOSE 00:07Z."""
    open_ts = datetime(2027, 1, 14, 23, 52, 0, tzinfo=UTC).timestamp()
    close_ts = open_ts + 900.0
    payload = _payload()
    payload["as_of"] = open_ts
    payload["bars"][0]["timestamp"] = open_ts
    for gruppe, feld in (
        ("bos", "time"),
        ("orderblocks", "anchor_ts"),
        ("fvg", "anchor_ts"),
        ("liquidity_sweeps", "time"),
    ):
        payload["structure"][gruppe][0][feld] = open_ts
    return payload, open_ts, close_ts


def test_a_bar_spanning_midnight_is_refused(tmp_path: Path) -> None:
    """Handelstag und Frische kommen von VERSCHIEDENEN Enden desselben Bars.

    ``run_commercial_family_shadow`` leitet den Handelstag aus ``payload["as_of"]``
    ab, also aus dem Bar-**OPEN**::

        trade_date = source_asof.date().isoformat()

    Die Wissenszeit dagegen ist der Bar-**CLOSE** (``payload_knowledge_ts``, seit
    #4870 -- Databento stempelt ``ts_event`` am OPEN, gewusst hat man es erst am
    CLOSE). Solange beide Enden auf denselben UTC-Tag fallen, faellt das nicht auf.
    Ueberspannt ein Bar Mitternacht, fallen sie auseinander, und
    ``_validate_prospective_commercial_setups`` in ``run_smc_live_incubation.py``
    lehnt den Batch mit einem ``ValueError`` ab. Das Verhalten ist LAUT, nicht still
    -- und genau das haelt dieser Test fest.

    **Warum es diesen Test gibt (2026-08-21).** Bis dahin lebte dieses Wissen
    ausschliesslich als Ausweichzweig in zwei CLI-Tests: die borgten sich die Uhr
    (``datetime.now(UTC) - 901``) und schoben den Bar im Mitternachtsfenster um
    1800 s in den Vortag. Der Zweig verhinderte nichts, er WICH aus -- und alterte
    dabei die Quelle so weit, dass er ``test_cli_is_local_only_and_writes_campaign_report``
    taeglich von 00:01Z bis 00:15Z rot machte (15 von 1440 Minuten, gemessen ueber
    alle Minuten eines Tages; ausserhalb war die Quelle 1 s alt, drinnen 1801 s
    gegen eine 300-s-Schwelle). Die Uhren sind jetzt gepinnt und die Zweige weg --
    das Wissen darf deshalb nicht mit ihnen verschwinden.

    **Aendert jemand das Verhalten absichtlich** -- etwa auf "Bar wird auf den
    OPEN-Tag gebucht, Wissenszeit hin oder her" --, dann roetet dieser Test und
    verlangt eine Entscheidung statt eines stillen Wechsels. Das ist eine Aussage
    ueber die Tagesrisiko-Buchfuehrung (``AccountState(as_of=...)`` haengt am
    Handelstag), nicht ueber einen Test.
    """
    payload, open_ts, close_ts = _payload_spanning_midnight()
    assert (
        datetime.fromtimestamp(open_ts, UTC).date()
        != datetime.fromtimestamp(close_ts, UTC).date()
    ), "Positivkontrolle: die Fixture ueberspannt die Datumsgrenze gar nicht"

    with pytest.raises(ValueError) as excinfo:
        run_shadow_once(
            payload=payload,
            now=datetime.fromtimestamp(close_ts + 1.0, UTC),
            **_paths(tmp_path),
        )

    meldung = str(excinfo.value)
    assert "trade_date" in meldung and "source_asof_ts" in meldung, (
        "die Ablehnung nennt ihren Grund nicht mehr -- ohne beide Namen kann der "
        f"naechste Leser die Mitternachts-Ursache nicht erkennen: {meldung!r}"
    )


def test_the_same_bar_one_hour_later_is_accepted(tmp_path: Path) -> None:
    """Gegenprobe: nicht die Fixture ist kaputt, sondern die Datumsgrenze entscheidet.

    Ohne diese Gegenprobe koennte der Test oben auch dann gruen sein, wenn die
    Fixture aus einem voellig anderen Grund abgelehnt wird -- und wuerde eine
    Ablehnung feiern, die mit Mitternacht nichts zu tun hat.
    """
    payload, open_ts, close_ts = _payload_spanning_midnight()
    versatz = 3600.0  # derselbe Bar, eine Stunde spaeter: beide Enden am 15.1.
    payload["as_of"] = open_ts + versatz
    payload["bars"][0]["timestamp"] = open_ts + versatz
    for gruppe, feld in (
        ("bos", "time"),
        ("orderblocks", "anchor_ts"),
        ("fvg", "anchor_ts"),
        ("liquidity_sweeps", "time"),
    ):
        payload["structure"][gruppe][0][feld] = open_ts + versatz
    assert (
        datetime.fromtimestamp(open_ts + versatz, UTC).date()
        == datetime.fromtimestamp(close_ts + versatz, UTC).date()
    )

    manifest = run_shadow_once(
        payload=payload,
        now=datetime.fromtimestamp(close_ts + versatz + 1.0, UTC),
        **_paths(tmp_path),
    )
    assert manifest["broker_io"] is False


def test_run_writes_one_complete_audit_only_snapshot(tmp_path: Path) -> None:
    paths = _paths(tmp_path)

    manifest = run_shadow_once(payload=_payload(), now=_NOW, **paths)

    assert manifest["status"] == "COMPLETED"
    assert manifest["broker_io"] is False
    assert manifest["network_io"] is False
    assert manifest["paper_orders_placed"] == 0
    rows = _audit(paths["audit_path"])
    assert len(rows) == 4
    assert {row["action"] for row in rows} == {"audit_only"}
    assert {row["source_snapshot_id"] for row in rows} == {manifest["source_snapshot_id"]}
    assert len(json.loads(paths["setups_path"].read_text(encoding="utf-8"))) == 4


def test_shadow_never_invokes_broker_order_placement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden_broker_call(*_args, **_kwargs):
        raise AssertionError("broker placement must be unreachable from shadow mode")

    monkeypatch.setattr(
        "scripts.run_smc_live_incubation.place_order_intents",
        forbidden_broker_call,
    )

    manifest = run_shadow_once(payload=_payload(), now=_NOW, **_paths(tmp_path))

    assert manifest["status"] == "COMPLETED"
    assert manifest["paper_orders_placed"] == 0


def test_restart_after_audit_repairs_manifest_without_duplicate_rows(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    first = run_shadow_once(payload=_payload(), now=_NOW, **paths)
    paths["manifest_path"].unlink()

    replay = run_shadow_once(payload=_payload(), now=_NOW, **paths)

    assert first["status"] == "COMPLETED"
    assert replay["status"] == "REPLAY_SKIPPED"
    assert len(_audit(paths["audit_path"])) == 4
    assert json.loads(paths["manifest_path"].read_text(encoding="utf-8"))["status"] == "REPLAY_SKIPPED"


def test_partial_snapshot_audit_fails_closed(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    run_shadow_once(payload=_payload(), now=_NOW, **paths)
    [first, *_] = _audit(paths["audit_path"])
    paths["audit_path"].write_text(json.dumps(first) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="partial or inconsistent audit"):
        run_shadow_once(payload=_payload(), now=_NOW, **paths)


@pytest.mark.parametrize(
    "override",
    [
        {"quantity": 100},
        {"stop_buffer_bps": 20.0},
        {"rr_target": 3.0},
    ],
)
def test_same_snapshot_with_changed_decision_contract_fails_closed(
    tmp_path: Path,
    override: dict,
) -> None:
    paths = _paths(tmp_path)
    run_shadow_once(payload=_payload(), now=_NOW, **paths)

    with pytest.raises(ValueError, match="partial or inconsistent audit"):
        run_shadow_once(payload=_payload(), now=_NOW, **override, **paths)


def test_fresh_lock_rejects_concurrent_run(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    lock_path = tmp_path / "shadow.lock"
    lock_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "token": "another-run",
                "pid": 123,
                "created_at_ts": datetime.now(UTC).timestamp(),
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="already locked"):
        run_shadow_once(
            payload=_payload(),
            now=_NOW,
            lock_path=lock_path,
            **paths,
        )


def test_stale_lock_is_recovered(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    lock_path = tmp_path / "shadow.lock"
    lock_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "token": "dead-run",
                "pid": 123,
                "created_at_ts": 1.0,
            }
        ),
        encoding="utf-8",
    )

    manifest = run_shadow_once(
        payload=_payload(),
        now=_NOW,
        lock_path=lock_path,
        **paths,
    )

    assert manifest["status"] == "COMPLETED"
    assert not lock_path.exists()


def test_no_setup_snapshot_is_recorded_without_creating_audit(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    payload = _payload()
    payload["structure"] = {
        "bos": [],
        "orderblocks": [],
        "fvg": [],
        "liquidity_sweeps": [],
    }

    manifest = run_shadow_once(payload=payload, now=_NOW, **paths)

    assert manifest["status"] == "NO_SETUPS"
    assert not paths["audit_path"].exists()


def test_cli_has_no_broker_or_network_switch(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    source = tmp_path / "input.json"
    # 2026-08-21: Uhr gepinnt statt geborgt. Vorher stand hier
    # `datetime.now(UTC) - 901` mit einem Mitternachts-Ausweichzweig, der den Bar um
    # 1800 s in den Vortag schob. Der Zweig pruefte die Datumsgrenze nicht, er wich
    # ihr aus -- und alterte dabei die Quelle. Beim Geschwister-CLI-Test
    # (Kampagne) machte genau das den Lauf taeglich 00:01Z-00:15Z rot. Die Grenze
    # selbst hat jetzt einen eigenen Test: test_a_bar_spanning_midnight_is_refused.
    payload = _payload()
    source.write_text(json.dumps(payload), encoding="utf-8")

    rc = main(
        [
            "--input",
            str(source),
            "--setups-output",
            str(paths["setups_path"]),
            "--gate-status-output",
            str(paths["gate_status_path"]),
            "--diagnostics-output",
            str(paths["diagnostics_path"]),
            "--audit-output",
            str(paths["audit_path"]),
            "--manifest-output",
            str(paths["manifest_path"]),
            "--max-setup-age-seconds",
            "999999999",
        ],
        now=_NOW,
    )

    assert rc == 0
    manifest = json.loads(paths["manifest_path"].read_text(encoding="utf-8"))
    assert manifest["broker_io"] is False
    assert manifest["network_io"] is False
