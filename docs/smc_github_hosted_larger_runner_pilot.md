# GitHub-Hosted Larger Runner Pilot

Stand: 2026-04-18

## Goal

Run `.github/workflows/smc-library-refresh.yml` on a larger GitHub-hosted
Linux runner without bringing back any self-hosted infrastructure.

## Current Active Runner

- `ubuntu-latest` (standard GitHub-hosted 2-core)

The workflow uses the repository variable `SMC_GH_HOSTED_RUNNER` with a fallback
to `ubuntu-latest`. The variable is currently not set, so all runs execute on
the standard `ubuntu-latest` runner. This applies to all SMC workflows:
`smc-library-refresh`, `smc-release-gates`, `smc-deeper-integration-gates`,
`smc-fast-pr-gates`, `smc-measurement-benchmark`, `smc-live-newsapi-refresh`.

> **Note:** Earlier versions of this document referenced `ubuntu-24.04-4core`.
> That label was planned but never activated in the organization runner settings.
> All production runs have always executed on `ubuntu-latest`.

## Recommended Pilot Shape

Use a 4-core Linux larger runner first.

Reason:

1. It is the lowest-risk cost step above the standard hosted runner.
2. It only needs roughly a 2x runtime improvement to break even against the
   current 108-minute baseline.
3. The 8-core tier needs a much larger runtime drop to justify the price.

## Activation

1. In the GitHub organization or enterprise settings, create a new
   GitHub-hosted larger runner.
2. Pick the GitHub-owned Linux x64 image `ubuntu-24.04`
   as documented in
   `actions/runner-images/images/ubuntu/Ubuntu2404-Readme.md`.
3. Pick the 4-core size.
4. Give the runner a stable name such as `ubuntu-24.04-4core`.
5. Grant the runner group access to the repository `skippALGO/skipp-algo`.
6. Update `.github/workflows/smc-library-refresh.yml` so that `runs-on`
   points to that exact runner label.
7. Trigger `smc-library-refresh` manually once and compare runtime against the
   current baseline.

## Verification

The workflow exposes the selected runner in two places:

1. an early `Emit runner selection` notice in the job log
2. the `Runner` row in the workflow summary table

## Rollback

Rollback is immediate:

1. change `runs-on` in `.github/workflows/smc-library-refresh.yml` back to
   `ubuntu-24.04`
2. push the workflow change

No organization-level runner teardown is required for rollback.
