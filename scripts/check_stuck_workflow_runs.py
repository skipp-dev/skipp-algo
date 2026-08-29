#!/usr/bin/env python3
"""Läufe, die nicht enden — die Ausfallart, für die es hier keinen Alarm gab.

Warum es diese Sonde gibt
=========================

Der Workflow-Fehleralarm ``lo-workflow-run-failed`` wertet ``latest run failed``
aus (``scripts/check_workflow_failure_alarm_coverage.py``) und steht auf
``noDataState: OK``. Er sieht damit **nur Endzustände**. Ein Lauf, der nie
endet, erzeugt kein ``failure`` und taucht in keiner Alarmregel auf:

* ``queued``, weil kein Runner das Label annimmt — ein falscher Wert in einer
  Repo-Variablen, ein totes self-hosted-Label auf einer der 15
  ``select-runner``-Lanes. GitHub plant den Job nie ein und beendet ihn nach
  24 h still als ``cancelled``.
* ``in_progress``, weil ein Job hängt und die eigene ``timeout-minutes`` ihn
  nicht killt — der ``validate (4)``-Hang (#4939/#4949) ist genau das.

Beides blockiert *required* Kontexte und damit jeden offenen PR, ohne dass
irgendwo etwas rot wird. ``runner-label-variable-watch`` (#5178) schließt die
eine **Ursache** dieser Klasse; diese Sonde schließt ihre **Sichtbarkeit** —
unabhängig davon, woher der Stillstand kommt.

Zwei Budgets, zwei Diagnosen
============================

Die Trennung ist der eigentliche Wert. ``queued`` und ``in_progress`` schicken
den Geweckten an völlig verschiedene Orte, und ein gemeinsamer Zähler hätte
genau diese Information eingeebnet:

* ``queued`` zu lange → **kein Runner hat angenommen.** Label/Selector prüfen.
  Nicht nach einem hängenden Test suchen — es läuft gar nichts.
* ``in_progress`` zu lange → **es läuft und endet nicht.** Der Job hat einen
  Runner; seine ``timeout-minutes`` greift nicht oder ist zu großzügig.

Exit-Codes
----------
0   kein Lauf über seinem Budget
1   mindestens ein Lauf steht — Alarm
8   Sonde ungültig (kein Token, API-Antwort unbrauchbar); ausdrücklich NICHT 0
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"

_GITHUB_API = "https://api.github.com"

#: Wie lange ein Lauf auf einen Runner warten darf.
#: 60 min ist reichlich: GitHub-hosted Standard-Runner nehmen in Sekunden an,
#: und die self-hosted-Lanes fallen über ``resolve_workflow_runner`` auf hosted
#: zurück, wenn kein Runner idle ist. Wer nach einer Stunde noch wartet, wartet
#: auf ein Label, das es nicht gibt.
QUEUED_BUDGET_MIN = 60

#: Wie lange ein Lauf laufen darf. Muss ÜBER dem größten ``timeout-minutes``
#: des Repos liegen (2026-08-29 gemessen: 240), sonst meldet die Sonde einen
#: gesunden Langläufer. Der Abstand ist Absicht und wird von
#: ``tests/test_check_stuck_workflow_runs.py`` gegen die echte Population
#: gehalten — wächst irgendwo ein Job-Limit über dieses Budget, wird der Test
#: rot statt die Sonde falsch zu alarmieren.
IN_PROGRESS_BUDGET_MIN = 330

_TIMEOUT_RE = re.compile(r"timeout-minutes:\s*(\d+)")


@dataclass(frozen=True)
class Stuck:
    """Ein stehender Lauf, formuliert für jemanden, der um 3 Uhr geweckt wird."""

    run_id: int
    workflow: str
    branch: str
    status: str  # queued | in_progress | waiting
    age_min: float
    budget_min: int
    url: str
    #: Welcher Zeitstempel das Alter ergab. `run_started_at` misst gearbeitete
    #: Zeit, `created_at` gewartete — die Offenlegung gehoert in den Alarm,
    #: sonst raet der Geweckte, welche der beiden Zahlen er vor sich hat.
    age_source: str

    @property
    def diagnosis(self) -> str:
        if self.status == "in_progress":
            return (
                "laeuft und endet nicht — der Job HAT einen Runner. Seine "
                "`timeout-minutes` greift nicht oder ist zu grosszuegig; im Log "
                "steht, wo er haengt"
            )
        return (
            "kein Runner hat den Job angenommen — NICHT nach einem haengenden "
            "Test suchen, es laeuft nichts. Runner-Label pruefen (Repo-Variable "
            "oder self-hosted-Selektor)"
        )

    def as_error_annotation(self) -> str:
        return (
            f"::error title=stuck-run-watch::{self.workflow} steht seit "
            f"{self.age_min:.0f} min in `{self.status}` (Budget "
            f"{self.budget_min} min, gemessen ab `{self.age_source}`), "
            f"Branch {self.branch}, Lauf {self.run_id}: "
            f"{self.diagnosis}. {self.url}"
        )


def max_declared_timeout(workflows_dir: Path | None = None) -> int:
    """Das groesste literale ``timeout-minutes`` im Repo.

    Abgeleitet statt gepflegt: das Budget dieser Sonde muss darueber liegen, und
    ob es das noch tut, soll ein Test an der echten Population messen — nicht
    eine Zahl in einem Kommentar behaupten.
    """
    directory = workflows_dir if workflows_dir is not None else WORKFLOWS_DIR
    werte = [
        int(m.group(1))
        for path in sorted(directory.glob("*.yml")) + sorted(directory.glob("*.yaml"))
        for m in _TIMEOUT_RE.finditer(path.read_text(encoding="utf-8"))
    ]
    return max(werte) if werte else 0


def evaluate(runs: list[dict[str, Any]], now: dt.datetime) -> list[Stuck]:
    """Reines Urteil — die Testbarkeit dieser Sonde haengt daran."""
    findings: list[Stuck] = []
    for run in runs:
        status = str(run.get("status") or "")
        if status not in ("queued", "waiting", "in_progress"):
            continue
        # Welche Quelle das Alter ergibt, entscheidet der STATUS — nicht, ob ein
        # Feld gesetzt ist.
        #
        # 2026-08-29 am ersten echten Lauf gemessen und damit eine Annahme
        # widerlegt, die hier bis eben stand: `run_started_at` fehle, solange
        # nichts lief. Falsch. GitHub setzt es auch fuer `queued` und zwar
        # identisch zu `created_at` (Lauf 32985711996: beide
        # 2026-08-26T15:38:15Z, Status `queued`). Die alte Praeferenz-Reihenfolge
        # stempelte deshalb "gemessen ab run_started_at" auf einen Lauf, der NIE
        # gestartet ist — sie las sich wie 68 Stunden ARBEIT, wo 68 Stunden
        # WARTEN standen. Die Zahl war richtig, das Etikett log; und ein Etikett,
        # das in genau dem Fall luegt, fuer den es erfunden wurde, ist schlimmer
        # als keins.
        #
        # `queued`/`waiting` haben per Definition nicht gearbeitet: dort ist
        # `created_at` die gesuchte Groesse. `in_progress` arbeitet: dort
        # `run_started_at`, mit `created_at` als Rueckfall, falls es doch einmal
        # fehlt.
        if status in ("queued", "waiting"):
            stamp, stamp_source = run.get("created_at"), "created_at (Wartezeit)"
        else:
            stamp, stamp_source = run.get("run_started_at"), "run_started_at (Laufzeit)"
            if stamp is None:
                stamp, stamp_source = run.get("created_at"), "created_at (Rueckfall)"
        try:
            begonnen = dt.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            continue
        alter = (now - begonnen).total_seconds() / 60
        budget = IN_PROGRESS_BUDGET_MIN if status == "in_progress" else QUEUED_BUDGET_MIN
        if alter <= budget:
            continue
        findings.append(
            Stuck(
                run_id=int(run.get("id") or 0),
                workflow=str(run.get("name") or "<ohne Namen>"),
                branch=str(run.get("head_branch") or "?"),
                status=status,
                age_min=alter,
                budget_min=budget,
                url=str(run.get("html_url") or ""),
                age_source=stamp_source,
            )
        )
    return sorted(findings, key=lambda f: f.age_min, reverse=True)


def fetch_in_flight(repo: str, token: str, fetcher: Any = None) -> list[dict[str, Any]]:
    """Alle Laeufe, die noch nicht fertig sind.

    ``fetcher`` ist injizierbar, damit die Tests ohne Netz laufen. Vorgabe ist
    der geteilte GitHub-Helfer aus ``check_workflow_freshness`` — bewusst
    wiederverwendet, damit hier keine zusaetzliche ``urlopen``-Stelle entsteht
    (Ledger in tests/test_http_client_discipline.py).
    """
    if fetcher is None:
        from scripts.check_workflow_freshness import _default_fetcher

        fetcher = _default_fetcher

    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "skipp-algo-stuck-run-watch",
    }

    runs: list[dict[str, Any]] = []
    gesehen: set[int] = set()
    for status in ("queued", "waiting", "in_progress"):
        page = 1
        while page <= 10:
            url = (
                f"{_GITHUB_API}/repos/{repo}/actions/runs"
                f"?status={status}&per_page=100&page={page}"
            )
            payload = fetcher(url, headers)
            if not isinstance(payload, dict) or "workflow_runs" not in payload:
                raise ValueError(
                    f"unerwartete API-Antwort fuer status={status}, Seite {page}: "
                    f"{type(payload).__name__}"
                )
            batch = payload.get("workflow_runs") or []
            for run in batch:
                rid = run.get("id")
                if rid not in gesehen:
                    gesehen.add(rid)
                    runs.append(run)
            if len(batch) < 100:
                break
            page += 1
    return runs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    args = parser.parse_args(argv)

    token = os.environ.get("GITHUB_TOKEN", "")
    token_source = "GITHUB_TOKEN"
    if not token:
        token = os.environ.get("GH_TOKEN", "")
        token_source = "GH_TOKEN"
    if not token:
        token_source = "<keins gesetzt>"

    if not args.repo or not token:
        print(
            "::error title=stuck-run-watch::Sonde ungueltig -- --repo und "
            "GITHUB_TOKEN/GH_TOKEN muessen gesetzt sein. Nicht als Erfolg gewertet.",
            file=sys.stderr,
        )
        return 8

    try:
        runs = fetch_in_flight(args.repo, token)
    except Exception as exc:
        # Breit gefangen mit Absicht: JEDE Stoerung auf dem Weg zur API ist ein
        # Sondenfehler und muss rc=8 ergeben, nicht ein stilles "nichts steht".
        print(
            f"::error title=stuck-run-watch::Sonde ungueltig -- laufende Laeufe "
            f"nicht lesbar: {exc}",
            file=sys.stderr,
        )
        return 8

    now = dt.datetime.now(dt.UTC)
    findings = evaluate(runs, now)

    lines = [
        "## stuck-run-watch",
        "",
        f"{len(runs)} Lauf/Laeufe in Arbeit geprueft "
        f"(Budget: queued {QUEUED_BUDGET_MIN} min, in_progress "
        f"{IN_PROGRESS_BUDGET_MIN} min).",
    ]
    if findings:
        lines += ["", "| Workflow | Status | Alter | Branch | Lauf |", "|---|---|---|---|---|"]
        for f in findings:
            lines.append(
                f"| {f.workflow} | `{f.status}` | {f.age_min:.0f} min "
                f"(ab `{f.age_source}`) | {f.branch} | {f.run_id} |"
            )
        for f in findings:
            lines += ["", f"**{f.workflow}** ({f.status}) — {f.diagnosis}."]
    else:
        lines += ["", "Kein Lauf ueber seinem Budget."]
    lines += ["", f"Token-Quelle: `{token_source}`."]

    print("\n".join(lines))
    for f in findings:
        print(f.as_error_annotation(), file=sys.stderr)

    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
