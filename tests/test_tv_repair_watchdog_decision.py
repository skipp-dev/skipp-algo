"""Die Entscheidung des Waechters, ausserhalb des Browsers und einzeln beweisbar."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from scripts import tv_repair_watchdog_decision as cli_module
from scripts.tv_repair_watchdog_decision import DAILY_DISPATCH_CAP, decide


def _snapshot(mode: str = "verify-only", mismatches: int = 0) -> dict:
    return {
        "executionMode": mode,
        "bindings": {
            "checkedConsumers": 10,
            "consumers": [
                {"scriptName": "SMC Setup Check", "mismatches": [{"label": "BUS Armed"}] * mismatches},
            ],
        },
    }


def test_drift_in_a_verify_snapshot_triggers_a_repair() -> None:
    decision = decide(_snapshot(mismatches=1), dispatches_today=0)
    assert decision.dispatch is True
    assert "mismatch" in decision.reason.lower()


def test_a_clean_snapshot_triggers_nothing() -> None:
    assert decide(_snapshot(mismatches=0), dispatches_today=0).dispatch is False


def test_a_repair_snapshot_never_triggers_another_repair() -> None:
    """Schleifenschutz ueber eine Tatsache im Artefakt, nicht ueber Herkunft."""
    decision = decide(_snapshot(mode="repair-only", mismatches=1), dispatches_today=0)
    assert decision.dispatch is False
    assert "repair-only" in decision.reason


def test_a_write_snapshot_never_triggers_a_repair() -> None:
    assert decide(_snapshot(mode="write", mismatches=1), dispatches_today=0).dispatch is False


def test_the_cap_stops_dispatching_and_says_so() -> None:
    decision = decide(_snapshot(mismatches=1), dispatches_today=DAILY_DISPATCH_CAP)
    assert decision.dispatch is False
    assert str(DAILY_DISPATCH_CAP) in decision.reason
    assert "operator" in decision.reason.lower(), (
        "ein Regelkreis, der aufgibt, muss lauter sein als einer, der arbeitet"
    )


def test_a_repair_already_in_flight_blocks_a_second_one() -> None:
    """Kein Stapeln: ein wartender Reparaturlauf genuegt.

    Der Deckel allein reicht dafuer nicht — drei Laeufe duerften sich sonst
    gleichzeitig um denselben Warteplatz der Session-Gruppe draengen.
    """
    decision = decide(_snapshot(mismatches=1), dispatches_today=0, repair_in_flight=True)
    assert decision.dispatch is False
    assert "flight" in decision.reason.lower() or "wartet" in decision.reason.lower()


def test_an_empty_observation_is_not_green() -> None:
    """checkedConsumers=0 heisst UNBEKANNT, nicht sauber."""
    empty = _snapshot(mismatches=0)
    empty["bindings"]["checkedConsumers"] = 0
    empty["bindings"]["consumers"] = []
    decision = decide(empty, dispatches_today=0)
    assert decision.dispatch is False
    assert "leer" in decision.reason.lower() or "empty" in decision.reason.lower()


@pytest.mark.parametrize("missing", ["executionMode", "bindings"])
def test_a_malformed_snapshot_refuses_rather_than_guesses(missing: str) -> None:
    broken = _snapshot(mismatches=1)
    del broken[missing]
    decision = decide(broken, dispatches_today=0)
    assert decision.dispatch is False


def test_a_top_level_list_snapshot_refuses_rather_than_crashes() -> None:
    """Syntaktisch gueltiges JSON (eine Liste), aber kein Objekt — kein Wurf."""
    decision = decide([], dispatches_today=0)
    assert decision.dispatch is False
    assert "kein objekt" in decision.reason.lower()


def test_a_non_dict_consumer_entry_refuses_rather_than_crashes() -> None:
    """Ein Konsumenten-Eintrag, der kein Objekt ist, darf nicht werfen."""
    broken = _snapshot(mismatches=0)
    broken["bindings"]["consumers"] = ["not-a-dict"]
    decision = decide(broken, dispatches_today=0)
    assert decision.dispatch is False
    assert "konsument" in decision.reason.lower()


def test_a_string_checked_consumers_count_is_treated_as_unknown() -> None:
    """Ein String '0' ist in Python truthy — muss trotzdem als UNBEKANNT gelten."""
    broken = _snapshot(mismatches=1)
    broken["bindings"]["checkedConsumers"] = "0"
    decision = decide(broken, dispatches_today=0)
    assert decision.dispatch is False
    assert (
        "leer" in decision.reason.lower()
        or "unbekannt" in decision.reason.lower()
        or "unklar" in decision.reason.lower()
    )


def test_cli_never_crashes_on_a_malformed_snapshot_and_still_writes_a_reason(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Pinnt exakt den vom Review reproduzierten Vertragsbruch: exit 0 + reason=.

    Vorher stuerzte decide() bei ``echo '[]' > snap.json`` mit AttributeError
    ab (Exit != 0, kein reason= in $GITHUB_OUTPUT) — genau der Vertragsbruch,
    den kein bisheriger Test abdeckte.
    """
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text("[]", encoding="utf-8")
    output_path = tmp_path / "github_output.txt"

    monkeypatch.setenv("GITHUB_OUTPUT", str(output_path))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "tv_repair_watchdog_decision.py",
            "--snapshot",
            str(snapshot_path),
            "--dispatches-today",
            "0",
        ],
    )

    exit_code = cli_module.main()

    assert exit_code == 0
    payload = output_path.read_text(encoding="utf-8")
    assert "dispatch=false" in payload
    assert "reason=" in payload
