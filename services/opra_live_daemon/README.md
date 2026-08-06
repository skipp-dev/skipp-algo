# OPRA live shadow daemon

This service is the only live OPRA consumer. It subscribes to a small parent
symbol hotlist, joins live `tcbbo` prints to OPRA definitions, runs the existing
UOA detector, and writes a local processed snapshot. It sends no alerts and
publishes no raw data.

The default is fail-closed:

```text
OPRA_LIVE_MODE=off
```

To run an approved local shadow:

```text
OPRA_LIVE_MODE=shadow
DATABENTO_API_KEY=<secret>
OPRA_LIVE_HOTLIST=SPY,QQQ,AAPL,NVDA,TSLA
# optional dynamic newline/comma list; changes trigger a resubscribe
OPRA_LIVE_HOTLIST_PATH=artifacts/monitoring/opra_hotlist.txt
OPRA_LIVE_SNAPSHOT_PATH=artifacts/monitoring/opra_live_shadow.json
OPRA_SHADOW_LEDGER_PATH=artifacts/monitoring/opra_shadow_ledger.jsonl
```

On Railway the isolated service uses the dedicated Dockerfile and a persistent
volume at `/app/data`:

```text
OPRA_LIVE_SNAPSHOT_PATH=/app/data/opra_live_shadow.json
OPRA_SHADOW_LEDGER_PATH=/app/data/opra_shadow_ledger.jsonl
DATABENTO_USAGE_SNAPSHOT_PATH=/app/data/databento_usage.json
```

Do not attach a public domain. The worker has no HTTP, alert, notification, or
product-publication surface. Operational verification uses Railway deployment
status, private logs, and the mounted files only. Databento's per-contract
symbology mapping messages are suppressed at INFO because a five-parent
subscription can otherwise exceed Railway's log-ingestion limit; warnings and
errors remain visible.

The service bootstraps definitions from the most recent available complete UTC
weekday and also subscribes to definition updates. It searches backwards for
up to seven days so weekend and provider-unavailable holiday windows do not
prevent a live restart. Errors other than the provider's explicit
`data_start_after_available_end` response remain fail-closed. The bootstrap is
not one-shot: the supervision loop re-attempts it while it is unsatisfied —
after a failure (Databento Historical answered 504 for hours on 2026-08-04,
leaving the replica definition-less for a whole trading day) with a delay that
doubles from 30 s to a 15 min cap, and after the UTC session roll, which clears
the held definitions. Trades whose
instrument is still unknown are held temporarily and counted; they are never
guessed. Reconnects use exponential backoff with jitter. The local snapshot is
written atomically and marked `shadow_only: true`.

The append-only ledger is local/private operational evidence and is ignored by
Git. It contains processed candidate metadata only, never credentials or full
provider records.

Operational gates before any product decision:

- observe 7–10 complete US sessions;
- verify definition coverage, duplicate rate, gaps and latency;
- verify zero direct UI provider calls and zero product alerts;
- run the checked-in shadow evaluation and decide separately whether the
  subscription has incremental value.
