# TradingView Storage-State Capture Runbook

Documented procedure for capturing TradingView's Playwright storage state
(session cookies + localStorage + IndexedDB) with
`scripts/create_tradingview_storage_state.ts` and rotating the
`TV_STORAGE_STATE` GitHub Actions secret.

**Audience:** operator with a TradingView account and local repo checkout.
**Cadence:** the capture must be refreshed at least every **72 h**
(`TV_STORAGE_STATE_MAX_AGE_HOURS` in `smc-library-refresh.yml`);
`credential-health-check.yml` warns at 80 % of TTL (57.6 h) and errors at
100 %. Practical rule: re-capture every **2 days** or immediately when the
daily credential-health issue pings.

Related docs: [tradingview-auth-modes.md](tradingview-auth-modes.md)
(auth resolution order), [tradingview_operational_publish_runbook_2026-04-17.md](tradingview_operational_publish_runbook_2026-04-17.md)
(§7.3 auth failures).

---

## 1. What the script does

`npm run tv:storage-state` → `tsx scripts/create_tradingview_storage_state.ts`

1. Launches Chromium. Local captures are headed by default; CI uses
   `--headless`.
2. Opens the TradingView sign-in page (or chart page in profile mode).
3. Lets you log in — manually, or automated if `TV_USERNAME`/`TV_PASSWORD`
   are set (a 2FA auto-submit helper assists with MFA code submission).
4. Polls up to 15 min (`--wait-timeout-ms`, default 900000) until an
   authenticated chart session is detected: URL contains `/chart`, no
   sign-in signals in the page body, and the captured storage state passes
   the auth heuristics in
   `automation/tradingview/lib/tv_validation_model.ts::inspectTradingViewStorageState`.
5. Atomically writes the storage state JSON (with `indexedDB: true`) as an
   owner-only (`0600`) file on POSIX hosts. **Note:** the script
   always stamps a `meta` block (`authValidatedAt`, `validationMode: "standard_session"`)
   on every normal session capture so that
   `scripts/credential_health_check.py::probe_tv_storage_state` can age the
   capture against the 72 h TTL without a separate stamping step.
   The metadata also records the observed `authMode`, whether TOTP was actually
   entered/submitted, and the non-secret session-owner label. The
   persistent-profile fallback (§4) uses
   `validationMode: "persistent_profile_chart_access"`.

The script **fails loudly** if the captured session still looks anonymous
(sign-in overlay visible, missing `sessionid` cookies) — rerun after a full
login in that case.

## 2. CLI flags / environment

| Flag | Env fallback | Default |
|---|---|---|
| `--out` | `TV_STORAGE_STATE` | `automation/tradingview/auth/storage-state.json` |
| `--login-url` | `TV_LOGIN_URL` | `https://www.tradingview.com/accounts/signin/` |
| `--chart-url` | `TV_CHART_URL` | `https://www.tradingview.com/chart/` |
| `--input-storage-state` | `TV_STORAGE_STATE_INPUT` | unset |
| `--force-fresh-login` | `TV_FORCE_FRESH_LOGIN` | false; ignores input storage state |
| `--wait-timeout-ms` | `TV_STORAGE_WAIT_TIMEOUT_MS` | `900000` (15 min) |
| `--poll-interval-ms` | `TV_STORAGE_POLL_INTERVAL_MS` | `3000` |
| `--persistent-profile-dir` | `TV_PERSISTENT_PROFILE_DIR` | unset |
| `--username` | `TV_USERNAME` | unset (manual login) |
| `--password` | `TV_PASSWORD` | unset (manual login) |
| `--totp-secret` | `TV_TOTP_SECRET` | unset |
| `--session-owner` | `TV_STORAGE_SESSION_OWNER` | `<hostname>:<pid>` |
| `--session-lock-file` | `TV_STORAGE_SESSION_LOCK_FILE` | `<out>.lock` |
| `--headless` | `TV_HEADLESS` | false locally; true by default in CI |

**Never** put `TV_USERNAME`/`TV_PASSWORD` on the command line in shared
shells (history leak); export them in the session or just log in manually.

### Browser selection

By default every TradingView session (this script and `newTradingViewSession`)
launches Playwright's **pinned bundled Chromium**
(`npx playwright install chromium`). Two env vars override that — they are
**mutually exclusive** (set at most one):

