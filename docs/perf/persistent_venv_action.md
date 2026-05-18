# Persistent venv composite action

Path: `.github/actions/setup-persistent-venv/action.yml`

## What

Creates-or-reuses a Python venv stored in a host-stable directory outside
the runner `_work` tree, keyed on the SHA-256 of `requirements.txt` plus the
Python version + extra packages. Re-runs on the same self-hosted host skip
the full `uv pip install` when nothing changed.

On github-hosted runners, or when the `persistent-root` input is empty, it
falls back to the historical behavior (fresh `.venv` under
`$GITHUB_WORKSPACE/.venv`) — so it is safe to wire in unconditionally.

## How to enable

Set the repository variable `SMC_PERSISTENT_VENV_ROOT` to a host-stable
directory on the self-hosted runner host:

```bash
gh variable set SMC_PERSISTENT_VENV_ROOT \
  --body "C:\\runner-venvs\\skipp-algo" \
  --repo skippALGO/skipp-algo
```

Recommended path conventions:

- Windows self-hosted: `C:\runner-venvs\skipp-algo` (matches the Defender
  exclusion path `C:\Users\<user>\AppData\Local\uv` reasoning — keep it on
  the NVMe and outside any per-job wiped directories).
- Linux self-hosted: `/opt/runner-venvs/skipp-algo`.

Make sure the path is covered by Defender exclusions (see
`scripts/harden-self-hosted-runner.ps1`) — otherwise the per-file scan cost
will eat most of the savings.

## How to disable / roll back

```bash
gh variable delete SMC_PERSISTENT_VENV_ROOT --repo skippALGO/skipp-algo
```

The composite immediately reverts to the fresh-venv path.

## What it caches

Layout under `$SMC_PERSISTENT_VENV_ROOT`:

```
<hash>/
  .complete        # stamp file; absence forces rebuild
  .venv/           # the actual venv
```

`<hash>` = first 16 hex chars of `sha256(requirements.txt || python_version || extra_packages)`.
Old `<hash>` directories accumulate; clean them with:

```powershell
Get-ChildItem C:\runner-venvs\skipp-algo -Directory |
  Where-Object LastAccessTime -lt (Get-Date).AddDays(-30) |
  Remove-Item -Recurse -Force
```

## Why this matters

`uv pip install -r requirements.txt pytest` against a cold pip cache is the
single dominant fixed cost in the validate job on self-hosted runners.
Persisting the venv across job invocations (when requirements have not
changed) skips this entirely.

The composite is also a prerequisite for the upcoming `uv sync` + `uv.lock`
migration — the cache key just becomes the lockfile hash instead of
`requirements.txt`.
