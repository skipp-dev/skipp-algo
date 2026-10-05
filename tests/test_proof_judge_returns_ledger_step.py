"""Der Urteiler fuer den Ledger-Schritt liest die Zeile, die das Skript druckt.

Korpus, beides echte Job-Logs von ``promotion-gate-daily``:

* ``106472364384`` — Lauf 35641718088 (2026-09-21), der eine produzierende
  Lauf seit dem 31.8., VOR dem Merge und also ohne Ledger-Schritt;
* ``110528686974`` — Lauf 36909606203 (2026-10-01), der erste Lauf MIT
  Ledger-Schritt: der Zeuge, auf dem der PASS des Eintrags steht.

Die beiden Zeilen fuer den PASS-Fall sind nicht erfunden: so druckte sie das
Skript, als der Schritt am 2026-10-01 lokal gegen den echten Pool vom 30.9.
lief.
"""
from __future__ import annotations

from scripts.proof_judges import corpus_for, load_judge
from scripts.proof_ledger import load_entries

_JUDGE = "returns_ledger_step"
_PRE_MERGE_RUN = "106472364384"
_WITNESS_RUN = "110528686974"
_LINE_1D = (
    "returns ledger 1D: pool 19/6245 events on plane, 19 closed trades observed, "
    "19 new, 0 contradicted, ledger now 19 (BOS:7, OB:4, SWEEP:8)"
)
_LINE_15M = (
    "returns ledger 15m: pool 740/6245 events on plane, 551 closed trades observed, "
    "551 new, 0 contradicted, ledger now 551 (BOS:185, FVG:126, OB:85, SWEEP:155)"
)


def _entry():
    return next(e for e in load_entries() if e.judge == _JUDGE)


def _judge(log: str):
    return load_judge(_JUDGE).judge({"log": log}, _entry())


def _corpus() -> dict[str, dict]:
    corpus = dict(corpus_for(_JUDGE))
    assert set(corpus) == {_PRE_MERGE_RUN, _WITNESS_RUN}, sorted(corpus)
    return corpus


def _real_log() -> str:
    return _corpus()[_PRE_MERGE_RUN]["log"]


def test_the_first_real_ledger_run_is_the_pass() -> None:
    verdict = _judge(_corpus()[_WITNESS_RUN]["log"])
    assert (verdict.state, verdict.branch) == ("PASS", "ledger_geschrieben")
    assert verdict.detail == "1D: 30 Zeilen; 15m: 634 Zeilen"


def test_the_echoed_refusal_in_a_clean_run_is_not_a_refusal() -> None:
    """Regression 2026-10-01: der Urteiler las Text statt der ausgegebenen Zeile.

    Der run-Block des Schritts steht in JEDEM Log, samt
    ``echo "::error …::… the events pool is gone"``. Die erste Fassung fand
    darin eine Verweigerung und urteilte den fehlerfreien ersten Lauf als FAIL.
    """
    log = _corpus()[_WITNESS_RUN]["log"]
    assert "the events pool is gone" in log  # das Echo ist da …
    assert "##[error]gates step reported produced=true" not in log  # … die Ausgabe nicht
    verdict = _judge(log)
    assert verdict.state == "PASS"


def test_an_emitted_pool_refusal_is_a_fail() -> None:
    emitted = (
        "2026-10-02T14:03:01Z ##[error]gates step reported produced=true "
        "but the events pool is gone\n"
    )
    verdict = _judge(_real_log() + emitted)
    assert (verdict.state, verdict.branch) == ("FAIL", "ledger_unvollstaendig")


def test_the_recorded_pre_merge_run_is_pending_not_passed() -> None:
    log = _real_log()
    # Positivkontrolle: der Lauf HAT produziert (der Schritt davor lief) …
    assert "wrote docs/calibration/gates/returns_series_2026-09-21.json" in log
    # … nur gab es den Ledger-Schritt noch nicht.
    verdict = _judge(log)
    assert (verdict.state, verdict.branch) == ("STEHT_AUS", "schritt_lief_nicht")
    assert _entry().version_probe not in log


def test_both_plane_lines_are_a_pass() -> None:
    verdict = _judge(f"{_real_log()}\n2026-10-02T14:03:01Z {_LINE_1D}\n2026-10-02T14:03:02Z {_LINE_15M}\n")
    assert (verdict.state, verdict.branch) == ("PASS", "ledger_geschrieben")
    assert verdict.detail == "1D: 19 Zeilen; 15m: 551 Zeilen"


def test_one_plane_alone_is_a_fail() -> None:
    for line in (_LINE_1D, _LINE_15M):
        verdict = _judge(f"{_real_log()}\n2026-10-02T14:03:01Z {line}\n")
        assert (verdict.state, verdict.branch) == ("FAIL", "ledger_unvollstaendig"), line


def test_a_refused_ledger_is_a_fail_even_with_the_other_plane_written() -> None:
    refusal = (
        "error: docs/calibration/gates/ledger/returns_ledger_15m.jsonl holds rows under "
        "[\"('touch_then_horizon_close', 5.0)\"], this run uses ('touch_then_horizon_close', 7.0). "
        "A ledger carries ONE trade definition; start a new file for a new rule or cost."
    )
    verdict = _judge(f"{_real_log()}\n2026-10-02T14:03:01Z {_LINE_1D}\n2026-10-02T14:03:02Z {refusal}\n")
    assert (verdict.state, verdict.branch) == ("FAIL", "ledger_unvollstaendig")


def test_the_run_block_echo_cannot_impersonate_the_line() -> None:
    echoed = (
        "2026-10-02T14:02:59Z \x1b[36;1m  python -m scripts.accumulate_returns_ledger \\\x1b[0m\n"
        '2026-10-02T14:02:59Z \x1b[36;1m    --ledger "${LEDGER_DIR}/returns_ledger_${PLANE}.jsonl" \\\x1b[0m\n'
    )
    verdict = _judge(_real_log() + echoed)
    assert (verdict.state, verdict.branch) == ("STEHT_AUS", "schritt_lief_nicht")


def test_an_empty_log_cannot_testify() -> None:
    verdict = _judge("")
    assert (verdict.state, verdict.branch) == ("KANN_NICHT_BEZEUGEN", "kein_log")
