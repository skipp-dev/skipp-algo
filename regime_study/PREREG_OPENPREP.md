# Pre-Registration: Markt-Mikrostruktur-Variablen im open-prep Outcome-Loop

**Registriert am:** 2026-07-04 (vor Beginn der Datensammlung — erste Outcome-Datei
mit den neuen Feldern ist `outcomes_2026-07-04.json`)
**Status:** LOCKED mit Commit dieser Datei. Änderungen nur als datierter
Nachtrag im Abschnitt „Amendments" — niemals rückwirkend.
**Bezug:** `OPENPREP_PINE_REGIME_IMPLEMENTATION_PLAN.md` (Workstream D2),
Modul `open_prep/market_microstructure.py` (Phase 1, 2026-07-04).
**Vorgeschichte:** Die Ensemble-Studie 2026-06/07 (archiviert unter
`artifacts/research/ensemble_2026-07/`) hat dreimal demonstriert, wie
Kleinstichproben-Muster ohne Pre-Registration zu Scheinbefunden führen.
Dieses Dokument existiert, damit das hier nicht passiert.

---

## 1. Fragestellung

Seit 2026-07-04 schreibt jeder open-prep-Lauf vier markt-weite
Mikrostruktur-Messwerte (observe-only) in jede Outcome-Zeile:

| Feld | Bedeutung |
|---|---|
| `market_efficiency_ratio` | Kaufman-ER, Daily Closes, 10-Tage-Fenster, Median über ~100 Aktien |
| `intraday_efficiency_ratio` | Kaufman-ER, 1h-Bars, ~5 Handelstage, Median über ~50 Aktien |
| `cs_dispersion` | Querschnitts-Stdabw. der 1-Tages-Renditen, 5d-geglättet (%) |
| `avg_pair_correlation` | Ø-Paarkorrelation der Tagesrenditen, 20d-Fenster |

Frage: Sagen diese Werte etwas darüber aus, an welchen Tagen die
open-prep-Kandidaten (30-Minuten-Horizont nach Open) besser funktionieren?

## 2. Konfirmatorische Hypothesen (fixiert, gerichtet)

- **H1 (Follow-Through):** GAP_AND_GO-Kandidaten haben eine höhere Hit-Rate
  an Tagen im **obersten** `intraday_efficiency_ratio`-Terzil als an Tagen
  im untersten Terzil.
- **H2 (Mean-Reversion):** GAP_FADE-Kandidaten haben eine höhere Hit-Rate
  an Tagen im **untersten** `intraday_efficiency_ratio`-Terzil als an Tagen
  im obersten Terzil.
- **H3 (Differenzierung):** Alle Kandidaten zusammen haben eine höhere
  Hit-Rate an Tagen im **obersten** `cs_dispersion`-Terzil als an Tagen im
  untersten Terzil.

**Festlegung ER-Variante:** Der Plan (geschrieben vor Phase 1) kannte nur
„ER". Die Implementierung liefert zwei Varianten. Für H1/H2 gilt
verbindlich die **Intraday-Variante** (`intraday_efficiency_ratio`), weil
der Outcome-Horizont (30 Minuten nach Open) ein Intraday-Mechanismus ist.
Die Daily-Variante ist nur explorativ (Abschnitt 8).

## 3. Datengrundlage

- **Quelle:** `artifacts/open_prep/outcomes/outcomes_YYYY-MM-DD.json`,
  Session-Datum ≥ 2026-07-04.
- **Analyseeinheit:** Kandidaten-Zeile (Symbol × Handelstag). Bei mehreren
  Läufen pro Tag zählt pro (Tag, Symbol) die Zeile des letzten Laufs.
- **Einschluss:** Zeile hat (a) alle vier numerischen Mikrostruktur-Felder
  non-null und (b) ein aufgelöstes Primär-Label (Abschnitt 4). Tage mit
  fehlgeschlagenem Snapshot fallen komplett heraus; Anzahl wird berichtet.
- **Cluster-Struktur (wichtig):** Die Mikrostruktur-Werte sind markt-weit —
  identisch für alle Zeilen eines Tages. Zeilen desselben Tages sind bzgl.
  des Regressors nicht unabhängig; die Teststatistik muss auf Tagesebene
  clustern (Abschnitt 6). Naive Zeilen-Zählung als n wäre Selbstbetrug.

## 4. Endpunkte

- **Primär:** Hit-Rate = Anteil Zeilen mit `profitable_30m_directional == true`
  unter den aufgelösten Zeilen (Feld non-null). Unaufgelöste Zeilen werden
  nicht in den Nenner gezählt (bestehende Konvention aus
  `compute_hit_rates`, eval-findings B1); ihre Anzahl wird berichtet.
