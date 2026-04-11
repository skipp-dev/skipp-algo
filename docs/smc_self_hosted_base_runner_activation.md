# Self-Hosted Base Runner Activation

This document describes how to activate and verify the self-hosted base split
for the SMC microstructure refresh path.

## Goal

Move the heavy Databento base-generation stage onto a dedicated self-hosted
runner while keeping gates, governance, publish, TradingView automation,
commit, and alerting on the current GitHub-hosted path.

The draft split is implemented here:

- `.github/workflows/smc-library-refresh-self-hosted-base-draft.yml`

The currently active production workflow remains here:

- `.github/workflows/smc-library-refresh.yml`

## Workflow Inputs

Dispatch `.github/workflows/smc-library-refresh-self-hosted-base-draft.yml`
with these inputs:

- `refresh_ref`
  Usually `main`.

- `self_hosted_runner_labels_json`
  JSON array of labels for the self-hosted base-generation job.
  Safe generic example:
  `["self-hosted","smc-base"]`

- `self_hosted_cache_dir`
  Persistent Databento cache root outside the checkout workspace.

- `github_hosted_runner`
  Runner used for gates, publish, and alerts after the self-hosted base job.
  Current pilot default: `ubuntu-24.04-4core`.

## Recommended Labels

Keep the custom label `smc-base` on the dedicated runner.

Recommended effective label set for the current local macOS machine:

- `self-hosted`
- `macOS`
- `ARM64`
- `smc-base`

## Cache Path

The persistent Databento cache must stay outside the checked-out repository,
because `actions/checkout` may clean the workspace.

Current local recommendation:

- `/Users/steffenpreuss/Library/Caches/skipp-algo/databento_volatility_cache`

## Test Sequence

1. Register or verify the dedicated self-hosted runner with the `smc-base` label.
2. Start the runner service.
3. Dispatch `.github/workflows/smc-library-refresh-self-hosted-base-draft.yml`.
4. Confirm that `Generate Base On Self-Hosted Runner` is picked up by the self-hosted runner.
5. Confirm that `Validate And Publish On GitHub-Hosted Runner` runs on the configured hosted runner.
6. Compare the draft runtime and stability against the active GitHub-hosted workflow.

## Rollback

Rollback is immediate because this path is draft-only:

1. Stop dispatching `.github/workflows/smc-library-refresh-self-hosted-base-draft.yml`.
2. Keep `.github/workflows/smc-library-refresh.yml` as the active production path.
