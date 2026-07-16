# SMC Onboarding

SMC Onboarding connects the supported SMC consumer scripts already present on a
TradingView chart to the `SMC Long-Dip Suite` on that same chart. It does not add
missing consumers automatically. Missing consumers are reported and can be added
before running onboarding again.

## Requirements

- Windows x64, macOS Apple Silicon, or macOS Intel.
- Google Chrome or Microsoft Edge installed locally.
- A TradingView account with access to the SMC scripts.
- A TradingView chart containing a running `SMC Long-Dip Suite`.
- Internet access to TradingView.

The packaged application includes Node.js and all required automation
dependencies. End users do not need to install Node.js, npm, Playwright, or a
separate automation browser.

## Quick start

1. Download the package matching your operating system and architecture.
2. Extract the entire package to a local folder.
3. Start `Start SMC Onboarding.cmd` on Windows or
   `Start SMC Onboarding.command` on macOS.
4. Paste the URL of the TradingView chart that should be configured.
5. If a browser window asks you to sign in, sign in directly at TradingView and
   leave the window open.
6. Wait while onboarding inventories the chart and connects every detected
   consumer.
7. Review the local HTML result report.

Running onboarding again is safe. It deliberately reselects every detected BUS
source so correct-looking dropdown labels with obsolete internal TradingView
parent IDs are repaired as well.

## What onboarding changes

For every supported consumer already on the chart, onboarding opens its settings
and connects each `BUS ...` input to the matching output of the chart's
`SMC Long-Dip Suite`. It then reopens the settings and verifies the selections.

Onboarding does not:

- add or remove indicators or strategies;
- update Pine source code;
- publish scripts or libraries;
- modify unrelated script settings;
- upload login data, bindings, chart URLs, or reports;
- publish the result to the production binding-monitoring snapshot.

## Result states

### Complete

The suite and all supported consumers were present, and every detected BUS
binding was connected and verified.

### Partial

The suite was present and every detected consumer was connected successfully,
but one or more supported consumers were not on the chart. Add any missing
consumers you want to use, then run onboarding again.

### Blocked

Onboarding could not safely start binding changes. Common causes are a missing
suite, unavailable suite BUS outputs, missing TradingView login, an invalid chart
URL, or an unsupported browser. When the chart was reachable, the report still
lists which consumers were detected and which were missing.

### Failed

At least one detected consumer could not be connected or verified. Other detected
consumers are still processed. Review the per-consumer details, correct the
reported problem, and run onboarding again.

## Files created locally

SMC Onboarding creates a dedicated browser profile and local reports in the
operating system's application-data folder:

- Windows: `%LOCALAPPDATA%\SMC Onboarding`
- macOS: `~/Library/Application Support/SMC Onboarding`

The HTML report is for people. The JSON report contains the same result in a
machine-readable form. See [Privacy and local data](PRIVACY.md) before sharing a
report or removing the local profile.

## More information

- [Windows installation](WINDOWS.md)
- [macOS installation](MACOS.md)
- [Preparing the TradingView chart](PREPARE_CHART.md)
- [Troubleshooting and error codes](TROUBLESHOOTING.md)
- [Privacy and local data](PRIVACY.md)

## Developer-only source installation

The source checkout supports:

```text
npm ci
npm run tv:onboard -- --chart-url https://www.tradingview.com/chart/...
```

This method requires Node.js and npm and is intended for developers. End users
should use the packaged application, which requires neither an npm installation
nor npm knowledge.
