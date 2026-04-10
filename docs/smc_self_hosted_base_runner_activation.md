# Self-Hosted Base Runner Activation

This document describes how to activate and verify the self-hosted split for the SMC base generator.

## Goal

Move the heavy Databento base-generation stage onto a dedicated self-hosted runner while keeping gates, publish, TradingView automation, commit, and alerting on GitHub-hosted runners.

The implementation is controlled by these files:

- `.github/workflows/smc-library-refresh.yml`
- `.github/workflows/smc-library-refresh-self-hosted-base-draft.yml`
- `scripts/generate_smc_micro_base_from_databento.py`

## Repository Variables

Set these repository variables under Settings -> Secrets and variables -> Actions -> Variables.

### Required for production switch

- `SMC_SELF_HOSTED_BASE_ENABLED`
  Value: `true`

- `SMC_SELF_HOSTED_BASE_RUNNER_LABELS_JSON`
  Example for a dedicated macOS runner:
  `[
    "self-hosted",
    "macOS",
    "ARM64",
    "smc-base"
  ]`

- `SMC_SELF_HOSTED_BASE_CACHE_DIR`
  Example:
  `/Users/steffenpreuss/Library/Caches/skipp-algo/databento_volatility_cache`

### Safe rollout recommendation

Before enabling the production split, keep:

- `SMC_SELF_HOSTED_BASE_ENABLED=false`

Then run the draft workflow manually and only switch the flag to `true` after the draft run proves that the runner can pick up the job and reach the generation stage.

## Runner Registration

### Recommended labels

Add the custom label `smc-base` during runner registration. GitHub will add the default labels automatically.

Expected effective label set for the current macOS machine:

- `self-hosted`
- `macOS`
- `ARM64` or `X64`
- `smc-base`

### Working directory and cache path

Recommended runner directories on the local machine:

- Runner home:
  `/Users/steffenpreuss/actions-runner/skipp-algo-smc-base`

- Persistent Databento cache:
  `/Users/steffenpreuss/Library/Caches/skipp-algo/databento_volatility_cache`

The cache path must stay outside the checked-out repository workspace because `actions/checkout` cleans the workspace by default.

## Test Sequence

1. Register the self-hosted runner with label `smc-base`.
2. Start the runner process.
3. Dispatch `.github/workflows/smc-library-refresh-self-hosted-base-draft.yml`.
4. Confirm that the `Generate Base On Self-Hosted Runner` job is picked up by the self-hosted runner.
5. Confirm that the workflow reaches `Generate SMC library payload on self-hosted runner`.
6. If the draft run is healthy, set `SMC_SELF_HOSTED_BASE_ENABLED=true`.
7. Let the next scheduled production refresh use the split path.

## Persistence

For a real production runner, run the actions runner as a persistent service after the first successful interactive test.

On macOS, that usually means installing the runner service from the runner directory after `config.sh` has completed.

## Rollback

If the self-hosted path causes trouble, rollback is immediate:

1. Set `SMC_SELF_HOSTED_BASE_ENABLED=false`.
2. Scheduled runs will revert to the original single-job GitHub-hosted path.
