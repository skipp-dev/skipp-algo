"""Der Urteiler fuer den Regel-Stempel liest die Zeile, die das Skript druckt.

Korpus, ein echtes Job-Log von ``adr0023-magnitude-shadow-daily``:

* ``110861865818`` — Lauf 37014478924 (2026-10-02, 13:39 UTC), der letzte Lauf
  VOR der Aenderung: die Zusammenfassung steht darin, ohne Regel.

Die Zeile fuer den PASS-Fall ist nicht erfunden: so druckt sie
``scripts/run_magnitude_shadow_ledger.py`` (siehe
``test_the_runner_prints_exactly_the_line_the_judge_reads``).
"""
from __future__ import annotations

import json
from pathlib import Path

from governance.family_returns import LEGACY_RETURN_RULE, RETURN_RULE
from scripts import run_magnitude_shadow_ledger as shadow
from scripts.proof_judges import corpus_for, load_judge
from scripts.proof_ledger import load_entries

_JUDGE = "shadow_ledger_return_rule"
_PRE_MERGE_JOB = "110861865818"
_STAMP = "2026-10-05T13:40:56.8654621Z "
_SUMMARY = "BOS(candidate): INCONCLUSIVE [all_thin] | SWEEP(candidate): INCONCLUSIVE [all_thin]"
_LEDGER = "artifacts/governance/magnitude_resolution_shadow.jsonl"


def _entry():
    return next(e for e in load_entries() if e.judge == _JUDGE)


def _judge(log: str):
    return load_judge(_JUDGE).judge({"log": log}, _entry())


def _real_log() -> str:
    corpus = dict(corpus_for(_JUDGE))
    assert set(corpus) == {_PRE_MERGE_JOB}, sorted(corpus)
    return corpus[_PRE_MERGE_JOB]["log"]


def test_the_last_run_before_the_change_is_not_yet_a_witness() -> None:
    log = _real_log()
    assert f"shadow ledger {_LEDGER}: BOS(candidate)" in log, "the corpus must carry the OLD summary line"
    verdict = _judge(log)
    assert (verdict.state, verdict.branch) == ("STEHT_AUS", "nicht_gestempelt")


def test_a_stamped_summary_is_the_pass() -> None:
    log = _real_log() + f"\n{_STAMP}shadow ledger {_LEDGER} [{RETURN_RULE}]: {_SUMMARY}\n"
    verdict = _judge(log)
    assert (verdict.state, verdict.branch) == ("PASS", "regel_gestempelt")
    assert RETURN_RULE in verdict.detail


def test_a_summary_stamped_with_another_rule_fails() -> None:
    """Fail-closed: a run that says it graded under Variant A after the change
    would be writing rows of the old rule into the new record."""
    log = _real_log() + f"\n{_STAMP}shadow ledger {_LEDGER} [{LEGACY_RETURN_RULE}]: {_SUMMARY}\n"
    verdict = _judge(log)
    assert (verdict.state, verdict.branch) == ("FAIL", "falsche_regel")
    assert LEGACY_RETURN_RULE in verdict.detail


def test_the_line_counts_only_as_emitted_output_not_as_script_text() -> None:
    """The runner prints every run block into the log, coloured, behind the
    timestamp. A stamped summary that appears only inside such an echo was not
    printed by the script."""
    echoed = f"\n{_STAMP}\x1b[36;1mecho 'shadow ledger {_LEDGER} [{RETURN_RULE}]: {_SUMMARY}'\x1b[0m\n"
    verdict = _judge(_real_log() + echoed)
    assert (verdict.state, verdict.branch) == ("STEHT_AUS", "nicht_gestempelt")


def test_an_empty_log_cannot_witness() -> None:
    verdict = _judge("")
    assert (verdict.state, verdict.branch) == ("KANN_NICHT_BEZEUGEN", "kein_log")


def test_the_runner_prints_exactly_the_line_the_judge_reads(tmp_path: Path, capsys) -> None:
    """Bind the judge to its PRODUCER, not to a line this test made up: run
    the real runner on a thin event list and judge what it printed."""
    events = tmp_path / "events.json"
    events.write_text(json.dumps([{"family": "BOS", "anchor_ts": 1_791_210_600.0}]), encoding="utf-8")
    ledger = tmp_path / "shadow.jsonl"
    rc = shadow.main([str(events), "--ledger", str(ledger), "--date", "2026-10-05"])
    assert rc == 3  # thin day: heartbeat rows, nothing measurable
    printed = [line for line in capsys.readouterr().err.splitlines() if line.startswith("shadow ledger ")]
    assert len(printed) == 1
    assert printed[0].startswith(f"shadow ledger {ledger} [{RETURN_RULE}]: ")
    verdict = _judge(f"{_STAMP}{printed[0]}\n")
    assert (verdict.state, verdict.branch) == ("PASS", "regel_gestempelt")
    rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
    assert rows and {row["return_rule"] for row in rows} == {RETURN_RULE}
