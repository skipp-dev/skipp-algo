# Live Overlay — Pine delivery status

> Status corrected 2026-07-16. This file previously described a Pine
> `request.get()`/JSON architecture that TradingView Pine does not support.

The Railway live-overlay daemon and its authenticated `/smc_live` API remain
operational for server-side and future supported consumers. There is currently
**no Pine consumer** for that REST endpoint:

- Pine v6 exposes no documented arbitrary HTTP GET/POST client.
- The retired `request.raw()` consumer failed in TradingView with CE10271.
- Webhooks send alerts out of TradingView and cannot pull JSON into Pine.
- Advanced Charts' JavaScript Datafeed API applies to charts embedded on our
  site, not to scripts running on tradingview.com.

Consequently `LIVE_OVERLAY_EXPECT_MARKET_TRAFFIC` must remain `0`, and its
"not armed" reminder stays paused, until an actual consumer exists. API health,
auth-denied traffic, and server errors are still monitored independently.

The approved planning path is
[ADR-0028](adr/0028-tradingview-data-provider-integration.md): qualify a real
TradingView-hosted provider integration, prove redistribution rights and
end-to-end conformance, then consume the onboarded series from Pine through a
documented TradingView API.
