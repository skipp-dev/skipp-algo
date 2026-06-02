# Director-Findings & Produktstrategie — 2026-06-02

> **Autor:** Product Owner / Director (autonom).
> **Anlass:** Seit Wochen Rückstand hinter Erwartungen; Zeit verrinnt in endlosen
> PRs; kurz vor Workflow-Starts werden fehlende Module entdeckt. Dieses Memo
> hält die Ursachen-Diagnose und die daraus abgeleiteten Aktionen fest, damit
> wir nächste Woche **nicht wieder im Kreisverkehr** stehen.
> **Kanonische Entscheidungen:** siehe Eintrag `2026-06-02 - product-focus-on-edge-over-governance` in [DECISIONS.md](DECISIONS.md).

---

## 1. Faktenbasis (Stand 2026-06-02)

Offene PR-Queue (11), nach Inhalt klassifiziert:

| Klasse | PRs | Anteil | Liefert SMC-Edge? |
|--------|-----|-------:|:-----------------:|
| Infra/Governance-Meta (ADR-Enforcement, Pin-Ledger, frozen roster, silent-skip, title-linter) | #2421, #2455, #2462, #2463, #2509 | ~45% | nein |
| Auto-Snapshot-PRs (Pine/Docs mit Run-IDs) | #2484, #2486, #2498 | ~27% | nein |
| Edge-Daten / Governance-Records | #2507, #2508 | ~18% | indirekt |
| **Direkter SMC-Trading-Edge** | **—** | **0%** | — |

**Kernbefund:** Kein einziger offener PR bringt nachweisbaren Trading-Edge. Wir
polieren das Fließband, während das Werkstück fehlt.

## 2. Diagnose — drei Ursachen

1. **Die Maschine wartet sich selbst.** Der überwiegende Teil der Arbeit ist
   Infrastruktur um die Produktfrage herum (Promotion-Gates, Pin-Ledger,
   Roster-Pins, Title-Linter). Korrekt gebaut — aber ein Promotion-Gate ist
   wertlos, solange nichts zur Promotion ansteht.

