# Clean-Room Momentum-Ribbon v2 — ADR-0019-Schatten-Kandidat erklärt

> **Stand:** 2026-06-03. **Zielgruppe:** Product Owner / Stakeholder ohne
> ML-Hintergrund. **Kurzfassung:** Unser aktueller Score schaut auf *kein*
> Momentum-Signal. Die Momentum-Ribbon v2 ist ein sauber nachgebautes,
> leak-freies Trendreife-Feature, das die diagnostizierte **Resolution-Lücke**
> schließen *könnte* — bewusst im Schatten gehalten, bis ein vorregistriertes
> A/B beweist, dass es echten, nicht-redundanten Mehrwert bringt.

Quelle: [`governance/family_momentum_ribbon_v2.py`](../../governance/family_momentum_ribbon_v2.py),
PR [#2534](https://github.com/skippALGO/skipp-algo/pull/2534).

---

## 1. Das Problem, das sie lösen soll

Unser aktueller Per-Family-Score (v1, Provenance-Tag
`atr_normalised_geometry_strength_v1`) schaut auf **genau ein Signal**: eine
ATR-normalisierte Geometrie-Stärke.

Die Murphy/Brier-Zerlegung des EV-20-Laufs hat klar gezeigt: Der
Promotion-Blocker ist die **Resolution (Diskrimination)** — also die Fähigkeit,
Gewinner von Verlierern zu trennen (siehe
[`why_no_family_promotes_resolution_blocker.md`](why_no_family_promotes_resolution_blocker.md)).
Die Feature-Gap-Analyse (ADR-0019) hat aufgedeckt: Der Score schaut auf **gar
kein Momentum- bzw. Trendreife-Signal**. Genau diese Lücke will die Ribbon
füllen.

## 2. Was die Ribbon technisch macht

Stell dir mehrere geglättete RSI-Linien unterschiedlicher Länge übereinander vor
— wie ein Guppy/GMMA-Bändermuster, aber auf dem **Oszillator** statt auf dem
Preis:

1. **USI = geglätteter RSI.** „Ultimate Strength Index" ist nur ein
   Marketing-Name für einen geglätteten RSI. Wir nehmen einen deterministischen
   **Cutler-RSI** (SMA von Gewinnen/Verlusten, keine Wilder-Seeding-
   Mehrdeutigkeit), optional EMA-geglättet.
2. **Multi-Length-Ribbon.** Mehrere dieser USI-Linien mit verschiedenen Längen
   (Default `(3, 5, 7, 11, 13)`) übereinandergelegt. Die **Stapelreihenfolge**
   kodiert den Trend: Im Aufwärtstrend liegen die schnellen (kurzen) Linien
   oben, im Abwärtstrend unten.
3. **Zwei modellnutzbare Features:**
   - **Stack-State** (kategorial): `+1` bull (streng absteigende Reihenfolge),
     `-1` bear (streng aufsteigend), `0` mixed.
   - **Stack-Score** (kontinuierlich, vorzeichenbehaftet): die mittlere
     Spreizung über alle geordneten Paare → Trendstärke und -reife.

## 3. „Clean-Room" — warum das wichtig ist

Die Vorlage waren zwei **Closed-Source** TradingView-Skripte. „Clean-Room"
heißt: Wir haben **keinen** proprietären Code übernommen, sondern nur die
öffentlich dokumentierten *Konzepte* (Smoothed-RSI-Ribbon, Stack-Order) aus
Lehrbuch-Bausteinen neu gebaut. Die exakte proprietäre Glättung ist für die Edge
irrelevant und wird als **Hyperparameter behandelt, nicht erraten**. Das hält
uns rechtlich und methodisch sauber.

## 4. „Schatten-Kandidat" (ADR-0019) — der entscheidende Punkt

„Schatten" bedeutet: Das Feature ist **noch NICHT verdrahtet**.

- Es fließt **nicht** in `raw_score` / `SCORE_SOURCE` und **nicht** in das
  Promotion-Gate.
- Es ist reine **Mess-Vorarbeit** — genau wie das Schwester-Feature
  `relative_volume_at` in `governance/family_score_features_v2.py`.
- ADR-0019 schreibt vor: Bevor irgendetwas verdrahtet wird, muss ein
  **vorregistriertes, purged Walk-Forward-A/B** (`governance/family_feature_ab.py`)
  beweisen, dass die Ribbon die **OOS-Resolution gegenüber dem v1-Score
  anhebt**.

Der ehrliche Vorbehalt steht direkt im Modul: Eine Momentum-Ribbon auf einem
Daily-Breakout-Setup **überlappt vermutlich stark** mit der bestehenden
SMC-Edge. Das A/B muss also *additiven* Lift von bloßer *Redundanz* trennen.
Dieses Modul **produziert nur den Kandidaten — es zertifiziert nichts.**

## 5. Zwei eingebaute Ehrlichkeits-Garantien

- **Leak-frei (Point-in-Time):** Jeder Wert an `anchor_idx` liest ausschließlich
  Closes mit Index `<= anchor_idx`. RSI-Fenster und EMA-Glättung schauen strikt
  rückwärts — nie auf einen Balken nach dem Anker. Konsistent mit dem
  EV-04-Lookahead-Guard und `family_event_score.atr_at`.
- **Ehrliche Auslassung:** Gibt `None` zurück (Feature *abwesend* — nie
  erfunden, nie mit Null gefüllt), wenn ein Close fehlt/ungültig ist, die
  Historie für die längste Länge plus Glättungs-Warmup nicht reicht, oder ein
  Fenster degeneriert ist. Insbesondere liefert die Stack-Auswertung `None`,
  wenn weniger als zwei Linien vorliegen (kein Paar zum Ordnen).

## 6. In einem Satz

Die Momentum-Ribbon v2 ist ein sauber nachgebautes, leak-freies
Trendreife-Signal, das die diagnostizierte Resolution-Lücke des v1-Scores
schließen *könnte* — aber bewusst im Schatten gehalten wird, bis ein
vorregistriertes A/B beweist, dass es echten, nicht-redundanten Mehrwert bringt.
