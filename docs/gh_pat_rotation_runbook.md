# GH_PAT Rotation Runbook

Operator reference for verifying and rotating the `GH_PAT` repository secret
that powers every workflow which pushes to `bot/*` branches, opens auto-PRs,
or files fallback issues.

This runbook exists because `GH_PAT` expiry is silent: a revoked or expired
token surfaces only as an HTTP `401`/`403` push failure deep inside a cron
log. The `credential-health-check.yml` daily probe gives advance warning, and
this document describes how to act on it.

---

## Current status (verified 2026-06-30)

- `GH_PAT` is **valid** and **not** near expiry.
- Probe result: `GH_PAT valid; expires in 340.9 days`.
- Expiry timestamp: `2027-06-06T05:55:43+00:00`.
- The `bot/live-experiment-snapshot` publish from `plan-2-8-evaluation.yml`
  is working again (run `28431210453` pushed successfully on 2026-06-30).

No rotation is required right now. The `credential-health-check.yml` probe
will raise a `warn` at 30 days before expiry and an `error` at 7 days. Treat
this runbook as the procedure to follow when that alert fires (expected
around early May 2027 for the current token).

---

## When to rotate

Rotate `GH_PAT` when any of the following is true:

- `credential-health-check.yml` reports `github_pat_validity` as `warn`
  (`expires in <= 30 days`) or `error` (`expired` or `<= 7 days`).
- A workflow push to a `bot/*` branch fails with HTTP `401` (token revoked
  or expired) or HTTP `403` (scope/permission insufficient).
- The token owner leaves the project or the token is suspected compromised.

The probe thresholds live in `scripts/credential_health_check.py`
(`probe_github_pat`): `<= 0 days -> error (expired)`, `<= 7 days -> error`,
`<= 30 days -> warn`, otherwise `ok`.

---

## Blast radius

`GH_PAT` is consumed by 25 workflows under `.github/workflows/`. Two use it
as the **primary** push/PR identity, so they fail hardest on a bad token:

- `credential-health-check.yml` — daily probe; also publishes the snapshot.
- `plan-2-8-evaluation.yml` — publishes `bot/live-experiment-snapshot`.

The remaining consumers use it for auto-PR creation, `update-branch` calls,
and self-hosted runner resolution (where it falls back to `github.token`).
A full list is produced by:

```bash
grep -rln "GH_PAT" .github/workflows/
```

---

## Required token scopes

The token must be able to: push commits to `bot/*` branches, open and update
pull requests, and create issues. Prefer a **fine-grained** PAT scoped to the
single repository.

### Fine-grained PAT (recommended)

Repository access: only `skipp-dev/skipp-algo`. Permissions:

| Permission | Access | Why |
|---|---|---|
| Contents | Read and write | push to `bot/*` snapshot/refresh branches |
| Pull requests | Read and write | open and update auto-PRs |
| Issues | Read and write | fallback issue creation on failures |
| Workflows | Read and write | bot PRs that touch `.github/workflows/**` |
| Metadata | Read | mandatory; branch-rule and repo reads |

### Classic PAT (fallback)

Scopes: `repo` (full) and `workflow`. Broader than necessary — use only if a
fine-grained token cannot be issued.

Set the expiry to the maximum the org policy allows (ideally 1 year) so the
rotation cadence stays predictable.

---

## Rotation steps

1. Create the new token under the bot/service account that owns the existing
   `GH_PAT` (keep ownership stable so commit attribution does not change).
   Use **GitHub Settings -> Developer settings -> Personal access tokens**
   and apply the scopes from the table above.
2. Copy the token value once; it is shown only at creation time.
3. Update the repository secret: **Repo Settings -> Secrets and variables ->
   Actions -> `GH_PAT` -> Update secret**. Paste the new value and save.
4. Do **not** delete the old token yet; keep it until verification passes so
   you can roll back by re-pasting it.
5. Run the verification below.
6. Once verification is green, revoke the old token from the account's token
   list.

---

## Verification

Run the credential probe on `main` and confirm the snapshot publish path:

```bash
gh workflow run credential-health-check.yml --repo skipp-dev/skipp-algo --ref main
```

Wait for the run to finish, then confirm the probe message:

```bash
gh run list --repo skipp-dev/skipp-algo --workflow=credential-health-check.yml --limit 1
```

The step summary must show the line `github_pat_validity: GH_PAT valid`
followed by the new `expires in <N> days` value, where `N` matches the new
token's expiry.

Then exercise the publish path that originally surfaced the alert:

```bash
gh workflow run plan-2-8-evaluation.yml --repo skipp-dev/skipp-algo --ref main
```

Success looks like `Pushed experiment snapshots to bot/live-experiment-snapshot`
in the **Publish snapshots to rolling bot branch** step. The branch
`bot/live-experiment-snapshot` should advance to a fresh commit.

---

## Troubleshooting

### Push fails with HTTP 403 even though the probe says the token is valid

The `/user` probe only proves the token can authenticate — it does **not**
prove write permission on `bot/*`. A `403` on `git push` with a non-expired
token means the token lacks `Contents: write` (fine-grained) or `repo`
(classic), or a branch ruleset blocks the push. Check, in order:

1. Token scopes match the table above.
2. The token's repository access includes `skipp-dev/skipp-algo`.
3. No ruleset on `bot/*` restricts who may push.

Historical note: on 2026-06-30 a `plan-2-8-evaluation` run failed with
`403` while an identical run 27 minutes later succeeded. The failing run was
on the pre-best-effort workflow version; PR #3064 made the publish step
best-effort (`exit 0` on push failure) so a transient `403` no longer fails
the whole job.

### Push fails with HTTP 401

The token is expired or revoked. Rotate immediately using the steps above.

### Probe cannot reach `api.github.com`

A network or rate-limit error is reported as `error` by the probe with the
HTTP status in the message. Re-run after a few minutes before assuming the
token is bad.
