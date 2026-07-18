# EQUS.SUMMARY daily parity status

Status: `insufficient evidence` until a credential-bound, cost-reviewed 10
symbol × 10 trading-day sample is supplied.

Implemented safeguards:

- `EQUS.SUMMARY` is the canonical EOD role and cannot degrade to an intraday or
  single-venue dataset.
- Daily production-export and terminal paths use the EOD role.
- Intraday outcome backfill remains on `EQUS.MINI`; it was not incorrectly
  migrated to the daily-only dataset.
- Existing historical manifests retain their original `DBEQ.BASIC` provenance.
- `scripts/compare_databento_daily_parity.py` compares coverage and OHLCV deltas
  and refuses to call a smaller sample complete.

No credential-bound parity download was performed as part of this code change.
Missing parity evidence is not represented as a successful comparison.
