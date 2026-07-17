# A0-Entscheidungs-, Reason- und Zeitvertrag

Stand: 2026-07-17  
Vertragsversion: 1  
Implementierung: `open_prep/a0_contract.py`

## Zweck

Der Vertrag trennt Providerdaten, berechnete Features, die reine
Schwellenentscheidung und zustandsabhängige Modifikatoren. Damit kann dieselbe
Momentaufnahme deterministisch wiedergegeben und später sowohl vom FMP- als
auch von einem Streamingadapter verwendet werden.

## Entscheidungsschichten

1. Der Provideradapter erzeugt einen `A0MarketSnapshot`.
2. `decide_core_level` wendet ausschließlich die effektiven A0/A1/A2-
   Schwellen an.
3. Die Engine wendet Hysterese, Momentum, Cooldown, technische Bestätigung,
   News und Requalifikation an.
4. `A0Decision` hält `core_level`, `final_level` und den vollständigen
   `reason_codes`-Pfad getrennt.

Provideradapter dürfen keine Levelentscheidung enthalten. Zustandsabhängige
Modifikatoren dürfen das Level nicht ohne einen stabilen Reason Code ändern.

## Volumenvertrag

| Feld | Bedeutung |
| --- | --- |
| `raw_daily_volume_ratio` | bisher gehandeltes Tagesvolumen geteilt durch historisches durchschnittliches Tagesvolumen derselben Quelle |
| `expected_volume_fraction` | zu diesem Zeitpunkt erwarteter kumulierter Tagesanteil |
| `normalized_volume_pace` | rohe Tagesratio geteilt durch erwarteten Tagesanteil |
| `volume_ratio` | befristeter Kompatibilitätsalias für die rohe Tagesratio; darf von neuer Fachlogik nicht verwendet werden |

## Zeitvertrag

| Feld | Definition |
| --- | --- |
| `ts_event` | plausibilisierte Provider-Ereigniszeit in Unixsekunden oder `null` |
| `ts_recv` | lokale beziehungsweise explizit gelieferte Empfangszeit |
| `observed_at` | Zeitpunkt, zu dem der Adapter die Momentaufnahme erstellt |
| `decision_at` | Zeitpunkt der Kernentscheidung |
| `data_age_ms` | `observed_at - ts_event`, niemals negativ; bei unbekannter Ereigniszeit `null` |
| `data_age_unknown` | `true`, wenn `ts_event` fehlt, nicht numerisch, vor 2000 liegt oder mehr als 60 Sekunden in der Zukunft liegt |
| `session_date` | US-Equities-Sitzungsdatum in `America/New_York` |

Sekunden- und Millisekunden-Epochen werden akzeptiert. Eine unbekannte oder
unplausible Zeit wird nicht als frisch interpretiert.

## Idempotenz

`decision_basis_id` identifiziert die normalisierte Provider-Momentaufnahme.
`decision_id` wird deterministisch aus dieser Basis, finalem Level und dem
geordneten Reason Trail gebildet. Ein Retry derselben fachlichen Entscheidung
erhält dieselbe ID; eine fachliche Level- oder Reason-Änderung erhält eine neue.

## Reason Codes

Die kanonische Liste ist `A0ReasonCode`. Sie umfasst:

- Kernschwellen für A0, A1 und A2 sowie die beiden Large-Move-Pfade
- PDH-/PDL-Upgrades
- Falling-Knife-, Stale-Velocity-, RSI-, technische und Momentum-Korrekturen
- Hysterese und Cooldown
- News-Katalysator-Upgrade
- Zeitablauf- und Requalifikations-Downgrade

Reason Codes sind persistente Maschinenschnittstellen. Umbenennungen benötigen
eine neue Vertragsversion oder eine explizite Migration.

## Persistenz und Kompatibilität

Das Signal-Event-Schema v2 persistiert den vollständigen Vertrag. Historische
Schema-v1-Zeilen bleiben lesbar, sind bei der Volumensemantik aber ausdrücklich
als `legacy_ambiguous_v1` gekennzeichnet. Fehlerhafte neue Zeilen werden nicht
stillschweigend als Altformat interpretiert.

## Noch offene Grenzen

- Der Streamingadapter ist noch nicht angeschlossen.
- Ein Sunset-Datum für den `volume_ratio`-Alias wird erst nach Migration aller
  Consumer festgelegt.
- Production-Promotion bleibt an die Messfenster und Gates des Action Plans
  gebunden.
