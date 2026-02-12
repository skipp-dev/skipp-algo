# SkippALGO — Kurzfassung für neue Nutzer

Stand: 2026-02-12

## Was ist SkippALGO?

SkippALGO ist ein TradingView-Skript mit zwei Teilen:

- **Indicator (`SkippALGO.pine`)**: Signale, Labels, Alerts, Dashboard
- **Strategy (`SkippALGO_Strategy.pine`)**: Backtest-Version mit gleicher Kernlogik

Das System kombiniert:

1. **Outlook (State)** = aktueller Marktzustand
2. **Forecast (Probability)** = Wahrscheinlichkeiten für die nächste Bewegung
3. **Entry/Exit Engine** = konkrete Handelssignale + Risk-Management

---

## In 60 Sekunden starten

1. `SkippALGO` auf den Chart legen
2. `Signal engine` zunächst auf **Hybrid** lassen
3. `Show Long labels` / `Show Short labels` nach Bedarf setzen
4. Alerts erstellen (pro Bar konsolidierte Message)
5. Erst nach einigen Bars/Session auf Forecast-Feinheiten tunen

---

## Wichtig zu wissen

- Das Skript ist auf **bar-close stabile Signale** ausgelegt (non-repainting-orientiert).
- **Strict Mode ist standardmäßig aktiv** (außer im Open-Window um Börsenöffnung).
- Bei REV-BUY gilt ein Sicherheitsfloor: **$pU \ge 37\%$**.

---

## Warum manchmal Alert ohne Label auf derselben Kerze?

Im Strict-Modus sind BUY/SHORT-Alerts um 1 Bar verzögert bestätigt.  
Deshalb kann ein BUY-Alert auf Kerze $t$ erscheinen, während das BUY-Entry-Label auf $t-1$ liegt.

Zusätzlich:

- Strict-Marker sind jetzt side-aware:
  - nur Long sichtbar, wenn `showLongLabels = true`
  - nur Short sichtbar, wenn `showShortLabels = true`

---

## Empfohlene Basis-Settings

Für viele Nutzer ein guter Start:

- Engine: `Hybrid`
- MTF confirmation: `ON`
- ATR Risk: `ON`
- Open-Window: `ON` (mit Default-Werten)
- Short Labels: `OFF`, wenn du nur Long handeln willst

---

## Was ist „Stalemate“?

Stalemate ist ein Zeit-/Fortschritts-Exit:  
Wenn ein Trade nach `staleBars` nicht mindestens `staleMinATR` Fortschritt gemacht hat, wird er beendet.

Ziel: Kapital nicht in seitwärts laufenden, ineffizienten Trades binden.

---

## Nächster Schritt für neue Nutzer

1. Erst nur Long oder nur Short handeln (klarer Fokus)
2. 1–2 Wochen paper testen
3. Dann erst `minDirProb`, `minEdgePP`, Strict-Parameter feinjustieren

---

## Mehr Details

Wenn du tiefer einsteigen willst:

- `docs/SkippALGO_Deep_Technical_Documentation_v6.2.22.md`
