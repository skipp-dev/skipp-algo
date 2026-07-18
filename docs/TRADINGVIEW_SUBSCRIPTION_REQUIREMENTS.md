# TradingView subscription requirements

**Last reviewed:** 2026-07-18
**Scope:** Pine scripts and TradingView publishing automation

## Supported boundary

TradingView is the chart and Pine execution environment. The repository does
not provide a chart-vendor data integration, and Pine scripts do not
consume the live-overlay REST service. Server-side services and Pine scripts
are separate products unless a documented, Pine-native data surface connects
them.

The subscription decision therefore depends only on TradingView's documented
Pine and chart limits:

- number of indicators allowed on one chart;
- availability and quota of lower-timeframe intrabar data;
- historical-bar depth and alert quotas;
- publishing and collaboration features needed by the operator.

## skipp-algo feature impact

| Repository capability | TradingView dependency |
|---|---|
| Core structure, order blocks, FVGs and bar-close signals | Pine execution |
| Higher-timeframe context | Pine `request.security()` quota |
| Intrabar participation and pressure | Pine `request.security_lower_tf()` quota and available intrabars |
| Multiple overlays on one chart | Indicator-per-chart limit |
| Library refresh and publish automation | Account publishing permissions |
| Server-side Databento/FMP processing | None; it does not run inside TradingView |
| Live-overlay REST service | None; there is no Pine consumer |

## Selection guidance

Do not choose a plan based on a presumed server-to-Pine network bridge. Choose
the smallest plan whose current indicator, intrabar, history, alert and
publishing limits cover the intended chart setup. TradingView changes plan
names and quotas over time, so verify those limits in the account's current
plan comparison before purchasing or renewing.

For a constrained account, disable optional lower-timeframe sampling and load
only the core scripts required for the workflow. This reduces TradingView
resource usage without changing the independent server-side pipelines.

## Repository invariant

Documentation and code must not describe an arbitrary Pine network consumer, a
chart-vendor partnership, or a server endpoint as a Pine data source.
Legitimate TradingView automation, Pine-native data requests and library
publishing remain supported.