- **Sekundär (deskriptiv):** Mittelwert `pnl_30m_pct_signed` je Terzil-Arm;
  Anteil `profitable_tb` (Triple-Barrier), sofern gefüllt.

## 5. Terzil-Definition (ex-ante, ohne Look-Ahead)

Für jeden Handelstag t wird der Perzentil-Rang des Tageswerts gegen die
**vorangegangenen** gesammelten Tageswerte derselben Messgröße berechnet
(Fenster: die letzten min(60, verfügbar) Handelstage **vor** t, aus den
Outcome-Dateien selbst rekonstruiert — kein API-Zugriff zur Auswertung
nötig, keine Survivorship-Abhängigkeit).

- Perzentil < 33,3 → unteres Terzil; > 66,7 → oberes Terzil; sonst Mitte.
  Das mittlere Terzil ist nicht Teil der konfirmatorischen Kontraste.
- **Burn-in:** Tage mit < 20 vorangegangenen gesammelten Tageswerten werden
  von der konfirmatorischen Analyse ausgeschlossen (betrifft ca. die ersten
  4 Kalenderwochen der Sammlung).

## 6. Statistisches Verfahren (fixiert)

- Je Hypothese: einseitiger Test der Hit-Rate-Differenz
  Δ = HitRate(hypothesenkonformes Terzil) − HitRate(Gegen-Terzil).
- **Primärtest:** Cluster-Bootstrap über Handelstage — Tage mit Zurücklegen
  resampeln, B = 10.000, Seed = 20260704; p einseitig = Anteil der
  Replikate mit Δ* ≤ 0. Berichtet werden Δ, 95%-Bootstrap-KI, p, sowie
  rohe Zähler (Zeilen und Tage je Arm).
- **Signifikanz:** α = 0,05/3 ≈ 0,0167 (Bonferroni über die drei
  konfirmatorischen Hypothesen).
- **Mindestbesetzung je Kontrast:** ≥ 40 aufgelöste Zeilen **und** ≥ 15
  Handelstage in jedem der beiden Terzil-Arme. Nicht erreicht ⇒ Hypothese
  wird als UNDERPOWERED berichtet (kein Test), Sammlung läuft weiter
  (Abschnitt 7).

## 7. Auswertungs-Trigger und Stop-Regeln

- **Trigger:** ≥ 300 aufgelöste, einschlussfähige Zeilen (Abschnitt 3)
  kumuliert seit 2026-07-04. Erwartung: ~5–6 Monate.
- **Kein Peeking:** Bis zum Trigger keine Hit-Rate-Auswertung nach
  Mikrostruktur-Terzilen — weder formal noch „nur mal gucken". Erlaubt ist
  ausschließlich das Zählen einschlussfähiger Zeilen (monatlicher
  Fortschritts-Check) und technisches Monitoring (Felder non-null?).
  Die generischen Feature-Importance-Reports laufen unverändert weiter;
  ihre Ausgaben werden nicht zur Modifikation dieser Hypothesen benutzt.
- **Einmalige Auswertung:** Genau eine konfirmatorische Auswertung am
  Trigger. UNDERPOWERED-Hypothesen (Abschnitt 6) dürfen in 50-Zeilen-
  Schritten nachgezogen werden, spätestens 12 Monate nach Registrierung
  wird geschlossen (Ergebnis dann: „inconclusive").
- **Bei Bestätigung:** separater Vorschlag für Gewichts-/Playbook-
  Integration (Plan D3) — keine automatische Änderung.
- **Bei Nicht-Bestätigung:** Felder bleiben observe-only/Anzeige. Keine
  Nachjustierung von Schwellen, Fenstern oder Terzil-Definitionen auf
  denselben Daten. Neue Hypothesen ⇒ neue Pre-Registration ⇒ frische Daten.
- Die Anzeige-Features (Pine-Panel, Alerts, `market_weather`-Ampel) sind
  von jedem Ausgang unberührt — sie sind als Information gerechtfertigt,
  nicht als validierte Prognose, und werden bis zu einer bestätigten
  Auswertung nirgends als „validiert" bezeichnet.

## 8. Explizit explorativ (nicht konfirmatorisch)

Werden, falls berichtet, immer als EXPLORATIV gekennzeichnet und begründen
keine Produktänderung: H1/H2 mit `market_efficiency_ratio` (Daily-Variante),
alles zu `avg_pair_correlation`, die `market_weather`-Ampel als Prädiktor,
Interaktionen mit `regime_at_entry` oder `vix9d_vix_ratio`, Tercile anderer
Fensterlängen.

## 9. Amendments

*(leer — Nachträge nur datiert und additiv)*
