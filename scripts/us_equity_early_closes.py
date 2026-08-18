"""US-Aktien-Fruehschluesse (13:00 ET) — Single Source fuer Gate und Flatten.

Review 2026-08-18 zu #4848, Important #2: An planmaessigen Halbtagen schliesst
der US-Kassamarkt 13:00 ET. Ein EOD-Flatten, der stur 15:45 ET feuert, kehrt
dort seinen Zweck um — reqGlobalCancel toetet die GTC-Schutz-Legs NACH dem
Close, die DAY-Market-Orders koennen nicht mehr ausfuehren, die Positionen
liegen ungeschuetzt ueber Nacht. Dieses Modul ist die EINZIGE Stelle, die
Fruehschluss-Daten kennt: die Shell (run-c13-eod-flatten.sh) fragt es fuer
das Gate-Ziel, der Flatten (c13_eod_flatten.py) fuer die After-Close-Sperre.

Quelle: NYSE-Feiertagskalender (https://www.nyse.com/markets/hours-calendars),
von Hand gepflegt. Der Horizont wird durch tests/test_us_equity_early_closes.py
erzwungen: laeuft er ab, roetet der Test mit Verlaengerungs-Anweisung —
der Kalender kann nicht still veralten.
"""

from __future__ import annotations

import argparse
from datetime import date

#: Planmaessige 13:00-ET-Schluesse. Juli-4.-Konstellationen, in denen der
#: Feiertag auf ein Wochenende faellt, haben KEINEN Halbtag (2026-07-03 war
#: ganztags geschlossen — beobachtet in open_prep/realtime_signals.py);
#: 2027-12-24 ist der beobachtete Weihnachts-FEIERTAG (25.12. = Samstag),
#: ebenfalls kein Halbtag.
EARLY_CLOSES_ET_1300: frozenset[date] = frozenset(
    {
        date(2026, 11, 27),  # Freitag nach Thanksgiving
        date(2026, 12, 24),  # Heiligabend (Donnerstag, Markt offen bis 13:00)
        date(2027, 11, 26),  # Freitag nach Thanksgiving
    }
)

#: Bis zu diesem Tag ist der Kalender GEPFLEGT (nicht: letzter Eintrag).
#: Der Horizont-Test roetet, sobald heute darueber liegt.
CALENDAR_HORIZON = date(2027, 12, 31)

_REGULAR_CLOSE = (16, 0)
_EARLY_CLOSE = (13, 0)
_FLATTEN_LEAD_MINUTES = 15


def close_time_et_hhmm(day: date) -> tuple[int, int]:
    """(HH, MM) des Kassaschlusses in ET fuer ``day``."""
    return _EARLY_CLOSE if day in EARLY_CLOSES_ET_1300 else _REGULAR_CLOSE


def flatten_target_et_hhmm(day: date) -> tuple[int, int]:
    """Gate-Ziel des EOD-Flatten: 15 Minuten vor dem Close des Tages."""
    close_hh, close_mm = close_time_et_hhmm(day)
    total = close_hh * 60 + close_mm - _FLATTEN_LEAD_MINUTES
    return divmod(total, 60)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True, help="ET-Handelstag (YYYY-MM-DD)")
    parser.add_argument(
        "--print",
        dest="what",
        choices=["flatten-target", "close"],
        default="flatten-target",
        help="flatten-target: 'HH MM' des Gate-Ziels; close: 'HH MM' des Schlusses",
    )
    args = parser.parse_args(argv)
    day = date.fromisoformat(args.date)
    hh, mm = close_time_et_hhmm(day) if args.what == "close" else flatten_target_et_hhmm(day)
    print(f"{hh:02d} {mm:02d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
