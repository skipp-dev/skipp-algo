# Shared helper for C13 launchd cron drivers.
#
# Publishes generated data artefacts to the dedicated ``data/phase-a-audit``
# branch via an ISOLATED git worktree, so the push never touches (or commits
# onto) whatever branch the primary working tree happens to have checked out
# when the LaunchAgent fires.
#
# Background (Lane 7 provider-boundary audit, 2026-06-10): the previous
# ``git commit + git push origin <current-branch>`` pattern committed cron
# data directly onto ``main``. When the local ``main`` lagged ``origin/main``
# the push was rejected non-fast-forward and the agents entered a compounding
# divergence loop, while the data never reached the branch the GH-hosted cron
# actually overlays from. Routing through a throwaway worktree keyed on
# ``origin/data/phase-a-audit`` removes both failure modes.
#
# Usage (from a driver, after ``set -euo pipefail`` and ``cd "${REPO}"``):
#     source "$(dirname "$0")/lib_c13_data_push.sh"
#     push_to_data_branch "<commit-subject>" "<status-marker-path>" \
#         "cache/wsh/${DATE}.jsonl" "cache/wsh/${DATE}.summary.json"
#
# Contract:
#   * Call ONCE, as the driver's final action (registers an EXIT-trap cleanup).
#   * File args are repo-relative paths that already exist in the primary tree.
#   * Writes a timestamped status marker on EVERY exit path so a degraded run
#     is detectable (``ok:pushed:*`` / ``ok:no-change:*`` / ``degraded:*``).
#   * Returns 0 for success / no-change / soft push failure (retried next run);
#     returns non-zero only for a hard precondition failure (no files, fetch
#     failed) so ``set -e`` surfaces it to the LaunchAgent exit status.
#
# Repo policy: never ``--force``, never ``--no-verify``.

C13_DATA_BRANCH="${C13_DATA_BRANCH:-data/phase-a-audit}"

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

    # R1: prune stale worktree registrations left by a previous SIGKILL /
    # power-loss BEFORE creating the new one. git rejects ``worktree add``
    # when the branch ref is already checked out in another (stale) worktree.
    git worktree prune --quiet 2>/dev/null || true

    local worktree_root worktree
    worktree_root="$(mktemp -d)"
    worktree="${worktree_root}/data-branch"

    # Expand the paths into the trap string NOW (while they are in scope).
    # A function-based trap referencing these ``local`` vars would fire at
    # script EXIT — after push_to_data_branch has returned and the locals are
    # gone — tripping ``set -u`` with 'worktree: unbound variable'. Embedding
    # the literal paths keeps cleanup correct and unbound-safe.
    trap "git worktree remove --force '${worktree}' 2>/dev/null || true; rm -rf '${worktree_root}' 2>/dev/null || true" EXIT

    # Fetch-first: fail LOUD if the data branch is missing or the network/auth
    # is down, rather than silently materialising a brand-new orphan branch.
    if ! git fetch origin "${C13_DATA_BRANCH}" --quiet 2>/dev/null; then
        echo "push_to_data_branch: DEGRADED — 'git fetch origin ${C13_DATA_BRANCH}' failed." >&2
        echo "  Check: (1) network/VPN, (2) git remote auth, (3) the branch exists on origin." >&2
        printf 'degraded:fetch-failed:%s\n' "${ts}" > "${marker}" || true
        return 1
    fi

    # R1: --detach avoids resetting the local branch ref, eliminating the
    # "branch already checked out in another worktree" contention class.
    # Push uses an explicit refspec (HEAD:refs/heads/…) so git does not
    # need a local branch ref in the worktree at all.
    if ! git worktree add --quiet --detach "${worktree}" "origin/${C13_DATA_BRANCH}"; then
        echo "push_to_data_branch: DEGRADED — git worktree add failed (stale lock? run: git worktree prune)" >&2
        printf 'degraded:worktree-add-failed:%s\n' "${ts}" > "${marker}" || true
        return 1
    fi

    local f
    for f in "${files[@]}"; do
        if [[ ! -f "${f}" ]]; then
            echo "push_to_data_branch: expected artefact '${f}' missing; skipping" >&2
            continue
        fi
        mkdir -p "${worktree}/$(dirname "${f}")"
        cp -f "${f}" "${worktree}/${f}"
        git -C "${worktree}" add -f "${f}"
    done

    if git -C "${worktree}" diff --staged --quiet; then
        echo "push_to_data_branch: no staged changes; nothing to publish"
        printf 'ok:no-change:%s\n' "${ts}" > "${marker}" || true
        return 0
    fi

    git -C "${worktree}" \
        -c user.name="skippalgo-c13-cron" \
        -c user.email="c13-cron@users.noreply.github.com" \
        commit -q -m "${subject}" \
               -m "Generated by a skippALGO C13 launchd cron agent (data-branch worktree)."

    # R5: capture push stderr so the degraded message names the actual cause
    # (auth, non-FF, network) rather than swallowing it.
    local push_err
    if push_err=$(git -C "${worktree}" push origin "HEAD:refs/heads/${C13_DATA_BRANCH}" 2>&1); then
        printf 'ok:pushed:%s:%s\n' "${ts}" "${files[0]}" > "${marker}" || true
        return 0
    fi

    # One retry on non-fast-forward: another C13 agent may have pushed to the
    # same data branch in the interim. Re-fetch, replay our single commit, push.
    echo "push_to_data_branch: push rejected (${push_err}); re-fetching ${C13_DATA_BRANCH} and retrying once" >&2
    local retry_err
    if git -C "${worktree}" fetch origin "${C13_DATA_BRANCH}" 2>/dev/null \
        && git -C "${worktree}" rebase "origin/${C13_DATA_BRANCH}" 2>/dev/null \
        && retry_err=$(git -C "${worktree}" push origin "HEAD:refs/heads/${C13_DATA_BRANCH}" 2>&1); then
        printf 'ok:pushed-retry:%s:%s\n' "${ts}" "${files[0]}" > "${marker}" || true
        return 0
    fi

    # Soft failure: do not abort the agent. The artefact is safe in the primary
    # tree; the next run republishes it. A human-visible marker records the gap.
    echo "push_to_data_branch: push to ${C13_DATA_BRANCH} failed (non-fatal; cause: ${retry_err:-${push_err}}); next run will retry" >&2
    printf 'degraded:push-failed:%s\n' "${ts}" > "${marker}" || true
    return 0
}
