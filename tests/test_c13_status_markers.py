"""Der Marker-Konsument (#4848 Review-Punkt #4): 10 Schreiber, jetzt 1 Leser-Kette.

Bis 19.8. war von zehn ``.<agent>_status_<DATE>``-Markern genau einer gelesen
(Flatten -> Reconcile, #4858); der DEGRADED-Reconcile vom 18.8. (TWS down,
Connection refused 7497) blieb unsichtbar. Diese Tests pinnen die neue Kette:
emit (Workstation, sanitisiert) -> data-branch -> check (Daily-Cron, rc ->
Issue-Opener). Die Format-Population ist GEMESSEN (19.8., alle 16 realen
Marker 16.-18.8.), nicht angenommen: KIND:msg:TS, KIND|msg, KIND msg und das
Append-Format des Commercial-Treibers (eine ``HH:MM:SSZ KIND|msg``-Zeile pro
Fire, worst line wins). Der erste Wurf parste nur ``KIND:`` und haette jeden
gruenen Tag alarmiert (prove-over-population-Klasse).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from scripts.c13_status_markers import (
    GREEN_KINDS,
    _parse_marker_content,
    _sanitize,
    check,
    collect_markers,
    emit,
    main,
)

_TS = "2026-08-18T21:05:04Z"


def _write_marker(live_dir: Path, agent: str, date: str, content: str) -> None:
    (live_dir / f".{agent}_status_{date}").write_text(content, encoding="utf-8")


@pytest.fixture()
def live_dir(tmp_path: Path) -> Path:
    d = tmp_path / "live"
    d.mkdir()
    _write_marker(
        d,
        "reconcile",
        "2026-08-18",
        f"DEGRADED:portfolio-after-failed:path=/Users/op/x/cache/live/portfolio_after.json:{_TS}\n",
    )
    _write_marker(d, "eod_flatten", "2026-08-18", f"SUCCESS:flattened=5:{_TS}\n")
    _write_marker(d, "audit_push", "2026-08-18", f"degraded:no-audit-file:{_TS}\n")
    _write_marker(d, "audit_push", "2026-08-17", f"ok:pushed:{_TS}\n")
    _write_marker(d, "phase_a", "2026-08-10", f"SUCCESS:done:{_TS}\n")  # ausserhalb Fenster
    (d / "incubation_2026-08-18.jsonl").write_text("{}\n", encoding="utf-8")  # kein Marker
    return d


def test_collect_parses_both_conventions_and_windows(live_dir: Path) -> None:
    rows = collect_markers(live_dir, date="2026-08-18", days_back=3)

    assert [(r["agent"], r["date"], r["kind"]) for r in rows] == [
        ("audit_push", "2026-08-17", "ok"),
        ("audit_push", "2026-08-18", "degraded"),
        ("eod_flatten", "2026-08-18", "SUCCESS"),
        ("reconcile", "2026-08-18", "DEGRADED"),
    ]
    reconcile = rows[-1]
    assert reconcile["ts"] == _TS
    # Die Nachricht darf Doppelpunkte enthalten und wird pfad-sanitisiert:
    # absolute Pfade verlassen die Workstation nur als Basename.
    assert "/Users/" not in reconcile["message"]
    assert "portfolio_after.json" in reconcile["message"]


def test_emit_writes_schema_and_is_deterministic(live_dir: Path, tmp_path: Path) -> None:
    out = tmp_path / "summary.json"
    emit(live_dir, date="2026-08-18", days_back=3, output=out)
    first = out.read_bytes()
    emit(live_dir, date="2026-08-18", days_back=3, output=out)

    assert out.read_bytes() == first
    data = json.loads(first)
    # 2026-08-19 (K5): 1->2, jede Zeile traegt jetzt "dir", die Summary
    # "scanned_dirs" — der Konsument urteilt sonst ueber eine Teilmenge.
    assert data["schema_version"] == 2
    assert data["window_end"] == "2026-08-18"
    assert data["scanned_dirs"] == [live_dir.as_posix()]
    assert len(data["markers"]) == 4
    assert all(m["dir"] == live_dir.as_posix() for m in data["markers"])


def _summary(tmp_path: Path, markers: list[dict]) -> Path:
    p = tmp_path / "s.json"
    p.write_text(
        json.dumps({"schema_version": 1, "window_end": "x", "window_days": 3, "markers": markers}),
        encoding="utf-8",
    )
    return p


def test_check_alarms_on_any_non_green_marker(live_dir: Path, tmp_path: Path) -> None:
    out = tmp_path / "summary.json"
    emit(live_dir, date="2026-08-18", days_back=3, output=out)

    # 18.8. traegt DEGRADED (reconcile + audit_push) -> rot.
    assert check(out, date="2026-08-18") == 1
    # Am 19.8. zaehlt der Vortag mit -> immer noch rot: still ist maximal 1 Tag.
    assert check(out, date="2026-08-19") == 1
    # Am 20.8. liegt nichts mehr im Fenster -> weich gruen (Wochenend-Semantik).
    assert check(out, date="2026-08-20") == 0


def test_check_green_when_all_markers_ok(tmp_path: Path) -> None:
    p = _summary(
        tmp_path,
        [
            {"agent": "reconcile", "date": "2026-08-18", "kind": "SUCCESS", "message": "", "ts": _TS},
            {"agent": "audit_push", "date": "2026-08-18", "kind": "ok", "message": "", "ts": _TS},
        ],
    )
    assert check(p, date="2026-08-18") == 0


def test_collect_parses_the_measured_real_formats(tmp_path: Path) -> None:
    """Pipe- und Leerzeichen-Trenner der realen Writer (ibkr_smoke stand im
    ersten Wurf als SUCCESS|smoke-ok-OFFENDER — Falsch-Alarm-Generator)."""
    d = tmp_path / "live"
    d.mkdir()
    _write_marker(d, "ibkr_smoke", "2026-08-18", "SUCCESS|smoke-ok audit=smoke_2026-08-18.jsonl\n")
    _write_marker(
        d,
        "audit_push",
        "2026-08-18",
        "ok pushed:2026-08-18T21:30:02Z:/Users/op/cache/live/incubation_2026-08-18.jsonl\n",
    )
    _write_marker(
        d, "reconcile", "2026-08-18", "DEGRADED portfolio-after-failed:path=portfolio_after.json\n"
    )

    rows = collect_markers(d, date="2026-08-18", days_back=1)

    assert [(r["agent"], r["kind"]) for r in rows] == [
        ("audit_push", "ok"),
        ("ibkr_smoke", "SUCCESS"),
        ("reconcile", "DEGRADED"),
    ]
    assert "/Users/" not in rows[0]["message"]


def test_append_style_marker_worst_line_wins(tmp_path: Path) -> None:
    """Commercial-Append-Format: Zeitpraefix-Zeilen, ein Fire pro Zeile.
    Gruene erste Zeile darf eine rote spaetere nicht verdecken."""
    d = tmp_path / "live"
    d.mkdir()
    _write_marker(
        d,
        "commercial_shadow",
        "2026-08-18",
        "14:07:00Z SUCCESS|campaign-observed:paper-dormant:verdict=PENDING\n"
        "15:05:13Z DEGRADED|campaign-attempt-failed:input=pit_AAPL_20260818T150506Z.json\n"
        "16:05:13Z SUCCESS|campaign-observed:paper-dormant:verdict=PENDING\n",
    )

    # Rote Zeile in der MITTE: eine Nur-erste-Zeile-Mutante rettet sich sonst
    # ueber den Letzte-Zeile-Fallback (Mutationsprobe 19.8. deckte das auf).
    rows = collect_markers(d, date="2026-08-18", days_back=1)
    assert rows[0]["kind"] == "DEGRADED"
    assert "campaign-attempt-failed" in rows[0]["message"]

    _write_marker(
        d,
        "commercial_shadow",
        "2026-08-18",
        "14:07:00Z SUCCESS|campaign-observed:paper-dormant:verdict=PENDING\n"
        "15:05:13Z SUCCESS|campaign-observed:paper-dormant:verdict=PENDING\n",
    )
    rows = collect_markers(d, date="2026-08-18", days_back=1)
    assert rows[0]["kind"] == "SUCCESS"


def test_real_format_green_day_stays_green_end_to_end(tmp_path: Path) -> None:
    """Der Test, der dem ersten Wurf fehlte: ein komplett gruener Tag in den
    ECHTEN On-Disk-Formaten muss rc=0 liefern — kein Falsch-Alarm."""
    d = tmp_path / "live"
    d.mkdir()
    _write_marker(d, "ibkr_smoke", "2026-08-18", "SUCCESS|smoke-ok audit=smoke_2026-08-18.jsonl\n")
    _write_marker(d, "tws_autostart", "2026-08-18", "SUCCESS|already-running\n")
    _write_marker(
        d, "audit_push", "2026-08-18", "ok pushed:2026-08-18T21:30:02Z:incubation_2026-08-18.jsonl\n"
    )
    _write_marker(
        d, "reconcile", "2026-08-18", "SUCCESS reconcile-complete:audit=incubation_2026-08-18.jsonl\n"
    )
    _write_marker(
        d,
        "commercial_shadow",
        "2026-08-18",
        "14:07:00Z SUCCESS|campaign-observed:paper-dormant:verdict=PENDING\n",
    )
    out = tmp_path / "s.json"
    emit(d, date="2026-08-18", days_back=1, output=out)

    assert check(out, date="2026-08-18") == 0


def test_empty_marker_fails_closed(tmp_path: Path) -> None:
    d = tmp_path / "live"
    d.mkdir()
    _write_marker(d, "reconcile", "2026-08-18", "")
    out = tmp_path / "s.json"
    emit(d, date="2026-08-18", days_back=1, output=out)

    assert check(out, date="2026-08-18") == 1


def test_check_fails_closed_on_unknown_kind(tmp_path: Path) -> None:
    p = _summary(
        tmp_path,
        [{"agent": "reconcile", "date": "2026-08-18", "kind": "PARTIAL", "message": "", "ts": _TS}],
    )
    assert check(p, date="2026-08-18") == 1


def test_check_missing_summary_is_soft(tmp_path: Path) -> None:
    assert check(tmp_path / "fehlt.json", date="2026-08-18") == 0


def test_cli_emit_then_check_roundtrip(live_dir: Path, tmp_path: Path) -> None:
    out = tmp_path / "summary.json"
    rc_emit = main(
        [
            "emit",
            "--live-dir", str(live_dir),
            "--date", "2026-08-18",
            "--days-back", "3",
            "--output", str(out),
        ]
    )
    rc_check = main(["check", "--summary", str(out), "--date", "2026-08-18"])

    assert rc_emit == 0
    assert rc_check == 1


def test_workflow_wires_check_into_the_issue_gate() -> None:
    """Der Konsument existiert nur, wenn der Cron ihn AUFRUFT und der
    Issue-Opener seinen rc liest — beide Kanten als Aufruf-Form gepinnt."""
    source = (
        Path(__file__).resolve().parents[1] / ".github" / "workflows" / "c13-daily-cron.yml"
    ).read_text(encoding="utf-8")

    assert "python -m scripts.c13_status_markers check" in source
    assert '--summary "${LIVE_DIR}/c13_status_markers.json"' in source
    # Anker ist die Step-DEFINITION, nicht die Phrase: sie steht wortgleich
    # auch in einem Kommentar des F-V3-15-Steps weiter oben (Kommentar-Falle,
    # dritter Treffer dieser Klasse in dieser Woche).
    gate = source.split("- name: Open issue if any required step failed", 1)[1]
    assert "steps.status_markers.outputs.rc != '0'" in gate.split("run:", 1)[0]


def test_audit_push_emits_and_ships_the_summary() -> None:
    source = (
        Path(__file__).resolve().parents[1] / "automation" / "launchd" / "run-c13-audit-push.sh"
    ).read_text(encoding="utf-8")

    assert "-m scripts.c13_status_markers emit" in source
    push_call = source.split("push_to_data_branch \\", 1)[1]
    assert '"${MARKERS_SUMMARY}"' in push_call


def _driver_marker_dirs() -> set[str]:
    """Marker-Verzeichnisse ABGELEITET aus den launchd-Treibern.

    Handlisten sind hier die Bug-Klasse (Doppelgaenger K5): der Konsument
    scannte ``cache/live``, waehrend drei Marker in ``cache/imbalance`` und
    ``cache/wsh`` liegen. Deshalb liest dieser Zeuge die Wahrheit aus den
    Schreibern statt sie zu wiederholen.
    """
    launchd = Path(__file__).resolve().parents[1] / "automation" / "launchd"
    pattern = re.compile(r'(?:STATUS_MARKER|MARKER)="(?:\$\{REPO\}/)?([^"]*)/\.[^"/]*_status_')
    dirs: set[str] = set()
    for script in sorted(launchd.glob("run-c13-*.sh")):
        dirs.update(pattern.findall(script.read_text(encoding="utf-8")))
    return dirs


def test_marker_dirs_cover_every_directory_a_driver_writes_into() -> None:
    """MARKER_DIRS ist die volle gemessene Population, nicht cache/live allein."""
    from scripts.c13_status_markers import MARKER_DIRS

    derived = _driver_marker_dirs()
    assert len(derived) >= 3, f"Zeuge leer/zu klein — Regex gebrochen? {derived}"
    configured = {d.as_posix() for d in MARKER_DIRS}
    assert derived <= configured, (
        f"Treiber schreiben nach {sorted(derived - configured)}, "
        f"MARKER_DIRS kennt nur {sorted(configured)}"
    )


def test_cron_overlay_and_emit_scan_the_same_directories() -> None:
    """Der Cron holt genau die Verzeichnisse aus der Datenbranch, die emit scannt.

    Driftet eine Seite, sammelt emit Marker, die der Cron nie ueberlagert
    (oder umgekehrt) — und der Konsument urteilt ueber eine Teilmenge.
    """
    from scripts.c13_status_markers import MARKER_DIRS

    cron = (
        Path(__file__).resolve().parents[1] / ".github" / "workflows" / "c13-daily-cron.yml"
    ).read_text(encoding="utf-8")
    overlay = re.search(r"for d in ([^\n;]*cache/live[^\n;]*)", cron)
    assert overlay, "Overlay-Schleife in c13-daily-cron.yml nicht gefunden"
    overlaid = set(overlay.group(1).split())
    assert overlaid == {d.as_posix() for d in MARKER_DIRS}


def test_audit_push_emit_call_covers_the_full_population() -> None:
    """Der Treiber darf emit nicht auf ein Verzeichnis verengen.

    Gegenprobe zur alten Form ``--live-dir cache/live``: entweder alle
    Verzeichnisse explizit, oder gar kein --live-dir (dann greift der
    Default MARKER_DIRS).
    """
    from scripts.c13_status_markers import MARKER_DIRS

    source = (
        Path(__file__).resolve().parents[1] / "automation" / "launchd" / "run-c13-audit-push.sh"
    ).read_text(encoding="utf-8")
    emit_call = source.split("-m scripts.c13_status_markers emit", 1)[1].split("push_to_data")[0]
    passed = set(re.findall(r"--live-dir\s+(\S+)", emit_call))
    if passed:
        assert passed == {d.as_posix() for d in MARKER_DIRS}, (
            f"emit-Aufruf verengt auf {sorted(passed)}"
        )


def test_check_still_reads_a_schema_1_summary(tmp_path: Path) -> None:
    """Uebergangsfenster: der Cron (neuer Code) liest eine Summary, die die
    Workstation noch mit Schema 1 (ohne ``dir``/``scanned_dirs``) geschrieben
    hat — bis der op-Baum den Pull hat. check() darf daran nicht scheitern
    und muss weiter rot werden, wenn ein Marker nicht gruen ist."""
    legacy = tmp_path / "legacy.json"
    legacy.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "window_end": "2026-08-18",
                "window_days": 3,
                "markers": [
                    {
                        "agent": "reconcile",
                        "date": "2026-08-18",
                        "kind": "DEGRADED",
                        "message": "portfolio-after-failed",
                        "ts": "2026-08-18T21:05:00Z",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    assert check(legacy, date="2026-08-18") == 1


# --- K4: die Marker-FORMATE der Treiber gegen den Parser ---------------------
#
# Doppelgaenger K4 (2026-08-19). Der Konsument versteht vier gemessene
# Zeilenformen, und bis hierher wurden sie ihm als HANDGESCHRIEBENE Literale
# vorgesetzt. Die Kopplung fehlte in beide Richtungen: aendert ein Treiber sein
# printf, merkt es niemand, und aendert der Parser seine Regex, merkt es
# ebenfalls niemand. Der oben ergaenzte Wächter koppelt die VERZEICHNISSE —
# dieser hier die FORMATE.
#
# Vorgehen: aus jedem Wrapper werden das printf im _write_marker und die
# Aufrufstellen gelesen, die Zeile daraus gerendert und durch den ECHTEN
# Parser geschickt. Kein Literal im Test.

_PRINTF_RE = re.compile(r"printf\s+'(?P<fmt>[^']*)'\s+(?P<args>[^>]*?)\s*(?:>>?\s*\"|2>)")
_LOCAL_RE = re.compile(r'local\s+(?P<name>\w+)="(?P<src>[^"]*)"')
_CALL_RE = re.compile(r'^\s*_write_marker\s+"(?P<a1>[^"]*)"(?:\s+"(?P<a2>[^"]*)")?', re.M)
_QUOTED_RE = re.compile(r'"([^"]*)"')
_STATUS_TOKEN_RE = re.compile(r"^[A-Za-z_]+$")
_DATE_CALL_RE = re.compile(r"\$\(date\s+-u\s+\+(?P<fmt>[^)]*)\)")

_FIXED = {"%F": "2026-08-19", "%T": "12:00:00", "%H": "12", "%M": "00", "%S": "00"}


def _render_date(shell_fmt: str) -> str:
    """`date -u +%H:%M:%SZ` -> `12:00:00Z`.

    Wichtig genug fuer eine eigene Funktion: beim ersten Wurf wurde hier
    pauschal ein voller ISO-Stempel eingesetzt, und der Wächter meldete
    run-c13-commercial-shadow.sh faelschlich als kaputt. Das FORMAT des
    Praefixes ist Teil der Kopplung — der Parser erkennt genau
    ``HH:MM:SSZ ``.
    """
    out = shell_fmt
    for token, value in _FIXED.items():
        out = out.replace(token, value)
    return out


def _resolve_token(token: str, positional: dict[str, str], bindings: dict[str, str]) -> str:
    """Ein printf-Argument des Wrappers -> der Wert, den es zur Laufzeit traegt."""
    date_call = _DATE_CALL_RE.fullmatch(token)
    if date_call:
        return _render_date(date_call.group("fmt"))
    named = re.fullmatch(r"\$\{(\w+)(?::-.*)?\}", token) or re.fullmatch(r"\$(\d)", token)
    if named:
        key = named.group(1)
        if key.isdigit():
            return positional[key]
        slot = re.search(r"\$\{?(\d)", bindings.get(key, ""))
        if slot:
            return positional[slot.group(1)]
        if key == "TS":
            return "2026-08-19T12:00:00Z"
    return "X"


def _driver_marker_lines() -> dict[str, list[tuple[str, str]]]:
    """Pro Wrapper: die real geschriebenen Marker-Zeilen + der gemeinte KIND."""
    root = Path(__file__).resolve().parents[1] / "automation" / "launchd"
    wrappers = sorted(root.glob("run-c13-*.sh"))
    assert wrappers, (
        "keine C13-Wrapper gefunden — jede Schleife darunter liefe leer und "
        "jede Zusicherung ginge vakuum durch"
    )
    result: dict[str, list[tuple[str, str]]] = {}

    for wrapper in wrappers:
        text = wrapper.read_text(encoding="utf-8")
        if "_write_marker() {" not in text:
            continue
        body = text.split("_write_marker() {", 1)[1].split("\n}", 1)[0]
        printf = _PRINTF_RE.search(body)
        assert printf, f"{wrapper.name}: kein printf im _write_marker gefunden"
        fmt = printf.group("fmt").replace("\\n", "\n")
        printf_args = _QUOTED_RE.findall(printf.group("args"))
        bindings = dict(_LOCAL_RE.findall(body))

        lines: list[tuple[str, str]] = []
        for arg1, arg2 in _CALL_RE.findall(text):
            positional = {"1": arg1, "2": arg2}
            rendered = fmt % tuple(
                _resolve_token(arg, positional, bindings) for arg in printf_args
            )
            # Kind-erst (`_write_marker "DEGRADED" "..."`) vs. Pfad-erst
            # (`_write_marker "${FEED_MARKER}" "degraded:..."`): im zweiten
            # Fall traegt der WERT den Status.
            intended = arg1 if _STATUS_TOKEN_RE.match(arg1) else arg2.split(":")[0]
            lines.append((rendered, intended))
        result[wrapper.name] = lines
    return result


def test_every_driver_marker_format_survives_the_parser() -> None:
    per_driver = _driver_marker_lines()

    # Vakuitaets-Boden: die Entdeckung darf nicht still leerlaufen.
    assert len(per_driver) >= 8, f"nur {len(per_driver)} Treiber gefunden — Layout geaendert?"
    total = sum(len(v) for v in per_driver.values())
    assert total >= 40, f"nur {total} Aufrufstellen gefunden — Erkennung gebrochen?"

    broken: list[str] = []
    for driver, lines in per_driver.items():
        for rendered, intended in lines:
            kind, _message, _ts = _parse_marker_content(rendered)
            if kind.lower() != intended.lower():
                broken.append(f"{driver}: {rendered.strip()!r} -> {kind!r} statt {intended!r}")

    assert not broken, (
        "Der Marker-Konsument liest den Status dieser Treiberzeilen falsch — "
        "printf-Format und Parser sind auseinandergelaufen. Ein falsch "
        "gelesener KIND heisst: eine DEGRADED-Meldung erscheint als unbekannter "
        "Status oder, schlimmer, als gruen.\n" + "\n".join(broken)
    )


def test_green_and_degraded_are_actually_distinguished() -> None:
    """Gegenprobe zum Boden oben: der Parser darf nicht ALLES gruen lesen."""
    per_driver = _driver_marker_lines()
    kinds = {
        _parse_marker_content(rendered)[0].lower()
        for lines in per_driver.values()
        for rendered, _ in lines
    }
    assert kinds & GREEN_KINDS, f"kein einziger gruener Treiber-Marker erkannt: {kinds}"
    assert kinds - GREEN_KINDS, f"kein einziger nicht-gruener Treiber-Marker erkannt: {kinds}"


# ----------------------------------------------------------------------
# Marker-Formate der PUSH-BIBLIOTHEK (Doppelgaenger, 19.8.).
# ----------------------------------------------------------------------
#
# ``_driver_marker_lines`` globt nur ``run-c13-*.sh`` und ueberspringt zudem
# jede Datei ohne ``_write_marker() {``. ``lib_c13_data_push.sh`` schreibt die
# Marker ALLER Push-Ketten (audit_push, reconcile_push, commercial_*_push,
# wsh-push, imbalance-push) mit EIGENEN printf-Formaten direkt nach
# ``${marker}`` — und lag damit vollstaendig ausserhalb der Kopplung.
# Gemessen 19.8.: Trenner in ``degraded:push-failed`` von ``:`` auf ``|``
# gebrochen ⇒ 19 passed. Genau dieser Bruch haette den Konsumenten den KIND
# nicht mehr erkennen lassen.

_LIB_MARKER_RE = re.compile(
    r"printf\s+'(?P<fmt>[^']*)'\s+[^>]*>\s*\"\$\{marker\}\"|"
    r"printf\s+'(?P<fmt2>[^']*)'\s+[^>]*>\s*\"\$\{_lock_marker\}\""
)


def _library_marker_formats() -> list[tuple[str, str]]:
    """(gerendertes Beispiel, gemeinter KIND) je Marker-printf der Bibliothek."""
    lib = (
        Path(__file__).resolve().parents[1]
        / "automation"
        / "launchd"
        / "lib_c13_data_push.sh"
    )
    text = lib.read_text(encoding="utf-8")
    out: list[tuple[str, str]] = []
    for match in _LIB_MARKER_RE.finditer(text):
        fmt = (match.group("fmt") or match.group("fmt2")).replace("\\n", "\n")
        rendered = fmt % tuple(
            ["2026-08-19T00:00:00Z", "cache/live/example.jsonl"][: fmt.count("%s")][i]
            for i in range(fmt.count("%s"))
        )
        intended = fmt.split(":", 1)[0]
        out.append((rendered, intended))
    return out


def test_every_library_marker_format_survives_the_parser() -> None:
    formats = _library_marker_formats()

    # Vakuitaetsboden: gemessen 10 Schreibstellen (Zeilen 136-237).
    assert len(formats) >= 8, (
        f"nur {len(formats)} Marker-printf in lib_c13_data_push.sh gefunden — "
        "Erkennung gebrochen oder Layout geaendert?"
    )

    broken: list[str] = []
    for rendered, intended in formats:
        kind, _message, _ts = _parse_marker_content(rendered)
        if kind.lower() != intended.lower():
            broken.append(f"{rendered.strip()!r} -> {kind!r} statt {intended!r}")
    assert not broken, "Bibliotheks-Marker, die der Konsument falsch liest:\n" + "\n".join(broken)


def test_library_marker_kinds_are_known_to_the_consumer() -> None:
    """Jeder KIND der Bibliothek muss gruen ODER bewusst degraded sein."""
    kinds = {intended.lower() for _rendered, intended in _library_marker_formats()}
    assert kinds, "keine KINDs extrahiert — der Zeuge liefe vakuum"
    unknown = kinds - set(GREEN_KINDS) - {"degraded"}
    assert not unknown, f"unbekannte Marker-KINDs der Push-Bibliothek: {sorted(unknown)}"


def test_sanitize_keeps_repo_relative_paths_intact() -> None:
    """Der Alarmtext trug systematisch verstuemmelte Dateinamen.

    ``_ABS_PATH_RE`` hatte keinen Anker und griff mitten in einen relativen
    Pfad: der reale ``ok:pushed``-Marker aus lib_c13_data_push.sh:218 wurde zu
    ``cacheincubation_2026-08-18.jsonl``. Absolute Pfade muessen weiter auf den
    Basisnamen kollabieren — die Privacy-Zusage haengt daran.
    """
    relativ = "ok:pushed:2026-08-18T21:30:02Z:cache/live/incubation_2026-08-18.jsonl"
    assert _sanitize(relativ) == relativ

    absolut = "portfolio-after-failed:/Users/spreuss/Documents/skipp-algo/cache/live/x.json"
    gekuerzt = _sanitize(absolut)
    assert "/Users/" not in gekuerzt
    assert gekuerzt.endswith("x.json")
