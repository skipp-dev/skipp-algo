"""Der Urteiler fuer die grobe Bilanz liest die Zeile, die das Skript druckt.

Korpus, ein echtes Job-Log von ``promotion-gate-daily``:

* ``111053132530`` — Lauf 37071929491 (2026-10-02, 22:22 UTC), der letzte
  Gate-Lauf VOR der Aenderung: beide Ledger-Zeilen stehen darin, ohne Korn.

Die Zeilen fuer PASS und FAIL sind nicht erfunden: so druckt sie
``scripts/accumulate_returns_ledger.py`` (siehe
``test_the_runner_prints_exactly_the_lines_the_judge_reads``), hier mit dem
Zeitstempel des Runners davor.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts.proof_judges import corpus_for, load_judge
from scripts.proof_ledger import load_entries

_JUDGE = "coarse_grain_ledger"
_FINE_JUDGE = "returns_ledger_step"
_PRE_MERGE_JOB = "111053132530"
_STAMP = "2026-10-05T14:08:11.1234567Z "
_COARSE = (
    "returns ledger 15m [pivot_lookup=50]: pool 2371/13822 events on plane, 12 closed trades observed, "
    "12 new, 0 contradicted, ledger now 12 (BOS:12)"
)
_FINE = (
    "returns ledger 15m [pivot_lookup=1]: pool 2371/13822 events on plane, 2126 closed trades observed, "
    "0 new, 0 contradicted, ledger now 2126 (BOS:381, FVG:591, OB:208, SWEEP:946)"
)
_REFUSAL = (
    "error: docs/calibration/gates/ledger/returns_ledger_15m_p50.jsonl holds rows under "
    "[\"('next_open_then_horizon_close', 5.0, 'exchange_aligned', 1)\"], this run uses "
    "('next_open_then_horizon_close', 5.0, 'exchange_aligned', 50). A ledger carries ONE trade "
    "definition; start a new file for a new rule, cost, bar grid or structure grain."
)
_REPO = Path(__file__).resolve().parents[1]


def _entry(judge: str = _JUDGE):
    return next(e for e in load_entries() if e.judge == judge)


def _judge(log: str, judge: str = _JUDGE):
    return load_judge(judge).judge({"log": log}, _entry(judge))


def _real_log() -> str:
    corpus = dict(corpus_for(_JUDGE))
    assert set(corpus) == {_PRE_MERGE_JOB}, sorted(corpus)
    return corpus[_PRE_MERGE_JOB]["log"]


def test_the_last_run_before_the_change_is_not_yet_a_witness() -> None:
    log = _real_log()
    assert "Z returns ledger 15m: pool" in log, "the corpus must carry the OLD lines without a grain"
    verdict = _judge(log)
    assert (verdict.state, verdict.branch) == ("STEHT_AUS", "nicht_gestempelt")


def test_the_old_lines_still_satisfy_the_track_record_judge() -> None:
    """The record's judge keeps reading the pre-change format: its PASS entry
    rests on a corpus in that format."""
    verdict = _judge(_real_log(), _FINE_JUDGE)
    assert (verdict.state, verdict.branch) == ("PASS", "ledger_geschrieben")


def test_a_coarse_line_is_the_pass_even_with_zero_rows() -> None:
    log = _real_log() + f"\n{_STAMP}{_FINE}\n{_STAMP}{_COARSE.replace('ledger now 12', 'ledger now 0')}\n"
    verdict = _judge(log)
    assert (verdict.state, verdict.branch) == ("PASS", "korn_geschrieben")
    assert "0 Zeilen" in verdict.detail


def test_the_new_format_lines_satisfy_both_judges_and_the_coarse_line_never_counts_as_the_record() -> None:
    """After the change every line names its grain, 1D included. The record's
    judge reads the fine lines and never takes the coarse line for the 15m
    record."""
    one_d = "returns ledger 1D [pivot_lookup=1]: pool 172/13822 events on plane, 168 closed trades observed, 0 new, 0 contradicted, ledger now 168 (BOS:44, OB:21, SWEEP:103)"
    new_only = f"{_STAMP}{one_d}\n{_STAMP}{_FINE}\n{_STAMP}{_COARSE}\n"
    assert _judge(new_only).branch == "korn_geschrieben"
    assert _judge(new_only, _FINE_JUDGE).branch == "ledger_geschrieben"
    # Only the coarse 15m line plus 1D: the record's 15m line is missing — FAIL, not a PASS on the coarse line.
    coarse_as_record = f"{_STAMP}{one_d}\n{_STAMP}{_COARSE}\n"
    assert _judge(coarse_as_record, _FINE_JUDGE).branch == "ledger_unvollstaendig"


def test_a_refusal_fails() -> None:
    log = _real_log() + f"\n{_STAMP}{_REFUSAL}\n"
    verdict = _judge(log)
    assert (verdict.state, verdict.branch) == ("FAIL", "verweigert")


def test_the_line_counts_only_as_emitted_output_not_as_script_text() -> None:
    """The runner prints every run block, coloured, behind the timestamp. A
    coarse line that appears only inside such an echo was not printed."""
    echoed = f"\n{_STAMP}\x1b[36;1mecho '{_COARSE}'\x1b[0m\n"
    verdict = _judge(_real_log() + echoed)
    assert (verdict.state, verdict.branch) == ("STEHT_AUS", "nicht_gestempelt")


def test_an_empty_log_cannot_testify() -> None:
    assert _judge("").state == "KANN_NICHT_BEZEUGEN"


def _event(symbol: str, grain: int) -> dict:
    anchor = 1_791_210_600.0
    closes = [100.5, 101.0, 101.5, 101.0, 100.5, 101.0, 101.5, 102.0]
    event = {
        "family": "BOS", "direction": "UP", "entry_mode": "immediate", "entry_price": 100.0,
        "bar_grid": "exchange_aligned", "pivot_lookup": grain, "anchor_ts": anchor, "regime": "TRENDING",
        "event_id": f"bos:{symbol}:15m:{int(anchor)}:BOS:UP:100.00" + (":p50" if grain == 50 else ""),
        "forward_opens": [100.0, *closes[:-1]], "forward_closes": closes,
        "forward_highs": [c + 0.5 for c in closes], "forward_lows": [c - 0.5 for c in closes],
        "forward_timestamps": [anchor + 900.0 * (i + 1) for i in range(8)],
    }
    return event


def test_the_runner_prints_exactly_the_lines_the_judge_reads(tmp_path: Path) -> None:
    """Run the real producer twice — fine and coarse — and judge its stdout
    (stamped as the runner would) with both judges; then make it refuse."""
    pool = tmp_path / "pool.json"
    pool.write_text(json.dumps([_event("AAPL", 1), _event("MSFT", 50)]), encoding="utf-8")

    def run(ledger: str, *extra: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "scripts.accumulate_returns_ledger", "--events", str(pool), "--plane", "15m",
             "--date", "2026-10-05", "--ledger", str(tmp_path / ledger), *extra],
            cwd=_REPO, capture_output=True, text=True, check=False,
        )

    fine = run("fine.jsonl")
    coarse = run("coarse.jsonl", "--pivot-lookup", "50")
    assert fine.returncode == 0 and coarse.returncode == 0, (fine.stderr, coarse.stderr)
    stamped = "".join(f"{_STAMP}{line}\n" for line in (fine.stdout + coarse.stdout).splitlines())
    assert "returns ledger 15m [pivot_lookup=1]:" in stamped and "returns ledger 15m [pivot_lookup=50]:" in stamped
    assert _judge(stamped).branch == "korn_geschrieben"
    # The record's judge wants 1D as well; with 15m only it says so, and never mistakes the coarse line for it.
    assert _judge(stamped, _FINE_JUDGE).branch == "ledger_unvollstaendig"

    refused = run("fine.jsonl", "--pivot-lookup", "50")  # the fine ledger, asked to take coarse rows
    assert refused.returncode == 2
    stamped_refusal = "".join(f"{_STAMP}{line}\n" for line in refused.stderr.splitlines())
    assert _judge(stamped_refusal).branch == "verweigert"
