"""Discipline pin: production hot paths must not use ``st_mtime`` for "newest"
artifact resolution (H-3, system review 2026-04-24).

Why
---
``Path.stat().st_mtime`` is fragile for "pick the newest artifact" — see
the docstring of :mod:`scripts.smc_artifact_resolver` for the failure
modes (rsync preserving mtime, equal-second ties, clock skew, parallel
runners). Production paths must instead use the deterministic
filename-ISO resolver.

Discipline
----------
This pin walks every ``.py`` under ``scripts/`` and rejects any
reference to ``st_mtime`` or ``os.path.getmtime`` unless:

  1. The file appears in :data:`_FILE_LEVEL_EXEMPT` (intentional mtime
     tooling such as the ``plan_2_8_digest_*`` family that explicitly
     measures file-system timestamps), OR
  2. The reference carries an inline marker
     ``# MTIME-RESOLVER-EXEMPT: <reason>`` within the 6 lines before
     the call site.
"""
from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS_DIR = _REPO_ROOT / "scripts"

_EXEMPT_MARKER = "MTIME-RESOLVER-EXEMPT:"
_PROXIMITY_LINES = 6

# Files whose ``st_mtime`` use is intentional (digest helpers, age
# reports, staleness probes). Each entry's value is a brief rationale.
_FILE_LEVEL_EXEMPT: dict[str, str] = {
    "smc_artifact_resolver.py": "Helper module that defines the deterministic resolver.",
    "measure_databento_ops_run.py": "Uses st_mtime only for ISO-string formatting in _safe_iso_from_file (display).",
    "tv_publish_evidence_summary.py": "Uses st_mtime only in _is_stale (age check, not freshness ordering).",
    "smc_micro_streamlit_app.py": "Composite key (trade_date_ordinal, st_mtime, name) — st_mtime is the secondary tiebreaker only.",
}

_MTIME_TOKEN_RE = re.compile(r"\b(st_mtime|getmtime)\b")


def _has_marker(source_lines: list[str], lineno: int) -> bool:
    start = max(0, lineno - 1 - _PROXIMITY_LINES)
    end = min(len(source_lines), lineno)
    for line in source_lines[start:end]:
        if _EXEMPT_MARKER in line:
            return True
    return False


def _iter_violations(path: Path) -> list[str]:
    rel = path.relative_to(_REPO_ROOT)
    if path.name in _FILE_LEVEL_EXEMPT:
        return []
    if path.name.startswith("plan_2_8_digest_"):
        # plan_2_8_digest_* helpers are intentional mtime tooling.
        return []
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    source_lines = source.splitlines()
    violations: list[str] = []
    for idx, line in enumerate(source_lines, start=1):
        # Strip "# ..." comments before scanning so the marker line itself
        # doesn't trigger.
        scanned = line.split("#", 1)[0]
        if _MTIME_TOKEN_RE.search(scanned):
            if _has_marker(source_lines, idx):
                continue
            violations.append(
                f"{rel}:{idx}: st_mtime/getmtime — use scripts.smc_artifact_resolver "
                "or add `# MTIME-RESOLVER-EXEMPT: <reason>` marker"
            )
    return violations


def test_no_mtime_pick_in_production_scripts() -> None:
    violations: list[str] = []
    for path in sorted(_SCRIPTS_DIR.rglob("*.py")):
        violations.extend(_iter_violations(path))
    assert not violations, (
        "Direct st_mtime / getmtime use detected in scripts/. Migrate to "
        "scripts.smc_artifact_resolver helpers or annotate each site with "
        "`# MTIME-RESOLVER-EXEMPT: <reason>`:\n  - "
        + "\n  - ".join(violations)
    )
