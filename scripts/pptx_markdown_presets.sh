#!/usr/bin/env bash

set -euo pipefail

usage() {
  cat <<'EOF'
Convert PPTX to Markdown with opinionated presets.

Usage:
  scripts/pptx_markdown_presets.sh <preset> <input.pptx> [output-file] [image-dir] [--dry-run]
  scripts/pptx_markdown_presets.sh preset=<preset> input=<input.pptx> [output=<output-file>] [images=<image-dir>] [dry_run=true]

Presets:
  clean    Public/shareable markdown (no presenter notes)
  full     Rich markdown (includes presenter notes)
  qmd      Quarto presentation markdown
  text     Text-only markdown (no images, no notes)

Aliases (agent-friendly):
  clean: clean, public, oeffentlich
  full:  full, voll
  qmd:   qmd, quarto
  text:  text, text-only, textonly

Examples:
  scripts/pptx_markdown_presets.sh clean slides/deck.pptx
  scripts/pptx_markdown_presets.sh full slides/deck.pptx out/deck.md assets/deck_images
  scripts/pptx_markdown_presets.sh qmd slides/deck.pptx out/deck.qmd --dry-run
  scripts/pptx_markdown_presets.sh preset=clean input=slides/deck.pptx dry_run=true
EOF
}

agent_spec() {
  cat <<'EOF'
AGENT SPEC (deterministic):
- Required: preset, input
- Optional: output, images, dry_run
- Format: key=value tokens, whitespace-separated

Allowed keys:
- preset  (clean|full|qmd|text and aliases)
- input   (*.pptx path)
- output  (target markdown file)
- images  (image directory)
- dry_run (true|false)

Example:
scripts/pptx_markdown_presets.sh preset=clean input=slides/deck.pptx output=out/deck.md images=out/deck_images dry_run=true
EOF
}

normalize_preset() {
  case "$1" in
    clean|public|oeffentlich)
      echo "clean"
      ;;
    full|voll)
      echo "full"
      ;;
    qmd|quarto)
      echo "qmd"
      ;;
    text|text-only|textonly)
      echo "text"
      ;;
    *)
      echo "$1"
      ;;
  esac
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" || "${1:-}" == "help" ]]; then
  usage
  exit 0
fi

if [[ "${1:-}" == "--agent-spec" ]]; then
  agent_spec
  exit 0
fi

if [[ $# -lt 2 ]]; then
  usage
  exit 2
fi

PRESET=""
INPUT_PPTX=""
OUTPUT_FILE=""
IMAGE_DIR=""
DRY_RUN="false"

# Agent-safe key=value mode.
for arg in "$@"; do
  case "$arg" in
    preset=*)
      PRESET="${arg#preset=}"
      ;;
    input=*)
      INPUT_PPTX="${arg#input=}"
      ;;
    output=*)
      OUTPUT_FILE="${arg#output=}"
      ;;
    images=*)
      IMAGE_DIR="${arg#images=}"
      ;;
    dry_run=true|dry_run=1)
      DRY_RUN="true"
      ;;
    dry_run=false|dry_run=0)
      DRY_RUN="false"
      ;;
  esac
done

# Positional fallback mode for humans.
if [[ -z "$PRESET" || -z "$INPUT_PPTX" ]]; then
  PRESET="${PRESET:-${1:-}}"
  INPUT_PPTX="${INPUT_PPTX:-${2:-}}"
  OUTPUT_FILE="${OUTPUT_FILE:-${3:-}}"
  IMAGE_DIR="${IMAGE_DIR:-${4:-}}"
fi

for arg in "$@"; do
  if [[ "$arg" == "--dry-run" ]]; then
    DRY_RUN="true"
  fi
done

PRESET="$(normalize_preset "$PRESET")"

if [[ -z "$PRESET" || -z "$INPUT_PPTX" ]]; then
  usage
  exit 2
fi

if [[ ! -f "$INPUT_PPTX" ]]; then
  echo "Input file not found: $INPUT_PPTX" >&2
  exit 1
fi

if [[ -z "$OUTPUT_FILE" ]]; then
  base="${INPUT_PPTX##*/}"
  base="${base%.*}"
  if [[ "$PRESET" == "qmd" ]]; then
    OUTPUT_FILE="${base}.qmd"
  else
    OUTPUT_FILE="${base}.md"
  fi
fi

if [[ -z "$IMAGE_DIR" ]]; then
  stem="${OUTPUT_FILE%.*}"
  IMAGE_DIR="${stem}_images"
fi

if [[ -x ".venv/bin/pptx2md" ]]; then
  PPTX2MD_BIN=".venv/bin/pptx2md"
elif command -v pptx2md >/dev/null 2>&1; then
  PPTX2MD_BIN="pptx2md"
else
  echo "pptx2md not found. Install it in .venv or PATH." >&2
  exit 1
fi

COMMON_ARGS=(
  "$INPUT_PPTX"
  "--enable-slides"
  "--try-multi-column"
  "-o" "$OUTPUT_FILE"
  "-i" "$IMAGE_DIR"
)

case "$PRESET" in
  clean)
    PRESET_ARGS=("--disable-notes")
    ;;
  full)
    PRESET_ARGS=()
    ;;
  qmd)
    PRESET_ARGS=("--qmd" "--disable-notes")
    ;;
  text)
    PRESET_ARGS=("--disable-notes" "--disable-image")
    ;;
  *)
    echo "Unknown preset: $PRESET" >&2
    echo "Expected one of: clean, full, qmd, text" >&2
    exit 2
    ;;
esac

cmd=("$PPTX2MD_BIN" "${COMMON_ARGS[@]}" "${PRESET_ARGS[@]}")

echo "Preset:      $PRESET"
echo "Input:       $INPUT_PPTX"
echo "Output:      $OUTPUT_FILE"
echo "Image dir:   $IMAGE_DIR"
echo "Converter:   $PPTX2MD_BIN"

if [[ "$DRY_RUN" == "true" ]]; then
  printf 'Dry-run command: '
  printf '%q ' "${cmd[@]}"
  printf '\n'
  exit 0
fi

"${cmd[@]}"
echo "Done."
