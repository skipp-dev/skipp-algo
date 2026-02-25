#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────
# vd_signals_live.sh — Realtime Signals direkt in VisiData öffnen
# ──────────────────────────────────────────────────────────────────
# Usage:
#   ./scripts/vd_signals_live.sh
#   ./scripts/vd_signals_live.sh --start-engine
#   ./scripts/vd_signals_live.sh --start-engine --interval 15
#
# Optionen:
#   --start-engine   startet open_prep.realtime_signals im Hintergrund,
#                    falls noch kein Prozess läuft
#   --interval N     Poll-Intervall für --start-engine (default 45)
#   --help           Hilfe anzeigen
#
# Liest live aus:
#   artifacts/open_prep/latest/latest_vd_signals.jsonl
#
# Tipp in VisiData:
#   - nach Signal filtern:   signal=A0
#   - nur Poll-Änderungen:   poll_changed=true
#   - wichtige Spalten: symbol, signal, direction, breakout, news,
#     news_score, signal_age_hms, tick, streak, d_price_pct, vol_ratio
# ──────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

DATA_FILE="$PROJECT_DIR/artifacts/open_prep/latest/latest_vd_signals.jsonl"
LOG_FILE="$PROJECT_DIR/artifacts/open_prep/latest/realtime_signals.log"

START_ENGINE=false
INTERVAL=45

while [[ $# -gt 0 ]]; do
  case "$1" in
    --start-engine)
      START_ENGINE=true
      shift
      ;;
    --interval)
      INTERVAL="${2:-45}"
      shift 2
      ;;
    --help|-h)
      sed -n '1,40p' "$0"
      exit 0
      ;;
    *)
      echo "Unbekannte Option: $1"
      echo "Nutze --help"
      exit 1
      ;;
  esac
done

for cmd in vd python3; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "❌ '$cmd' nicht gefunden."
    exit 1
  fi
done

mkdir -p "$(dirname "$DATA_FILE")"

if [[ "$START_ENGINE" == true ]]; then
  if pgrep -f "open_prep.realtime_signals" >/dev/null 2>&1; then
    echo "ℹ️  Realtime-Engine läuft bereits."
  else
    echo "▶️  Starte Realtime-Engine (interval=${INTERVAL}s) …"
    # ENV laden, wenn vorhanden
    if [[ -f "$PROJECT_DIR/.env" ]]; then
      set -a
      # shellcheck disable=SC1091
      source "$PROJECT_DIR/.env"
      set +a
    fi
    nohup env PYTHONPATH="$PROJECT_DIR" \
      python3 -m open_prep.realtime_signals --interval "$INTERVAL" \
      > "$LOG_FILE" 2>&1 &
    sleep 2
  fi
fi

if [[ ! -f "$DATA_FILE" ]]; then
  echo "⏳ Signaldatei existiert noch nicht:"
  echo "   $DATA_FILE"
  echo ""
  echo "Starte ggf. zuerst:"
  echo "  ./scripts/vd_signals_live.sh --start-engine"
  exit 1
fi

echo "📈 Öffne Realtime-Signale in VisiData:"
echo "   $DATA_FILE"
echo ""
echo "Hot quick filters:"
echo "  signal=A0         (nur A0)"
echo "  signal=A1         (nur A1)"
echo "  poll_changed=true (nur neue Änderungen pro Poll)"
echo ""

exec vd --filetype jsonl "$DATA_FILE"
