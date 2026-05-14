# GitHub Copilot Repository Instructions

## Workflow authoring rules

### Shell default (REQUIRED in every workflow file)

Every `.github/workflows/*.yml` file **must** include the following block at the
top level (before `jobs:`):

```yaml
defaults:
  run:
    shell: bash
```

**Why:** The repository uses a Windows self-hosted runner (`SMC_GH_HOSTED_RUNNER`).
Without this declaration every `run:` step defaults to PowerShell (`pwsh`), which
cannot parse bash syntax (`[[ ]]`, `set -o pipefail`, heredocs, etc.).  Adding
`defaults: run: shell: bash` routes all steps through WSL bash on Windows and is a
no-op on `ubuntu-latest`.  Omitting it causes a `ParserError` at job startup and
fails the entire CI run.

The `fast-gates` required status check enforces this via a lint step; a PR that
adds a workflow file without the declaration will be blocked from merging.

### Runner label

Use the repository variable instead of a hard-coded runner label:

```yaml
runs-on: ${{ vars.SMC_GH_HOSTED_RUNNER || 'ubuntu-latest' }}
```

`SMC_GH_HOSTED_RUNNER` is currently set to `self-hosted` (the local Windows runner).
The fallback `ubuntu-latest` is used when the self-hosted runner is offline.
**Never** use `ubuntu-latest-l` — that label no longer exists.
