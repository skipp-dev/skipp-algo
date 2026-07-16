# Preparing the TradingView chart

## Before starting

Use one chart pane for the SMC installation. A second suite or duplicate
consumers in another pane of the same layout make TradingView's source dropdown
ambiguous.

1. Open the exact TradingView chart layout that should be configured.
2. Add exactly one `SMC Long-Dip Suite` to that chart pane.
3. Wait for the suite to load and confirm that it shows no compile or runtime
   error.
4. Add each consumer that the user wants to use to the same chart pane.
5. Save the chart layout.
6. Copy the chart URL from the browser address bar.

Supported consumers are:

- SMC Decision Board
- SMC Long-Dip Strategy
- SMC Long-Dip Alerts
- SMC Setup Check
- SMC Breakout Overlay
- SMC Confluence Hub
- SMC Long-Dip Mobile

The display title `SMC Long-Dip Dashboard` is also recognized as the Decision
Board consumer.

## Required producer

Every consumer receives runtime state from the `SMC Long-Dip Suite` instance on
the same chart. Onboarding stops before changing bindings when the suite is
missing or its BUS outputs are not selectable.

## Missing consumers

Missing consumers do not block the consumers already present. A `partial` result
lists each missing consumer. Add only the consumers the user wants, save the
layout, and run onboarding again. Existing connections are safe to reapply.

## Multiple charts

Onboarding operates on one chart URL per run. Run it separately for each chart
layout that contains SMC consumers. The producer and consumers must be on the
same chart during a run.
