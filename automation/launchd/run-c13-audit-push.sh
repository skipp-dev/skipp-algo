#!/usr/bin/env bash
# C13 Phase-A — daily local cron driver to push audit artefacts to the
# dedicated `data/phase-a-audit` branch (keeps cron-bot churn off main).
#
# Invoked by ~/Library/LaunchAgents/com.skippalgo.c13.audit-push.plist
# Mon-Fri targeting 17:30 ET — 90 minutes after the 16:00 ET US-equity
# close (the plist fires at three ET-bracketing local times; the ET gate
# below lets exactly one proceed).
#
# Repo policy: never --force, never --no-verify. The target branch is a
# dedicated, UNPROTECTED bot branch (`data/phase-a-audit`, excluded from
# main-governance by design — see README.md); pushes use the same
# PAT-authenticated origin as the local `git push` (gh CLI keyring
# credentials are reused by git).

set -euo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"

# ET timezone gate: the plist fires at three candidate LOCAL times bracketing
# the 17:30 ET target across US/EU DST; proceed only in the true ET window
# (lib_c13_et_gate.sh). Root-caused 2026-07-07: a non-ET Mac fired these ~6h off.
# 17:30 ET; the +7h candidate crosses midnight (00:30 next-day Berlin), so its
# plist Weekday entries are shifted +1 -- the gate keys off the true ET weekday.
source "$(dirname "$0")/lib_c13_et_gate.sh"
c13_require_et_window "$REPO" 17 30 10 audit-push || exit 0
DATE="$(date -u +%Y-%m-%d)"

cd "${REPO}"

AUDIT="cache/live/incubation_${DATE}.jsonl"
SETUPS="cache/live/setups_${DATE}.jsonl"
GATES="cache/live/gate_status.json"
# Deploy-hygiene sidecar written by run-c13-phase-a.sh: how far this Mac's
# checkout is behind origin/main on the paper-submit order path. Powers the
# `C13 submitter on stale checkout` alert. push_to_data_branch skips it cleanly
# if a fetch hiccup left it unwritten today.
CHECKOUT_FRESHNESS="cache/live/checkout_freshness.json"
# Traded-universe outcomes (universe_source=STATIC stamp) — the TradingView
# panel publisher prefers this over the CI screener outcomes committed on
# main (Option-a decision 2026-07-09). push_to_data_branch skips it quietly
# when the morning export did not run.
#
# outcomes_local/, NOT outcomes/: run-c13-phase-a-export.sh redirects the
# local STATIC writes via OPEN_PREP_OUTCOMES_DIR to outcomes_local/, while
# outcomes/ is the git-tracked CI screener file (FMP universe) that ALWAYS
# exists — so the old path published the WRONG universe on every push and
# the "skip quietly" branch was unreachable. Proven on the branch itself:
# every published outcomes_*.json carried universe_source=FMP_US_MID_LARGE,
# and Option-a had never once taken effect (Grenzgänger-Sweep B5,
# 2026-08-18).
OUTCOMES="artifacts/open_prep/outcomes_local/outcomes_${DATE}.json"

# Status marker so a degraded run is DETECTABLE rather than silently green.
# Written on every exit path (degraded:* or ok:*). cache/live is gitignored
# on main, so the marker never enters a commit.
STATUS_MARKER="cache/live/.audit_push_status_${DATE}"
mkdir -p cache/live 2>/dev/null || true

# Publishing-Lib und Marker-Summary VOR dem No-Audit-Exit (Grenzgaenger-Sweep
# 2026-08-22): der Emit sass dahinter, und seit seiner Geburt (#4848, 19.8.)
# gab es keinen einzigen Audit-Tag mehr — cache/live/c13_status_markers.json
# hatte auf data/phase-a-audit NIE existiert. Die Ampel floss also exakt an
# den Tagen nicht, die sie beleuchten soll (Dormanz, tote Treiber). Der
# Digest muss JEDEN Wochentag fliessen, unabhaengig vom Audit.
# shellcheck source=automation/launchd/lib_c13_data_push.sh
source "$(dirname "$0")/lib_c13_data_push.sh"
# Status-marker summary (#4848 Review-Punkt #4): sanitized digest of the last
# three days' .<agent>_status_* markers, consumed by c13-daily-cron's
# status_markers step. Best-effort: a summary failure must never block the
# audit push; a missing/stale summary is since 2026-08-22 a HARD alarm on
# the cron side (check()), not a warning.
MARKERS_SUMMARY="cache/live/c13_status_markers.json"
VENV="${C13_VENV:-${REPO}/.venv}"
"${VENV}/bin/python" -m scripts.c13_status_markers emit \
    --live-dir cache/live --live-dir cache/imbalance --live-dir cache/wsh \
    --date "${DATE}" --days-back 3 \
    --output "${MARKERS_SUMMARY}" \
    || echo "audit-push: WARN — status-marker summary emit failed; pushing without it" >&2

if [[ ! -f "${AUDIT}" ]]; then
    echo "audit-push: DEGRADED — no audit artefact at ${AUDIT}. Phase-A produced no" \
         "incubation file today; check com.skippalgo.c13.phase-a (Full-Disk-Access/TCC," \
         "venv path, or upstream trade-cards). Pushing the status-marker summary alone." >&2
    echo "degraded:no-audit-file:$(date -u +%FT%TZ)" > "${STATUS_MARKER}" || true
    # push_to_data_branch schreibt sein EIGENES Ergebnis in das Marker-Arg
    # (ok:pushed/degraded:push-*). Danach die semantische Wahrheit
    # zurueckschreiben: der Tag hatte kein Audit — das ist es, was morgen im
    # Digest stehen muss. Ein verlorener push-failed-Detailtext ist verkraftbar:
    # scheitert der Push, wird die Summary stale und check() roetet CI-seitig.
    push_to_data_branch \
        "chore(c13): status markers ${DATE} (no-audit day)" \
        "${STATUS_MARKER}" \
        "${MARKERS_SUMMARY}" \
        || echo "audit-push: WARN — summary-only push failed; check() reds on staleness" >&2
    echo "degraded:no-audit-file:$(date -u +%FT%TZ)" > "${STATUS_MARKER}" || true
    exit 0
fi

# Publish the audit artefacts onto data/phase-a-audit via the shared
# publishing-clone helper (audit pass-3 finding A1). The helper owns the
# hardened push pipeline — a dedicated hook-free clone under
# ~/.cache/skippalgo/c13-data-clone with a self-healing re-clone on
# corruption, fail-loud markers on every exit path (R4), push-stderr
# capture (R5), and a one-shot non-fast-forward retry — so this driver no
# longer duplicates (and silently drifts from) that logic. clone/fetch
# failures return non-zero and ``set -e`` surfaces them; push failures are
# soft (marker degraded:push-failed, retried on the next run). The primary
# working tree's checked-out branch is never touched.
# NOTE: this was a ``git worktree`` of the dev clone until 2026-07-06 — if
# you are debugging a frozen data branch, the state lives in the cache dir
# above, not in ``git worktree list``. See lib_c13_data_push.sh's header.
# (Lib + Marker-Summary werden seit 2026-08-22 VOR dem No-Audit-Exit oben
# geladen bzw. emittiert — die Summary faehrt in diesem Push nur noch mit.)
push_to_data_branch \
    "chore(c13): phase-a audit ${DATE}" \
    "${STATUS_MARKER}" \
    "${AUDIT}" \
    "${SETUPS}" \
    "${GATES}" \
    "${CHECKOUT_FRESHNESS}" \
    "${OUTCOMES}" \
    "${MARKERS_SUMMARY}"
