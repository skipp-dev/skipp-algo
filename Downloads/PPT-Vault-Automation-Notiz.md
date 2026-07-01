# PPT-Vault Automation Notes

Updated: 2026-07-01

## Target Behavior

As soon as a new `.pptx` lands in `~/Downloads/PPT-Vault`, the system should automatically:

1. choose the best available file for presentation (`_best.md` > `_extracted.md` > `.md` > `.pptx`),
2. open it in the workbench (VS Code Insiders + Typora + Obsidian).

## What Was Set Up

### 1) PPTX -> Markdown Toolchain

The following scripts were created/configured in `~/Downloads`:

- `pptx_md_from_worktree.sh`
  - uses the known worktree environment for extraction.
- `pptx_md_extract_and_best.sh`
  - automatically generates:
    - `<name>_extracted.md`
    - `<name>_best.md`
- `pptx_md_batch.sh`
  - batch processing for full folders (`--pattern`, `--limit`, `--dry-run`, optional recursive mode).

### 1b) Markdown/Quarto -> PPTX (user-friendly)

- `md_to_pptx_easy.sh`
  - one-command export from `.md`/`.qmd` to `.pptx`.
  - `.md` uses the Marp pipeline.
  - `.qmd` uses Quarto render.
  - default output mode is `editable` PPTX.
  - optional auto-open in VS Code Insiders.

Examples:

```bash
cd ~/Downloads
./md_to_pptx_easy.sh "Q-DAY.md"
PPTX_OPEN=false ./md_to_pptx_easy.sh "Q-DAY.md" "~/Downloads"
PPTX_EDITABLE=false ./md_to_pptx_easy.sh "slides.md"
```

### 2) Open/Read/Edit

Created scripts:

- `open-markdown-workbench.sh`
  - opens the target in VS Code + Typora + Obsidian.
  - supports `VS_CODE_FLAVOR=insiders|stable|auto`.
- `open-pptx-smart.sh`
  - automatically chooses the best target file per PPTX:
    1. `<base>_best.md`
    2. `<base>_extracted.md`
    3. `<base>.md`
    4. `<base>.pptx`

### 2b) VS Code Insiders Right-Click Shortcuts

A local Insiders extension was added:

- path: `~/.vscode-insiders/extensions/spreuss.pptx-tools-0.0.1`

Explorer context menu (right-click on file):

- `to_md`
  - visible for `.pptx/.ppt`
  - calls `~/Downloads/pptx_md_extract_and_best.sh`
- `to_qmd`
  - visible for `.pptx/.ppt`
  - calls `pptx2md` in qmd mode and creates `<base>.qmd`
- `to_pptx`
  - visible for `.md/.qmd`
  - calls `~/Downloads/md_to_pptx_easy.sh`
- `open_smart`
  - visible for `.pptx/.ppt/.md/.qmd`
  - calls `VS_CODE_FLAVOR=insiders ~/Downloads/open-pptx-smart.sh`

Notes:

- After local extension updates in Insiders, run once:
  - `Developer: Reload Window`
- If menu entries are missing:
  1. verify `spreuss.pptx-tools` is enabled in Insiders,
  2. restart Insiders,
  3. verify file extension is supported (`.pptx`, `.md`, `.qmd`).

### 2c) Auto-Watch Directly in VS Code Insiders

The local extension `spreuss.pptx-tools` now also contains an auto-watcher:

- starts when Insiders starts (`onStartupFinished`),
- watches by default: `/Users/spreuss/Downloads/PPT-Vault`,
- automatically triggers `open_smart` when a `.pptx` is new/updated.

Visible feedback in Insiders:

- on startup: info message `PPTX watcher active on ...`
- on trigger: short status message `PPTX watcher: opening ...`
- additional logs in output channel `PPTX Tools`

Configurable in VS Code settings:

- `pptxTools.autoWatch.enabled` (default: `true`)
- `pptxTools.autoWatch.folder` (default: `/Users/spreuss/Downloads/PPT-Vault`)
- `pptxTools.autoWatch.debounceMs` (default: `3000`)

Important:

- after extension changes: `Developer: Reload Window`.

### 3) VS Code Workspace Setup

Under `~/Downloads/.vscode`:

- `settings.json` with Markdown-friendly defaults.
- `extensions.json` with recommendations.

Installed extensions (stable VS Code):

- `yzhang.markdown-all-in-one`
- `davidanson.vscode-markdownlint`
- `shd101wyy.markdown-preview-enhanced`
- `marp-team.marp-vscode`
- `quarto.quarto`

### 4) Typora & Obsidian

Installed via Homebrew:

- Typora
- Obsidian

## PPT-Vault Automation

### Worker Script

- `~/Downloads/ppt-vault-auto-open.sh`

Behavior:

- scans `~/Downloads/PPT-Vault` for `.pptx`.
- tracks already processed files in:
  - `~/Downloads/.ppt-vault-auto-open.state`
- writes runtime logs to:
  - `~/Downloads/ppt-vault-auto-open.log`
- for new files, calls:
  - `VS_CODE_FLAVOR=insiders ~/Downloads/open-pptx-smart.sh <file>`

### Debounce / Stability Check

Enabled in worker:

- `PPT_DEBOUNCE_SECONDS` (default: `3`)
- `PPT_STABILITY_CHECKS` (default: `3`)
- `PPT_STABILITY_INTERVAL` (default: `1`)

