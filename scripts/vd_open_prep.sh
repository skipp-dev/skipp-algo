#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────
# vd_open_prep.sh — Open-Prep Pipeline → VisiData (Terminal-Excel)
# ──────────────────────────────────────────────────────────────────
# Usage:
#   ./scripts/vd_open_prep.sh              # frische Daten holen + VisiData
#   ./scripts/vd_open_prep.sh --cached     # letzten Lauf wiederverwenden
#   ./scripts/vd_open_prep.sh --view VIEW  # direkt eine View öffnen
#   ./scripts/vd_open_prep.sh --watch 300  # auto-refresh alle 300s (5 min)
#
# Views:  ranked | gap-go | gap-watch | earnings | trade-cards
#         macro | regime | sectors | v2 | playbooks | news
#         signals | signals-trader | signals-live | all
#
# Auto-Refresh (--watch):
#   Pipeline + jq-Extraction laufen im Hintergrund alle N Sekunden.
#   In VisiData: Ctrl+R = Reload vom Disk → zeigt sofort frische Daten.
#   Beim Beenden von VisiData wird der Hintergrund-Refresher gestoppt.
#
# Hotkeys in VisiData:
#   q       = zurück / beenden
#   / + F   = Suche / Filtern
#   [ / ]   = Sortieren (asc / desc)
#   - / _   = Spalte ein-/ausblenden
#   g/       = Regex über alle Spalten
#   . (dot) = Spaltentyp setzen ($ = Währung, % = Prozent, # = Integer)
#   Shift+F = Frequency-Table (Histogramm)
#   s       = Sheet speichern (CSV/JSON/TSV)
#   Ctrl+R  = Reload aktuelles Sheet von Disk (nach --watch Refresh)
# ──────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
# Canonical path (new); falls back to legacy package-dir location (symlink).
JSON_FILE="$PROJECT_DIR/artifacts/open_prep/latest/latest_open_prep_run.json"
[[ -f "$JSON_FILE" ]] || JSON_FILE="$PROJECT_DIR/open_prep/latest_open_prep_run.json"
EXTRACT_DIR="$PROJECT_DIR/artifacts/open_prep/vd_extracts"

# ── Defaults ──
USE_CACHED=false
VIEW="all"
WATCH_INTERVAL=0    # 0 = no auto-refresh; >0 = seconds between refreshes

# ── Parse args ──
while [[ $# -gt 0 ]]; do
  case "$1" in
    --cached|-c) USE_CACHED=true; shift ;;
    --view|-v)   VIEW="${2:-all}"; shift 2 ;;
    --watch|-w)  WATCH_INTERVAL="${2:-300}"; shift 2 ;;
    --help|-h)
      head -30 "$0" | tail -28
      exit 0
      ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

# ── Ensure tools ──
for cmd in jq vd; do
  if ! command -v "$cmd" &>/dev/null; then
    echo "❌ '$cmd' nicht gefunden. Bitte installieren: brew install $cmd"
    exit 1
  fi
done

# ── Auto-start RT signal engine (if not already running) ───────
RT_LOG="$PROJECT_DIR/artifacts/open_prep/latest/realtime_signals.log"
_RT_PYTHON="$PROJECT_DIR/.venv/bin/python"
[[ -x "$_RT_PYTHON" ]] || _RT_PYTHON="$(command -v python3)"
if ! pgrep -f "open_prep.realtime_signals" >/dev/null 2>&1; then
  echo "▶️  Starte Realtime-Engine im Hintergrund …"
  mkdir -p "$(dirname "$RT_LOG")"
  if [[ -z "${FMP_API_KEY:-}" ]] && [[ -f "$PROJECT_DIR/.env" ]]; then
    set -a
    source "$PROJECT_DIR/.env"
    set +a
  fi
  nohup env PYTHONPATH="$PROJECT_DIR" \
    "$_RT_PYTHON" -m open_prep.realtime_signals --interval 45 \
    > "$RT_LOG" 2>&1 &
  echo "  ▶️  Engine gestartet (PID $!)"
fi

