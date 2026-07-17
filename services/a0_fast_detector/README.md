# A0-Fast Shadow Worker

Dieser Worker ist die isolierte Deployment-Grenze für A0-Fast. Er abonniert
Databento `EQUS.MINI` mit `ohlcv-1s`, führt quellenreines kumuliertes
Regular-Hours-Volumen und verwendet die gemeinsame Kernentscheidung aus
`open_prep.a0_contract`.

## Sicherheitsvertrag

- Start nur mit `A0_FAST_MODE=shadow`.
- Keine Notification-, Slack-, Pine- oder Signals-Publication-Abhängigkeit.
- Explizites Symbolset; kein implizites `ALL_SYMBOLS`.
- Referenzdatei muss Previous Close und ADV aus Databento enthalten.
- Mid-session-Start, erkannte Lücke oder fehlende Referenz erzeugen kein A0.
- Ausgaben sind `A0_FAST_SHADOW`-Logereignisse mit `decision_scope=core_only`.
- Der produktive FMP-Producer bleibt vollständig unabhängig.

## Pflichtvariablen

| Variable | Bedeutung |
| --- | --- |
| `A0_FAST_MODE` | muss `shadow` sein |
| `DATABENTO_API_KEY` | Databento-Zugang des isolierten Workers |
| `A0_FAST_SYMBOLS` | kommasepariertes, explizites Symbolset |
| `A0_FAST_REFERENCE_FILE` | gemountete JSON-Datei mit `StreamReference`-Zeilen |

Optional: `A0_FAST_MAX_GAP_SECONDS`, `A0_FAST_A0_VOLUME`,
`A0_FAST_A0_PRICE` und die entsprechenden A1-/A2-Schwellen.

## Noch nicht produktionsbereit

Der Worker besitzt noch keinen automatischen Historical Bootstrap und keinen
Reconnect-Gap-Replay. Daher bleibt er nach einem Mid-session-Restart oder einer
Lücke bewusst stumm. A0-302 muss diese Rekonstruktion belegen, bevor ein
mehrsitziger Shadow-Rollout beginnt. Die geloggte Entscheidung ist außerdem
`core_only`; die vollständige zustandsabhängige Parität folgt in A0-303.
