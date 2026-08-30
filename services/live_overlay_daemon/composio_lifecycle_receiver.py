"""Draht A: das Ablauf-Ereignis einer Composio-Verbindung entgegennehmen.

Aus der Recherche vom 2026-08-30: eine Vorwarnung vor dem Ablauf gibt es
NICHT. ``composio.connected_account.expired`` ist das einzige dokumentierte
Signal, und es feuert erst NACH einem gescheiterten Refresh — typischerweise
vor dem naechsten Cron-Aufruf, aber ohne Zusage. Der Katalog-Abruf mit echtem
Key hat am 2026-08-30 bestaetigt, dass unser Projekt genau drei Ereignisse
abonnieren kann und dieses **nur in Webhook-Version V3** existiert.

**Warum der Alarm NICHT ueber Composio geht.** Der naheliegende Weg waere ein
Slack-DM oder ein GitHub-Issue wie im Grafana-Fanout nebenan — beide laufen
aber durch ``composio_ops``, also durch genau die Schicht, deren Tod hier
gemeldet wird. Stirbt die Slack-Verbindung, faellt die Slack-Meldung mit ihr;
und die GitHub-Route ebenso, wenn es GitHub trifft. Ein Alarm, der seinen
eigenen Ausfall melden soll, darf nicht durch das ausgefallene System laufen.

Deshalb: dieser Empfaenger **liefert nichts aus**. Er schreibt den Befund in
das Ledger und haelt ihn im Prozesszustand, aus dem die ``/metrics``-Flaeche
eine Gauge bildet. Prometheus HOLT die ab, Grafana alarmiert daraus — beides
ohne jede Composio-Beteiligung.

**Was dieser Draht NICHT ist:** ein Ersatz fuer den taeglichen Zustands-Poll.
Composio dokumentiert weder Zustell-SLA noch Retry noch Dead-Letter; ein
verlorenes Ereignis waere unbemerkbar. Der Poll bleibt der fail-closed-Boden,
dieser Empfaenger ist das schnelle, aber unzuverlaessige Signal darueber.
"""

from __future__ import annotations

import datetime as dt
import hmac
import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi import Path as ApiPath

router = APIRouter()
logger = logging.getLogger(__name__)

_EXPIRY_EVENT = "composio.connected_account.expired"
# Gemessen am 2026-08-30 gegen den eigenen Projekt-Key: dieses Ereignis gibt
# es NUR in V3. Ein Abonnement in V1/V2 bekaeme es nie zu sehen.
_REQUIRED_WEBHOOK_VERSION = "V3"
_MAX_BODY_BYTES = 16_384

_lock = threading.Lock()
_expired: dict[str, dict[str, Any]] = {}


def _ledger_path() -> Path:
    override = os.getenv("COMPOSIO_LIFECYCLE_LEDGER", "").strip()
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[2] / "artifacts" / "monitoring" / "composio_lifecycle.jsonl"


def expired_connections() -> dict[str, dict[str, Any]]:
    """Kopie des Befundstands — die Quelle der Gauge in ``metrics.py``."""
    with _lock:
        return {key: dict(value) for key, value in _expired.items()}


def reset_state() -> None:
    """Nur fuer Tests: der Prozesszustand ist sonst absichtlich langlebig."""
    with _lock:
        _expired.clear()


def _resolve(data: dict[str, Any], keys: tuple[str, ...]) -> tuple[str, str]:
    """-> (Wert, HERKUNFT). Nie eine ``or``-Kette ueber verschiedene Schluessel.

    Composio hat die Feldnamen zwischen v2 und v3 umbenannt und liefert je
    nach Ereignis snake_case oder camelCase, deshalb ueberhaupt mehrere
    Kandidaten. Eine ``a or b or c``-Kette wuerde aber verschweigen, WELCHER
    gegriffen hat — und wenn der Empfaenger spaeter das Falsche liest, steht
    im Ledger ein plausibler Wert ohne Hinweis auf seine Herkunft. Der
    Repo-Waechter gegen genau dieses Muster verlangt die ausdrueckliche
    Aufloesung samt Quelle (docs/review-checklist-field-preference-chains.md).
    """
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value:
            return value, key
        if isinstance(value, dict):
            nested = value.get("slug")
            if isinstance(nested, str) and nested:
                return nested, f"{key}.slug"
    return "unbekannt", "keiner"


