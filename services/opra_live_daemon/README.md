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

The service bootstraps definitions from the previous complete UTC day and also
subscribes to definition updates. Trades whose instrument is still unknown are
held temporarily and counted; they are never guessed. Reconnects use exponential
backoff with jitter. The local snapshot is written atomically and marked
`shadow_only: true`.

The append-only ledger is local/private operational evidence and is ignored by
Git. It contains processed candidate metadata only, never credentials or full
provider records.

Operational gates before any product decision:

- observe 7–10 complete US sessions;
- verify definition coverage, duplicate rate, gaps and latency;
- verify zero direct UI provider calls and zero product alerts;
- run the checked-in shadow evaluation and decide separately whether the
  subscription has incremental value.
