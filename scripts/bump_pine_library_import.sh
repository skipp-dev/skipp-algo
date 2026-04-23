#!/usr/bin/env bash
# bump_pine_library_import.sh — Bump a Pine library import version across consumer files.
#
# Usage:
#   ./scripts/bump_pine_library_import.sh <from_version> <to_version> [library_path]
#
# Examples:
#   # Default library (preuss_steffen/smc_micro_profiles_generated): bump /1 -> /2
#   ./scripts/bump_pine_library_import.sh 1 2
#
#   # Different library
#   ./scripts/bump_pine_library_import.sh 3 4 preuss_steffen/some_other_lib
#
# Behavior:
#   - Rewrites `import <library_path>/<from>` to `import <library_path>/<to>`
#     across tracked *.pine files at the repo root.
#   - Excludes generator-owned trees: pine/generated/ and tests/fixtures/generated_seed/.
#     Those mirrors are re-emitted by scripts/generate_smc_micro_profiles.py and must
#     not be hand-edited.
#   - Prints a summary of changed files and the new import lines for review.
#   - Idempotent: running twice with the same args leaves the working tree clean
#     on the second run.
#
# Exit codes:
#   0  Success (one or more files updated, OR no matching imports found — both fine)
#   2  Bad arguments
#   3  Run from outside a git repo / no .pine files tracked
#
# Context: PR #51 + Issue #59 — TradingView library republish bumps the published
# version; consumer .pine files must follow once the new version is live on TV.

set -euo pipefail

usage() {
  sed -n '2,30p' "$0" | sed 's|^# \{0,1\}||'
  exit 2
}

if [[ $# -lt 2 || $# -gt 3 ]]; then
  usage
fi

FROM="$1"
TO="$2"
LIB="${3:-preuss_steffen/smc_micro_profiles_generated}"

if ! [[ "$FROM" =~ ^[0-9]+$ ]] || ! [[ "$TO" =~ ^[0-9]+$ ]]; then
  echo "error: <from_version> and <to_version> must be integers" >&2
  exit 2
fi

if [[ "$FROM" == "$TO" ]]; then
  echo "error: from and to versions are identical (${FROM})" >&2
  exit 2
fi

# Anchor to repo root so the script works from any cwd.
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [[ -z "$REPO_ROOT" ]]; then
  echo "error: not inside a git repository" >&2
  exit 3
fi
cd "$REPO_ROOT"

# Collect candidate consumer files (tracked .pine files, excluding generator-owned trees).
# Use a while-read loop instead of `mapfile` for portability with macOS bash 3.2.
CANDIDATES=()
while IFS= read -r line; do
  CANDIDATES+=("$line")
done < <(
  git ls-files '*.pine' \
    | grep -v '^pine/generated/' \
    | grep -v '^tests/fixtures/generated_seed/' \
    || true
)

if [[ ${#CANDIDATES[@]} -eq 0 ]]; then
  echo "error: no tracked *.pine files found outside generator-owned trees" >&2
  exit 3
fi

OLD_PATTERN="${LIB}/${FROM}"
NEW_PATTERN="${LIB}/${TO}"

# Detect sed in-place flavor (BSD/macOS needs '' after -i, GNU does not).
sed_inplace() {
  if sed --version >/dev/null 2>&1; then
    sed -i "$@"
  else
    sed -i '' "$@"
  fi
}

CHANGED=()
for f in "${CANDIDATES[@]}"; do
  if grep -q -F "$OLD_PATTERN" "$f"; then
    sed_inplace "s|${OLD_PATTERN}|${NEW_PATTERN}|g" "$f"
    CHANGED+=("$f")
  fi
done

echo "Library:       ${LIB}"
echo "Version bump:  /${FROM} -> /${TO}"
echo "Scanned:       ${#CANDIDATES[@]} consumer .pine files"
echo "Updated:       ${#CHANGED[@]} files"

if [[ ${#CHANGED[@]} -eq 0 ]]; then
  echo "No matching imports found — nothing to do."
  exit 0
fi

echo
echo "Changed files:"
printf '  %s\n' "${CHANGED[@]}"

echo
echo "New import lines:"
grep -nH -F "import ${NEW_PATTERN}" "${CHANGED[@]}" || true

echo
echo "Next steps:"
echo "  git diff --stat"
echo "  git diff -U0 -- '*.pine' | grep -E '^[-+]import'   # sanity: only import lines changed"
echo "  git add -u && git commit -m 'chore(pine): bump ${LIB} import /${FROM} -> /${TO}'"
