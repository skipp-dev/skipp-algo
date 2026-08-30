"""Draht B: taeglicher Zustands-Poll ueber ALLE gepinnten Verbindungen.

Warum es das zusaetzlich zur Verbindungsprobe gibt — zwei Gruende, beide
gemessen:

1. **Die Probe deckt nur die READ-Seite.** ``composio_canary.py`` fuehrt vier
   nicht-mutierende Proben, alle mit ``access="read"``. Die vier
   WRITE-Verbindungen (Alert-DMs nach Slack, Research-Digest nach Notion,
   Ops-Digest nach Outlook, Incident-Issues nach GitHub) hat nie etwas
   geprueft — sie waeren erst im Ernstfall als tot aufgefallen, also genau
   dann, wenn ein Alarm zugestellt werden soll.
2. **Der Webhook ist kein Netz.** ``composio.connected_account.expired``
   feuert zwar nach einem gescheiterten Refresh, aber Composio dokumentiert
   dafuer weder ein Zustell-SLA noch Retry oder Dead-Letter (Recherche
   2026-08-30). Ein verlorenes Ereignis waere unbemerkbar. Dieser Poll ist
   die Untergrenze: er sieht den Zustand spaetestens am naechsten Morgen.

**Kein Doppelgaenger zur Probe.** Die beiden messen Verschiedenes und haben
sich am 2026-08-26 nachweislich widersprochen: die API meldete alle Accounts
``ACTIVE``, waehrend die Proben ``token_revoked`` bzw. HTTP 401 zurueckgaben.
Der Poll fragt "was sagt Composio ueber den Account", die Probe "kommt ein
echter Aufruf durch". Ein gruener Poll ist deshalb ausdruecklich KEIN Beweis
fuer gueltige Credentials — nur ein rot gewordener Poll ist ein Beweis fuer
das Gegenteil.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

try:
    import composio_ops
except ImportError:
    from scripts import composio_ops

TOOLKITS = ("SLACK", "GITHUB", "OUTLOOK", "NOTION")
ACCESS = ("READ", "WRITE")

# Alles ausser ACTIVE ist ein Befund. Bewusst eine ALLOW-Liste: ein neuer,
# hier unbekannter Status (Composio fuehrt u.a. INITIALIZING, INITIATED,
# EXPIRED, FAILED) darf nicht still als gesund durchgehen — das ist dieselbe
# Deny-vs-Allow-Lehre wie beim meta-watchdog (#5199).
_GESUND = "ACTIVE"


def pinned_accounts(environ: dict[str, str] | None = None) -> dict[str, str]:
    """``<toolkit>.<access>`` -> ``ca_…``, nur was wirklich gepinnt ist.

    Eine fehlende Variable ist hier KEIN Fehler: nicht jede Kombination
    existiert (die WRITE_AUTH_CONFIG-Seite etwa gibt es bewusst nicht). Was
    fehlt, wird nicht behauptet — gezaehlt wird nur, was da ist.
    """
    env = environ if environ is not None else dict(os.environ)
    treffer: dict[str, str] = {}
    for toolkit in TOOLKITS:
        for access in ACCESS:
            wert = env.get(f"COMPOSIO_{toolkit}_{access}_ACCOUNT_ID", "").strip()
            if wert:
                treffer[f"{toolkit.lower()}.{access.lower()}"] = wert
    return treffer


def fetch_accounts(api_key: str, *, opener: Any = None) -> dict[str, dict[str, Any]]:
    """``ca_…`` -> Account-Datensatz, ueber alle Seiten hinweg."""
    treffer: dict[str, dict[str, Any]] = {}
    cursor: str | None = None
    for _ in range(10):  # Seitenschranke; 13 Accounts heute, 500 waeren viel
        url = f"{composio_ops._base_url()}/api/v3/connected_accounts?limit=50"
        if cursor:
            url = f"{url}&cursor={urllib.parse.quote(cursor)}"
        request = urllib.request.Request(
            url,
            headers={"x-api-key": api_key, "User-Agent": "skipp-algo-composio-poll/1"},
        )
        client = opener or urllib.request.build_opener()
        with client.open(request, timeout=25) as response:  # nosec B310 - Composio-Host
            payload = json.loads(response.read().decode("utf-8"))
        for eintrag in payload.get("items") or []:
            if isinstance(eintrag, dict) and eintrag.get("id"):
                treffer[str(eintrag["id"])] = eintrag
        cursor = payload.get("next_cursor") or None
        if not cursor:
            break
    return treffer


def evaluate(
    gepinnt: dict[str, str], vorhanden: dict[str, dict[str, Any]]
) -> tuple[list[str], list[str]]:
    """-> (befunde, ok). Reine Funktion, damit ohne Netz testbar."""
    befunde: list[str] = []
    ok: list[str] = []
    for name, account_id in sorted(gepinnt.items()):
        eintrag = vorhanden.get(account_id)
        if eintrag is None:
            # Gepinnt, aber im Projekt nicht auffindbar: geloescht, oder der
            # Pin zeigt auf eine fremde Entity. Genau der Zustand vom 26.8.,
            # als ein Dashboard-Reconnect Accounts unter pg-test-<uuid> anlegte.
            befunde.append(
                f"{name} ({account_id}): im Projekt NICHT GEFUNDEN — geloescht "
                "oder der Pin zeigt auf eine fremde Entity"
            )
            continue
        status = str(eintrag.get("status", "?"))
        if status != _GESUND:
            grund = str(eintrag.get("status_reason") or "kein status_reason")
            befunde.append(f"{name} ({account_id}): status={status} — {grund}")
        elif eintrag.get("is_disabled"):
            befunde.append(f"{name} ({account_id}): ACTIVE, aber is_disabled=true")
        else:
            ok.append(f"{name} ({account_id}): {status}")
    return befunde, ok


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output")
    args = parser.parse_args(argv)

    gepinnt = pinned_accounts()
    if not gepinnt:
        # Vakuitaetsboden: ohne einen einzigen Pin prueft dieser Poll NICHTS
        # und darf das nicht als Erfolg melden.
        print(
            "::error title=composio-poll::keine einzige COMPOSIO_*_ACCOUNT_ID "
            "gesetzt — dieser Poll haette nichts geprueft.",
            file=sys.stderr,
        )
        return 1

    try:
        vorhanden = fetch_accounts(composio_ops._api_key())
    except (urllib.error.URLError, OSError, ValueError, KeyError, RuntimeError) as exc:
        print(f"::error title=composio-poll::Abruf fehlgeschlagen: {exc}", file=sys.stderr)
        return 1

    befunde, ok = evaluate(gepinnt, vorhanden)

    for zeile in ok:
        print(f"  OK      {zeile}")
    for zeile in befunde:
        print(f"  BEFUND  {zeile}")
        print(f"::error title=composio-poll::{zeile}")

    print(f"gepinnt: {len(gepinnt)} · gesund: {len(ok)} · Befunde: {len(befunde)}")

    if args.output:
        from scripts.smc_atomic_write import atomic_write_text

        atomic_write_text(
            json.dumps(
                {"ok": not befunde, "checked": len(gepinnt), "findings": befunde},
                indent=2,
                sort_keys=True,
            )
            + "\n",
            args.output,
        )

    return 1 if befunde else 0


if __name__ == "__main__":
    sys.exit(main())
