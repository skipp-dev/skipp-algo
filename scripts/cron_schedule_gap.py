"""Groesster LEGITIMER Abstand zwischen zwei Cron-Feuerungen — aus dem cron abgeleitet.

Ein Freshness-Budget unterhalb dieses Abstands erzeugt garantiert wiederkehrenden
Fehlalarm: der Workflow ist dann stale, obwohl er exakt nach Plan laeuft. Das ist
eine harte, nicht willkuerliche Untergrenze — im Gegensatz zu einer Obergrenze,
die eine Ermessensfrage waere.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

_DOW = {"sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6}
_MON = {
    m: i + 1
    for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
    )
}


def _feld(roh: str, tief: int, hoch: int, namen: dict[str, int]) -> set[int]:
    werte: set[int] = set()
    for teil in roh.split(","):
        schritt = 1
        if "/" in teil:
            teil, s = teil.split("/", 1)
            schritt = int(s)
        if teil in ("*", "?"):
            a, b = tief, hoch
        elif "-" in teil.strip("-"):
            a_s, b_s = teil.split("-", 1)
            a, b = _einzeln(a_s, namen), _einzeln(b_s, namen)
        else:
            a = b = _einzeln(teil, namen)
        werte.update(range(a, b + 1, schritt))
    return werte


def _einzeln(roh: str, namen: dict[str, int]) -> int:
    roh = roh.strip().lower()
    return namen[roh] if roh in namen else int(roh)


def feuerungen(cron: str, start: datetime, tage: int) -> list[datetime]:
    minute_s, stunde_s, dom_s, monat_s, dow_s = cron.split()
    minuten = _feld(minute_s, 0, 59, {})
    stunden = _feld(stunde_s, 0, 23, {})
    dom = _feld(dom_s, 1, 31, {})
    monate = _feld(monat_s, 1, 12, _MON)
    dow = {d % 7 for d in _feld(dow_s, 0, 7, _DOW)}
    dom_frei = dom_s.strip() in ("*", "?")
    dow_frei = dow_s.strip() in ("*", "?")

    raus: list[datetime] = []
    tag = start.replace(hour=0, minute=0, second=0, microsecond=0)
    for _ in range(tage):
        # POSIX: sind BEIDE Tagesfelder eingeschraenkt, gilt ODER, nicht UND.
        d_ok = tag.day in dom
        w_ok = ((tag.weekday() + 1) % 7) in dow
        treffer = (d_ok and w_ok) if (dom_frei or dow_frei) else (d_ok or w_ok)
        if tag.month in monate and treffer:
            for h in sorted(stunden):
                for m in sorted(minuten):
                    raus.append(tag.replace(hour=h, minute=m))
        tag += timedelta(days=1)
    return raus


def _werktagsstunden(a: datetime, b: datetime) -> float:
    """Stunden zwischen a und b, Samstag/Sonntag (UTC) abgezogen."""
    ges = 0.0
    cur = a
    while cur < b:
        naechster = min(b, (cur + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0))
        if naechster <= cur:
            naechster = cur + timedelta(hours=1)
        naechster = min(naechster, b)
        if cur.weekday() not in (5, 6):
            ges += (naechster - cur).total_seconds() / 3600
        cur = naechster
    return ges


def groesster_abstand(crons: str | list[str], werktags: bool) -> float:
    """Groesster Abstand in Stunden ueber ein volles Jahr (faengt Monats-Crons).

    Mehrere ``schedule``-Eintraege werden VEREINIGT, nicht einzeln bewertet: der
    Abstand der zusammengelegten Feuerungsliste ist der einzige, den der Workflow
    tatsaechlich erlebt. Das Minimum ueber die Einzel-Crons ist eine OBERGRENZE
    davon und haette korrekte Budgets als zu eng angeklagt.
    """
    if isinstance(crons, str):
        crons = [crons]
    start = datetime(2026, 1, 1, tzinfo=UTC)
    f = sorted({t for cron in crons for t in feuerungen(cron, start, 400)})
    if len(f) < 2:
        return float("inf")
    # Rand verwerfen: das Fenster schneidet den ersten/letzten Abstand ab.
    kern = f[1:-1] if len(f) > 3 else f
    best = 0.0
    for i in range(len(kern) - 1):
        d = (
            _werktagsstunden(kern[i], kern[i + 1])
            if werktags
            else (kern[i + 1] - kern[i]).total_seconds() / 3600
        )
        best = max(best, d)
    return best
