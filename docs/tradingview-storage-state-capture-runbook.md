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

1. Launches a **headed** Chromium (`headless: false`, slowMo 100) — a visible
   browser window is required; this does not work on a headless host.
2. Opens the TradingView sign-in page (or chart page in profile mode).
3. Lets you log in — manually, or automated if `TV_USERNAME`/`TV_PASSWORD`
   are set (a 2FA auto-submit helper assists with MFA code submission).
4. Polls up to 15 min (`--wait-timeout-ms`, default 900000) until an
   authenticated chart session is detected: URL contains `/chart`, no
   sign-in signals in the page body, and the captured storage state passes
   the auth heuristics in
   `automation/tradingview/lib/tv_validation_model.ts::inspectTradingViewStorageState`.
5. Writes the storage state JSON (with `indexedDB: true`) plus a `meta`
   block containing `authValidatedAt` (ISO-8601) — this timestamp is what
   `scripts/credential_health_check.py::probe_tv_storage_state` ages
   against the 72 h TTL.

The script **fails loudly** if the captured session still looks anonymous
(sign-in overlay visible, missing `sessionid` cookies) — rerun after a full
login in that case.

## 2. CLI flags / environment

| Flag | Env fallback | Default |
|---|---|---|
| `--out` | `TV_STORAGE_STATE` | `automation/tradingview/auth/storage-state.json` |
| `--login-url` | `TV_LOGIN_URL` | `https://www.tradingview.com/accounts/signin/` |
| `--chart-url` | `TV_CHART_URL` | `https://www.tradingview.com/chart/` |
| `--wait-timeout-ms` | `TV_STORAGE_WAIT_TIMEOUT_MS` | `900000` (15 min) |
| `--poll-interval-ms` | `TV_STORAGE_POLL_INTERVAL_MS` | `3000` |
| `--persistent-profile-dir` | `TV_PERSISTENT_PROFILE_DIR` | unset |
| `--username` | `TV_USERNAME` | unset (manual login) |
| `--password` | `TV_PASSWORD` | unset (manual login) |

**Never** put `TV_USERNAME`/`TV_PASSWORD` on the command line in shared
shells (history leak); export them in the session or just log in manually.

## 3. Standard procedure (storage-state mode)

```bash
cd /path/to/skipp-algo

# 1. Capture — a Chromium window opens; log in (incl. MFA), wait for the chart.
npm run tv:storage-state

# 2. Security guard — verifies the capture is NOT tracked by git.
npm run tv:auth-security

# 3. Sanity-check the capture (age + session cookies present).
python3 - <<'EOF'
import json, datetime
d = json.load(open("automation/tradingview/auth/storage-state.json"))
va = d["meta"]["authValidatedAt"]
age = (datetime.datetime.now(datetime.timezone.utc)
       - datetime.datetime.fromisoformat(va.replace("Z", "+00:00"))).total_seconds() / 3600
names = {c["name"] for c in d.get("cookies", []) if "tradingview" in c.get("domain", "")}
assert {"sessionid", "sessionid_sign"} <= names, f"missing session cookies: {names}"
print(f"OK — authValidatedAt={va}, age={age:.1f}h, cookies={sorted(names)}")
EOF

# 4. Rotate the GitHub Actions secret (raw JSON is accepted;
#    gzip+base64 also works — the workflow auto-detects both).
gh secret set TV_STORAGE_STATE --repo skippALGO/skipp-algo \
  < automation/tradingview/auth/storage-state.json

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
carries the auth); the written file then gets
`meta.validationMode = "persistent_profile_chart_access"`.
Local consumers then run with
`TV_PERSISTENT_PROFILE_DIR=automation/tradingview/auth/chromium-profile`
(see the `*:profile` npm scripts).

## 5. Security rules

- `automation/tradingview/auth/` is **gitignored**; the
  `tv:auth-security` guard
  (`scripts/check_tradingview_storage_state_security.py`) fails CI if a
  plaintext storage-state artifact ever becomes tracked content. Run it
  after every capture.
- The capture contains live `sessionid`/`sessionid_sign` cookies —
  treat the file like a password. Do not attach it to issues, logs or
  artifacts.
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
| Automated login loops on CAPTCHA | TradingView bot defense | Drop `TV_USERNAME`/`TV_PASSWORD`, log in manually in the opened window |
| Playwright "browser not found" | Chromium not installed for Playwright | `npx playwright install chromium` |
