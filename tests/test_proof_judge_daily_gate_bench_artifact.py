"""Der Urteiler fuer #5584 liest die AUSGEGEBENE Zeile, nicht das Skript-Echo.

Beide Korpus-Logs sind echte Job-Logs von ``promotion-gate-daily``:

* ``106472364384`` — Lauf 35641718088 (2026-09-21), der einzige von 18 Laeufen
  seit dem 31.8., der sein Tagesartefakt fand;
* ``109923374032`` — Lauf 36726137478 (2026-09-30), einer der 17, die es nicht
  fanden und gruen uebersprangen.
"""
from __future__ import annotations

import re

from scripts.proof_judges import corpus_for, load_judge
from scripts.proof_ledger import load_entries

_JUDGE = "daily_gate_bench_artifact"
_FOUND_RUN = "106472364384"
_MISSING_RUN = "109923374032"


def _entry():
    return next(e for e in load_entries() if e.judge == _JUDGE)


def _corpus() -> dict[str, dict]:
    corpus = dict(corpus_for(_JUDGE))
    assert set(corpus) == {_FOUND_RUN, _MISSING_RUN}, sorted(corpus)
    return corpus


def test_the_run_that_found_its_artifact_is_a_pass() -> None:
    verdict = load_judge(_JUDGE).judge(_corpus()[_FOUND_RUN], _entry())
    assert (verdict.state, verdict.branch) == ("PASS", "tagesartefakt_gefunden")
    assert "smc-measurement-benchmark-rolling-2026-09-21 fetched from run 35620730221" in verdict.detail


def test_the_run_that_skipped_green_is_not_a_pass() -> None:
    verdict = load_judge(_JUDGE).judge(_corpus()[_MISSING_RUN], _entry())
    assert (verdict.state, verdict.branch) == ("PRUEFEN", "tagesartefakt_fehlt")


def test_both_logs_contain_the_fetched_text_as_script_echo() -> None:
    """Positivkontrolle fuer die Falle, gegen die der Urteiler gebaut ist.

    Der Runner druckt den run-Block in jedes Log. Wer nach dem TEXT sucht,
    findet ihn auch im Lauf vom 30.9., der nichts fand.
    """
    for run_id, evidence in _corpus().items():
        assert "fetched from run" in evidence["log"], run_id
        assert "${ART_NAME} fetched from run" in evidence["log"], run_id


def test_the_script_echo_alone_is_not_a_witness() -> None:
    """Das echte Fund-Log, um genau die AUSGEGEBENE Zeile gekuerzt."""
    log = _corpus()[_FOUND_RUN]["log"]
    emitted = re.compile(r"^.*##\[notice\]artifact smc-measurement-benchmark-rolling-.*$", re.MULTILINE)
    assert len(emitted.findall(log)) == 1
    without = emitted.sub("", log)
    assert "fetched from run" in without  # das Echo steht noch da
    verdict = load_judge(_JUDGE).judge({"log": without}, _entry())
    assert (verdict.state, verdict.branch) == ("STEHT_AUS", "download_nicht_erreicht")


def test_an_empty_log_cannot_testify() -> None:
    verdict = load_judge(_JUDGE).judge({"log": ""}, _entry())
    assert (verdict.state, verdict.branch) == ("KANN_NICHT_BEZEUGEN", "kein_log")


def test_no_bench_run_at_all_reads_like_a_missing_artifact() -> None:
    verdict = load_judge(_JUDGE).judge(
        {"log": "2026-10-02T14:00:10Z ##[warning]no recent completed rolling-bench run on main\n"},
        _entry(),
    )
    assert (verdict.state, verdict.branch) == ("PRUEFEN", "tagesartefakt_fehlt")
