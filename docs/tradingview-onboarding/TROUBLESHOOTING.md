# Troubleshooting and error codes

Every blocking message states what happened, whether bindings were changed, and
what to do next. Running onboarding again is safe after correcting the problem.

## `ONB-OS-001` — unsupported operating system

The package supports Windows and macOS. Use a matching supported computer and
download the correct package architecture.

## `ONB-BROWSER-001` — browser not found

No supported local browser was detected, or the path supplied with
`--browser-path` does not exist.

Install Google Chrome or Microsoft Edge and rerun onboarding. npm and a separate
Playwright browser are not required.

## `ONB-BROWSER-002` — browser could not start

Close other SMC Onboarding windows and rerun. A dedicated profile cannot be
opened by two processes at the same time. If a custom browser path was supplied,
verify that it points to a trusted Chrome or Edge executable.

No binding changes are made when the browser cannot start.

## `ONB-CHART-001` — invalid or missing chart URL

Open the target TradingView chart, copy the complete
`https://www.tradingview.com/chart/...` URL, and rerun. The suite and consumers
must be on that same chart.

## `ONB-AUTH-001` — sign-in not completed

Start onboarding again, complete sign-in in the browser window opened by the
application, and keep that window open. MFA and CAPTCHA must be completed directly
at TradingView.

The application never requests the password in its terminal window.

## `ONB-SUITE-001` — suite missing

`SMC Long-Dip Suite` is not on the target chart. No bindings were changed. Add the
suite, wait for it to load, save the chart, and rerun onboarding.

## `ONB-SUITE-002` — BUS outputs unavailable

The suite title is visible, but its BUS outputs cannot be selected. No consumer
bindings were changed. Open the suite and resolve its compile or runtime error,
then rerun onboarding.

## `ONB-CONSUMER-000` — no supported consumers found

The suite is present, but there is nothing to connect. Add at least one supported
consumer to the same chart and rerun.

## Missing consumer in a partial result

This is not a technical failure. Every detected consumer was connected. Add any
listed consumer the user wants to use, save the layout, and rerun onboarding.

## `ONB-BINDING-001` — detected consumer could not be connected

The consumer was present but one or more BUS sources could not be set or verified.
Other detected consumers are still processed. Check that the consumer and suite
are on the same chart, that both load without errors, and that TradingView has
finished rendering their settings. Then rerun.

If the report says `unknown parent id`, do not trust an unchanged dropdown label.
Rerunning onboarding force-reselects every BUS source and replaces the obsolete
internal parent reference.

## `ONB-CONFIG-001` — incomplete or damaged package

Download a fresh copy and extract the entire package. Do not copy only the start
file. End users should not attempt to repair the package with `npm install`.

## `ONB-UNEXPECTED-001` — unexpected failure

Close the application and browser, rerun once, and review the new local HTML
report. If the issue repeats, share the report with support after reviewing it for
local information. Never share the browser-profile folder.

## Installation method requires npm

This message appears only when a user runs the developer source checkout. Use the
portable Windows or macOS package for an installation without Node.js or npm.
