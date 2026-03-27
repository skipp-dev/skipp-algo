# Degraded-Mode Runbook

Operator reference for diagnosing and resolving degraded-mode states
surfaced in the Terminal sidebar.

---

## Quick Health Check

The sidebar shows per-provider status icons and feed diagnostics.
An overall "Degraded" banner appears when **any** of the conditions
below is active.

| Icon | Meaning |
|------|---------|
| ✅   | Provider up, normal latency |
| ⚡   | Provider degraded (≥30% recent failures) |
| 🔴   | Provider down (≥80% failures **or** 5+ consecutive) |
| ❓   | No calls recorded yet |

---

## Common Scenarios

### 1. Provider Down — Benzinga / News API

**Symptom:** 🔴 next to "News API", no new articles in the feed.

**Root causes:**
- `BENZINGA_API_KEY` expired or rate-limited.
- Benzinga API outage (check https://status.benzinga.com).
- Network / DNS issue from the host.

**Actions:**
1. Check `.env` for a valid `BENZINGA_API_KEY`.
2. Curl the health endpoint:  
   `curl -s -o /dev/null -w "%{http_code}" "https://api.benzinga.com/api/v2/news?token=$BENZINGA_API_KEY&pageSize=1"`
3. If 401/403: rotate the key.
4. Click **Reset Cursor** in the sidebar after fixing to force a fresh poll.

---

### 2. Feed Stale (> 5 min during market hours)

**Symptom:** Yellow "Feed age: Xm" warning in the sidebar.

**Root causes:**
- API returning empty results (low-news period or cursor stuck).
- Background poller stopped or crashed.
- All sources disabled (no Benzinga key, no TradingView).

**Actions:**
1. Click **Poll Now** to trigger an immediate poll.
2. If the poll returns 0 items, click **Reset Cursor**.
3. Check `consecutive_empty_polls` in the sidebar — if > 5, the
   cursor may be stuck at a future timestamp.
4. If off-hours (> 15m threshold), this is expected and no action
   is needed.

---

### 3. Consecutive Empty Polls (≥ 3)

**Symptom:** "X consecutive empty polls — cursor may be stuck" in
the degraded-mode reasons.

**Root causes:**
- Cursor timestamp is ahead of the newest article.
- Benzinga feed is genuinely quiet (common overnight / weekends).
- Filter settings are too restrictive (category / relevance).

**Actions:**
1. Click **Reset Cursor** to clear the updatedSince filter.
2. Review filter settings in the sidebar (categories, min relevance).
3. If persistent, check the Benzinga dashboard for account status.

---

### 4. Background Poller Error

**Symptom:** "Background poller error: …" in the degraded-mode
reasons, or the poll count stops incrementing.

**Root causes:**
- Unhandled exception in the poll cycle (check terminal logs).
- SQLite lock contention (another process holding the DB).
- Memory pressure causing the thread to be killed.

**Actions:**
1. Check the Streamlit terminal output for stack traces.
2. Click **Reset dedup DB** to close and recreate the database
   connection (this also restarts the background poller).
3. If memory-related, restart the Streamlit server.

---

### 5. TradingView API Degraded / Down

**Symptom:** ⚡ or ⚠️ indicator in the sidebar for TradingView.

**Root causes:**
- TradingView's unofficial API is rate-limited or blocked.
- Network filtering (corporate proxy blocking the endpoint).

**Actions:**
1. The system auto-recovers when TradingView becomes reachable
   again — health transitions are logged in the alert log.
2. If persistent, check network connectivity:  
   `curl -s -o /dev/null -w "%{http_code}" "https://news-headlines.tradingview.com/v2/headlines"`
3. TradingView headlines are supplementary; the terminal continues
   functioning with Benzinga alone.

---

### 6. Databento Not Configured

**Symptom:** Dash (—) next to Databento in the sidebar.

This is **informational**, not degraded.  Quote enrichment (bid/ask,
volume) is disabled but the terminal works without it.

**Action:** Set `DATABENTO_API_KEY` in `.env` if you want quote data.

---

## Programmatic Access

The `degraded_mode_reasons()` function in `terminal_status_helpers.py`
returns a `list[str]` of all active reasons.  It accepts:

- `provider_statuses` — list of `ProviderStatus` dicts from
  `ProviderTracker.all_statuses()`
- `feed_staleness_min` — minutes since the newest feed item
- `consecutive_empty_polls` — current empty-poll streak
- `bg_poller_last_failure` — dict with `last_poll_error` key
- `is_market_hours` — whether US equity markets are open

An empty list means the system is healthy.

The `ProviderTracker` class in `smc_tv_bridge/provider_status.py` can
be integrated with any adapter call to automatically track availability,
latency percentiles, and consecutive failure counts.

---

## Related Files

| File | Purpose |
|------|---------|
| `terminal_status_helpers.py` | Pure status-rendering functions |
| `smc_tv_bridge/provider_status.py` | Provider health tracking primitives |
| `terminal_feed_lifecycle.py` | Feed staleness + market-hours detection |
| `terminal_background_poller.py` | Background poll thread |
| `streamlit_terminal.py` | Sidebar rendering (consumes all above) |