Flow:

1. wait `DEBOUNCE_SECONDS` after detecting a new file,
2. check multiple times that `mtime|size` stays stable,
3. only then open the file.

### Auto Cleanup for Test Files

Enabled in worker:

- `PPT_AUTOCLEAN_DAYS` (default: `7`)

Behavior:

- removes `AUTO_TEST_*.pptx` in `PPT-Vault` if older than `PPT_AUTOCLEAN_DAYS`.
- additionally removes old test artifacts:
  - `AUTO_TEST_*_extracted.md`
  - `AUTO_TEST_*_best.md`
- example: `PPT_AUTOCLEAN_DAYS=14` keeps test files for 14 days.
- with `PPT_AUTOCLEAN_DAYS=-1`, cleanup is disabled.

### LaunchAgent (macOS launchd)

Installed/active:

- `~/Library/LaunchAgents/com.spreuss.pptvault.autoopen.plist`

Configuration:

- `RunAtLoad = true`
- `WatchPaths = /Users/spreuss/Downloads/PPT-Vault`
- starts `~/Downloads/ppt-vault-auto-open.sh`
- launchd logs:
  - `~/Downloads/ppt-vault-auto-open.launchd.out.log`
  - `~/Downloads/ppt-vault-auto-open.launchd.err.log`

## Important Notes

- On first run, existing PPTX files are only marked as "seen" (no mass-open of old files).
- Only new/updated files are processed.
- Correct file extension is `.pptx` (not `.ppts`).

## Commands (Quick Reference)

### Smart Open (single file)

```bash
cd ~/Downloads
VS_CODE_FLAVOR=insiders ./open-pptx-smart.sh "Q-DAY.pptx"
```

### Generate Extracted + Best (single file)

```bash
cd ~/Downloads
./pptx_md_extract_and_best.sh "Q-DAY.pptx" "~/Downloads"
```

### Markdown/Quarto -> PPTX (single file)

```bash
cd ~/Downloads
./md_to_pptx_easy.sh "Q-DAY.md"
./md_to_pptx_easy.sh "Q-DAY.qmd"
```

### Batch

```bash
cd ~/Downloads
./pptx_md_batch.sh --dry-run
./pptx_md_batch.sh -d ~/Downloads -p "Q-*.pptx" --limit 5
```

### Open Workbench

```bash
cd ~/Downloads
VS_CODE_FLAVOR=insiders ./open-markdown-workbench.sh "Q-DAY_best.md"
```

### Quick test for Insiders context menu

1. In Insiders Explorer, select a file with a supported extension.
2. Right-click:
  - `.pptx` -> `to_md` / `to_qmd` / `open_smart`
  - `.md/.qmd` -> `to_pptx` / `open_smart`
3. If entries are missing: run `Developer: Reload Window`.

### Reload LaunchAgent

```bash
UID_NOW="$(id -u)"
PLIST="$HOME/Library/LaunchAgents/com.spreuss.pptvault.autoopen.plist"
launchctl bootout "gui/${UID_NOW}" "$PLIST" >/dev/null 2>&1 || true
launchctl bootstrap "gui/${UID_NOW}" "$PLIST"
launchctl enable "gui/${UID_NOW}/com.spreuss.pptvault.autoopen"
launchctl kickstart -k "gui/${UID_NOW}/com.spreuss.pptvault.autoopen"
```

### Stop LaunchAgent

```bash
UID_NOW="$(id -u)"
launchctl disable "gui/${UID_NOW}/com.spreuss.pptvault.autoopen"
launchctl bootout "gui/${UID_NOW}" "$HOME/Library/LaunchAgents/com.spreuss.pptvault.autoopen.plist"
```

## Validation (already completed)

- `AUTO_TEST_Q-DAY.pptx` in `PPT-Vault` was detected and opened.
- `AUTO_TEST_Q-DAY_2.pptx` was detected with debounce:
  - `WAIT: debounce ...`
  - `STABLE: ...`
  - then `OPENED: ...`
- `AUTO_TEST_OLD.pptx` (artificially aged) was removed automatically:
  - `CLEANUP: removed 1 AUTO_TEST_*.pptx file(s) older than 7 day(s).`
- `AUTO_TEST_OLD2` test set (pptx + extracted + best) was removed automatically:
  - `CLEANUP: removed 1 AUTO_TEST_*.pptx and 2 AUTO_TEST_*_{extracted,best}.md file(s) older than 7 day(s).`

## Troubleshooting

- If nothing opens:
  1. check whether the agent is active (`launchctl print ...com.spreuss.pptvault.autoopen`).
  2. check logs (`ppt-vault-auto-open.log` + launchd out/err).
  3. verify executability of:
     - `~/Downloads/open-pptx-smart.sh`
     - `~/Downloads/open-markdown-workbench.sh`
     - `~/Downloads/ppt-vault-auto-open.sh`

Known macOS behavior:

- `launchd` can fail on folders like `Downloads` because of TCC/FDA restrictions (`Operation not permitted`).
- therefore the Insiders auto-watch (2c) is the more robust default while Insiders is running.
- if only stable VS Code opens instead of Insiders:
  - set `VS_CODE_FLAVOR=insiders` (already hardwired in worker script).