2. **„Fehlende Module kurz vor Start" ist ein Struktursymptom, kein Pech.**
   Beispiele aus dieser Woche: `data()`-Title-Bug im Auto-Generator (#2498/#2509),
   Roster verweist auf nicht existierende Tests (#2463), Decision-JSONs lagen nur
   auf Branches statt auf main (#2508). Ursache: **keine Single Source of Truth
   und kein Pre-Flight-Integrationscheck.** Generatoren produzieren Artefakte,
   die Gates verletzen, die sie selbst nicht vorab prüfen → Drift wird zur
   Laufzeit statt zur Build-Zeit entdeckt.

3. **Wir messen Aktivität, nicht Edge.** Grüne CI wird mit Produktfortschritt
   verwechselt. Die eigentliche Frage — *hat eine SMC-Strategie out-of-sample
   stabilen, positiven Edge auf Live-Databento?* — verschwindet im Infra-Lärm.

## 3. North Star

> **Die SMC-Suite ist erst dann ein Produkt, wenn eine SMC-Strategie einen
> reproduzierbaren, out-of-sample positiven Edge auf Live-Databento-Daten
> nachweist — gemessen durch das Promotion-Gate, nicht durch grüne CI.**

Alles, was diesen Nachweis nicht direkt voranbringt, ist nachrangig.

## 4. Drei strategische Schlüsse

- **A) STOP-Liste.** Auto-Snapshot-PRs (Pine/Docs mit Run-IDs) werden nicht
  mehr als Review-PR geführt, sondern als Job-Artifact / `snapshots/`-Commit.
  ADR-Enforcement-PRs sind substanziell fertig → durchmergen und Thema
  schließen. Kein neues Governance-Tooling, bis eine echte Strategie zur
  Promotion ansteht.
- **B) Ein Wertstrom.** Die EV-20-Edge-Pipeline (real Databento → Decision-JSON
  → Promotion-Gate) ist der einzige Pfad, der das North-Star-Kriterium berührt.
  Die 16 geretteten Decision-JSONs (#2508) werden **ausgewertet, nicht
  archiviert** — Ziel: erstes echtes Verdict *Edge ja / nein / unklar*.
- **C) Drift an der Quelle abfangen.** Ein wiederverwendbarer Pre-Flight-Validator
  (Title-Concern + referenzierte Test-Pfade + Schema-Version) wird von **jedem**
  Generator vor `gh pr create` aufgerufen. Der heutige `data(`→`chore(`-Fix
  (#2509) ist genau dieses Prinzip — bisher einmalig statt systematisch.

## 5. Nächste Aktionen (priorisiert)

1. **Queue leeren — heute.** ADR-/Infra-PRs (#2455, #2462, #2463, #2509)
   durchmergen, ADR-Thema schließen. Auto-Snapshot-PRs (#2484, #2486, #2498)
   schließen bzw. auf Artifact umstellen.
2. **EV-20 echten Run vorbereiten + Decisions auswerten.** Die 16 JSONs aus
   #2508 gegen das Promotion-Gate laufen lassen → erster echter Produktdatenpunkt.
3. **`scripts/preflight_generated_pr.py` bauen** und in
   `edge-pipeline-real-run.yml` + Snapshot-Workflows vor `gh pr create`
   einhängen — verhindert die „kurz-vor-Start"-Drift-Klasse strukturell.

## 6. EV-20 — Erstes echtes Verdict (run 26791442554, 5 Decisions)

Die 16+5 geretteten Decisions wurden ausgewertet (`python -m governance.family_verdict`).
Das Ergebnis ist über alle 5 Runs **konsistent** und liefert den ersten echten
Produktdatenpunkt:

| Familie | Verdict | PSR | Sample | Blocker | brier / ece |
|---------|---------|----:|-------:|---------|-------------|
| BOS | no_edge | 0.99–1.00 | 894–961 (ok) | brier (±ece) | 0.246 / 0.059 |
| OB  | no_edge | 1.000 | 679–708 (ok) | brier (±ece) | 0.242 / 0.034 |
| FVG | no_edge | 1.000 | 758–807 (ok) | brier (±ece) | 0.240 / 0.044 |
| SWEEP | inconclusive | 0.93–1.00 | 100 (< 120) | brier+ece+fdr | 0.266 / 0.175 |

**Kernbefund:** Der bindende Constraint ist **Kalibrierung, nicht das
Return-Signal.** PSR liegt für BOS/OB/FVG weit über der 0.95-Schwelle bei
adäquatem Sample — aber die Wahrscheinlichkeitsvorhersagen sind nahezu
uninformativ: `brier ≈ 0.24` liegt knapp unter dem Münzwurf-Baseline von 0.25.
Das Gate blockt also korrekt: Die Strategie macht im Backtest Geld, aber ihre
Probability-Estimates sind nahe Zufall. Eine Promotion ist erst möglich, wenn
die Familien **informative, kalibrierte Wahrscheinlichkeiten** liefern.

**Sekundär-Flags:**

- PSR sättigt bei ~1.000 für BOS/OB/FVG, während SWEEP (mit Almgren-Chriss-
  Slippage) bei 0.96 landet → Verdacht, dass die Return-Inputs von BOS/OB/FVG
  nicht kosten-/kapazitätsadjustiert sind wie SWEEP. PSR-Kostenparität prüfen.
- SWEEP ist *inconclusive*, weil `observed_n = 100 < min_sample_n = 120` — ein
  längeres Fenster ist nötig, bevor ein Urteil zulässig ist.

**Daraus folgt der nächste Wertstrom** (ersetzt „mehr Governance bauen"): die
Probability-Kalibrierung der SMC-Familien verbessern (informativer `brier` unter
Schwelle) plus PSR-Kostenparität über die Familien herstellen. Das ist das eine
Gate zwischen uns und der ersten promotbaren Strategie.

> **EV-20-Run-Bereitschaft:** Alle Pipeline-Skripte vorhanden
> (`pull_databento_edge_input`, `run_edge_pipeline`, `family_verdict`,
> `build_family_metrics`). Ein *neuer* Live-Fetch braucht `DATABENTO_API_KEY` —
> operator-gebunden, ausschließlich direkt im Terminal einzugeben (nie über ein
> Tool/Prompt). Die *Auswertung* bestehender Decisions braucht keinen Key und
> ist oben bereits erfolgt.

## 7. Anti-Kreisverkehr-Mechanismus

Dieses Memo + der `DECISIONS.md`-Eintrag sind die durable Referenz. Vor jeder
neuen Governance-/Infra-Arbeit gilt die Prüffrage: **„Bringt das die EV-20-
Edge-Auswertung näher? Wenn nein — warum jetzt?"**