| Env var | Effect |
|---|---|
| `TV_CHROMIUM_EXECUTABLE_PATH` | Launch this exact Chromium binary. No fallback: launch errors name the var. |
| `TV_BROWSER_CHANNEL` | Launch a branded channel (`chrome`, `msedge`, …; Playwright validates the value). No fallback: launch errors name the var. |

With neither set and the bundled Chromium **missing**, non-persistent launches
fall back to the system `chrome` channel **once, loudly** (a `[tv-launch]`
warning is printed). Persistent-profile launches never fall back — a different
browser build opening the long-lived auth profile would corrupt its version —
they fail with a remedy hint instead: install the pinned Chromium, or set
`TV_BROWSER_CHANNEL=chrome` so *all* sessions consistently use system Chrome.
Any other launch failure (timeout, profile lock, sandbox) propagates untouched.

The scheduled `tradingview-storage-refresh.yml` uses
`--input-storage-state` with the current `TV_STORAGE_STATE` secret as a
bootstrap. In the healthy path the existing session is verified against a
live chart and re-written with a fresh `meta.authValidatedAt`, so
`TV_USERNAME`/`TV_PASSWORD`/`TV_TOTP_SECRET` are only needed as fallback
when TradingView no longer accepts the bootstrap session.

### CI fresh-login and dry-run controls

Manual dispatches expose three typed inputs:

- `force_fresh_login=true` ignores the bootstrap state and requires all of
  `TV_USERNAME`, `TV_PASSWORD`, and `TV_TOTP_SECRET`.
- `confirm_session_disconnect=true` is mandatory with a forced login because
  TradingView may terminate another active account session.
- `dry_run=true` (the manual default) captures and validates a new state but
  skips both the secret-writer token preflight and `gh secret set`. The existing
  `TV_STORAGE_STATE` therefore remains unchanged even when the fresh login
  succeeds.

Safe MFA-path probe:

```bash
gh workflow run tradingview-storage-refresh.yml \
  --repo skipp-dev/skipp-algo \
  --ref main \
  -f force_fresh_login=true \
  -f confirm_session_disconnect=true \
  -f dry_run=true
```

Only a separate, explicitly reviewed run with `dry_run=false` promotes the
validated capture into the repository secret. Failed validation always occurs
before the secret-write step.

The capture script holds an exclusive, owner-labelled lock beside its output
file (or at `TV_STORAGE_SESSION_LOCK_FILE`) and refuses a second capture on the
same host/path. GitHub Actions additionally serializes refresh workflow runs
through the `tradingview-storage-refresh` concurrency group. These mechanisms
prevent cooperating capture processes from racing. They cannot detect a
manually opened Chrome/TradingView session or coordinate a local process with a
GitHub-hosted runner; a fresh CI login can still disconnect that browser
session.

## 3. Standard procedure (storage-state mode)

```bash
cd /path/to/skipp-algo

# 1. Capture — a Chromium window opens; log in (incl. MFA), wait for the chart.
npm run tv:storage-state

# 2. Security guard — verifies the capture is NOT tracked by git.
npm run tv:auth-security

# 3. Inspect the capture (session cookies + meta.authValidatedAt).
#    INFORMATIONAL ONLY — step 4 is the gate. Do not read `age` and proceed by
#    eye: this block used to print a leading "OK" for any age, which is how a
#    382.5 h capture was hand-pushed over a fresh session on 2026-07-14 (#3640).
python3 - <<'EOF'
import json, datetime
p = "automation/tradingview/auth/storage-state.json"
d = json.load(open(p))
names = {c["name"] for c in d.get("cookies", []) if "tradingview" in c.get("domain", "")}
assert {"sessionid", "sessionid_sign"} <= names, f"missing session cookies: {names}"
meta = d.get("meta", {})
assert meta.get("authValidatedAt"), "meta.authValidatedAt missing — re-run tv:storage-state"
now = datetime.datetime.now(datetime.timezone.utc)
va = meta["authValidatedAt"]
age = (now - datetime.datetime.fromisoformat(va.replace("Z", "+00:00"))).total_seconds() / 3600
print(f"authValidatedAt={va}, age={age:.1f}h, cookies={sorted(names)}")
EOF

# 4. Rotate the GitHub Actions secret — VALIDATED, this is the gate.
#    Runs the same `tv_storage_state_age` probe with the same 72 h TTL that
#    tradingview-storage-refresh.yml applies before IT writes the secret, and
#    refuses to write on anything but `ok`. A bare `gh secret set` skips that
#    gate — that is precisely how a 2026-06-29 capture overwrote the fresh
#    07-13 session and stalled the publish chain (#3640).
npm run tv:rotate-secret

#    Non-default path or repo:
#    scripts/tv_rotate_storage_state_secret.sh path/to/state.json
#    TV_SECRET_REPO=owner/name npm run tv:rotate-secret
#
#    The script sends raw JSON. Both formats are accepted — the probe's
#    _loads_tv_storage_state falls back to gzip+base64 and the publish
#    workflows auto-detect — but raw keeps the hand path inspectable. The CI
#    refresh writes gzip+base64 for size.

# 5. Verify end-to-end via the daily probe.
gh workflow run credential-health-check.yml
# then: gh run watch --workflow=credential-health-check.yml
# expected: tv_storage_state_age = ok (age < 57.6h)
```

