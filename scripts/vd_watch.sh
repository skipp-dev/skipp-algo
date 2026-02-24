#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────
# vd_watch.sh — Live-Terminal-Dashboard mit watch + jq
# ──────────────────────────────────────────────────────────────────
# Usage:
#   ./scripts/vd_watch.sh              # Zeigt cached JSON, refresht alle 60s
#   ./scripts/vd_watch.sh -n 30        # alle 30s refreshen
#   ./scripts/vd_watch.sh --live       # Pipeline vor jedem Refresh ausführen
#   ./scripts/vd_watch.sh --live -n 90 # Live-Pipeline alle 90s
#   ./scripts/vd_watch.sh --once       # einmal anzeigen, kein watch
#   ./scripts/vd_watch.sh --refresh    # einmal Pipeline laufen lassen + anzeigen
# ──────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
JSON_FILE="$PROJECT_DIR/open_prep/latest_open_prep_run.json"
VENV_PYTHON="$PROJECT_DIR/.venv/bin/python"

INTERVAL=60
ONCE=false
LIVE=false
REFRESH=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    -n)      INTERVAL="${2:-60}"; shift 2 ;;
    --once)  ONCE=true; shift ;;
    --live)  LIVE=true; shift ;;
    --refresh) REFRESH=true; shift ;;
    *)       shift ;;
  esac
done

_run_pipeline() {
  echo "⏳ Pipeline wird ausgeführt …"
  cd "$PROJECT_DIR"
  local log="/tmp/vd_watch_pipeline.log"
  if "$VENV_PYTHON" -m open_prep.run_open_prep > /dev/null 2>"$log"; then
    echo "✅ Pipeline OK  ·  $(date '+%H:%M:%S')"
  else
    echo "⚠️  Pipeline-Fehler (exit $?) — Log: $log"
    tail -5 "$log" 2>/dev/null || true
  fi
}

_render() {
  if [[ ! -f "$JSON_FILE" ]]; then
    echo "⏳ Warte auf Daten …"
    return
  fi

  local ts regime bias n_ranked n_go n_v2
  ts=$(jq -r '.run_datetime_utc // "?"' "$JSON_FILE")
  regime=$(jq -r '.regime.regime // "N/A"' "$JSON_FILE" 2>/dev/null || echo "N/A")
  bias=$(jq -r '.macro_bias // 0' "$JSON_FILE")
  n_ranked=$(jq '.ranked_candidates | length' "$JSON_FILE" 2>/dev/null || echo 0)
  n_go=$(jq '.ranked_gap_go | length' "$JSON_FILE" 2>/dev/null || echo 0)
  n_v2=$(jq '.ranked_v2 | length' "$JSON_FILE" 2>/dev/null || echo 0)

  echo "═══════════════════════════════════════════════════════════════════"
  echo "  OPEN PREP MONITOR  ·  $ts"
  echo "  Regime: $regime  ·  Macro Bias: $bias  ·  Ranked: $n_ranked  ·  GAP-GO: $n_go  ·  v2: $n_v2"
  echo "═══════════════════════════════════════════════════════════════════"
  echo ""

  echo "── GAP-GO ──────────────────────────────────────────────────────────"
  jq -r '.ranked_gap_go[:10][] | "\(.symbol)\t\(.score | tostring | .[0:6])\t\(.gap_pct | tostring | .[0:6])%\t\(.gap_grade // "-")\tATR: \(.atr_pct // 0 | tostring | .[0:5])%\t\(.warn_flags // "")"' "$JSON_FILE" 2>/dev/null | column -t -s $'\t' || echo "  (keine)"
  echo ""

  echo "── Ranked Candidates (Top 10) ──────────────────────────────────────"
  jq -r '.ranked_candidates[:10][] | "\(.symbol)\tscore=\(.score | tostring | .[0:6])\tgap=\(.gap_pct | tostring | .[0:6])%\t\(.gap_bucket // "-")\tlong=\(.long_allowed)\t\(.no_trade_reason // "")"' "$JSON_FILE" 2>/dev/null | column -t -s $'\t' || echo "  (keine)"
  echo ""

  # v2 tiered (if available)
  local v2_count
  v2_count=$(jq '.ranked_v2 | length' "$JSON_FILE" 2>/dev/null || echo 0)
  if [[ "$v2_count" -gt 0 ]]; then
    echo "── v2 HIGH CONVICTION ──────────────────────────────────────────────"
    jq -r '[.ranked_v2[]? | select(.confidence_tier == "HIGH_CONVICTION")] | .[:5][] | "  🟢 \(.symbol)\tscore=\(.score | tostring | .[0:6])\tgap=\(.gap_pct | tostring | .[0:6])%\tHR=\(.historical_hit_rate // 0 | . * 100 | floor | tostring)%"' "$JSON_FILE" 2>/dev/null | column -t -s $'\t' || echo "  (keine)"
    echo ""

    echo "── Playbooks ───────────────────────────────────────────────────────"
    jq -r '.ranked_v2[:8][] | "  \(.symbol)\t\(.playbook.playbook // "—")\t\(.playbook.event_label // "—")\t\(.playbook.materiality // "—")\t\(.playbook.recency_bucket // "—")\texec=\(.playbook.execution_quality // "—")\tsize=\(.playbook.size_adjustment // 0 | tostring | .[0:4])\talign=\(.playbook.regime_aligned // false)"' "$JSON_FILE" 2>/dev/null | column -t -s $'\t' || echo "  (keine)"
    echo ""
  fi

  echo "── US High Impact Events ───────────────────────────────────────────"
  jq -r '.macro_us_high_impact_events_today[:5][] | "\(.time_utc // "?")\t\(.name // "?")\t\(.impact // "?")\t\(.actual // "?") / \(.forecast // "?")"' "$JSON_FILE" 2>/dev/null | column -t -s $'\t' || echo "  (keine)"
  echo ""

  echo "── Sectors ─────────────────────────────────────────────────────────"
  jq -r '[.sector_performance[]?] | sort_by(-.changesPercentage) | .[:6][] | "\(.sector_emoji) \(.sector)\t\(.changesPercentage | tostring | .[0:6])%"' "$JSON_FILE" 2>/dev/null | column -t -s $'\t' || echo "  (keine)"
}

export JSON_FILE
export LIVE
export PROJECT_DIR
export VENV_PYTHON

if [[ "$REFRESH" == true ]]; then
  # Einmal Pipeline laufen lassen, dann anzeigen
  _run_pipeline
  _render
elif [[ "$ONCE" == true ]]; then
  if [[ "$LIVE" == true ]]; then
    _run_pipeline
  fi
  _render
else
  if [[ "$LIVE" == true ]]; then
    # Im Live-Modus: Pipeline + Render in einem Aufruf
    watch -n "$INTERVAL" -t --color "$0 --once --live"
  else
    watch -n "$INTERVAL" -t --color "$0 --once"
  fi
fi
