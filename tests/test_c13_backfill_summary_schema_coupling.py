"""The F-V3-15 progress assertion must survive writer schema drift.

2026-08-15 sweep finding (Population C, quiet defaults): the c13 cron's
progress step read all six backfill counters with ``jq … // 0``. Every
counter is UNCONDITIONALLY emitted by the writer
(``scripts/backfill_live_outcomes.backfill_live_outcomes``, summary dict) —
so a missing key only ever means schema drift, and with ``// 0`` a rename
pulled every counter to zero: ``closable=0``, ``rc=0`` forever, and the
exact silent-skip class the assertion was built to catch (F-V3-15) reopened,
green. The existing advisory-chain test STUBS jq (pattern-matching the
filter string), so writer drift was invisible to it.

This file closes the loop by EXECUTION on both sides: the real writer
produces a real summary, and the REAL jq binary runs the workflow's actual
filter strings (extracted from the YAML, not copied) against it. A key the
writer stops emitting turns the filter into a loud error — proven here by
deleting keys one at a time.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "c13-daily-cron.yml"

jq = shutil.which("jq")
pytestmark = pytest.mark.skipif(jq is None, reason="jq binary not available")


def _workflow_filters() -> list[str]:
    """The six jq filter strings, read from the workflow — not re-typed."""
    text = WORKFLOW.read_text(encoding="utf-8")
    filters = re.findall(r"jq -r '(\.backfill\.records_\w+ [^']*)'", text)
    assert len(filters) == 6, (
        f"expected the six counter filters in the progress step, found "
        f"{len(filters)}: {filters} — if the step changed shape, update this "
        "extraction WITH it, do not let the coupling go vacuous"
    )
    return filters


def _real_summary(tmp_path: Path) -> dict:
    """A summary produced by the actual writer, not a hand-typed copy."""
    import sys

    sys.path.insert(0, str(REPO_ROOT))
    from scripts.backfill_live_outcomes import backfill_live_outcomes

    ledger = tmp_path / "live_outcomes.jsonl"
    ledger.write_text("", encoding="utf-8")
    return backfill_live_outcomes(ledger)


def _run_jq(filter_string: str, payload: dict) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [jq, "-r", filter_string],
        input=json.dumps({"backfill": payload}),
        capture_output=True,
        text=True,
    )


def test_every_workflow_filter_reads_the_real_writers_summary(tmp_path: Path) -> None:
    summary = _real_summary(tmp_path)
    for filter_string in _workflow_filters():
        done = _run_jq(filter_string, summary)
        assert done.returncode == 0, (
            f"{filter_string!r} errors against the REAL writer summary "
            f"{summary} — writer and workflow have drifted apart: {done.stderr}"
        )
        assert done.stdout.strip().isdigit(), done.stdout


def test_a_renamed_counter_fails_the_filter_loudly(tmp_path: Path) -> None:
    """Deleting each key in turn must turn its filter into an error — with
    `// 0` every one of these read as a quiet zero instead."""
    summary = _real_summary(tmp_path)
    for filter_string in _workflow_filters():
        key = re.match(r"\.backfill\.(records_\w+)", filter_string).group(1)
        drifted = {k: v for k, v in summary.items() if k != key}
        done = _run_jq(filter_string, drifted)
        assert done.returncode != 0, (
            f"{filter_string!r} still answers on a summary missing {key} — "
            "schema drift reads as zero progress and the F-V3-15 assertion "
            "goes vacuous"
        )
        assert "schema drift" in done.stderr
