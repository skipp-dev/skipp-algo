# Live Overlay — Pine delivery status

> Status corrected 2026-07-16. This file previously described a Pine
> a retired server-to-Pine network architecture that TradingView Pine does not
> support.

The Railway live-overlay daemon and its authenticated `/smc_live` API remain
operational for server-side consumers — since 2026-07-22/23 the Layer-B
Sidecar technical poller IS a live consumer (sustained ~3.9 req/min measured
on production /metrics, see tests/test_live_overlay_dashboard_contract.py).
There is still **no Pine consumer** for that REST endpoint:

- Pine v6 exposes no documented arbitrary HTTP GET/POST client.
- The retired Pine network consumer failed to compile in TradingView.
- Webhooks send alerts out of TradingView and cannot pull JSON into Pine.
- Advanced Charts' JavaScript Datafeed API applies to charts embedded on our
  site, not to scripts running on tradingview.com.

`LIVE_OVERLAY_EXPECT_MARKET_TRAFFIC` was therefore flipped to `1` in
production on 2026-07-23 (this file previously said "must remain 0 until an
actual consumer exists" — that consumer now exists, see above). The
"lo-expected-traffic-not-armed" rule now guards the opposite direction:
reverting the flag to 0 while the consumer is live is the alertable state.
API health, auth-denied traffic, and server errors are monitored independently.

No TradingView delivery path is planned for this REST bridge.
