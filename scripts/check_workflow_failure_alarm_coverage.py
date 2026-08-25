#!/usr/bin/env python3
"""Sieht der Workflow-Fehleralarm die merge-kritischen Workflows WIRKLICH?

Der Grafana-Alarm ``lo-workflow-run-failed`` ("Monitored workflow latest run
failed") wertet ``live_overlay_github_workflow_phase_code`` aus. Welche
Workflows dort auftauchen, entscheidet **keine Repo-Datei**, sondern die
Umgebungsvariable ``GITHUB_WORKFLOW_MONITOR_IDS`` auf dem live_overlay_daemon —
eine Liste von Workflow-IDs, die nichts im Repo deklariert, testet oder
dokumentiert. Ein Tippfehler, ein vergessener Eintrag oder ein zurueckgesetztes
Deployment macht den Alarm fuer einen Workflow blind, ohne dass irgendetwas rot
wird: die Alarmregel steht auf ``noDataState: OK``, und eine fehlende Zeitreihe
ist genau kein Datum.

Gemessen am 2026-08-20: 26 IDs konfiguriert, **8** Zeitreihen vorhanden, und
``smc-fast-pr-gates`` in keiner der beiden Mengen — obwohl seit der Umstellung
auf ``strict_required_status_checks_policy: false`` der main-Lauf das
Rueckfangnetz ist.

**Warum die Pruefung nicht einfach "Zeitreihe muss existieren" lautet.**
Die Bruecke holt EINE Seite der neuesten Laeufe auf ``main`` (``per_page``,
Vorgabe 100) und filtert sie gegen die ID-Liste. Am 2026-08-20 deckte diese
Seite ``14:28Z``-``19:27Z`` ab, also rund fuenf Stunden. Ein Workflow, dessen
letzter main-Lauf aelter ist, hat schlicht keine Zeitreihe — voellig unabhaengig
davon, ob er konfiguriert ist. Eine Pruefung, die daraus einen Fehlschlag macht,
wuerde jedes ruhige Wochenende Fehlalarm geben.

Deshalb prueft dieses Skript nur dort, wo die Vorbedingung **belegt** ist:
Taucht der Workflow in derselben Seite auf, die auch die Bruecke sieht, dann
MUSS er eine Zeitreihe haben. Taucht er nicht auf, gibt es keine Aussage — und
das Skript sagt das, statt es als Erfolg zu verbuchen.

Exit-Codes
----------
0   jede belegbare Forderung erfuellt
1   ein Workflow ist in der Seite, hat aber keine Zeitreihe -> Alarm ist blind
8   Sonde ungueltig (kein Token, keine Serien ueberhaupt, leere Lauf-Seite)

Aufruf::

    GITHUB_TOKEN=$(gh auth token) GRAFANA_API_KEY=... \
        python -m scripts.check_workflow_failure_alarm_coverage
"""

from __future__ import annotations

import os
import sys
import time
import urllib.error
import urllib.parse
from collections.abc import Callable
from typing import Any

try:
    from scripts.check_workflow_freshness import _default_fetcher
    from scripts.grafana_alert_rules_upsert import _api_key, _request
except ImportError as exc:  # pragma: no cover - invocation-style guard
    raise SystemExit(
        "run as `python -m scripts.check_workflow_failure_alarm_coverage` from the "
        f"repo root (the shared HTTP helpers must be importable): {exc}"
    ) from exc

# Workflow-DATEI -> warum ihr Fehlschlag auf main gesehen werden muss.
#
# Die Datei ist der Schluessel, nicht der Anzeigename: der Name steht im YAML
# und laesst sich aendern, ohne dass jemand hier vorbeikommt. Die Aufloesung
# Datei -> Name passiert unten ueber die GitHub-API, damit eine Umbenennung
# diesen Waechter nicht still leerlaufen laesst.
REQUIRED_WORKFLOWS: dict[str, str] = {
    "smc-fast-pr-gates.yml": (
        "einziger required Check. Seit strict_required_status_checks_policy=false "
        "(2026-08-20) kann ein PR mergen, ohne gegen das neueste main geprueft zu "
        "sein -- der main-Lauf IST das Rueckfangnetz. Seine Nicht-pytest-Schritte "
        "(ruff, actionlint, zizmor, TS-Vakuitaets-Guard, Docker-Bau und Start-Probe, "
        "Dashboard- und Manifest-Drift) laufen in KEINEM anderen Workflow."
    ),
    "ci.yml": (
        "faehrt auf main die volle Suite ueber vier Shards. Faengt den semantischen "
        "Konflikt zweier je gruener PRs -- die Ausfallart, die strict=false einfuehrt."
    ),
}

