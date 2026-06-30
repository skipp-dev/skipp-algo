#!/usr/bin/env bash
# Pull the current SMC Live Overlay dashboard JSON back from Grafana Cloud,
# then re-apply idempotent UX transforms.
set -euo pipefail

GRAFANA_URL="https://bronzeporridge977.grafana.net"
DASHBOARDS=(
  "smc-live-overlay-v1|services/live_overlay_daemon/infra/grafana/dashboard.json"
  "smc-live-overlay-signals-v1|services/live_overlay_daemon/infra/grafana/dashboard-signals-experiments.json"
)

API_KEY=$(security find-generic-password -s skipp.grafana.api -w)

for dashboard in "${DASHBOARDS[@]}"; do
  IFS="|" read -r DASHBOARD_UID TARGET <<< "${dashboard}"

  curl -fsS -H "Authorization: Bearer ${API_KEY}" \
    "${GRAFANA_URL}/api/dashboards/uid/${DASHBOARD_UID}" \
    | jq '.dashboard' \
    > "${TARGET}"

  python scripts/update_overlay_dashboard.py "${TARGET}"

  echo "Pulled dashboard ${DASHBOARD_UID} to ${TARGET} and re-applied UX transforms."
done
