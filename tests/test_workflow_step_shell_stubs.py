"""Der Stub-Vertrag des Step-Harness: stdin wird konsumiert, nicht verwaist.

Warum es diesen File gibt: ``validate (1)`` starb am 2026-08-28 (Lauf
33149634990) mit ``KeyError: 'rc'`` in
``test_a_stalled_backfill_publishes_a_failing_rc_and_opens_the_issue`` — und
war im naechsten Lauf gruen. Die Wurzel lag nicht im Test, sondern im Harness:
ein Stub, der stdin nie liest, laesst die linke Seite von
``echo "$json" | jq -r ...`` unter ``set -o pipefail`` an SIGPIPE sterben,
sobald der Scheduler sie spaeter dran nimmt als den Stub-Exit. 26 Testdateien
benutzen diesen Harness; die Rennluecke betraf jede Pipe in jeden gestubbten
Step hinein.

Diese Tests beweisen den Mechanismus in beide Richtungen mit einem kuenstlich
verzoegerten Schreiber statt mit Glueck — und sie pinnen die zwei
stdin-Vertraege, an denen die erste Fassung dieses Fixes selbst gescheitert
ist (Drain VOR dem Script frass den ``exec``-Weiterleitungen ihr stdin weg;
vier promotion-gate-Tests gingen rot).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from tests._workflow_step_shell import Stub, _stub_body

#: Gross gegen den Stub-Kaltstart, klein gegen das 60-s-Budget des Harness.
#: 50 ms waren NICHT genug: der allererste Lauf eines frischen Stubs kann
#: laenger brauchen (gemessen 2026-08-28, rc=0 im Kaltstart, danach 141) —
#: eine Negativkontrolle, die nur meistens stirbt, ist selbst eine Flake.
#: Bei 500 ms: alter Koerper 10/10 tot, neuer 10/10 lebendig.
_WRITER_DELAY = "0.5"

_JQ_CASE = (
    'case "$2" in\n'
    "  *records_backfilled*) echo 0 ;;\n"
    "  *) echo 0 ;;\n"
    "esac"
)


def _write_stub(tmp_path: Path, body: str) -> Path:
    stub = tmp_path / "jq"
    stub.write_text(body, encoding="utf-8")
    stub.chmod(0o755)
    return stub


def _run_pipeline_into(stub_path: Path) -> subprocess.CompletedProcess[str]:
    """Exakt die Gestalt der Produktions-Zeile: verzoegerter echo | Stub."""
    return subprocess.run(
        [
            "bash", "--noprofile", "--norc", "-c",
            'set -euo pipefail\n'
            f'x=$({{ sleep {_WRITER_DELAY}; echo \'{{"backfill": {{}}}}\'; }} '
            f'| "{stub_path}" -r ".backfill.records_backfilled // error")\n'
            'echo "verdict=$x"\n',
        ],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=30,
    )


def test_a_late_writer_no_longer_dies_of_sigpipe(tmp_path: Path) -> None:
    call_log = tmp_path / "calls"
    call_log.write_text("", encoding="utf-8")
    stub = _write_stub(tmp_path, _stub_body(Stub(script=_JQ_CASE), call_log))

    result = _run_pipeline_into(stub)
    assert result.returncode == 0, result.stderr
    assert "verdict=0" in result.stdout


def test_the_old_body_without_the_drain_did_die_there(tmp_path: Path) -> None:
    """Negativkontrolle gegen den ALTEN Koerper, nicht gegen eine Vermutung.

    Der Drain-Trap wird aus dem heutigen Koerper herausgeschnitten — was
    bleibt, IST der Koerper von vor diesem Fix. Stirbt er unter der
    Verzoegerung nicht, prueft der Positivtest oben nichts und dieser File
    muss neu gedacht werden.

    Auf macOS-bash stirbt die linke Seite als 141 (128+SIGPIPE); gepinnt wird
    nur "der Step stirbt", weil allein daran der KeyError hing — welchen
    Code die Shell dem Tod gibt, ist Plattformfarbe.
    """
    call_log = tmp_path / "calls"
    call_log.write_text("", encoding="utf-8")
    body = _stub_body(Stub(script=_JQ_CASE), call_log)
    assert "trap 'cat > /dev/null" in body, "Drain-Trap fehlt schon im Erzeuger"
    old_body = "\n".join(
        line for line in body.splitlines() if "cat > /dev/null" not in line
    ) + "\n"
    stub = _write_stub(tmp_path, old_body)

    result = _run_pipeline_into(stub)
    assert result.returncode != 0, (
        "der alte Koerper ueberlebte den verzoegerten Schreiber — dann ist "
        "der Mechanismus-Beweis dieses Files vakuum"
    )


def test_the_trap_preserves_the_stubs_exit_code(tmp_path: Path) -> None:
    """Ein Stub, der 5 sagt, muss nach dem Drain immer noch 5 sagen.

    Die EXIT-Trap-Platzierung haengt daran: POSIX erhaelt den Status eines
    expliziten ``exit N`` ueber den Trap hinweg. Waere das falsch, saehe
    jeder Fehlschlag-Stub (``Stub(exit_code=5)``) wie Erfolg aus und alle
    Fehlerpfad-Tests des Harness wuerden vakuum gruen.
    """
    call_log = tmp_path / "calls"
    call_log.write_text("", encoding="utf-8")
    stub = _write_stub(tmp_path, _stub_body(Stub(exit_code=5), call_log))

    result = subprocess.run(
        ["bash", "--noprofile", "--norc", "-c", f'echo hi | "{stub}"; echo "rc=$?"'],
        capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=30,
    )
    assert "rc=5" in result.stdout, result.stdout


def test_a_passthrough_stub_still_owns_its_stdin(tmp_path: Path) -> None:
    """`exec real "$@"` bekommt stdin unangetastet — kein Trap davor."""
    call_log = tmp_path / "calls"
    call_log.write_text("", encoding="utf-8")
    stub = _write_stub(tmp_path, _stub_body(Stub(passthrough="cat"), call_log))

    result = subprocess.run(
        ["bash", "--noprofile", "--norc", "-c", f'echo geheimnis | "{stub}"'],
        capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=30,
    )
    assert result.stdout.strip() == "geheimnis"


def test_a_script_that_execs_a_real_tool_still_receives_stdin(tmp_path: Path) -> None:
    """Die Regression, die die erste Fassung dieses Fixes gerissen hat.

    ``_PY_STUB`` und ``_GNU_HEAD`` in test_promotion_gate_daily_workflow_contract
    sind ``script``-Stubs, die per ``exec`` an das echte Tool weiterreichen —
    dessen stdin gehoert dem Tool. Ein Drain VOR dem Script frass es leer
    (vier Tests rot); der EXIT-Trap verschwindet mit dem ``exec`` und laesst
    stdin in Ruhe.
    """
    call_log = tmp_path / "calls"
    call_log.write_text("", encoding="utf-8")
    stub = _write_stub(
        tmp_path, _stub_body(Stub(script='exec cat "$@"'), call_log)
    )

    result = subprocess.run(
        ["bash", "--noprofile", "--norc", "-c", f'echo durchgereicht | "{stub}"'],
        capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=30,
    )
    assert result.stdout.strip() == "durchgereicht"


def test_a_script_that_reads_stdin_itself_still_receives_it(tmp_path: Path) -> None:
    """Konsumiert das Script stdin selbst, findet der Trap nur noch EOF vor."""
    call_log = tmp_path / "calls"
    call_log.write_text("", encoding="utf-8")
    stub = _write_stub(tmp_path, _stub_body(Stub(script="cat"), call_log))

    result = subprocess.run(
        ["bash", "--noprofile", "--norc", "-c", f'echo inhalt | "{stub}"'],
        capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=30,
    )
    assert result.stdout.strip() == "inhalt"
