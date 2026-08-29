#!/usr/bin/env python3
"""Haelt die live gesetzten Runner-Variablen gegen die Allowlist im Repo.

Warum es diese Sonde gibt
=========================

Ein falsches Runner-Label macht einen Lauf nicht rot, sondern **verhindert ihn**.
GitHub findet kein passendes Label, plant den Job nie ein, laesst ihn ``queued``
bis zum 24-h-Limit stehen und beendet ihn dann still als ``cancelled``. Drei
Schutzmechanismen greifen dabei alle nicht:

* ``timeout-minutes`` laeuft erst, wenn ein Runner den Job ANGENOMMEN hat.
* Der Fehleralarm ``lo-workflow-run-failed`` wertet ``latest run failed`` aus
  (``scripts/check_workflow_failure_alarm_coverage.py``) bei ``noDataState: OK``
  -- ein Lauf, der nie endet, erzeugt kein ``failure``.
* Die Runner-Contract-Tests pinnen den **Ausdruck** ``vars.X in runs_on``, nie den
  **Wert**. Der lebt bei GitHub, nicht im Repo; kein Test kann ihn sehen.

Gemessen am 2026-08-29 ueber die volle ``runs-on``-Grundgesamtheit auf ``main``:
97 Stellen, davon **80** an ``SMC_GH_HOSTED_RUNNER`` -- inklusive der beiden
einzigen required Kontexte ``fast-gates``/``gate``. Ein Tippfehler dort haette
das gesamte Repo lautlos stillgelegt.

Warum eine Sonde und kein Workflow-Job
======================================

Ein Wachposten INNERHALB der Actions kann diese Klasse prinzipiell nicht
schliessen: er muesste laufen, wenn nichts mehr laeuft. Der ``runner-preflight``
in ``ci.yml`` (#5171) ist genau deshalb nur die halbe Antwort -- er haengt selbst
an ``SMC_GH_HOSTED_RUNNER``. Diese Sonde laeuft in einem Workflow, dessen
``runs-on`` **literal** ist und keine Variable liest; sie startet also auch dann
noch, wenn jede variablengesteuerte Lane des Repos steht.

Anti-Drift
==========

Die Menge der geprueften Variablen wird **abgeleitet**, nicht gepflegt: das Skript
liest jede ``runs-on``-Zeile in ``.github/workflows`` und sammelt die dort
interpolierten ``vars.X``. Eine neue Runner-Variable ist damit ab ihrer ersten
Verwendung abgedeckt; fehlt ihr ein Allowlist-Eintrag, ist DAS der Befund. Eine
handgepflegte Liste haette genau diese Drift nicht fangen koennen -- dieselbe
Klasse wie der Wachposten, dessen Population aus sich selbst stammt.

Exit-Codes
----------
0   jede abgeleitete Variable hat einen Eintrag, jeder Eintrag wird benutzt, und
    jeder live gesetzte Wert steht auf seiner Allowlist
1   mindestens ein Befund (unbekannter Wert, fehlender oder toter Eintrag)
8   Sonde ungueltig (kein Token, API-Antwort unbrauchbar) -- ausdruecklich NICHT 0:
    eine Sonde, die nichts messen konnte, hat nichts bewiesen

Aufruf::

    GITHUB_TOKEN=$(gh auth token) python -m scripts.check_runner_label_variables \
        --repo skipp-dev/skipp-algo
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"
ALLOWLIST_PATH = REPO_ROOT / ".github" / "runner_label_allowlist.json"

#: ``runs-on:`` ist die einzige Stelle, an der ein Variablenwert darueber
#: entscheidet, ob ein Job ueberhaupt geplant wird. Bewusst eng: eine Variable in
#: einem ``env:``-Block kann einen Lauf rot machen, aber nicht verschwinden lassen.
_RUNS_ON_RE = re.compile(r"^\s*runs-on:\s*(?P<value>.+?)\s*$", re.M)
_VARS_RE = re.compile(r"vars\.([A-Z][A-Z0-9_]*)")

_GITHUB_API = "https://api.github.com"


@dataclass(frozen=True)
class Finding:
    """Ein Befund, formuliert so, dass der Geweckte ihn ohne den Run versteht."""

    kind: str  # bad_value | missing_entry | stale_entry
    variable: str
    detail: str

    def as_error_annotation(self) -> str:
        return f"::error title=runner-label-variable-watch::{self.variable}: {self.detail}"


def derive_runner_variables(workflows_dir: Path | None = None) -> dict[str, tuple[str, ...]]:
    """Welche ``vars.X`` entscheiden ueber ein ``runs-on``? Aus den Dateien gelesen.

    Rueckgabe: Variablenname -> die Fundstellen (``datei.yml`` je Vorkommen,
    sortiert und dedupliziert), damit ein Befund die betroffenen Lanes benennen
    kann statt nur die Variable.

    Bewusst textuell statt ueber ``yaml.safe_load``: ``runs-on`` kann in einer
    Matrix, in einem Reusable-Workflow-Aufruf oder hinter einem Anker stehen, und
    ein Parser-Umweg wuerde genau die Stellen verlieren, die niemand erwartet.
    Der Preis -- ein ``runs-on`` in einem Kommentar wuerde mitgezaehlt -- ist
    harmlos: er erzeugt hoechstens einen Eintrag zu viel, nie einen zu wenig.
    """
    directory = workflows_dir if workflows_dir is not None else WORKFLOWS_DIR
    sites: dict[str, list[str]] = {}
    for path in sorted(directory.glob("*.yml")) + sorted(directory.glob("*.yaml")):
        text = path.read_text(encoding="utf-8")
        for match in _RUNS_ON_RE.finditer(text):
            for name in _VARS_RE.findall(match.group("value")):
                sites.setdefault(name, []).append(path.name)
    return {name: tuple(sorted(set(files))) for name, files in sorted(sites.items())}


def load_allowlist(path: Path | None = None) -> dict[str, dict[str, Any]]:
    """Die Allowlist, auf das Wesentliche reduziert und validiert.

    Eine kaputte Allowlist ist ein Sondenfehler, kein leeres Ergebnis: sie wuerde
    sonst als "nichts zu beanstanden" durchgehen.
    """
    target = path if path is not None else ALLOWLIST_PATH
    raw = json.loads(target.read_text(encoding="utf-8"))
    variables = raw.get("variables")
    if not isinstance(variables, dict) or not variables:
        raise ValueError(f"{target}: `variables` fehlt oder ist leer")
    for name, entry in variables.items():
        allowed = entry.get("allowed") if isinstance(entry, dict) else None
        if not isinstance(allowed, list) or not allowed:
            raise ValueError(f"{target}: `{name}.allowed` fehlt oder ist leer")
        if not all(isinstance(label, str) and label.strip() == label and label for label in allowed):
            raise ValueError(f"{target}: `{name}.allowed` enthaelt einen leeren oder gepolsterten Wert")
    return variables


def evaluate(
    derived: dict[str, tuple[str, ...]],
    allowlist: dict[str, dict[str, Any]],
    live_values: dict[str, str],
) -> list[Finding]:
    """Reines Urteil ohne Netz -- die Testbarkeit dieser Sonde haengt daran."""
    findings: list[Finding] = []

    for name, files in derived.items():
        entry = allowlist.get(name)
        if entry is None:
            findings.append(
                Finding(
                    kind="missing_entry",
                    variable=name,
                    detail=(
                        f"steuert `runs-on` in {', '.join(files)}, hat aber keinen "
                        f"Allowlist-Eintrag in .github/runner_label_allowlist.json. "
                        "Ein unbekannter Wert dort laesst die betroffenen Jobs nicht "
                        "fehlschlagen, sondern nie starten."
                    ),
                )
            )

    for name in sorted(allowlist):
        if name not in derived:
            findings.append(
                Finding(
                    kind="stale_entry",
                    variable=name,
                    detail=(
                        "steht auf der Allowlist, wird aber von keinem `runs-on` mehr "
                        "gelesen. Eintrag entfernen -- eine Allowlist, die tote Namen "
                        "traegt, sieht groesser aus als ihr Schutz reicht."
                    ),
                )
            )

    for name, entry in sorted(allowlist.items()):
        if name not in derived:
            continue
        allowed = tuple(entry["allowed"])
        value = live_values.get(name)
        if value is None or value == "":
            if not entry.get("unset_ok", False):
                findings.append(
                    Finding(
                        kind="bad_value",
                        variable=name,
                        detail=(
                            f"ist nicht gesetzt, aber als pflichtig markiert. "
                            f"Erlaubt: {', '.join(allowed)}."
                        ),
                    )
                )
            continue
        if value not in allowed:
            findings.append(
                Finding(
                    kind="bad_value",
                    variable=name,
                    detail=(
                        f"steht auf `{value}`, das ist kein erlaubtes Runner-Label. "
                        f"Erlaubt: {', '.join(allowed)}. Betroffene Lanes: "
                        f"{', '.join(derived[name])}. Ein unbekanntes Label macht diese "
                        "Jobs nicht rot -- sie starten nie und werden nach 24 h still "
                        "`cancelled`. Zurueckrollen: Repo-Variable auf einen erlaubten "
                        "Wert setzen oder loeschen."
                    ),
                )
            )

    return findings


def fetch_live_values(repo: str, token: str, fetcher: Any = None) -> dict[str, str]:
    """Die aktuell gesetzten Repo-Variablen, ueber die Actions-API.

    ``fetcher`` ist injizierbar, damit die Tests ohne Netz laufen. Die Vorgabe ist
    der geteilte GitHub-Helfer aus ``check_workflow_freshness`` -- absichtlich
    wiederverwendet statt neu geschrieben, damit hier keine zusaetzliche
    ``urlopen``-Stelle entsteht (Ledger in tests/test_http_client_discipline.py).
    """
    if fetcher is None:
        from scripts.check_workflow_freshness import _default_fetcher

        fetcher = _default_fetcher

    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "skipp-algo-runner-label-watch",
    }

    values: dict[str, str] = {}
    page = 1
    seen = 0
    while True:
        url = f"{_GITHUB_API}/repos/{repo}/actions/variables?per_page=100&page={page}"
        payload = fetcher(url, headers)
        if not isinstance(payload, dict) or "variables" not in payload:
            raise ValueError(f"unerwartete API-Antwort auf Seite {page}: {type(payload).__name__}")
        batch = payload.get("variables") or []
        for item in batch:
            values[str(item["name"])] = str(item.get("value", ""))
        seen += len(batch)
        total = payload.get("total_count")
        # Paginieren, bis die API sich selbst fuer fertig erklaert. Ohne diese
        # Schleife wuerde ein Repo mit >100 Variablen eine Variable still
        # verlieren -- und eine fehlende Variable liest `evaluate` als "nicht
        # gesetzt", also im Zweifel als in Ordnung.
        if not batch or not isinstance(total, int) or seen >= total or page > 50:
            break
        page += 1
    return values


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    args = parser.parse_args(argv)

    # Bewusst keine `a or b`-Kette ueber zwei verschiedene Schluessel: welche
    # Quelle gegriffen hat, gehoert in die Ausgabe. Eine stille Kette macht aus
    # "das falsche Token war gesetzt" ein unauffindbares 403.
    token = os.environ.get("GITHUB_TOKEN", "")
    token_source = "GITHUB_TOKEN"
    if not token:
        token = os.environ.get("GH_TOKEN", "")
        token_source = "GH_TOKEN"
    if not token:
        token_source = "<keins gesetzt>"

    if not args.repo or not token:
        print(
            "::error title=runner-label-variable-watch::Sonde ungueltig -- "
            "--repo und GITHUB_TOKEN/GH_TOKEN muessen gesetzt sein. "
            "Nicht als Erfolg gewertet.",
            file=sys.stderr,
        )
        return 8

    try:
        allowlist = load_allowlist()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"::error title=runner-label-variable-watch::Allowlist unlesbar: {exc}", file=sys.stderr)
        return 8

    derived = derive_runner_variables()
    if not derived:
        # Positivkontrolle: dieses Repo HAT variablengesteuerte runs-on. Eine
        # leere Ableitung heisst, dass der Scanner nichts gefunden hat -- ein
        # Sondenfehler, kein sauberes Ergebnis.
        print(
            "::error title=runner-label-variable-watch::Sonde ungueltig -- kein "
            "einziges variablengesteuertes `runs-on` gefunden. Entweder ist das "
            "Workflow-Verzeichnis leer oder der Scanner ist blind geworden.",
            file=sys.stderr,
        )
        return 8

    try:
        live = fetch_live_values(args.repo, token)
    # Breit gefangen mit Absicht: JEDE Stoerung auf dem Weg zur API (Netz, TLS,
    # 401, kaputtes JSON) ist ein Sondenfehler und muss zu rc=8 fuehren, nicht zu
    # einem stillen "keine Befunde". Ein enger except-Zweig haette hier genau die
    # Ausfallart durchgelassen, gegen die diese Sonde gebaut ist.
    except Exception as exc:
        print(
            f"::error title=runner-label-variable-watch::Sonde ungueltig -- "
            f"Actions-Variablen nicht lesbar: {exc}",
            file=sys.stderr,
        )
        return 8

    findings = evaluate(derived, allowlist, live)

    lines = [
        "## runner-label-variable-watch",
        "",
        f"Geprueft: {len(derived)} variablengesteuerte `runs-on`-Variablen "
        f"ueber {len(set(f for files in derived.values() for f in files))} Workflow-Dateien.",
        "",
        "| Variable | Wert | Lanes | Urteil |",
        "|---|---|---|---|",
    ]
    for name, files in derived.items():
        value = live.get(name) or "<unset>"
        bad = [f for f in findings if f.variable == name]
        verdict = "OK" if not bad else bad[0].kind
        lines.append(f"| `{name}` | `{value}` | {len(files)} | {verdict} |")
    for finding in findings:
        lines += ["", f"**{finding.variable}** — {finding.detail}"]

    lines += ["", f"Token-Quelle: `{token_source}`."]

    # Ausgabe geht nach stdout, NICHT in eine Datei: der Aufrufer leitet sie mit
    # `| tee -a "$GITHUB_STEP_SUMMARY"` weiter (Muster aus proof-ledger-monitor).
    # Ein eigener Schreibpfad hier waere eine zweite Wahrheit ueber denselben
    # Bericht -- und eine Rohschreibstelle in scripts/, die das Atomic-Write-
    # Ledger zu Recht anmerkt.
    print("\n".join(lines))

    for finding in findings:
        print(finding.as_error_annotation(), file=sys.stderr)

    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
