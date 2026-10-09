#!/usr/bin/env bash
#
# Validated rotation of the TV_STORAGE_STATE Actions secret.
#
# Why this exists
# ---------------
# `tradingview-storage-refresh.yml` never writes the secret without first
# running the `tv_storage_state_age` probe and requiring severity == ok (step
# "Validate captured storage state"). A hand-run `gh secret set` skips that gate
# entirely.
#
# That gap is not theoretical: on 2026-07-14T12:33Z a manual push put a capture
# from 2026-06-29 into TV_STORAGE_STATE, clobbering the fresh session the cron
# had captured and validated on 07-13. TradingView rejected the 15-day-old
# session (accountProbeStatuses=403,403), the refresh cron could no longer
# bootstrap, and the publish chain stalled (#3640).
#
# This runs the SAME probe with the SAME TTL as CI and only writes on ok, so the
# hand path and the CI path cannot disagree about what "valid" means.
#
# Usage
# -----
#   npm run tv:rotate-secret                  # default path + repo
#   scripts/tv_rotate_storage_state_secret.sh [STATE_JSON]
#
#   TV_SECRET_REPO=owner/name  override the target repo
#   TV_STORAGE_STATE_MAX_AGE_HOURS=72  override the TTL (matches CI's default)
#   PYTHON=/path/to/python  interpreter used for the probe
#
# Exits non-zero WITHOUT touching the secret when the capture is stale, is
# missing meta.authValidatedAt, or cannot be parsed.

set -euo pipefail

STATE_PATH="${1:-automation/tradingview/auth/storage-state.json}"
SECRET_REPO="${TV_SECRET_REPO:-skipp-dev/skipp-algo}"
MAX_AGE_HOURS="${TV_STORAGE_STATE_MAX_AGE_HOURS:-72}"
PYTHON_BIN="${PYTHON:-python3}"
SECRET_NAME="TV_STORAGE_STATE"

if [ ! -f "${STATE_PATH}" ]; then
  echo "error: no capture at ${STATE_PATH} — run 'npm run tv:storage-state' first." >&2
  exit 1
fi

REPORT_DIR="$(mktemp -d)"
trap 'rm -rf "${REPORT_DIR}"' EXIT
REPORT="${REPORT_DIR}/cred-health.json"

echo "==> Validating ${STATE_PATH} (TTL ${MAX_AGE_HOURS}h) with the same probe CI uses..."

# Mirrors the "Validate captured storage state" step of
# tradingview-storage-refresh.yml verbatim, including every --skip: the
# fail-loud contract makes the exit code the gate, so a non-TV probe failing
# here (e.g. an unrelated expired key) must not block a TV rotation.
TV_STORAGE_STATE="$(cat "${STATE_PATH}")" \
  "${PYTHON_BIN}" scripts/credential_health_check.py \
    --tv-max-age-hours "${MAX_AGE_HOURS}" \
    --skip-gh-pat \
    --skip-databento \
    --skip-fmp \
    --skip-benzinga \
    --skip-finnhub \
    --skip-newsapi \
    --output "${REPORT}" \
  || true  # a non-ok probe exits non-zero; the severity check below is the gate

"${PYTHON_BIN}" - "${REPORT}" <<'PYEOF'
import json, pathlib, sys

report_path = pathlib.Path(sys.argv[1])
if not report_path.is_file():
    # credential_health_check returns 1 without writing --output when every
    # probe was skipped (e.g. an empty capture leaves TV_STORAGE_STATE blank).
    # No signal means no permission to rotate.
    print(
        "REFUSING to rotate: the probe produced no report, so the capture was "
        "never validated. Check the probe output above.",
        file=sys.stderr,
    )
    sys.exit(1)
report = json.loads(report_path.read_text())
probes = {p["name"]: p for p in report.get("probes", [])}
tv = probes.get("tv_storage_state_age", {})
severity = tv.get("severity", "unknown")
if severity != "ok":
    print(
        f"REFUSING to rotate: capture failed validation ({severity}).\n"
        f"  {tv.get('message', '<no message>')}\n"
        "\nThis is the gate the CI refresh applies before it writes the secret.\n"
        "Do NOT push this capture — re-run 'npm run tv:storage-state' and log in\n"
        "for real. Re-uploading an older local capture is what broke #3640.",
        file=sys.stderr,
    )
    sys.exit(1)
print(f"Capture is fresh: {tv.get('message', '')}")
PYEOF

echo "==> Writing ${SECRET_NAME} to ${SECRET_REPO}..."
# Raw JSON. Both formats work — credential_health_check._loads_tv_storage_state
# falls back to gzip+base64, and the publish workflows auto-detect — but raw
# keeps the hand path inspectable. CI writes gzip+base64 for size.
gh secret set "${SECRET_NAME}" --repo "${SECRET_REPO}" < "${STATE_PATH}"

echo "==> Done. Confirm end-to-end with:"
echo "    gh workflow run credential-health-check.yml"
