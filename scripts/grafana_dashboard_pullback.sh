#!/usr/bin/env bash
# Pull the current SMC Live Overlay dashboard JSON back from Grafana Cloud,
# then re-apply idempotent UX transforms.
set -euo pipefail

GRAFANA_URL="https://bronzeporridge977.grafana.net"
DASHBOARD_UID="smc-live-overlay-v1"
TARGET="services/live_overlay_daemon/infra/grafana/dashboard.json"

API_KEY=$(security find-generic-password -s skipp.grafana.api -w)

curl -s -H "Authorization: Bearer ${API_KEY}" \
  "${GRAFANA_URL}/api/dashboards/uid/${DASHBOARD_UID}" \
  | jq '.dashboard' \
  > "${TARGET}"

python scripts/update_overlay_dashboard.py

echo "Pulled dashboard to ${TARGET} and re-applied UX transforms."
