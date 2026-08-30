"""Was hat sich seit unserem Pin geaendert? — der Aenderungstext zur Drift.

Der Recherchebericht vom 2026-08-30 liess Frage 3 (Tool-Versions-Pinning)
offen: keine der gepruefen Behauptungen belegte einen offiziellen Drift-Kanal.
Der Aufruf mit echtem ``ak_``-Key beantwortete es —
``GET /api/v3/toolkits/changelog`` liefert 1497 Toolkits, je mit absteigender
Versionsliste UND dem Aenderungstext je Version.

**Dieses Skript faellt bewusst KEIN Urteil.** Ob ein Pin veraltet ist,
entscheidet bereits ``composio_contract_check.py`` gegen
``/api/v3.1/tools?toolkit_versions=latest``. Zwei Urteile ueber dieselbe
Tatsache aus zwei Quellen sind genau das Doppelgaenger-Muster, gegen das
dieses Repo einen eigenen Sweep faehrt: sie driften auseinander, und dann
glaubt man der falschen. Der Beitrag hier ist die Frage, die der
Contract-Check NICHT beantwortet — *was* sich geaendert hat, also ob die
Drift Kosmetik oder ein Schema-Bruch ist.

Beispiel aus der Messung: Notion ``20260819_00`` — "Webhook trigger response
schemas now use explicit match operators for filter fields". Das ist eine
Aussage, mit der ein Operator etwas anfangen kann; "Version ist alt" nicht.

Folge fuer den Exit-Code: 0, solange das Skript berichten konnte. Ein nicht
erreichbarer Kanal ist eine Warnung, kein Job-Fehlschlag — er wuerde sonst
den Canary faellen, ohne dass an den Verbindungen etwas waere. Der Preis ist,
dass ein dauerhaft toter Kanal nur als Warnung sichtbar waere; abgesichert
ist dagegen, dass die AUSGABE stimmt (Guard-Test ueber eine gedriftete
Fixture), nicht bloss dass das Skript laeuft.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from typing import Any

try:
    import composio_ops
except ImportError:
    from scripts import composio_ops

# Die Antwort ist ~2,7 MB (1497 Toolkits). Mit dem 20-s-Standard der
# Nachbarskripte lief der Abruf am 2026-08-30 in einen Read-Timeout.
_TIMEOUT = 120.0


def fetch_changelog(api_key: str, *, opener: Any = None) -> dict[str, dict[str, Any]]:
    """``toolkit-name`` (klein) -> Katalogeintrag mit ``versions``."""
    request = urllib.request.Request(
        f"{composio_ops._base_url()}/api/v3/toolkits/changelog",
        headers={"x-api-key": api_key, "User-Agent": "skipp-algo-composio-drift/1"},
    )
    client = opener or urllib.request.build_opener()
    with client.open(request, timeout=_TIMEOUT) as response:  # nosec B310 - Composio-Host
        payload = json.loads(response.read().decode("utf-8"))
    return {str(item.get("name", "")).lower(): item for item in payload.get("items", [])}


def drift_lines(
    pinned: dict[str, str], catalog: dict[str, dict[str, Any]]
) -> list[str]:
    """Je Toolkit eine Zusammenfassung — rein, also ohne Netz testbar."""
    zeilen: list[str] = []
    for toolkit, version in sorted(pinned.items()):
        eintrag = catalog.get(toolkit)
        if eintrag is None:
            zeilen.append(f"::warning title=composio-drift::{toolkit}: nicht im Katalog")
            continue
        versionen = [str(v.get("version", "")) for v in eintrag.get("versions") or []]
        if not versionen:
            zeilen.append(f"::warning title=composio-drift::{toolkit}: Katalog ohne Versionen")
            continue
        if versionen[0] == version:
            zeilen.append(f"  aktuell  {toolkit}: {version}")
            continue
        if version not in versionen:
            zeilen.append(
                f"::warning title=composio-drift::{toolkit}: gepinnte Version "
                f"{version} steht NICHT im Katalog (zurueckgezogen?), neueste "
                f"ist {versionen[0]}"
            )
            continue
        neuer = eintrag["versions"][: versionen.index(version)]
        zeilen.append(
            f"::warning title=composio-drift::{toolkit}: {len(neuer)} Version(en) "
            f"hinter {versionen[0]} (gepinnt {version})"
        )
        for v in neuer:
            text = " ".join(str(v.get("changelog", "")).split())
            text = text.replace(f"## Changelog for `{toolkit}`", "").strip()
            zeilen.append(f"    {v.get('version')}: {text[:300] or '(leerer Changelog)'}")
    return zeilen


def pinned_versions() -> dict[str, str]:
    """``toolkit`` -> gepinnte Version, aus configs/composio_tools.json."""
    treffer: dict[str, str] = {}
    for spec in composio_ops.tool_registry().values():
        treffer.setdefault(str(spec["toolkit"]), str(spec["version"]))
    return treffer


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)

    pinned = pinned_versions()
    if not pinned:
        print(
            "::error title=composio-drift::die Pin-Registry ist leer — "
            "dieser Bericht haette nichts verglichen.",
            file=sys.stderr,
        )
        return 1

    try:
        catalog = fetch_changelog(composio_ops._api_key())
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, RuntimeError) as exc:
        # Warnung, kein Fehlschlag: siehe Modul-Docstring.
        print(f"::warning title=composio-drift::Drift-Kanal nicht erreichbar: {exc}")
        return 0

    for zeile in drift_lines(pinned, catalog):
        print(zeile)
    return 0


if __name__ == "__main__":
    sys.exit(main())
