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

## 6.1 EV-20 — Vertiefung (Step-1+2-Audit) und Korrektur

Eine rigorose Zerlegung der Aggregate (`scripts/ev20_resolution_cost_audit.py`,
5-Run-Mittel) **präzisiert und korrigiert** die obige „Kalibrierung"-Verkürzung.
Beide Audits brauchen **keinen** API-Key.

| Familie | brier | Resolution-Band¹ | Sharpe/J² | PSR vs 0 | PSR vs SPY³ | Events/J⁴ |
|---------|------:|-----------------:|----------:|---------:|------------:|----------:|
| BOS | 0.242 | 0.008–0.043 (3–17 %) | 1.96 | 1.000 | 0.996 | 571 |
| OB  | 0.241 | 0.010–0.047 (4–19 %) | 2.86 | 1.000 | 1.000 | 431 |
| FVG | 0.235 | 0.015–0.052 (6–21 %) | 3.68 | 1.000 | 1.000 | 483 |
| SWEEP | 0.257 | −0.007–0.134 (Untergrenze < 0) | 4.07 | 0.996 | 0.990 | 62 |

¹ Brier-Zerlegung `Brier = Uncertainty(0.25) − Resolution + Reliability`; da
Reliability (quadratische Gaps) ≪ ECE (absolute Gaps), liegt der realistische
Wert nahe der **Untergrenze**. ² annualisiert über `ppy=252`. ³ neu gerechnet
gegen SPY-Buy-and-Hold (annual Sharpe 0.55). ⁴ `n_returns / 1.62 J` Fenster.

**Korrektur 1 — es ist Trennschärfe, nicht „Eichung".** `ece ≈ 0.034–0.044` ist
**niedrig**, die Wahrscheinlichkeiten sind also im Mittel korrekt geeicht. Der
bindende Blocker ist die **brier-Schwelle (≤ 0.22)**, und die wird verfehlt, weil
die **Resolution (Trennschärfe) schwach** ist: realistisch nur **3–6 %** der
Gesamt-Unsicherheit für BOS/OB/FVG, bei SWEEP an der Untergrenze sogar negativ.
Im Klartext: Das System trennt gewinnende kaum von verlierenden Setups. Eine
reine Recalibration-Kurve brächte **nichts** (ECE ist ja schon gut) — es braucht
**diskriminierendere Features**.

**Korrektur 2 — der Return-Edge überlebt den richtigen Benchmark.** Die gestrige
Vermutung „PSR sättigt nur, weil gegen Null getestet" ist **falsch**: PSR bleibt
0.99–1.00 **auch gegen SPY-Buy-and-Hold**. Der primäre Return-Edge ist real und
benchmark-robust — das ist der verkaufbare Kern.

**Korrektur 3 — die Zahl, die noch nicht investor-tauglich ist.** Die
annualisierten Sharpes (1.96–4.07) stehen auf einer **fragwürdigen Zeitbasis**:
die Annualisierung nutzt `ppy=252`, die tatsächliche Event-Kadenz ist aber
431–571/Jahr. **Vor jedem Investoren-Gespräch muss `ppy` gegen die echte Kadenz
abgeglichen werden** — sonst ist keine Sharpe-Zahl belastbar.

**Wichtig für die Story:** Das Calibration-Target ist als
`sign_return_secondary_diagnostic` deklariert — der blockierende brier-Check misst
einen **Sekundär-Diagnostik-Score**, nicht den primären Return-Edge.

### Strategische Gabel (investor-tauglich, mit Daten entscheiden)

- **A) Signal schärfen.** Wenn scharfe Wahrscheinlichkeiten für Sizing/Risk
  gewollt sind, ist das Sekundär-Gate richtig → **M1 = brier < 0.22** durch
  diskriminierende Features (Confluence-Stärke, HTF-Alignment, Liquiditätskontext);
  Resolution muss grob verdoppelt werden.
- **B) Gate korrigieren.** Wenn ein starker, benchmark-robuster Return-Edge nicht
  an einer **Sekundär**-sign-Wahrscheinlichkeit scheitern soll → ADR-Entscheid, ob
  brier auf dem Sekundär-Diagnostik `info` statt `blocker` ist. Mit Evidenz.

Vorbedingung für **beide**: Zeitbasis-/`ppy`-Fix, sonst ist keine SR-Zahl
belastbar. Der nächste Live-Run (erweitertes Universum/Fenster, damit SWEEP
≥ 120 Trigger erreicht) liefert dann das **zweite** Verdict — und damit den
Kandidaten für **M1: erste Familie auf `edge_supported`**, das erste Objekt mit
Verkaufswert.

## 7. Anti-Kreisverkehr-Mechanismus

Dieses Memo + der `DECISIONS.md`-Eintrag sind die durable Referenz. Vor jeder
neuen Governance-/Infra-Arbeit gilt die Prüffrage: **„Bringt das die EV-20-
Edge-Auswertung näher? Wenn nein — warum jetzt?"**
