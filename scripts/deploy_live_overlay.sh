#!/usr/bin/env bash
# Deploy the live_overlay_daemon to Railway, stamping the real git commit +
# branch into the image first.
#
# Why this wrapper exists: `railway up` is a CLI upload with no git context,
# so Railway injects NO RAILWAY_GIT_* vars. Without a stamp, the
# `live_overlay_build_info` gauge reads commit="unknown" and cannot tell you
# which code is live -- this blind spot caused two silent no-op redeploys on
# 2026-07-06. The daemon reads build_stamp.txt as a fallback (see
# metrics._build_identity), so stamping it before upload makes the deployed
# commit visible in Grafana.
#
# The stamp is restored to its committed placeholder on exit so the working
# tree stays clean whether the deploy succeeds or fails.
#
# Usage: scripts/deploy_live_overlay.sh [extra railway up args]
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

stamp="services/live_overlay_daemon/build_stamp.txt"
commit="$(git rev-parse --short=12 HEAD)"
branch="$(git rev-parse --abbrev-ref HEAD)"

# Restore the placeholder no matter how we exit (success, failure, Ctrl-C).
trap 'git checkout -- "$stamp" 2>/dev/null || true' EXIT

printf '%s\n%s\n' "$commit" "$branch" >"$stamp"
echo "Stamped $stamp -> commit=$commit branch=$branch"

railway up --service live_overlay_daemon --environment production --detach "$@"
echo "Uploaded. Verify once live:"
echo "  live_overlay_build_info{commit=\"$commit\"}  (should replace 'unknown')"
