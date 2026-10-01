"""Der Urteiler fuer #5586 liest die ausgegebene Produkt-Annotation.

Korpus: das echte Job-Log der Sonde vom 2026-10-01 (Lauf 36827349579, Job
110255904403) — ein Lauf VOR dem Merge, also ohne Produkt-Zeile.
"""
from __future__ import annotations

from scripts.proof_judges import corpus_for, load_judge
from scripts.proof_ledger import load_entries

_JUDGE = "freshness_product_row"
_PRE_MERGE_RUN = "110255904403"
_ROW = "product:docs/calibration/gates/track_record_gate_*.json"


def _entry():
    return next(e for e in load_entries() if e.judge == _JUDGE)


def _judge(log: str):
    return load_judge(_JUDGE).judge({"log": log}, _entry())


def _real_log() -> str:
    corpus = dict(corpus_for(_JUDGE))
    assert set(corpus) == {_PRE_MERGE_RUN}, sorted(corpus)
    return corpus[_PRE_MERGE_RUN]["log"]


def test_the_recorded_pre_merge_run_is_pending_not_passed() -> None:
    log = _real_log()
    # Positivkontrolle: das Log ist ein echter Sonden-Lauf mit Annotationen …
    assert "##[error]smc-library-refresh.yml: STALE" in log
    assert "##[notice]promotion-gate-daily.yml: fresh" in log
    # … nur eben ohne die neue Zeile.
    verdict = _judge(log)
    assert (verdict.state, verdict.branch) == ("STEHT_AUS", "zeile_fehlt")


def test_the_version_probe_is_absent_from_the_pre_merge_log() -> None:
    assert _entry().version_probe not in _real_log()


def test_an_evaluated_row_is_a_pass_whatever_it_found() -> None:
    """Welcher Befund, entscheidet der Monitor — bewiesen wird die Auswertung."""
    base = _real_log()
    for emitted in (
        f"##[notice]{_ROW}: fresh (30.5h ago)",
        f"##[warning]{_ROW}: stale as DECLARED -- stale as declared (known incident); "
        "expectation expires 2026-10-08",
        f"##[error]{_ROW}: STALE -- last success 750.5h ago, budget 72.0h",
    ):
        verdict = _judge(f"{base}\n2026-10-02T06:55:22.9Z {emitted}\n")
        assert (verdict.state, verdict.branch) == ("PASS", "zeile_ausgewertet"), emitted


def test_a_row_that_sees_nothing_is_a_fail() -> None:
    verdict = _judge(
        f"{_real_log()}\n2026-10-02T06:55:22.9Z ##[error]{_ROW}: MISSING -- "
        "no dated file matches the pattern in the checkout\n"
    )
    assert (verdict.state, verdict.branch) == ("FAIL", "muster_findet_nichts")


def test_the_run_block_echo_cannot_impersonate_the_row() -> None:
    """Der Runner druckt den run-Block; dort steht die Zeile als --product "docs/…"."""
    echoed = (
        '2026-10-02T06:55:01.0Z \x1b[36;1m  --product "docs/calibration/gates/'
        'track_record_gate_*.json=72:weekday:expected-stale-until=2026-10-08"\x1b[0m\n'
    )
    verdict = _judge(_real_log() + echoed)
    assert (verdict.state, verdict.branch) == ("STEHT_AUS", "zeile_fehlt")


def test_an_empty_log_cannot_testify() -> None:
    verdict = _judge("")
    assert (verdict.state, verdict.branch) == ("KANN_NICHT_BEZEUGEN", "kein_log")