## 4. Alternative: persistent-profile mode

For repeated local publish/preflight work, keep a persistent Chromium
profile so you log in once and reuse it:

```bash
npm run tv:profile-login
# = create_tradingview_storage_state.ts --persistent-profile-dir \
#     automation/tradingview/auth/chromium-profile
```

This both refreshes the profile dir **and** writes
`storage-state.json`. In profile mode the script accepts a chart session
even when storage-state heuristics look anonymous (the profile itself
carries the auth); **only in that anonymous-looking fallback** does the
written file get a `meta` block with
`validationMode = "persistent_profile_chart_access"` plus `authValidatedAt`.
When the heuristics already look authenticated, the file is written with
`validationMode = "standard_session"` (same `meta` shape as a regular
§2 capture). The §3 sanity-check passes in both cases — no manual
re-run is needed.
Local consumers then run with
`TV_PERSISTENT_PROFILE_DIR=automation/tradingview/auth/chromium-profile`
(see the `*:profile` npm scripts).

## 5. Security rules

- `.gitignore` ignores `automation/tradingview/auth/` **wholesale** — every
  storage-state file, browser profile, and future byproduct under it (the
  old per-file list proved leaky). The `tv:auth-security` guard
  (`scripts/check_tradingview_storage_state_security.py`) is the backstop:
  it fails CI if ANY file under an auth directory ever becomes tracked
  content. Run it after every capture.
- The capture contains live `sessionid`/`sessionid_sign` cookies —
  treat the file like a password. Do not attach it to issues, logs or
  artifacts.
- Captures and capture locks are written with `0600` on POSIX hosts. If a
  capture crashes, the lock remains fail-closed. Verify no capture process is
  still running before deleting the stale `.lock` file.
- Rotate the GitHub secret promptly after capture; delete stray copies
  (`/tmp`, Downloads) afterwards.

## 6. Secret-snapshot pitfall (observed 2026-06-12)

GitHub Actions resolves secrets at **job start**, not step start. A
long-running `smc-library-refresh` job (~4 h generate step) that started
*before* the secret rotation will still preflight with the **old** cookie
and fail at the TTL gate. That is expected — the next queued run
(`cancel-in-progress: false`) picks up the new secret and self-heals. Do
not cancel the running job just because the secret was rotated.

## 7. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `Timed out waiting for an authenticated TradingView chart session` | Login not completed / sign-in overlay open | Complete login + MFA, open a chart, rerun |
| `Captured TradingView session still looks anonymous` | Cookie consent/sign-in modal still visible, or login silently failed | Dismiss overlays, confirm avatar/username visible on chart, rerun |
| `credential-health` still red after rotation | Dispatched run started before `gh secret set` finished | Re-dispatch `credential-health-check.yml` |
| Probe reports `storage_state missing meta block` | Capture was done before the always-write-meta fix (pre-2026-06-17) | Re-run `npm run tv:storage-state`, then rotate the secret |
| Automated login loops on CAPTCHA | TradingView bot defense | Drop `TV_USERNAME`/`TV_PASSWORD`, log in manually in the opened window |
| Playwright "browser not found" | Chromium not installed for Playwright | `npx playwright install chromium` |
