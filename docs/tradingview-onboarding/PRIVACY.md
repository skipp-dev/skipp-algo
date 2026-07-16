# Privacy and local data

## TradingView credentials

SMC Onboarding does not ask for, read, or store a TradingView password. Sign-in
happens directly in the locally installed Chrome or Edge window on TradingView's
site.

## Dedicated browser profile

The application uses a dedicated local browser profile instead of the user's
normal Chrome or Edge profile. Chrome and Edge receive separate onboarding
profiles so one browser cannot migrate or damage the other browser's profile.
This limits access to unrelated browsing data and allows the TradingView login to
be reused on the next run.

Do not upload, email, or share the browser-profile folder. Treat it like an active
login session.

## Reports

HTML and JSON reports are stored locally. They contain:

- the producer status;
- supported, detected, missing, and failed consumer names;
- binding counts;
- error codes and remediation messages.

Reports do not intentionally include passwords, cookies, storage state, chart
URLs, Pine source code, or TradingView account identifiers. Review a report before
sharing it with support.

## Network and telemetry

The application communicates with TradingView through the controlled local
browser. It has no SMC telemetry endpoint and does not upload onboarding reports.
It does not publish data to the production Grafana binding snapshot.

## Remove local data

Close all onboarding browser windows before deleting local data:

- Windows: `%LOCALAPPDATA%\SMC Onboarding`
- macOS: `~/Library/Application Support/SMC Onboarding`

The next run will create a new dedicated profile and require TradingView sign-in
again.
