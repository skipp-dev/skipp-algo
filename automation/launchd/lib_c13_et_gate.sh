#!/usr/bin/env bash
# lib_c13_et_gate.sh — DST-robust "run at a US-market (ET) wall-clock time" gate
# for the C13 launchd wrappers.
#
# The problem: launchd `StartCalendarInterval` fires in the Mac's LOCAL
# timezone, but these jobs are scheduled against US Eastern market time (ET).
# On a non-ET Mac (e.g. Europe/Berlin) a plist that says "09:28" fires at 09:28
# LOCAL = 03:28 ET — 6 hours before the US open, so ORB orders never fill and
# the pre-market TWS smoke always trips smoke_HALT (root-caused 2026-07-07).
#
# The fix has two halves that MUST go together:
#   1. The plist fires at the THREE candidate local times that bracket the ET
#      target across the mismatched US/EU DST windows — the Berlin↔ET offset is
#      +5h (EU-off/US-on, late Oct–early Nov), +6h (the common case) or +7h
#      (EU-on/US-off, mid–late March). e.g. 09:28 ET -> 14:28 / 15:28 / 16:28.
#   2. This gate lets exactly ONE fire per ET weekday proceed: the one whose
#      TRUE ET clock (via TZ=America/New_York, which tracks US DST for us) is
#      within [target ± tolerance]. The other two candidate fires no-op.
#
# It is therefore correct year-round with no hardcoded offset and no reliance
# on the Mac's timezone matching ET.
#
# Usage (top of a wrapper, after REPO is defined):
#   source "$(dirname "$0")/lib_c13_et_gate.sh"
#   c13_require_et_window "$REPO" 09 28 10 phase-a || exit 0   # 09:28 ET ±10m
#
# Returns 0 (proceed) or non-zero (skip — the caller should `|| exit 0`).
# Tests inject a fixed clock via C13_GATE_NOW_ET="HH:MM" and C13_GATE_NOW_DOW=N.

c13_require_et_window() {
    local repo="$1" thh="$2" tmm="$3" tol="$4" job="$5"

    local et_date et_dow et_hh et_mm
    et_date="$(TZ=America/New_York date +%Y-%m-%d)"
    # Test hooks: override the ET wall clock / weekday deterministically.
    if [ -n "${C13_GATE_NOW_ET:-}" ]; then
        et_hh="${C13_GATE_NOW_ET%%:*}"
        et_mm="${C13_GATE_NOW_ET##*:}"
        et_dow="${C13_GATE_NOW_DOW:-1}"
    else
        et_dow="$(TZ=America/New_York date +%u)"   # 1=Mon .. 7=Sun
        et_hh="$(TZ=America/New_York date +%H)"
        et_mm="$(TZ=America/New_York date +%M)"
    fi

    if [ "$((10#$et_dow))" -gt 5 ]; then
        echo "c13-gate[$job]: ET weekday=$et_dow is a weekend — skip." >&2
        return 1
    fi

    local now_min tgt_min diff
    now_min=$((10#$et_hh * 60 + 10#$et_mm))
    tgt_min=$((10#$thh * 60 + 10#$tmm))
    diff=$((now_min - tgt_min))
    diff=${diff#-}
    if [ "$diff" -gt "$((10#$tol))" ]; then
        echo "c13-gate[$job]: ET now ${et_hh}:${et_mm}, target ${thh}:${tmm} (+-${tol}m) — not the window, skip." >&2
        return 1
    fi

    # Exactly-once per ET day: a second in-window candidate fire (or a launchd
    # catch-up after wake) must not double-run — for phase-a that would mean
    # duplicate paper orders.
    local marker="${repo}/cache/live/.c13_gate_${job}_${et_date}"
    if [ -e "$marker" ]; then
        echo "c13-gate[$job]: already ran for ET ${et_date} — skip." >&2
        return 1
    fi
    mkdir -p "${repo}/cache/live"
    printf '%s ET %s:%s (target %s:%s)\n' "$et_date" "$et_hh" "$et_mm" "$thh" "$tmm" > "$marker"
    return 0
}
