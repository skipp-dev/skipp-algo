# Warum (noch) keine SMC-Familie promotet wird — Resolution ist der Blocker

> **Stand:** 2026-06-02. **Zielgruppe:** Product Owner / Stakeholder ohne
> ML-Hintergrund. **Kurzfassung:** Der Return-Edge ist real, aber die
> Wahrscheinlichkeitsvorhersagen der Familien sind zu wenig trennscharf
> (Resolution-Problem). Das ist der einzige verbleibende harte Blocker auf dem
> Weg zur ersten promotbaren Strategie — und er lässt sich **nicht** mit
> Governance lösen, sondern nur mit besseren, diskriminierenderen Features.

---

## 1. Worum es geht

Wir bauen Trading-Strategien (die SMC-Familien `BOS`, `OB`, `FVG`, `SWEEP`).
Bevor eine Strategie echtes Geld bekommt, muss sie durch ein **Promotion-Gate**
— eine Checkliste von Prüfpunkten (Guards). Erst wenn genug Häkchen gesetzt
sind, gilt eine Strategie als promotbar.

Die Checkliste hat **zwei Stufen** (festgelegt in ADR-0015):

- **Tier 1 — `edge_supported`:** Hat die Strategie überhaupt einen echten
  Vorteil? Verdient sie out-of-sample Geld? (PSR, Stichprobengröße,
  Integritäts-Checks.)
- **Tier 2 — `risk_sizeable`:** Kann ich die Strategie auch dosieren und
  risikomanagen? Dafür müssen ihre Wahrscheinlichkeitsvorhersagen verlässlich
  sein (Brier, ECE).

Tier 2 ist strenger und baut auf Tier 1 auf.

## 2. Was E1, E2, E3 gemacht haben (und was nicht)

Auf der Tier-1-Checkliste standen drei Punkte, die das Gate **nicht bewerten
konnte** — nicht weil die Strategie schlecht war, sondern weil die Pipeline die
nötige Messung gar nicht geliefert hat. Das Gate sagte dann ehrlich „noch nicht
gemessen" und blockierte vorsichtshalber.

Bild: eine TÜV-Checkliste, bei der drei Felder leer bleiben, weil das Messgerät
nie angeschlossen wurde. Der Prüfer kann nicht abhaken — also fällt das Auto
durch, obwohl es vielleicht fährt.

Die drei E-Tracks haben genau diese leeren Felder behandelt:

| Track | Guard | Was getan wurde |
|-------|-------|-----------------|
| **E1** (ADR-0016) | `provenance`-Keys (3 ML-Felder) | Geklärt, dass diese Felder für unsere ML-freie Pipeline nicht zutreffen → sauber als „nicht anwendbar" gewaivt, statt sie zu erfinden |
| **E2** (ADR-0017) | `live_vs_wf_ratio` | Mess-Methode definiert, die das Feld befüllt (jüngstes Datenfenster als Live-Surrogat) |
| **E3** (ADR-0018) | `conformal_coverage` | Mess-Methode definiert (split-conformal), die das Feld befüllt |

**Der ehrliche Teil:** Es wurde **keine Schwelle gesenkt** und **kein Ergebnis
geschönt**. Es wurde nur das Messgerät angeschlossen. „Messbar gemacht oder als
nicht-zutreffend gewaivt" heißt: das Gate kann jetzt ein ehrliches Häkchen oder
Kreuz setzen, wo vorher nur „unbekannt" stand. Kein verschobenes Tor — nur
Lampen eingeschaltet, die vorher dunkel waren.

## 3. Warum trotzdem keine Familie promotet

Weil das eigentliche Problem woanders liegt — auf Tier 2, beim **Brier-Score**,
der an der **Resolution** (Trennschärfe) hängt.