# ── Helper: run pipeline ──
_run_pipeline() {
  cd "$PROJECT_DIR"

  # Source .env for FMP_API_KEY (if not already exported)
  if [[ -z "${FMP_API_KEY:-}" ]] && [[ -f "$PROJECT_DIR/.env" ]]; then
    set -a
    source "$PROJECT_DIR/.env"
    set +a
  fi

  # Detect Python: prefer .venv, fall back to system python3
  PYTHON="$PROJECT_DIR/.venv/bin/python"
  [[ -x "$PYTHON" ]] || PYTHON="$(command -v python3)"

  PIPELINE_LOG="$PROJECT_DIR/artifacts/open_prep/latest/pipeline_run.log"
  mkdir -p "$(dirname "$PIPELINE_LOG")"

  if PYTHONPATH="$PROJECT_DIR" "$PYTHON" -m open_prep.run_open_prep > /dev/null 2>"$PIPELINE_LOG"; then
    return 0
  else
    return 1
  fi
}

# ── Helper: extract sub-datasets from JSON ──
_extract() {
  local name="$1" filter="$2"
  jq "$filter" "$JSON_FILE" > "$EXTRACT_DIR/${name}.json" 2>/dev/null || true
}

_run_extraction() {
  [[ -f "$JSON_FILE" ]] || return 1
  mkdir -p "$EXTRACT_DIR"

  # Core tables
  _extract "ranked_candidates"    '[.ranked_candidates[]? | {symbol, score, gap_pct, gap_bucket, gap_grade, price, atr_pct, ext_hours_score, news_catalyst_score, momentum_z_score, long_allowed, warn_flags, no_trade_reason, premarket_high, premarket_low, premarket_spread_bps, premarket_stale, volume, avg_volume}]'
  _extract "gap_go"               '[.ranked_gap_go[]? | {symbol, score, gap_pct, gap_grade, price, atr_pct, ext_hours_score, news_catalyst_score, long_allowed, warn_flags, no_trade_reason, premarket_high, premarket_low}]'
  _extract "gap_watch"            '[.ranked_gap_watch[]? | {symbol, score, gap_pct, gap_grade, price, atr_pct, ext_hours_score, warn_flags, no_trade_reason}]'
  _extract "earnings"             '[.ranked_gap_go_earnings[]? | {symbol, score, gap_pct, earnings_timing, warn_flags}]'
  _extract "trade_cards"          '[.trade_cards[]?]'
  _extract "macro_events"         '[.macro_us_high_impact_events_today[]?]'

  # v2 pipeline tables (with playbook)
  _extract "ranked_v2"            '[.ranked_v2[]? | {symbol, score, confidence_tier, gap_pct, gap_grade, breakout_direction, breakout_pattern, is_consolidating, consolidation_score, symbol_regime, playbook: .playbook.playbook, playbook_reason: .playbook.playbook_reason, event_class: .playbook.event_class, event_label: .playbook.event_label, materiality: .playbook.materiality, recency_bucket: .playbook.recency_bucket, source_tier: .playbook.source_tier, execution_quality: .playbook.execution_quality, size_adjustment: .playbook.size_adjustment, max_loss_pct: .playbook.max_loss_pct, regime_aligned: .playbook.regime_aligned, time_horizon: .playbook.time_horizon, gap_go_score: .playbook.gap_go_score, fade_score: .playbook.fade_score, drift_score: .playbook.drift_score, historical_hit_rate, regime, symbol_sector, atr_pct, news_catalyst_score, freshness_half_life_s, warn_flags}]'
  _extract "filtered_out_v2"      '[.filtered_out_v2[]? | {symbol, gap_pct, filter_reasons}]'

  # Playbook-only view (compact)
  _extract "playbooks"            '[.ranked_v2[]? | .playbook | {symbol, playbook, playbook_reason, event_class, event_label, materiality, recency_bucket, source_tier, execution_quality, size_adjustment, max_loss_pct, time_horizon, entry_trigger, invalidation, exit_plan, regime_aligned, no_trade_zone, no_trade_zone_reason, gap_go_score, fade_score, drift_score}]'

  # Regime overview
  _extract "regime"               '.regime // {}'

  # Sector performance
  _extract "sectors"              '[.sector_performance[]? | {sector, changesPercentage, sector_emoji}]'

  # News (with playbook enrichment)
  _extract "news"                 '[.news_catalyst_by_symbol // {} | to_entries[]? | {symbol: .key, score: .value.news_catalyst_score, sentiment: .value.sentiment_label, event_class: .value.event_class, event_label: .value.event_label, materiality: .value.materiality, recency: .value.recency_bucket, source_tier: .value.source_tier, mentions: .value.mentions_24h, actionable: .value.is_actionable}] | sort_by(-.score)'

  # Earnings calendar
  _extract "earnings_calendar"    '[.earnings_calendar[]? | {symbol, date, earnings_timing, eps_estimate, revenue_estimate, eps_actual, revenue_actual}]'

  # Upgrades/Downgrades
  _extract "upgrades"             '[.upgrades_downgrades // {} | to_entries[]? | {symbol: .key, action: .value.upgrade_downgrade_action, firm: .value.upgrade_downgrade_firm, date: .value.upgrade_downgrade_date, emoji: .value.upgrade_downgrade_emoji}]'

  # Watchlist
  _extract "watchlist"            '[.watchlist[]? | {symbol, note, added_at, source}]'

  # Tomorrow outlook
  _extract "tomorrow"             '.tomorrow_outlook // {}'

  # Diff
  _extract "diff"                 '.diff // {}'

  # Endpoint capabilities
  _extract "capabilities"         '[.data_capabilities // {} | to_entries[]? | {feature: .key, status: .value.status, http_status: .value.http_status, detail: .value.detail}]'

  # Realtime signals (prefer compact VD snapshot if available)
  VD_SIGNALS_FILE="$PROJECT_DIR/artifacts/open_prep/latest/latest_vd_signals.jsonl"
  SIGNALS_FILE="$PROJECT_DIR/artifacts/open_prep/latest/latest_realtime_signals.json"
  [[ -f "$SIGNALS_FILE" ]] || SIGNALS_FILE="$PROJECT_DIR/open_prep/latest_realtime_signals.json"

  if [[ -f "$VD_SIGNALS_FILE" ]]; then
    # Check if VD signals file is stale (>5 min old)
    _vd_age_s=$(( $(date +%s) - $(stat -f "%m" "$VD_SIGNALS_FILE" 2>/dev/null || stat -c "%Y" "$VD_SIGNALS_FILE" 2>/dev/null || echo "$(date +%s)") ))
    if [[ "$_vd_age_s" -gt 300 ]]; then
      echo "⚠️  RT-Signale veraltet ($(( _vd_age_s / 60 ))m) — Engine läuft möglicherweise nicht." >&2
    fi
    jq -s '.' "$VD_SIGNALS_FILE" > "$EXTRACT_DIR/realtime_signals_live.json" 2>/dev/null || echo "[]" > "$EXTRACT_DIR/realtime_signals_live.json"

    jq -s '[.[] | {
      symbol,
      signal,
      direction,
      breakout,
      news,
      news_url,
      news_score,
      news_s,
      signal_age_hms,
      news_polarity,
      signal_since_at,
      price,
      chg_pct,
      vol_ratio,
      score,
      tick,
      streak,
      d_price_pct,
      tier,
      last_change_age_s,
      poll_seq,
      poll_changed
    }]' "$VD_SIGNALS_FILE" > "$EXTRACT_DIR/realtime_signals_trader.json" 2>/dev/null || echo "[]" > "$EXTRACT_DIR/realtime_signals_trader.json"
  elif [[ -f "$SIGNALS_FILE" ]]; then
    jq '[.signals[]? | {
      symbol,
      signal: .level,
      direction,
      breakout: "",
      news: (.news_headline // ""),
      news_url: (.details.news_url // ""),
      news_score,
      news_s: (if (.details.polarity // 0) > 0.05 then "🟢" elif (.details.polarity // 0) < -0.05 then "🔴" else "🟡" end),
      signal_age_hms: (((((now - (.level_since_epoch // .fired_epoch // now)) | floor) / 3600) | floor | tostring) + ":" + (((((now - (.level_since_epoch // .fired_epoch // now)) | floor) % 3600 / 60) | floor | tostring) | if length==1 then "0" + . else . end) + ":" + (((((now - (.level_since_epoch // .fired_epoch // now)) | floor) % 60) | floor | tostring) | if length==1 then "0" + . else . end)),
      news_polarity: (.details.polarity // 0),
      signal_since_at: .level_since_at,
      price,
      chg_pct: .change_pct,
      vol_ratio: .volume_ratio,
      score,
      tick: "",
      streak: 0,
      d_price_pct: 0,
      tier: .confidence_tier,
      last_change_age_s: 0,
      poll_seq: 0,
      poll_changed: false
    }]' "$SIGNALS_FILE" > "$EXTRACT_DIR/realtime_signals_live.json" 2>/dev/null || echo "[]" > "$EXTRACT_DIR/realtime_signals_live.json"
    cp "$EXTRACT_DIR/realtime_signals_live.json" "$EXTRACT_DIR/realtime_signals_trader.json"
  else
    echo "[]" > "$EXTRACT_DIR/realtime_signals_live.json"
    echo "[]" > "$EXTRACT_DIR/realtime_signals_trader.json"
  fi

  # Backward-compatible alias used by old view name
  cp "$EXTRACT_DIR/realtime_signals_live.json" "$EXTRACT_DIR/realtime_signals.json"
}

# ── Run pipeline if not cached ──
if [[ "$USE_CACHED" == false ]] || [[ ! -f "$JSON_FILE" ]]; then
  echo "🔄 Pipeline wird ausgeführt (Auto-Universum) …"
  if _run_pipeline; then
    echo "✅ Pipeline abgeschlossen."
  else
    echo "❌ Pipeline fehlgeschlagen. Log: $PROJECT_DIR/artifacts/open_prep/latest/pipeline_run.log"
    tail -5 "$PROJECT_DIR/artifacts/open_prep/latest/pipeline_run.log" 2>/dev/null || true
    exit 1
  fi
fi

if [[ ! -f "$JSON_FILE" ]]; then
  echo "❌ Keine Daten gefunden: $JSON_FILE"
  exit 1
fi

# ── Initial extraction ──
_run_extraction

# ── Extract timestamp ──
RUN_TS=$(jq -r '.run_datetime_utc // "unknown"' "$JSON_FILE")
echo "📊 Datenstand: $RUN_TS"

# ── Staleness check: warn if data is old ──
if [[ -f "$JSON_FILE" ]]; then
  _file_age_s=$(( $(date +%s) - $(stat -f "%m" "$JSON_FILE" 2>/dev/null || stat -c "%Y" "$JSON_FILE" 2>/dev/null || echo "$(date +%s)") ))
  _file_age_m=$(( _file_age_s / 60 ))
  if [[ "$_file_age_m" -gt 5 ]]; then
    echo "⚠️  WARNUNG: Daten sind ${_file_age_m} Minuten alt! Pipeline ggf. erneut starten."
  elif [[ "$_file_age_m" -gt 2 ]]; then
    echo "ℹ️  Daten-Alter: ${_file_age_m} Minuten"
  fi
fi

# Summary one-liner
MACRO_BIAS=$(jq -r '.macro_bias // 0' "$JSON_FILE")
N_RANKED=$(jq '.ranked_candidates | length' "$JSON_FILE" 2>/dev/null || echo 0)
N_GAP_GO=$(jq '.ranked_gap_go | length' "$JSON_FILE" 2>/dev/null || echo 0)
N_V2=$(jq '.ranked_v2 | length' "$JSON_FILE" 2>/dev/null || echo 0)
REGIME=$(jq -r '.regime.regime // "N/A"' "$JSON_FILE" 2>/dev/null || echo "N/A")
echo "🏛️  Regime: $REGIME · Macro Bias: $MACRO_BIAS · Ranked: $N_RANKED · GAP-GO: $N_GAP_GO · v2: $N_V2"
echo ""

# ── Watch mode: background refresher ──
WATCH_PID=""
_cleanup_watch() {
  if [[ -n "$WATCH_PID" ]]; then
    kill "$WATCH_PID" 2>/dev/null || true
    wait "$WATCH_PID" 2>/dev/null || true
    echo ""
    echo "🛑 Auto-Refresh gestoppt."
  fi
}
trap _cleanup_watch EXIT

if [[ "$WATCH_INTERVAL" -gt 0 ]]; then
  echo "🔄 Auto-Refresh alle ${WATCH_INTERVAL}s aktiv. In VisiData: Ctrl+R = Reload."
  echo ""
  (
    _consecutive_fails=0
    while true; do
      sleep "$WATCH_INTERVAL"
      if _run_pipeline 2>/dev/null; then
        _run_extraction 2>/dev/null
        _ts=$(jq -r '.run_datetime_utc // "?"' "$JSON_FILE" 2>/dev/null)
        echo "  ↻ Refresh $(date +%H:%M:%S) (Daten: $_ts)" >&2
        _consecutive_fails=0
      else
        _consecutive_fails=$(( _consecutive_fails + 1 ))
        echo "  ⚠ Refresh fehlgeschlagen $(date +%H:%M:%S) (${_consecutive_fails}× in Folge)" >&2
        # Auto-recovery: after 3 consecutive failures, clear env caches
        # and extend sleep to avoid hammering a broken API.
        if [[ "$_consecutive_fails" -ge 3 ]]; then
          echo "  🔄 Auto-Recovery: 3 Fehler in Folge — warte 60s vor erneutem Versuch" >&2
          # Re-source .env in case keys were rotated
          if [[ -f "$PROJECT_DIR/.env" ]]; then
            set -a
            # shellcheck disable=SC1091
            source "$PROJECT_DIR/.env"
            set +a
          fi
          sleep 60
          _consecutive_fails=0
        fi
      fi
    done
  ) &
  WATCH_PID=$!
fi

# ── Launch VisiData ──
case "$VIEW" in
  ranked)
    echo "📋 Ranked Candidates → VisiData"
    vd "$EXTRACT_DIR/ranked_candidates.json"
    ;;
  gap-go)
    echo "📋 GAP-GO Kandidaten → VisiData"
    vd "$EXTRACT_DIR/gap_go.json"
    ;;
  gap-watch)
    echo "📋 GAP-WATCH Kandidaten → VisiData"
    vd "$EXTRACT_DIR/gap_watch.json"
    ;;
  earnings)
    echo "📋 Earnings → VisiData"
    vd "$EXTRACT_DIR/earnings.json"
    ;;
  trade-cards)
    echo "📋 Trade Cards → VisiData"
    vd "$EXTRACT_DIR/trade_cards.json"
    ;;
  macro)
    echo "📋 US High Impact Events → VisiData"
    vd "$EXTRACT_DIR/macro_events.json"
    ;;
  regime)
    echo "📋 Regime → VisiData"
    vd "$EXTRACT_DIR/regime.json"
    ;;
  sectors)
    echo "📋 Sector Performance → VisiData"
    vd "$EXTRACT_DIR/sectors.json"
    ;;
  v2)
    echo "📋 v2 Tiered Candidates (with Playbook) → VisiData"
    vd "$EXTRACT_DIR/ranked_v2.json"
    ;;
  playbooks)
    echo "📋 Playbook Details → VisiData"
    vd "$EXTRACT_DIR/playbooks.json"
    ;;
  news)
    echo "📋 News Catalysts → VisiData"
    vd "$EXTRACT_DIR/news.json"
    ;;
  signals)
    echo "🔴 Realtime Signals → VisiData"
    vd "$EXTRACT_DIR/realtime_signals.json"
    ;;
  signals-trader)
    echo "🎯 Realtime Signals (Trader Compact) → VisiData"
    vd "$EXTRACT_DIR/realtime_signals_trader.json"
    ;;
  signals-live)
    echo "⚡ Realtime Signals (Live Snapshot) → VisiData"
    vd "$EXTRACT_DIR/realtime_signals_live.json"
    ;;
  all)
    echo "📋 Alle Sheets → VisiData (q = zurück, gS = Sheet-Liste)"
    echo "   Sheets: realtime_signals_live, realtime_signals_trader, ranked_candidates, gap_go, gap_watch, earnings, trade_cards,"
    echo "           macro_events, ranked_v2, playbooks, sectors, news,"
    echo "           earnings_calendar, upgrades, watchlist, capabilities"
    echo ""
    vd \
      "$EXTRACT_DIR/realtime_signals_live.json" \
      "$EXTRACT_DIR/realtime_signals_trader.json" \
      "$EXTRACT_DIR/ranked_candidates.json" \
      "$EXTRACT_DIR/gap_go.json" \
      "$EXTRACT_DIR/gap_watch.json" \
      "$EXTRACT_DIR/earnings.json" \
      "$EXTRACT_DIR/trade_cards.json" \
      "$EXTRACT_DIR/macro_events.json" \
      "$EXTRACT_DIR/ranked_v2.json" \
      "$EXTRACT_DIR/playbooks.json" \
      "$EXTRACT_DIR/sectors.json" \
      "$EXTRACT_DIR/news.json" \
      "$EXTRACT_DIR/earnings_calendar.json" \
      "$EXTRACT_DIR/upgrades.json" \
      "$EXTRACT_DIR/watchlist.json" \
      "$EXTRACT_DIR/capabilities.json"
    ;;
  *)
    echo "❌ Unbekannte View: $VIEW"
    echo "   Verfügbar: ranked | gap-go | gap-watch | earnings | trade-cards"
    echo "              macro | regime | sectors | v2 | playbooks | news"
    echo "              signals | signals-trader | signals-live | all"
    exit 1
    ;;
esac
