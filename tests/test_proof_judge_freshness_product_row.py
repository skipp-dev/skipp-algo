"""Der Urteiler fuer #5586 liest die ausgegebene Produkt-Annotation.

Korpus, beides echte Job-Logs der Sonde vom 2026-10-01:

* ``110255904403`` — Lauf 36827349579 (06:55 UTC), VOR dem Merge, ohne
  Produkt-Zeile;
* ``110446234362`` — Lauf 36885087891 (15:32 UTC), NACH dem Merge: die Zeile
  ist ausgewertet und meldet den deklariert alten Gate-Bericht.
"""
from __future__ import annotations

from scripts.proof_judges import corpus_for, load_judge
from scripts.proof_ledger import load_entries

_JUDGE = "freshness_product_row"
_PRE_MERGE_RUN = "110255904403"
_POST_MERGE_RUN = "110446234362"
_ROW = "product:docs/calibration/gates/track_record_gate_*.json"


def _entry():
    return next(e for e in load_entries() if e.judge == _JUDGE)


def _judge(log: str):
    return load_judge(_JUDGE).judge({"log": log}, _entry())


def _corpus() -> dict[str, dict]:
    corpus = dict(corpus_for(_JUDGE))
    assert set(corpus) == {_PRE_MERGE_RUN, _POST_MERGE_RUN}, sorted(corpus)
    return corpus


def _real_log() -> str:
    return _corpus()[_PRE_MERGE_RUN]["log"]


def test_the_recorded_post_merge_run_is_the_pass() -> None:
    """Der Zeuge, auf dem der PASS des Eintrags steht.

    Der Lauf endete ``failure`` (andere Zeilen sind ueberfaellig) — der
    Urteiler liest den Inhalt, nicht die Conclusion.
    """
    log = _corpus()[_POST_MERGE_RUN]["log"]
    assert "##[error]probe rc=2 overall=stale" in log
    verdict = _judge(log)
    assert (verdict.state, verdict.branch) == ("PASS", "zeile_ausgewertet")
    assert "stale as DECLARED" in verdict.detail
    assert "expectation expires 2026-10-08" in verdict.detail


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


# --- 2026-10-02: the row moved from the verdict file to the returns series ---


def _series_entry():
    entries = [e for e in load_entries() if e.judge == _JUDGE and "returns_series_" in e.version_probe]
    assert len(entries) == 1, [e.id for e in entries]
    return entries[0]


_SERIES_ROW = (
    "2026-10-05T06:31:02.1000000Z ##[notice]product:docs/calibration/gates/returns_series_*.json: "
    "fresh (30.5h, budget 72h, newest returns_series_2026-10-02.json)\n"
)


def test_the_two_entries_witness_different_rows() -> None:
    first, second = _entry(), _series_entry()
    assert first.id == "5586" and second.id != first.id
    assert "track_record_gate_" in first.version_probe
    assert "returns_series_" in second.version_probe


def test_the_old_row_is_no_witness_for_the_new_entry() -> None:
    """The recorded run of 2026-10-01 evaluated the verdict-file row. For the
    entry about the series row that run predates the change."""
    judge = load_judge(_JUDGE).judge
    log = _corpus()[_POST_MERGE_RUN]["log"]
    assert (judge({"log": log}, _entry()).state, judge({"log": log}, _entry()).branch) == ("PASS", "zeile_ausgewertet")
    verdict = judge({"log": log}, _series_entry())
    assert (verdict.state, verdict.branch) == ("STEHT_AUS", "zeile_fehlt")


def test_the_series_row_is_the_pass_for_the_new_entry_only() -> None:
    judge = load_judge(_JUDGE).judge
    log = _real_log() + _SERIES_ROW
    verdict = judge({"log": log}, _series_entry())
    assert (verdict.state, verdict.branch) == ("PASS", "zeile_ausgewertet")
    assert "returns_series_2026-10-02.json" in verdict.detail
    # … and it cannot stand in for #5586's row.
    old = judge({"log": log}, _entry())
    assert (old.state, old.branch) == ("STEHT_AUS", "zeile_fehlt")


def test_a_series_row_that_sees_nothing_is_a_fail() -> None:
    log = _real_log() + (
        "2026-10-05T06:31:02.1000000Z ##[error]product:docs/calibration/gates/returns_series_*.json: "
        "MISSING (no dated file matches)\n"
    )
    verdict = load_judge(_JUDGE).judge({"log": log}, _series_entry())
    assert (verdict.state, verdict.branch) == ("FAIL", "muster_findet_nichts")
