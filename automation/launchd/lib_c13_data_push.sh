# Shared helper for C13 launchd cron drivers.
#
# Publishes generated data artefacts to the dedicated ``data/phase-a-audit``
# branch via a DEDICATED, hook-free publishing clone, so the push never
# touches (or commits onto) whatever branch the primary working tree happens
# to have checked out when the LaunchAgent fires — and never runs the code
# repo's client-side hook gauntlet against a data-only publish.
#
# Background (Lane 7 provider-boundary audit, 2026-06-10): the previous
# ``git commit + git push origin <current-branch>`` pattern committed cron
# data directly onto ``main``. When the local ``main`` lagged ``origin/main``
# the push was rejected non-fast-forward and the agents entered a compounding
# divergence loop, while the data never reached the branch the GH-hosted cron
# actually overlays from.
#
# Background 2 (C13 revival, 2026-07-06): the follow-up design routed the
# publish through a throwaway ``git worktree`` of the PRIMARY dev clone.
# Worktrees share the primary clone's client-side hooks, so every publish
# ran the full pre-push guard suite — written for code pushes — against a
# data-branch checkout: one hook even rewrites files mid-push (the pytest-
# provenance manifest scanner), which aborts the push. Every data publish
# failed silently from 2026-06-12 onward and the audit branch froze. A
# dedicated clone has NO client-side hooks (hooks are per-clone opt-in via
# ``pre-commit install``; this clone deliberately never opts in), which is
# exactly the posture of the GH-hosted CI checkout that pushes the same
# branch. This is not a hook bypass (repo policy forbids ``--no-verify``,
# and none is used) — the guard suite still gates every code push from the
# dev clone.
#
# Usage (from a driver, after ``set -euo pipefail`` and ``cd "${REPO}"``):
#     source "$(dirname "$0")/lib_c13_data_push.sh"
#     push_to_data_branch "<commit-subject>" "<status-marker-path>" \
#         "cache/wsh/${DATE}.jsonl" "cache/wsh/${DATE}.summary.json"
#
# Contract:
#   * File args are repo-relative paths that already exist in the primary tree.
#   * Writes a timestamped status marker on EVERY exit path so a degraded run
#     is detectable (``ok:pushed:*`` / ``ok:no-change:*`` / ``degraded:*``).
#   * Returns 0 for success / no-change / soft push failure (retried next run);
#     returns non-zero only for a hard precondition failure (no files, clone/
#     fetch failed) so ``set -e`` surfaces it to the LaunchAgent exit status.
#
# Repo policy: never ``--force``, never ``--no-verify``.

C13_DATA_BRANCH="${C13_DATA_BRANCH:-data/phase-a-audit}"

# Persistent publishing clone. Kept outside the repo tree; override in tests.
# ``--filter=blob:none`` keeps history cheap — blobs are fetched lazily for
# the single checkout, then updates are incremental.
C13_DATA_CLONE_DIR="${C13_DATA_CLONE_DIR:-${HOME}/.cache/skippalgo/c13-data-clone}"

_c13_ensure_data_clone() {
    # Ensures a usable publishing clone exists at ${C13_DATA_CLONE_DIR} and
    # is synced to origin/${C13_DATA_BRANCH}. Self-heals a corrupted clone by
    # wiping and re-cloning ONCE. Prints an error and returns 1 on failure.
    local origin_url="$1"
    local clone="${C13_DATA_CLONE_DIR}"
    local attempt

    for attempt in 1 2; do
        if ! git -C "${clone}" rev-parse --git-dir >/dev/null 2>&1; then
            rm -rf "${clone}"
            mkdir -p "$(dirname "${clone}")"
            if ! git clone --quiet --filter=blob:none --single-branch \
                    --branch "${C13_DATA_BRANCH}" "${origin_url}" "${clone}" 2>/dev/null; then
                echo "push_to_data_branch: DEGRADED — clone of ${C13_DATA_BRANCH} from origin failed." >&2
                echo "  Check: (1) network/VPN, (2) git remote auth, (3) the branch exists on origin." >&2
                return 1
            fi
        fi
        # Token/remote rotation on the primary repo must propagate.
        git -C "${clone}" remote set-url origin "${origin_url}" 2>/dev/null || true
        if git -C "${clone}" fetch origin "${C13_DATA_BRANCH}" --quiet 2>/dev/null \
            && git -C "${clone}" checkout -q -B "${C13_DATA_BRANCH}" \
                   "origin/${C13_DATA_BRANCH}" 2>/dev/null \
            && git -C "${clone}" clean -qfd 2>/dev/null; then
            return 0
        fi
        # First failure: assume clone corruption (interrupted fetch, partial
        # checkout) — wipe and let the loop re-clone from scratch.
        echo "push_to_data_branch: publishing clone unusable (attempt ${attempt}); wiping ${clone} and re-cloning" >&2
        rm -rf "${clone}"
    done
    echo "push_to_data_branch: DEGRADED — could not sync the publishing clone to origin/${C13_DATA_BRANCH}." >&2
    return 1
}

