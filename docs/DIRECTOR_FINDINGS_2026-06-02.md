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

## 6. Anti-Kreisverkehr-Mechanismus

Dieses Memo + der `DECISIONS.md`-Eintrag sind die durable Referenz. Vor jeder
neuen Governance-/Infra-Arbeit gilt die Prüffrage: **„Bringt das die EV-20-
Edge-Auswertung näher? Wenn nein — warum jetzt?"**