def record(payload: dict[str, Any], *, now: dt.datetime | None = None) -> dict[str, Any]:
    """Ereignis bewerten und festhalten. Rein genug, um ohne HTTP zu testen."""
    # Auch hier ausdrueckliche Aufloesung statt `or`-Kette: der V3-Umschlag
    # fuehrt `type`, aeltere Beispiele in der Doku `event`. Welcher gegriffen
    # hat, gehoert in die Antwort — sonst debuggt man spaeter im Nebel.
    event_type, typ_quelle = _resolve(payload, ("type", "event"))
    if event_type != _EXPIRY_EVENT:
        # Fremde Ereignisse mit 200 quittieren: ein Fehlercode brächte
        # Composio nur zum Wiederholen, und wir wollen nichts davon.
        return {
            "ok": True,
            "recorded": False,
            "reason": f"ignoriert: {event_type} (Feld {typ_quelle})",
        }

    data = payload.get("data")
    data = data if isinstance(data, dict) else {}
    stamp = (now or dt.datetime.now(dt.UTC)).isoformat()
    account, account_quelle = _resolve(
        data, ("connected_account_id", "connectedAccountId", "id", "nanoid")
    )
    toolkit, toolkit_quelle = _resolve(
        data, ("toolkit_slug", "toolkitSlug", "toolkit", "app_name")
    )
    user, user_quelle = _resolve(data, ("user_id", "userId"))
    eintrag = {
        "account_id": account,
        "toolkit": toolkit.lower(),
        "user_id": user,
        "received_at": stamp,
        "event_id": str(payload.get("id") or ""),
        "event_type_source": typ_quelle,
        # Herkunft mitschreiben: ohne sie steht im Ledger ein plausibler Wert,
        # und niemand kann spaeter sagen, welches Feld ihn geliefert hat.
        "field_sources": {
            "account_id": account_quelle,
            "toolkit": toolkit_quelle,
            "user_id": user_quelle,
        },
    }

    with _lock:
        _expired[account] = eintrag

    # ERROR, nicht WARNING: eine abgelaufene Verbindung ist unbeaufsichtigt
    # NICHT heilbar (der refresh-Endpunkt ist deprecated und liefert eine
    # Redirect-URL fuer einen Menschen). Das braucht Handarbeit.
    logger.error(
        "Composio-Verbindung abgelaufen: toolkit=%s account=%s user=%s — "
        "unbeaufsichtigt nicht heilbar, Connect-Link per API noetig",
        eintrag["toolkit"], account, eintrag["user_id"],
    )

    pfad = _ledger_path()
    try:
        pfad.parent.mkdir(parents=True, exist_ok=True)
        with open(pfad, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(eintrag, sort_keys=True) + "\n")
    except OSError as exc:
        # Das Ledger ist die Nachlese, der Prozesszustand traegt die Gauge.
        # Ein nicht schreibbarer Pfad darf das Ereignis nicht verschlucken.
        logger.warning("Composio-Lifecycle-Ledger nicht schreibbar (%s): %s", pfad, exc)

    return {"ok": True, "recorded": True, "toolkit": eintrag["toolkit"], "account_id": account}


@router.api_route("/{token}/composio-lifecycle", methods=["POST"], include_in_schema=False)
async def webhook(request: Request, token: str = ApiPath(...)) -> dict[str, Any]:
    expected = os.getenv("COMPOSIO_LIFECYCLE_WEBHOOK_TOKEN", "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="Composio lifecycle receiver is not configured")
    # bytes: ein nicht-ASCII-Token im Pfad liesse die str-Form werfen.
    if not hmac.compare_digest(token.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="invalid webhook token")

    roh = await request.body()
    if len(roh) > _MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="webhook body too large")
    try:
        payload = json.loads(roh.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail="invalid JSON body") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="webhook body must be an object")

    return record(payload)