PROM_DATASOURCE_UID = "grafanacloud-prom"
METRIC = 'live_overlay_github_workflow_phase_code{job="live_overlay"}'
DEFAULT_REPO = "skipp-dev/skipp-algo"
# Muss zu GITHUB_WORKFLOW_MONITOR_PER_PAGE des Daemons passen; dessen Vorgabe
# ist 100 (services/live_overlay_daemon/config.py). Sieht dieses Skript eine
# GROESSERE Seite als die Bruecke, faende es Workflows, die sie nie sieht, und
# meldete Fehlalarm. Kleiner ist unschaedlich (weniger belegbare Forderungen).
RUN_PAGE_SIZE = 100


class ProbeInvalidError(RuntimeError):
    """Die Sonde konnte nichts messen. Kein Ergebnis, kein Befund."""


# 2026-08-25: der Cron-Lauf 32821936783 starb an einem EINZELNEN GitHub-503
# (SONDE UNGUELTIG, exit 8) — die Historie davor war taeglich gruen. Ein
# Transient soll die Sonde nicht faellen.
_TRANSIENT_VERSUCHE = 3
_TRANSIENT_BACKOFF_S = 4.0


def _mit_transient_retry(
    fn: Callable[..., Any],
    /,
    *args: Any,
    schlaf: Callable[[float], None] = time.sleep,
) -> Any:
    """Idempotente GET-Abrufe gegen 5xx-/Netz-Transienten haerten.

    Nur Transienten werden wiederholt: HTTP >= 500, URLError, Timeout. Ein
    ECHTER Fehler (4xx wie 401/403, kaputtes JSON, ProbeInvalidError) bleibt
    sofort laut. Nach dem letzten Versuch wird die Ausnahme unveraendert
    weitergereicht — der Exit bleibt 8, die Sonde bleibt fail-closed.
    """
    letzte: Exception | None = None
    for versuch in range(1, _TRANSIENT_VERSUCHE + 1):
        try:
            return fn(*args)
        except urllib.error.HTTPError as exc:  # Subklasse von URLError: zuerst
            if exc.code < 500:
                raise
            letzte = exc
        except (urllib.error.URLError, TimeoutError) as exc:
            letzte = exc
        if versuch < _TRANSIENT_VERSUCHE:
            print(
                f"transient ({letzte}) — Versuch {versuch}/{_TRANSIENT_VERSUCHE}, "
                f"neuer Versuch in {_TRANSIENT_BACKOFF_S:.0f}s",
                file=sys.stderr,
            )
            schlaf(_TRANSIENT_BACKOFF_S)
    if letzte is None:  # pragma: no cover - Schleife endet nur nach Ausnahme
        raise RuntimeError("Retry-Schleife endete ohne Ergebnis und ohne Ausnahme")
    raise letzte


def _prom_datasource_id(key: str) -> int:
    sources = _request("GET", "/api/datasources", key)
    for src in sources:
        if src.get("uid") == PROM_DATASOURCE_UID:
            return int(src["id"])
    raise ProbeInvalidError(
        f"Datenquelle {PROM_DATASOURCE_UID!r} nicht gefunden "
        f"(vorhanden: {sorted(str(s.get('uid')) for s in sources)[:8]})"
    )


def observed_workflows(key: str) -> set[str]:
    """Workflow-Namen, fuer die der Alarm ueberhaupt Daten hat."""
    ds_id = _prom_datasource_id(key)
    query = urllib.parse.quote(METRIC)
    res = _request("GET", f"/api/datasources/proxy/{ds_id}/api/v1/query?query={query}", key)
    result = ((res or {}).get("data") or {}).get("result") or []
    names = {str(item.get("metric", {}).get("workflow", "")) for item in result}
    names.discard("")
    if not names:
        raise ProbeInvalidError(
            "die Metrik liefert NULL Zeitreihen. Das ist kein 'alles unbeobachtet', "
            "sondern eine kaputte Sonde oder eine tote Bruecke -- ein Ergebnis waere "
            "hier eine Luege."
        )
    return names


