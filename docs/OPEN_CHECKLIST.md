# Open Execution Checklist

Kurz-Checkliste fuer den US-Open-Workflow mit `databento_volatility_screener`.

Hinweis zu Uhrzeiten: Empfohlene Zeitfenster (z. B. `15:23-15:26`) sind Startfenster, keine Laufzeitgarantie.
Die tatsaechliche Laufzeit fuer `Refresh Data Basis` haengt von Cache-Status, API-Latenz, Datensatzgroesse und Lookback ab.

## 10-Zeilen Execution Sheet

1. Status check: Daten `fresh`, kein `stale`-Hinweis, Export heute.
2. Kandidat: Nur Watchlist `#1-#3` priorisieren.
3. Gap-Qualitaet: `prev_close_to_premarket_pct >= +1.5%`.
4. Liquiditaet: Premarket nicht duenn (`premarket_volume` und `premarket_trade_count` solide).
5. Open-Power: `open_1m_rvol_20d >= 1.2` oder `open_5m_rvol_20d >= 1.2`.
6. Trigger L1: Reclaim bestaetigt, Entry nur auf `l1_limit_buy`.
7. Risk: Hard-SL sofort aktiv (`l1_stop_loss`), kein Averaging Down.
8. Add only on confirm: `L2/L3` nur wenn Struktur haelt und neues Hochdruck-Momentum entsteht.
9. Invalidation: 2x Reclaim-Fail oder Strukturbruch -> Exit/Skip sofort.
10. Disziplin: Max. 2 schlechte Trades pro Tag, danach nur A+-Setups oder Schluss.

## Go/No-Go Kurzregel

- `GO`: Gap + Liquiditaet + RVOL + sauberer Reclaim.
- `NO-GO`: Datenluecken, duenne Liquiditaet, sofortige Rejection, Strukturbruch.

## Ablauf (30 Sekunden)

1. In der UI Data Status pruefen.
2. Top-N Tabelle auf `#1-#3` reduzieren.
3. Detail Entry oeffnen und die 10 Punkte nacheinander abhaken.
4. Nur bei vollem Go handeln, sonst ohne Diskussion skippen.