- Eine Strategie soll für jedes Setup eine Wahrscheinlichkeit ausgeben („dieser
  Trade gewinnt mit 70 %").
- Der Brier-Score misst, wie gut diese Wahrscheinlichkeiten sind. Niedriger =
  besser. Die Schwelle ist **0,22**.
- Unsere Familien liegen bei **0,228–0,284**. Zum Vergleich: **0,25 ist der
  reine Münzwurf** (immer „50 %" sagen).

Heißt: Die Wahrscheinlichkeitsvorhersagen sind nur knapp besser als Raten.

### 3.1 Brier zerlegt — wo genau klemmt es

Der Brier-Score besteht aus zwei Teilen:

```text
Brier = Uncertainty(0,25) − Resolution + Reliability
        ^Konstante          ^Trennschärfe ^Eichung
```

- **Reliability / Eichung** (gemessen über ECE ≈ 0,034–0,044): **gut.** Wenn die
  Strategie „70 %" sagt, treffen ungefähr 70 % ein. Die Zahlen lügen nicht.
- **Resolution / Trennschärfe:** **das Problem.** Nur **3–6 %** der
  Gesamt-Unsicherheit wird aufgelöst. Im Klartext: Die Strategie gibt bei guten
  und schlechten Setups fast immer Werte nahe 50 % aus — sie trennt Gewinner
  kaum von Verlierern.

**Konsequenz:** Eine reine Nachkalibrierung (die Wahrscheinlichkeitskurve
glätten) würde **nichts** bringen, weil die Eichung schon gut ist. Das Problem
ist nicht, wie die Wahrscheinlichkeiten skaliert sind, sondern dass die
Strategie zu wenig Information hat, um gute von schlechten Trades zu trennen.

### 3.2 Die scheinbar paradoxe Pointe aus E3

Die `conformal_coverage`-Messung kam bei **1,0** heraus (Ziel: 0,9) — auf den
ersten Blick ein „bestandener" Wert. Aber das ist **kein Erfolgssignal**:

> Weil die Strategie schlecht trennt, gibt sie breite, vorsichtige Vorhersagen
> aus. Breite Vorhersagen werden fast immer getroffen → hohe Coverage. Das
> zertifiziert, dass die Vorhersage-Mengen kalibriert sind, **nicht** dass die
> Strategie gut diskriminiert.

Genau deshalb ist das kein Fortschritt im verkaufbaren Sinn. Eine Familie kann
`conformal_coverage` klären **und trotzdem** am Brier scheitern. Das tut sie auch.

## 4. Was „der einzige Pfad mit echtem Produktwert ist die Resolution" bedeutet

- **Der Return-Edge ist real.** PSR ≈ 0,99–1,00, sogar gegen SPY-Buy-and-Hold.
  Die Strategien verdienen im Backtest tatsächlich Geld. Das ist der verkaufbare
  Kern.
- **E1/E2/E3 waren Aufräum- und Mess-Arbeit** — notwendig für die Ehrlichkeit
  der Checkliste, aber sie erzeugen keinen neuen Edge.
- **Der eine harte Blocker (M1) ist die Resolution.** Den löst man nicht mit
  mehr Governance, ADRs oder Gate-Logik, sondern nur mit besseren,
  diskriminierenderen Features — echter Modelling-Arbeit am Signal selbst: Was
  unterscheidet einen gewinnenden `BOS`-Breakout von einem verlierenden? Diese
  Information fehlt dem Modell aktuell.

**Bilanz:** Das Fließband (Gate, Guards, Provenance) ist fertig poliert. Das
Werkstück — eine Strategie mit trennscharfen Wahrscheinlichkeiten — existiert
noch nicht. Der nächste echte Produktschritt ist, dem Modell beizubringen, gute
von schlechten Setups zu unterscheiden.

## 5. Belegende Zahlen (5-Run-Mittel, EV-20)

| Familie | Brier | ECE | Resolution-Band | PSR vs 0 | PSR vs SPY | Verdict |
|---------|------:|----:|-----------------|---------:|-----------:|---------|
| `BOS` | 0,242 | 0,059 | 0,008–0,043 (3–17 %) | 1,000 | 0,996 | tier-1 fähig, tier-2 blockiert |
| `OB` | 0,242 | 0,034 | 0,010–0,047 (4–19 %) | 1,000 | 1,000 | tier-1 fähig, tier-2 blockiert |
| `FVG` | 0,240 | 0,044 | 0,015–0,052 (6–21 %) | 1,000 | 1,000 | tier-1 fähig, tier-2 blockiert |
| `SWEEP` | 0,266 | 0,175 | −0,007–0,134 (Untergrenze < 0) | 0,996 | 0,990 | inconclusive (n < 120) |

Brier-Schwelle (tier-2 `risk_sizeable`): **≤ 0,22**. Alle Familien verfehlen sie
wegen schwacher Resolution, nicht wegen schlechter Eichung.

## 6. Verwandte Dokumente

- ADR-0015 — Zwei-Stufen-Taxonomie (`edge_supported` / `risk_sizeable`).
- ADR-0016 — Pipeline-Provenance-Klassen (E1).
- ADR-0017 — Live-Incubation-Surrogat für `live_vs_wf_ratio` (E2).
- ADR-0018 — Split-Conformal-Coverage aus Walk-Forward-OOS (E3).