push_to_data_branch() {
    local subject="$1"; shift
    local marker="$1"; shift
    local files=("$@")
    local ts; ts="$(date -u +%FT%TZ)"

    if [[ ${#files[@]} -eq 0 ]]; then
        echo "push_to_data_branch: no artefact paths supplied" >&2
        # R4: marker dir pre-created below; write is loud on failure.
        mkdir -p "$(dirname "${marker}")" 2>/dev/null || true
        printf 'degraded:no-files:%s\n' "${ts}" > "${marker}" || true
        return 1
    fi

    # R4: pre-create the marker directory so write failures surface on stderr
    # rather than silently no-oping when the dir does not exist yet.
    mkdir -p "$(dirname "${marker}")" 2>/dev/null || true

    local origin_url
    if ! origin_url="$(git remote get-url origin 2>/dev/null)"; then
        echo "push_to_data_branch: DEGRADED — cannot resolve 'origin' remote URL from the primary repo." >&2
        printf 'degraded:no-origin:%s\n' "${ts}" > "${marker}" || true
        return 1
    fi

    if ! _c13_ensure_data_clone "${origin_url}"; then
        printf 'degraded:fetch-failed:%s\n' "${ts}" > "${marker}" || true
        return 1
    fi
    local clone="${C13_DATA_CLONE_DIR}"

    # R6 (2026-07-07): the stage/commit window must degrade WITH a marker.
    # These were bare statements before — a cp/add/commit failure (disk full,
    # index.lock, clone corrupted between sync and stage) aborted via the
    # caller's ``set -e`` without writing any marker, so dashboards read
    # "never ran" instead of "degraded" and the cause vanished into launchd
    # stderr. Every failure here now writes degraded:stage-failed /
    # degraded:commit-failed before returning non-zero.
    local f
    for f in "${files[@]}"; do
        if [[ ! -f "${f}" ]]; then
            echo "push_to_data_branch: expected artefact '${f}' missing; skipping" >&2
            continue
        fi
        if ! mkdir -p "${clone}/$(dirname "${f}")" \
            || ! cp -f "${f}" "${clone}/${f}" \
            || ! git -C "${clone}" add -f "${f}"; then
            echo "push_to_data_branch: staging '${f}' into the publishing clone FAILED" >&2
            printf 'degraded:stage-failed:%s\n' "${ts}" > "${marker}" || true
            return 1
        fi
    done

    if git -C "${clone}" diff --staged --quiet; then
        echo "push_to_data_branch: no staged changes; nothing to publish"
        printf 'ok:no-change:%s\n' "${ts}" > "${marker}" || true
        return 0
    fi

    if ! git -C "${clone}" \
        -c user.name="skippalgo-c13-cron" \
        -c user.email="c13-cron@users.noreply.github.com" \
        commit -q -m "${subject}" \
               -m "Generated by a skippALGO C13 launchd cron agent (data-branch publishing clone)."; then
        echo "push_to_data_branch: commit in the publishing clone FAILED" >&2
        printf 'degraded:commit-failed:%s\n' "${ts}" > "${marker}" || true
        return 1
    fi

    # R5: capture push stderr so the degraded message names the actual cause
    # (auth, non-FF, network) rather than swallowing it.
    local push_err
    if push_err=$(git -C "${clone}" push origin "HEAD:refs/heads/${C13_DATA_BRANCH}" 2>&1); then
        printf 'ok:pushed:%s:%s\n' "${ts}" "${files[0]}" > "${marker}" || true
        return 0
    fi

    # One retry on non-fast-forward: another C13 agent may have pushed to the
    # same data branch in the interim. Re-fetch, replay our single commit, push.
    echo "push_to_data_branch: push rejected (${push_err}); re-fetching ${C13_DATA_BRANCH} and retrying once" >&2
    local retry_err
    if git -C "${clone}" fetch origin "${C13_DATA_BRANCH}" 2>/dev/null \
        && git -C "${clone}" rebase "origin/${C13_DATA_BRANCH}" 2>/dev/null \
        && retry_err=$(git -C "${clone}" push origin "HEAD:refs/heads/${C13_DATA_BRANCH}" 2>&1); then
        printf 'ok:pushed-retry:%s:%s\n' "${ts}" "${files[0]}" > "${marker}" || true
        return 0
    fi
    git -C "${clone}" rebase --abort 2>/dev/null || true

    # Soft failure: do not abort the agent. The artefact is safe in the primary
    # tree; the next run republishes it. A human-visible marker records the gap.
    echo "push_to_data_branch: push to ${C13_DATA_BRANCH} failed (non-fatal; cause: ${retry_err:-${push_err}}); next run will retry" >&2
    printf 'degraded:push-failed:%s\n' "${ts}" > "${marker}" || true
    return 0
}
