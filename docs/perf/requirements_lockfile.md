# requirements.lock (uv pip compile)

Fully-pinned lockfile generated from `requirements.txt` by
`uv pip compile`. Provides deterministic installs and removes the
dependency-resolution step from every CI install.

## Regenerate

```bash
python scripts/regenerate_requirements_lock.py            # re-pin everything as-is
python scripts/regenerate_requirements_lock.py --upgrade  # bump every package
python scripts/regenerate_requirements_lock.py --upgrade-package httpx
```

The helper just wraps `uv pip compile requirements.txt --output-file requirements.lock --python-version 3.12`.

## Enable in CI

Set the repository variable `SMC_USE_REQUIREMENTS_LOCK` to `true`:

```bash
gh variable set SMC_USE_REQUIREMENTS_LOCK --body "true" --repo skippALGO/skipp-algo
```

While the var is set, the validate job installs from `requirements.lock`
instead of `requirements.txt`. Unset (or any other value) restores the
historical behavior with zero workflow change:

```bash
gh variable delete SMC_USE_REQUIREMENTS_LOCK --repo skippALGO/skipp-algo
```

## Drift check

```bash
python scripts/regenerate_requirements_lock.py --check
```

Returns non-zero if regenerating from the current `requirements.txt` would
change the lockfile. Useful as a manual gate when bumping deps.
