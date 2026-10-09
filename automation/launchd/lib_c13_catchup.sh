# Shared catch-up / backfill helper for C13 launchd cron drivers.
#
# Problem (Item 4/5, 2026-06-15): the LaunchAgents are scheduled via
# ``StartCalendarInterval``. When the workstation is asleep at the scheduled
# minute, launchd fires the job ONCE on the next wake — and it *coalesces*
# multiple missed occurrences into that single run. So if the machine was
# asleep for three business days, only ONE run happens on wake and the other
# two days are silently lost. There was no mechanism to detect and replay the
# missed run-dates.
#
# This helper computes the set of business days (Mon-Fri) within a bounded
# lookback window whose per-date completion marker is missing or degraded, so
# a driver can iterate and reprocess each missed date in one wake-up.
#
# Completion signal: the same status marker that ``lib_c13_data_push.sh``
# writes — ``<marker_dir>/<marker_prefix><DATE>`` — whose first line starts
# with ``ok:`` on success (``ok:pushed`` / ``ok:no-change`` / ``ok:pushed-retry``)
# and ``degraded:`` on a soft failure. A date is considered DONE only when its
# marker exists and starts with ``ok:``; otherwise it is replayed.
#
# Usage (from a driver, after ``set -euo pipefail`` and ``cd "${REPO}"``):
#     source "$(dirname "$0")/lib_c13_catchup.sh"
#     # Wrap the per-date body in a function taking the date as $1:
#     process_one_date() { local DATE="$1"; ...; }
#     # Then replay every missed business day (today only if no dates are missing):
#     c13_run_with_catchup \
#         "${REPO}/cache/imbalance" ".push_status_" process_one_date
#
# Window size is bounded (default 7 calendar days, override via
# ``C13_CATCHUP_LOOKBACK_DAYS``) so a permanently-failing date — e.g. a market
# holiday with no data — is retried for at most a week rather than forever.
#
# Pure date helpers are portable across BSD ``date`` (macOS, where the drivers
# run) and GNU ``date`` (Linux, where CI runs the unit test).

# Detect the ``date`` flavour once at source time via the kernel name.
# macOS ships BSD date; Linux ships GNU date.
case "$(uname -s)" in
    Darwin*)  _C13_DATE_FLAVOUR="bsd" ;;
    *)        _C13_DATE_FLAVOUR="gnu" ;;
esac

# Echo the ISO weekday (1=Mon .. 7=Sun) for a YYYY-MM-DD date.
c13__dow() {
    local d="$1"
    if [[ "${_C13_DATE_FLAVOUR}" == "gnu" ]]; then
        date -u -d "${d}" +%u
    else
        date -j -u -f "%Y-%m-%d" "${d}" +%u
    fi
}

# Echo YYYY-MM-DD for (today_UTC - N calendar days).
c13__utc_minus_days() {
    local n="$1"
    if [[ "${_C13_DATE_FLAVOUR}" == "gnu" ]]; then
        date -u -d "${n} days ago" +%Y-%m-%d
    else
        date -u -v-"${n}"d +%Y-%m-%d
    fi
}

# Echo the business days (Mon-Fri) in the inclusive window
# [today_UTC - lookback, today_UTC], oldest first.
#   $1 = lookback (calendar days); defaults to C13_CATCHUP_LOOKBACK_DAYS or 7.
c13_business_dates_in_window() {
    local lookback="${1:-${C13_CATCHUP_LOOKBACK_DAYS:-7}}"
    local i d dow
    for (( i=lookback; i>=0; i-- )); do
        d="$(c13__utc_minus_days "${i}")"
        dow="$(c13__dow "${d}")"
        if [[ "${dow}" -ge 1 && "${dow}" -le 5 ]]; then
            printf '%s\n' "${d}"
        fi
    done
}

# Return 0 if the marker file exists and its first line marks success.
#   $1 = marker path.
#   $2 = success prefix (optional, default ``ok:``). Drivers that publish via
#        lib_c13_data_push.sh use ``ok:``; phase-a writes ``SUCCESS|`` markers.
c13_marker_is_ok() {
    local m="$1"
    local ok_prefix="${2:-ok:}"
    [[ -f "${m}" ]] || return 1
    local first=""
    IFS= read -r first < "${m}" 2>/dev/null || true
    [[ "${first}" == "${ok_prefix}"* ]]
}

# Echo the business days within the lookback window whose completion marker is
# absent or non-success, oldest first.
#   $1 = marker_dir, $2 = marker_prefix (e.g. ".push_status_"),
#   $3 = lookback (calendar days; optional),
#   $4 = success prefix (optional, default ``ok:``).
c13_missing_business_dates() {
    local marker_dir="$1"
    local marker_prefix="$2"
    local lookback="${3:-${C13_CATCHUP_LOOKBACK_DAYS:-7}}"
    local ok_prefix="${4:-ok:}"
    local d
    while IFS= read -r d; do
        [[ -z "${d}" ]] && continue
        if ! c13_marker_is_ok "${marker_dir}/${marker_prefix}${d}" "${ok_prefix}"; then
            printf '%s\n' "${d}"
        fi
    done < <(c13_business_dates_in_window "${lookback}")
}

# Replay a per-date callback over every missed business day in the window.
# Safety net: if no dates are missing, still run today once.
#   $1 = marker_dir, $2 = marker_prefix, $3 = callback fn name (takes DATE),
#   $4 = lookback (optional), $5 = success prefix (optional, default ``ok:``).
# The callback is invoked once per date; a non-zero callback exit is logged but
# does NOT abort the remaining dates (best-effort backfill). Returns the number
# of dates whose callback failed (0 = all good) so the caller can set its exit
# status if desired.
c13_run_with_catchup() {
    local marker_dir="$1"
    local marker_prefix="$2"
    local callback="$3"
    local lookback="${4:-${C13_CATCHUP_LOOKBACK_DAYS:-7}}"
    local ok_prefix="${5:-ok:}"

    local dates today failures=0 d
    today="$(date -u +%Y-%m-%d)"
    dates="$(c13_missing_business_dates "${marker_dir}" "${marker_prefix}" "${lookback}" "${ok_prefix}")"

    # Safety net: if every marker is already ``ok`` (nothing missed) still run
    # today's job so a normal on-time wake behaves exactly as before.
    if [[ -z "${dates}" ]]; then
        dates="${today}"
    fi

    local count
    count="$(printf '%s\n' "${dates}" | grep -c . || true)"
    if [[ "${count}" -gt 1 ]]; then
        echo "c13 catch-up: ${count} business day(s) to (re)process: $(printf '%s ' ${dates})" >&2
    fi

    for d in ${dates}; do
        if ! "${callback}" "${d}"; then
            echo "c13 catch-up: callback '${callback}' failed for ${d} (continuing)" >&2
            failures=$(( failures + 1 ))
        fi
    done

    return "${failures}"
}
