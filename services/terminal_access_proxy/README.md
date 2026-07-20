# Terminal access proxy

The proxy keeps the Streamlit Terminal behind `TERMINAL_ACCESS_TOKEN` and also
exports a bounded machine contract for the local Skipp Sidecar:

```text
GET /api/v1/news-candidates
Authorization: Bearer <TERMINAL_ACCESS_TOKEN>
```

The response schema is `skipp-live-news-candidates/1`. It contains at most one
current `ALERT`, `FOCUS`, or `MONITOR` item per ticker from the retained Terminal
JSONL. This is a candidate export, not a complete-market or no-news assertion.
Missing feed state fails with `503`; malformed, stale and inactive rows are not
exported and are counted in diagnostics.

Configuration:

- `TERMINAL_JSONL_PATH` (default `artifacts/terminal_feed.jsonl`)
- `TERMINAL_CANDIDATE_MAX_AGE_SECONDS` (default 14400; range 60–86400)
- `TERMINAL_CANDIDATE_LIMIT` (default 100; range 1–500)

The endpoint uses `Cache-Control: no-store`. The existing HTML session and
Bearer authentication rules remain unchanged; credentials are never forwarded
to Streamlit.
