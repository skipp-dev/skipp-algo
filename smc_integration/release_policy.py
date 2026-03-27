from __future__ import annotations

import os
import subprocess
from typing import Iterable

# Operational release baseline used by pre-release refresh and strict release gates.
RELEASE_REFERENCE_SYMBOLS: tuple[str, ...] = ("USAR", "TMQ")
RELEASE_REFERENCE_TIMEFRAMES: tuple[str, ...] = ("5m", "15m")

# Reuse existing integration stale baseline (90 days) from composite meta handling
# so release freshness policy remains consistent with repository-wide staleness rules.
RELEASE_STALE_AFTER_SECONDS: int = 90 * 24 * 60 * 60

# Small operational evidence policy used for GELB->GRUEN release decisions.
EVIDENCE_LOOKBACK_DAYS: int = 14
EVIDENCE_MIN_DEEPER_OK_RUNS: int = 3
EVIDENCE_MIN_RELEASE_OK_RUNS: int = 2


def csv_from_values(values: Iterable[str]) -> str:
    items: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = str(raw).strip()
        if not value:
            continue
        if value in seen:
            continue
        seen.add(value)
        items.append(value)
    return ",".join(items)


def parse_csv(raw: str, *, normalize_upper: bool = False) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for token in str(raw).split(","):
        value = token.strip()
        if normalize_upper:
            value = value.upper()
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def resolve_git_commit() -> str | None:
    env_sha = str(os.environ.get("GITHUB_SHA", "")).strip()
    if env_sha:
        return env_sha
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    value = str(result.stdout).strip()
    return value or None


def runtime_metadata() -> dict[str, object]:
    return {
        "git_commit": resolve_git_commit(),
        "github_workflow": str(os.environ.get("GITHUB_WORKFLOW", "")).strip() or None,
        "github_run_id": str(os.environ.get("GITHUB_RUN_ID", "")).strip() or None,
        "github_run_number": str(os.environ.get("GITHUB_RUN_NUMBER", "")).strip() or None,
        "github_event_name": str(os.environ.get("GITHUB_EVENT_NAME", "")).strip() or None,
        "github_ref": str(os.environ.get("GITHUB_REF", "")).strip() or None,
        "github_ref_name": str(os.environ.get("GITHUB_REF_NAME", "")).strip() or None,
    }
