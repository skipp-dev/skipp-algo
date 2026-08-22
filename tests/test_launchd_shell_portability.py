"""Skripte unter ``automation/`` haben ZWEI Wahrheiten — dieser Waechter kennt beide.

Die Treiber dort laufen in Produktion per ``launchd`` auf **macOS (BSD-Userland)**
und werden in CI auf **ubuntu (GNU-coreutils)** getestet. Jedes Shell-Konstrukt,
dessen Semantik sich zwischen beiden unterscheidet, hat damit zwei verschiedene
Wahrheiten — und beide Pruefflaechen sehen jeweils nur eine davon.

## Warum ein TEXTpruefer, und kein Laufzeittest

Ein Laufzeittest auf dem Entwickler-Mac bestaetigt zwangslaeufig das BSD-Verhalten;
er *kann* die Linux-Wahrheit nicht sehen. Ein Textpruefer haengt nicht davon ab, auf
welcher Plattform er laeuft — er ist die einzige Sorte Wache, die im Pre-Push-Hook
feuert statt erst im CI-Lauf nach dem Push.

## Zwei Richtungen, und die gefaehrlichere ist die unerlebte

**BSD-only** (``mktemp -t`` ohne X'e) laeuft auf dem Mac und bricht in CI. Das kostet
einen roten Push-Zyklus — aergerlich, aber laut. Genau das passierte am 2026-08-22
bei PR #4992: lokal 4/4 gruen, in CI drei rote Checks aus **einer** Wurzel.

**GNU-only** (``date -d``, ``readlink -f``, ``timeout``, ``stat -c``) laeuft in CI
**durch** und bricht im Mac-Cron zur Laufzeit. Diese Richtung faengt heute niemand:
CI sieht sie nicht, und der Mac sieht sie erst, wenn der Treiber nachts scheitert.
Was ein stiller Treiberausfall dort anrichtet, ist gemessen — der Hang vom 2026-08-21
legte ueber den launchd-Singleton alle Folgefeuer inklusive Montag stumm.

## Warum das hier ein harter Nullgate sein darf

Zum Zeitpunkt der Einfuehrung war der Bestand **sauber**: 0 Treffer ueber alle 16
Skripte, in beiden Richtungen. Es gibt also keine Altlast, keine Ratsche und keine
Ausnahmeliste zu pflegen. Diese Gelegenheit verfaellt — jeder spaeter zugelassene
Treffer macht den Waechter teurer.

## Warum die Ausnahmen so eng sind

Die naive Negativliste roetet **korrekten** Code. Repo-weit gemessen ist
``stat -f "%m" f || stat -c "%Y" f`` das RICHTIGE portable Idiom (so in
``scripts/vd_open_prep.sh:169``), und ``sed -i`` in einem Plattform-Zweig ebenso
(``scripts/bump_pine_library_import.sh:90``). Ein Waechter, der richtigen Code
roetet, bekommt binnen Wochen Ausnahmen angeschraubt und wird vakuant. Deshalb
genau zwei Auswege, beide eng und beide selbst getestet:

1. **Fallback-Kette auf derselben Zeile** — steht neben dem Konstrukt sein
   Gegenstueck (``stat -f`` und ``stat -c``), ist die Zeile absichtlich portabel.
2. **``# portable-ok: <Grund>``** — ein ausdruecklicher, begruendeter Verzicht am
   Fundort. Ohne Grund zaehlt er nicht.

Bei Geburt ist Ausweg 2 **null mal** benutzt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from tests._guard_corpus import iter_tracked_files, repo_root

REPO_ROOT = repo_root()

# Sparse-Checkout / kaputtes Glob wuerden den Waechter still leeren. 12 statt 16:
# Luft fuer geloeschte Treiber, ohne dass ein Totalausfall der Suche durchgeht.
_MIN_SCRIPTS = 12

_WAIVER = re.compile(r"#\s*portable-ok:\s*\S+")


@dataclass(frozen=True)
class Construct:
    """Ein Konstrukt mit zwei Wahrheiten, plus seine eigene Positivkontrolle."""

    name: str
    rx: re.Pattern[str]
    breaks_on: str
    portable: str
    #: Gegenstueck auf derselben Zeile ⇒ absichtliche Fallback-Kette.
    counterpart: re.Pattern[str] | None
    #: Zeilen, die das Muster treffen MUSS -- sonst ist es Dekoration.
    must_match: tuple[str, ...]
    #: Zeilen, die es NICHT treffen darf -- sonst roetet es korrekten Code.
    must_not_match: tuple[str, ...]


_GNU_ONLY: tuple[Construct, ...] = (
    Construct(
        name="date -d / --date",
        rx=re.compile(r"\bdate\s+(?:-d|--date)\b"),
        breaks_on="macOS (BSD date kennt -d nicht)",
        portable="date -j -f … oder die Rechnung in Python/`date -v` mit Fallback",
        counterpart=re.compile(r"\bdate\s+-(?:v|j|r)\b"),
        must_match=('date -d "2026-01-01" +%s', "X=$(date --date=@170 +%F)"),
        must_not_match=("date +%Y-%m-%d", 'date -u +"%H:%M:%SZ"', "update_dates"),
    ),
    Construct(
        name="readlink -f",
        rx=re.compile(r"\breadlink\s+-[a-zA-Z]*f\b"),
        breaks_on="macOS (BSD readlink kennt -f nicht)",
        portable='cd "$(dirname "$0")" && pwd -P',
        counterpart=None,
        must_match=('p=$(readlink -f "$0")', "readlink -ef x"),
        must_not_match=('readlink "$link"',),
    ),
    Construct(
        name="timeout(1)",
        rx=re.compile(r"(?<![\w./-])timeout\s+(?:-\S+\s+)*-?\d"),
        breaks_on="macOS (weder timeout noch gtimeout vorhanden, 2026-08-22 gemessen)",
        portable="Wartefrist von Hand, TERM vor KILL (siehe run-c13-eod-flatten.sh)",
        counterpart=None,
        must_match=("timeout 600 ./run.sh", "timeout -k 5 30 cmd"),
        must_not_match=("TIMEOUT_S=600", 'echo "timeout reached"', "--timeout 30"),
    ),
    Construct(
        name="grep -P",
        rx=re.compile(r"\bgrep\s+-[a-zA-Z]*P\b"),
        breaks_on="macOS (BSD grep ohne PCRE)",
        portable="grep -E",
        counterpart=None,
        must_match=("grep -P '\\d+' f", "grep -oP x f"),
        must_not_match=("grep -E 'a|b' f", "grep -q PATTERN f"),
    ),
    Construct(
        name="stat -c",
        rx=re.compile(r"\bstat\s+-c\b"),
        breaks_on="macOS (BSD stat nutzt -f)",
        portable='stat -f "%m" f 2>/dev/null || stat -c "%Y" f',
        counterpart=re.compile(r"\bstat\s+-f\b"),
        must_match=('stat -c %Y "$f"',),
        must_not_match=('stat -f "%m" "$f"',),
    ),
    Construct(
        name="sed -i ohne Suffix",
        rx=re.compile(r"\bsed\s+(?:-[a-zA-Z]+\s+)*-i(?![a-zA-Z.])(?!\s+(['\"])\1)"),
        breaks_on="macOS (BSD sed verlangt ein Suffix-Argument nach -i)",
        portable="sed -i.bak … && rm -f ….bak  (oder in eine Temp-Datei schreiben)",
        counterpart=None,
        must_match=("sed -i s/a/b/ f", 'sed -i -e "s/a/b/" f'),
        must_not_match=("sed -i '' s/a/b/ f", "sed -i.bak s/a/b/ f", "sed -E 's/a/b/' f"),
    ),
    Construct(
        name="sed -r",
        rx=re.compile(r"\bsed\s+-[a-zA-Z]*r\b"),
        breaks_on="macOS (BSD sed nutzt -E)",
        portable="sed -E",
        counterpart=None,
        must_match=("sed -r 's/(a)/\\1/' f", "sed -nr x"),
        must_not_match=("sed -E 's/(a)/\\1/' f", "sed 's/r/x/' f"),
    ),
    Construct(
        name="find -printf",
        rx=re.compile(r"(?<=\s)-printf\b"),
        breaks_on="macOS (BSD find kennt -printf nicht)",
        portable="find … -exec stat … oder -print0 | xargs -0",
        counterpart=None,
        must_match=('find . -printf "%p\\n"',),
        must_not_match=("find . -print0", 'printf "%s\\n" x'),
    ),
    Construct(
        name="base64 -w",
        rx=re.compile(r"\bbase64\s+-w"),
        breaks_on="macOS (BSD base64 kennt -w nicht)",
        portable="base64 | tr -d '\\n'",
        counterpart=None,
        must_match=("base64 -w0 < f", "base64 -w 0 < f"),
        must_not_match=("base64 < f", "base64 -D < f"),
    ),
    Construct(
        name="xargs -r",
        rx=re.compile(r"\bxargs\s+-[a-zA-Z0-9]*r\b"),
        breaks_on="macOS (BSD xargs kennt -r nicht; es ist dort ohnehin das Standardverhalten)",
        portable="xargs (BSD fuehrt bei leerer Eingabe von sich aus nicht aus)",
        counterpart=None,
        must_match=("xargs -r rm", "xargs -0r rm"),
        must_not_match=("xargs -0 rm", "xargs rm"),
    ),
    Construct(
        name="tac",
        rx=re.compile(r"(?<![\w./-])tac\b"),
        breaks_on="macOS (kein tac; dort tail -r)",
        portable="tail -r  (oder awk)",
        counterpart=re.compile(r"\btail\s+-r\b"),
        must_match=("tac f", "cat f | tac"),
        must_not_match=("attac_helper", "./bin/tack", "# tac wird hier bewusst"),
    ),
)

_BSD_ONLY: tuple[Construct, ...] = (
    Construct(
        name="mktemp -t ohne X'e",
        rx=re.compile(r"\bmktemp\s+(?:-[a-zA-Z]*t)\s+(?!\S*XXX)\S+"),
        breaks_on="Linux (GNU: 'too few X's in template') — die Falle aus PR #4992",
        portable='mktemp "${TMPDIR:-/tmp}/name.XXXXXX"  (volle Vorlage, ohne -t)',
        counterpart=None,
        must_match=("TMP=$(mktemp -t c13_eod)", "mktemp -dt foo"),
        must_not_match=(
            'TMP=$(mktemp "${TMPDIR:-/tmp}/n.XXXXXX")',
            "mktemp -t name.XXXXXX",
            "mktemp -d",
        ),
    ),
    Construct(
        name="stat -f",
        rx=re.compile(r"\bstat\s+-f\b"),
        breaks_on="Linux (GNU stat -f meldet das DATEISYSTEM, nicht die Datei — still falsch)",
        portable='stat -f "%m" f 2>/dev/null || stat -c "%Y" f',
        counterpart=re.compile(r"\bstat\s+-c\b"),
        must_match=('stat -f "%m" "$f"',),
        must_not_match=('stat -c "%Y" "$f"',),
    ),
    Construct(
        name="date -r / -v",
        rx=re.compile(r"\bdate\s+-[rv]\b|\bdate\s+-v[-+\d]"),
        breaks_on="Linux (GNU date -r erwartet eine DATEI, -v gibt es nicht)",
        portable="date -d …  mit Fallback, oder die Rechnung in Python",
        counterpart=re.compile(r"\bdate\s+(?:-d|--date)\b"),
        must_match=("date -r 1700000000", "date -v-1d +%F"),
        must_not_match=("date +%s", "date -u +%F"),
    ),
    Construct(
        name="md5 statt md5sum",
        rx=re.compile(r"(?<![\w./-])md5\s"),
        breaks_on="Linux (dort heisst es md5sum)",
        portable="md5sum … 2>/dev/null || md5 …",
        counterpart=re.compile(r"(?<![\w./-])md5sum\b"),
        must_match=('md5 "$f"',),
        must_not_match=("md5sum f", "MD5_X=1", "openssl md5-x"),
    ),
    Construct(
        name="sed -i '' (BSD-Form)",
        rx=re.compile(r"\bsed\s+(?:-[a-zA-Z]+\s+)*-i\s+(['\"])\1"),
        breaks_on="Linux (GNU liest das '' als sed-Skript und laesst die Datei unveraendert)",
        portable="sed -i.bak … && rm -f ….bak",
        counterpart=None,
        must_match=("sed -i '' s/a/b/ f", 'sed -i "" -e x f'),
        must_not_match=("sed -i.bak s/a/b/ f", "sed -i s/a/b/ f"),
    ),
)

_ALL: tuple[Construct, ...] = _GNU_ONLY + _BSD_ONLY


def _code_of(line: str) -> str:
    """Die Zeile ohne ihren Kommentar-Schwanz.

    Nur ein ``#`` am Zeilenanfang oder nach Weissraum zaehlt; ``foo#bar`` und
    ``"#kanal"`` bleiben stehen. Das kann im Zweifel zu VIEL stehen lassen --
    die sichere Richtung, denn ein Waechter darf lieber einmal zu oft fragen
    als still wegsehen.
    """
    return re.split(r"(?:^|\s)#", line, maxsplit=1)[0]


def _findings(path: Path) -> list[tuple[int, str, Construct]]:
    out: list[tuple[int, str, Construct]] = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if _WAIVER.search(raw):
            continue
        code = _code_of(raw)
        for construct in _ALL:
            if not construct.rx.search(code):
                continue
            if construct.counterpart is not None and construct.counterpart.search(code):
                continue  # absichtliche Fallback-Kette auf derselben Zeile
            out.append((lineno, raw.strip(), construct))
    return out


def _scripts() -> list[Path]:
    return [
        p
        for p in iter_tracked_files("*.sh", exclude_dirs=("__pycache__", "node_modules"))
        if p.is_relative_to(REPO_ROOT / "automation")
    ]


def test_the_script_corpus_is_not_silently_empty() -> None:
    """Ohne diese Zusicherung waere ein leeres Glob ein gruener Waechter."""
    scripts = _scripts()
    assert len(scripts) >= _MIN_SCRIPTS, (
        f"nur {len(scripts)} Skripte unter automation/ gefunden, erwartet >= "
        f"{_MIN_SCRIPTS}. Entweder ist das Glob kaputt oder der Checkout unvollstaendig "
        f"— in beiden Faellen misst dieser Waechter nichts."
    )


def test_launchd_scripts_carry_no_platform_specific_construct() -> None:
    """Harter Nullgate: der Bestand war bei Einfuehrung sauber und bleibt es."""
    problems: list[str] = []
    for path in _scripts():
        rel = path.relative_to(REPO_ROOT).as_posix()
        for lineno, text, construct in _findings(path):
            problems.append(
                f"{rel}:{lineno}  [{construct.name}] bricht auf {construct.breaks_on}\n"
                f"      {text}\n"
                f"      portabel: {construct.portable}"
            )
    assert not problems, (
        "Plattformabhaengige Shell-Konstrukte in automation/ (Cron laeuft auf macOS, "
        "die Suite auf Linux — beide sehen nur je EINE Wahrheit):\n\n"
        + "\n".join(problems)
        + "\n\nAusweg 1: Fallback-Kette auf derselben Zeile (z. B. 'stat -f … || stat -c …').\n"
        "Ausweg 2: '# portable-ok: <Grund>' am Fundort, wenn das Konstrukt dort "
        "nachweislich richtig ist."
    )


def test_every_pattern_has_a_working_positive_control() -> None:
    """Ohne diese Probe waere ein blindes Muster nicht von einem sauberen Bestand zu
    unterscheiden.

    Beim Bauen dieses Waechters waren DREI der sechzehn Muster blind, und diese
    Probe hat alle drei gefunden, bevor sie in einen PR kamen:

    * ``base64 -w`` -- das ``\\b`` hinter dem ``w`` frisst die Wortgrenze in ``-w0``
    * ``timeout`` -- die erste Fassung verlangte die Zahl direkt hinter dem Befehl
      und sah ``timeout -k 5 30 cmd`` nicht
    * ``xargs -r`` -- ``[a-zA-Z]*`` deckt die Ziffer in ``-0r`` nicht ab

    Ein leeres Ergebnis ist eben kein Befund, solange nicht gezeigt ist, dass das
    Werkzeug ueberhaupt misst.
    """
    blind: list[str] = []
    noisy: list[str] = []
    for construct in _ALL:
        for sample in construct.must_match:
            if not construct.rx.search(_code_of(sample)):
                blind.append(f"{construct.name!r} trifft NICHT: {sample!r}")
        for sample in construct.must_not_match:
            if construct.rx.search(_code_of(sample)):
                noisy.append(f"{construct.name!r} roetet faelschlich: {sample!r}")
    assert not blind, "blinde Muster:\n  " + "\n  ".join(blind)
    assert not noisy, "falsch-positive Muster:\n  " + "\n  ".join(noisy)


def test_the_fallback_exemption_does_not_swallow_the_bare_construct(tmp_path: Path) -> None:
    """Die Ausnahme darf die Regel nicht aufheben.

    Beide Auswege werden hier an synthetischen Dateien gefahren -- gegen den
    echten Bestand ginge es nicht, der ist absichtlich leer.
    """

    def findings_for(body: str) -> list[tuple[int, str, Construct]]:
        path = tmp_path / "probe.sh"
        path.write_text(body, encoding="utf-8")
        return _findings(path)

    # nackt ⇒ Fund
    assert findings_for('stat -f "%m" "$f"\n'), "nacktes 'stat -f' muss ein Fund sein"
    # Fallback-Kette auf derselben Zeile ⇒ kein Fund
    assert not findings_for('stat -f "%m" "$f" 2>/dev/null || stat -c "%Y" "$f"\n')
    # ... aber auf ZWEI Zeilen bleibt es ein Fund (die Kette muss echt sein)
    assert findings_for('stat -f "%m" "$f"\nstat -c "%Y" "$f"\n')
    # begruendeter Verzicht ⇒ kein Fund
    assert not findings_for('stat -f "%m" "$f"  # portable-ok: nur auf dem Mac aufgerufen\n')
    # Verzicht OHNE Grund zaehlt nicht
    assert findings_for('stat -f "%m" "$f"  # portable-ok:\n')
    # ein Konstrukt IM Kommentar ist kein Fund
    assert not findings_for("# frueher stand hier mktemp -t foo\n")


def test_no_waiver_is_in_use_yet() -> None:
    """Der Bestand kam ohne Ausnahmen aus -- das soll auffallen, wenn es endet.

    Kein Verbot: wer einen Verzicht braucht, hebt die Zahl hier und begruendet ihn
    im PR. Der Punkt ist, dass das eine sichtbare Entscheidung bleibt statt einer
    stillen Gewohnheit.
    """
    waived = [
        f"{p.relative_to(REPO_ROOT).as_posix()}:{n}"
        for p in _scripts()
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        if _WAIVER.search(line)
    ]
    assert not waived, (
        "neue '# portable-ok:'-Verzichte in automation/: "
        + ", ".join(waived)
        + ". Wenn der Verzicht richtig ist, diese Zusicherung im SELBEN PR anpassen "
        "und den Grund im PR-Text nennen."
    )
