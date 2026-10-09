"""Output-fixture pin for the public calibration report (Sprint C10 / DR-2026-04-27).

The companion ``test_public_schema_pin.py`` SHA-pins the *source* of
:func:`scripts.emit_public_calibration_report.build_public_report`. That
catches code drift but not *output* drift: a refactor that re-wires an
imported helper without mutating the function body would slip past the
AST pin while silently changing the on-the-wire JSON shape consumed by
the dashboard and the freeze-exit gate.

This test is the second defence line: it rebuilds the canonical sample
input with deterministic inputs and deepdiff-compares against the
frozen output fixture committed under
``docs/calibration/schemas/v1.3.0_sample_output.json``.

Drift remediation
-----------------
If this test fails:

1. Inspect the diff. If the new output shape is intentional and
   additive-only (per ``docs/schema_versioning.md``):
   - bump ``PUBLIC_SCHEMA_VERSION`` if needed
   - regenerate the fixture: see "Regenerating the fixture" below
   - update ``test_public_schema_pin.py`` (additive_fields_introduced)
2. If the change is breaking (field removed/renamed): MAJOR bump,
   ADR, CHANGELOG entry, fixture regeneration.

Regenerating the fixture
------------------------
``python -m scripts.regen_public_report_fixture`` is intentionally NOT
shipped — re-generating must be a deliberate human act. Use the
``_build_canonical_report`` helper in this module verbatim from a
REPL, redact ``generated_at`` to ``"__REDACTED_TIMESTAMP__"`` (it is
non-deterministic), and commit the result.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts.emit_public_calibration_report import (
    PUBLIC_SCHEMA_VERSION,
    build_public_report,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_PATH = (
    REPO_ROOT
    / "docs"
    / "calibration"
    / "schemas"
    / "v1.3.0_sample_output.json"
)

_REDACTED_TIMESTAMP = "__REDACTED_TIMESTAMP__"


def _build_canonical_report() -> dict[str, Any]:
    """Deterministic input set used to regenerate the fixture.

    Keep this stable. Any change here MUST be matched by a fresh
    fixture commit.
    """
    cal_payload = {
        "family_weights": {"BOS": 0.40, "OB": 0.35, "FVG": 0.25},
        "family_stats": {
            "BOS": {"total_events": 800, "total_hits": 480},
            "OB": {"total_events": 600, "total_hits": 320},
            "FVG": {"total_events": 400, "total_hits": 200},
        },
        "testable_calibration": {
            "n_events": 1800,
            "ece_binned_n10": 0.034,
            "smooth_ece": 0.029,
            "dce_upper_bound": 0.041,
            "brier": 0.224,
            "positive_rate": 0.555,
        },
    }
    track_record_gate = {
        "status": "green",
        "n_trades": 250,
        "checks": [
            {
                "name": "oos_trades",
                "status": "green",
                "value": 250.0,
                "threshold": 100.0,
            }
        ],
        "summary": {"sharpe_annualized": 1.42},
    }
    regime_stratified = {
        "regimes": {
            "TREND_UP": {"n_trades": 120, "sharpe_annualized": 1.55},
        },
        "aggregate_freq_weighted_sharpe": 1.39,
        "bh_fdr_rejected": 1,
    }
    families = [
        {
            "name": "BOS",
            "live_days": 120,
            "n_trades": 45,
            "kill_switch_fires": 0,
            "drift_verdict": "pass",
        },
        {
            "name": "OB",
            "live_days": 95,
            "n_trades": 38,
            "kill_switch_fires": 0,
            "drift_verdict": "acceptable",
        },
    ]
    report = build_public_report(
        cal_payload,
        source_path=None,
        source_commit_sha="deadbeefcafebabe",
        source_workflow_run="12345",
        track_record_gate=track_record_gate,
        regime_stratified=regime_stratified,
        families=families,
    )
    # generated_at is non-deterministic (datetime.now); redact so the
    # fixture stays stable across runs.
    report["generated_at"] = _REDACTED_TIMESTAMP
    return report


def _diff_lines(actual: Any, expected: Any, path: str = "") -> list[str]:
    """Lightweight deep-diff (no scipy/deepdiff dependency).

    Returns a list of one-line "<path>: actual != expected" strings.
    """
    out: list[str] = []
    if type(actual) is not type(expected):
        out.append(
            f"{path or '<root>'}: type mismatch "
            f"actual={type(actual).__name__} expected={type(expected).__name__}",
        )
        return out
    if isinstance(actual, dict):
        keys = set(actual) | set(expected)
        for k in sorted(keys):
            if k not in actual:
                out.append(f"{path}.{k}: missing in actual")
            elif k not in expected:
                out.append(f"{path}.{k}: unexpected key in actual")
            else:
                out.extend(_diff_lines(actual[k], expected[k], f"{path}.{k}"))
    elif isinstance(actual, list):
        if len(actual) != len(expected):
            out.append(
                f"{path}: list length actual={len(actual)} expected={len(expected)}",
            )
        for i, (a, e) in enumerate(zip(actual, expected, strict=False)):
            out.extend(_diff_lines(a, e, f"{path}[{i}]"))
    else:
        if actual != expected:
            out.append(f"{path}: actual={actual!r} expected={expected!r}")
    return out


def test_fixture_file_exists() -> None:
    assert FIXTURE_PATH.is_file(), f"missing fixture at {FIXTURE_PATH}"


def test_fixture_carries_current_schema_version() -> None:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert fixture.get("schema_version") == PUBLIC_SCHEMA_VERSION, (
        f"fixture schema_version {fixture.get('schema_version')!r} drifted "
        f"from PUBLIC_SCHEMA_VERSION {PUBLIC_SCHEMA_VERSION!r}. "
        "Regenerate the fixture (see module docstring)."
    )


def test_canonical_report_matches_fixture() -> None:
    """Defence line 2: producer output must match the frozen fixture.

    Catches semantic output drift that the AST-SHA pin cannot see —
    e.g. an imported helper rewrites the value of a field while the
    function body remains byte-identical.
    """
    actual = _build_canonical_report()
    expected = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    diffs = _diff_lines(actual, expected, path="report")
    if diffs:
        raise AssertionError(
            "build_public_report output drifted from the frozen fixture:\n"
            + "\n".join(f"  {d}" for d in diffs[:30])
            + (f"\n  ... and {len(diffs) - 30} more" if len(diffs) > 30 else "")
            + "\n\nIf the change is intentional, regenerate "
            f"{FIXTURE_PATH.relative_to(REPO_ROOT)} and bump "
            "additive_fields_introduced in the schema-pin JSON."
        )
