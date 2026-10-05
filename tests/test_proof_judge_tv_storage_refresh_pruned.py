"""Der Urteiler fuer #5682 liest die Zeilen, die Workflow und Prune-Skript drucken.

Korpus, ein echtes Job-Log von ``tradingview-storage-refresh`` (Job ``refresh``):

* ``111603532773`` — Lauf 37259501362 (2026-10-05, 03:27 UTC), der letzte Lauf
  VOR #5682: Mitschnitt geglueckt, Pruefung stirbt an
  ``/usr/bin/python: Argument list too long`` (exit 126).

Die Zeilen fuer die anderen Faelle sind nicht erfunden: die Prune-Zeile druckt
``scripts/tv_prune_storage_state.py`` (siehe
``test_the_prune_script_prints_exactly_the_line_the_judge_reads``), die
Erfolgszeile steht im Schreibschritt des Workflows.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts.proof_judges import corpus_for, load_judge
from scripts.proof_ledger import load_entries

_JUDGE = "tv_storage_refresh_pruned"
_PRE_MERGE_JOB = "111603532773"
_TS = "2026-10-06T03:28:15.3085441Z "
_ROOT = Path(__file__).resolve().parents[1]
_WORKFLOW = _ROOT / ".github" / "workflows" / "tradingview-storage-refresh.yml"


def _entry():
    return next(e for e in load_entries() if e.judge == _JUDGE)


def _judge(log: str):
    return load_judge(_JUDGE).judge({"log": log}, _entry())


def _real_log() -> str:
    corpus = dict(corpus_for(_JUDGE))
    assert set(corpus) == {_PRE_MERGE_JOB}, sorted(corpus)
    return corpus[_PRE_MERGE_JOB]["log"]


_PRUNED = f"{_TS}Pruned storage state: cookies 412 -> 19, origins 1 -> 1, size 140.2 KiB -> 20.0 KiB\n"


def test_the_last_run_before_the_fix_is_not_yet_a_witness() -> None:
    log = _real_log()
    assert "Argument list too long" in log, "the corpus must carry the failure #5682 fixes"
    verdict = _judge(log)
    assert (verdict.state, verdict.branch) == ("STEHT_AUS", "kein_prune_lauf")


def test_pruned_and_written_is_the_pass() -> None:
    log = _PRUNED + f"{_TS}Storage state validation passed\n{_TS}TV_STORAGE_STATE secret updated successfully.\n"
    verdict = _judge(log)
    assert (verdict.state, verdict.branch) == ("PASS", "rotiert")
    assert "412 -> 19" in verdict.detail


def test_the_echoed_script_of_the_write_step_is_not_a_success() -> None:
    """GitHub prints each step's script when it starts; the echo is in it."""
    echoed = f'{_TS}\x1b[36;1mecho "TV_STORAGE_STATE secret updated successfully."\x1b[0m\n'
    verdict = _judge(_PRUNED + echoed + f"{_TS}##[error]Process completed with exit code 1.\n")
    assert (verdict.state, verdict.branch) == ("FAIL", "nach_prune_gescheitert")


def test_a_failure_after_the_prune_is_a_fail_with_the_reason() -> None:
    log = _PRUNED + f"{_TS}/usr/bin/python: Argument list too long\n{_TS}##[error]Process completed with exit code 126.\n"
    verdict = _judge(log)
    assert (verdict.state, verdict.branch) == ("FAIL", "nach_prune_gescheitert")
    assert "exit code 126" in verdict.detail


def test_an_error_before_the_prune_does_not_count_against_it() -> None:
    log = f"{_TS}##[error]an earlier, retried capture attempt\n" + _PRUNED + f"{_TS}TV_STORAGE_STATE secret updated successfully.\n"
    assert _judge(log).branch == "rotiert"


def test_a_refused_prune_is_a_fail() -> None:
    log = (
        f"{_TS}error: no 'sessionid' cookie on tradingview.com after pruning (3 of 40 cookies kept)"
        " — refusing to write an unusable session\n"
        f"{_TS}##[error]Process completed with exit code 1.\n"
    )
    verdict = _judge(log)
    assert (verdict.state, verdict.branch) == ("FAIL", "prune_verweigert")


def test_a_dry_run_proves_the_path_not_the_rotation() -> None:
    verdict = _judge(_PRUNED + f"{_TS}Storage state validation passed\n")
    assert (verdict.state, verdict.branch) == ("STEHT_AUS", "trockenlauf")


def test_an_empty_log_cannot_witness() -> None:
    assert _judge("").state == "KANN_NICHT_BEZEUGEN"


def test_the_prune_script_prints_exactly_the_line_the_judge_reads(tmp_path: Path) -> None:
    state = {
        "cookies": [{"name": "sessionid", "value": "v", "domain": ".tradingview.com"}, {"name": "x", "value": "v", "domain": ".ads.example"}],
        "origins": [],
        "meta": {"authValidatedAt": "2026-10-06T03:00:00+00:00"},
    }
    path = tmp_path / "storage-state.json"
    path.write_text(json.dumps(state), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "scripts.tv_prune_storage_state", str(path)],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    log = "".join(f"{_TS}{line}\n" for line in proc.stdout.splitlines())
    log += f"{_TS}TV_STORAGE_STATE secret updated successfully.\n"
    assert _judge(log).branch == "rotiert"


def test_the_workflow_prints_exactly_the_success_line_the_judge_reads() -> None:
    assert 'echo "TV_STORAGE_STATE secret updated successfully."' in _WORKFLOW.read_text(encoding="utf-8")