def _gh(url: str, token: str) -> dict[str, Any]:
    return _default_fetcher(
        url,
        {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )


def workflow_names_by_file(repo: str, token: str) -> dict[str, str]:
    """Datei -> Anzeigename, ueber alle Seiten."""
    names: dict[str, str] = {}
    page = 1
    while page <= 10:
        payload = _gh(
            f"https://api.github.com/repos/{repo}/actions/workflows?per_page=100&page={page}",
            token,
        )
        batch = payload.get("workflows") or []
        if not batch:
            break
        for wf in batch:
            names[str(wf.get("path", "")).split("/")[-1]] = str(wf.get("name", ""))
        page += 1
    if not names:
        raise ProbeInvalidError("die Workflow-Liste des Repos kam leer zurueck")
    return names


def workflows_in_run_page(repo: str, token: str) -> set[str]:
    """Genau das Fenster, das auch die Bruecke sieht: neueste Laeufe auf main."""
    payload = _gh(
        f"https://api.github.com/repos/{repo}/actions/runs"
        f"?branch=main&per_page={RUN_PAGE_SIZE}",
        token,
    )
    runs = payload.get("workflow_runs") or []
    if not runs:
        raise ProbeInvalidError("die Lauf-Seite kam leer zurueck -- kein Fenster, keine Aussage")
    return {str(run.get("name", "")) for run in runs}


def evaluate(
    required: dict[str, str],
    names_by_file: dict[str, str],
    in_page: set[str],
    observed: set[str],
) -> tuple[list[str], list[str], list[str]]:
    """-> (blind, belegt_ok, ohne_aussage). Reine Funktion, damit testbar."""
    blind: list[str] = []
    ok: list[str] = []
    stumm: list[str] = []
    for datei in sorted(required):
        name = names_by_file.get(datei)
        if not name:
            # Datei weg oder umbenannt: das ist selbst ein Befund, kein Durchwinken.
            blind.append(f"{datei}: kein Workflow dieses Dateinamens im Repo")
            continue
        if name not in in_page:
            stumm.append(f"{datei} ({name}): kein main-Lauf im Fenster -- keine Aussage")
        elif name in observed:
            ok.append(f"{datei} ({name})")
        else:
            blind.append(
                f"{datei} ({name}): laeuft auf main, hat aber KEINE Zeitreihe -- "
                "der Alarm kann fuer ihn nicht feuern"
            )
    return blind, ok, stumm


def main(argv: list[str] | None = None) -> int:
    del argv
    repo = os.environ.get("GITHUB_WORKFLOW_ALARM_REPO") or DEFAULT_REPO
    # Kein `a or b`-Vorzugskette: der Waechter gegen genau dieses Muster verlangt
    # eine ausdrueckliche Aufloesung samt Herkunft, damit im Fehlerfall dransteht,
    # WELCHE Quelle gegriffen hat (docs/review-checklist-field-preference-chains.md).
    token = ""
    token_source = ""
    for kandidat in ("GITHUB_TOKEN", "GH_PAT"):
        wert = os.environ.get(kandidat, "").strip()
        if wert:
            token, token_source = wert, kandidat
            break
    if not token:
        print("SONDE UNGUELTIG: weder GITHUB_TOKEN noch GH_PAT gesetzt.", file=sys.stderr)
        return 8
    try:
        key = _api_key()
        observed = _mit_transient_retry(observed_workflows, key)
        names_by_file = _mit_transient_retry(workflow_names_by_file, repo, token)
        in_page = _mit_transient_retry(workflows_in_run_page, repo, token)
    except ProbeInvalidError as exc:
        print(f"SONDE UNGUELTIG: {exc}", file=sys.stderr)
        return 8
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        # Bewusst kein blankes `except Exception`: der Repo-Waechter gegen breite
        # Except-Stellen ist genau dafuer da. Diese vier decken Transport (OSError,
        # inkl. URLError/HTTPError), kaputtes JSON (ValueError), fehlende Felder
        # (KeyError) und die Helfer-Fehler (RuntimeError, u.a. fehlender API-Key).
        print(f"SONDE UNGUELTIG: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 8

    blind, ok, stumm = evaluate(REQUIRED_WORKFLOWS, names_by_file, in_page, observed)

    print(f"GitHub-Token aus    : {token_source}")
    print(f"Zeitreihen im Alarm : {len(observed)}")
    print(f"Workflows im Fenster: {len(in_page)}  (dieselbe Seite, die die Bruecke sieht)")
    for line in ok:
        print(f"  OK      {line}")
    for line in stumm:
        print(f"  --      {line}")
    for line in blind:
        print(f"  BLIND   {line}")

    if blind:
        print(
            "\nDer Fehleralarm ist fuer die obigen Workflows blind. Ursache ist fast "
            "immer GITHUB_WORKFLOW_MONITOR_IDS auf dem live_overlay_daemon: die Liste "
            "lebt NUR in der Railway-Umgebung, kein Repo-Artefakt deklariert sie.\n"
            "  railway ssh --service live_overlay_daemon -- sh -lc "
            "'printf \"%s\\n\" \"$GITHUB_WORKFLOW_MONITOR_IDS\"'\n"
            "  gh api repos/skipp-dev/skipp-algo/actions/workflows --paginate "
            "--jq '.workflows[]|\"\\(.id)\\t\\(.path)\"'",
            file=sys.stderr,
        )
        return 1
    if not ok:
        print(
            "\nKein einziger geforderter Workflow war belegbar -- alles 'keine Aussage'. "
            "Das ist kein Bestehen; die Pruefung hat nichts geprueft.",
            file=sys.stderr,
        )
        return 8
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
