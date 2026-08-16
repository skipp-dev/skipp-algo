"""The survivorship fail-soft chain is coupled, so a rename cannot unhook it.

2026-08-15 sweep finding (Population C, the one BY-DESIGN item promoted to a
contract): ``universe_survivorship_bias_risk`` travels three hops —

    scripts/databento_production_export.py   (writes it into the manifest)
    scripts/build_promotion_gate_bundle.py   (reads it, stamps provenance)
    scripts/run_promotion_gate.py            (ORs it into the demote flag)

Every hop is individually documented as fail-soft (absent key -> None/False,
"no behaviour change") — which means a rename at ANY hop silently disables
the promote-refusal for survivorship-biased runs (#3453 class) with all
suites green. No test coupled the hops; this file is that coupling: the key
literal is EXTRACTED from each source (not re-typed), the three must agree,
and the bundle-side reader is executed against a manifest carrying the
exporter's actual key.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

_EXPORTER = REPO_ROOT / "scripts" / "databento_production_export.py"
_BUNDLE = REPO_ROOT / "scripts" / "build_promotion_gate_bundle.py"
_GATE = REPO_ROOT / "scripts" / "run_promotion_gate.py"
_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "promotion-gate-daily.yml"


def _extract(path: Path, pattern: str) -> str:
    match = re.search(pattern, path.read_text(encoding="utf-8"))
    assert match, f"{path.name}: hop not found via {pattern!r} — if the site moved, move this extraction WITH it"
    return match.group(1)


def _writer_key() -> str:
    return _extract(_EXPORTER, r'"(universe_survivorship_bias_risk)":\s*universe_metadata\.get')


def test_all_three_hops_read_the_key_the_exporter_writes() -> None:
    writer = _writer_key()
    bundle = _extract(_BUNDLE, r'data\.get\("(\w+)"\) if isinstance\(data, dict\)')
    gate = _extract(_GATE, r'provenance", None\) or \{\}\)\.get\("(\w+)"\)')
    assert writer == bundle == gate, (
        f"the survivorship chain has drifted apart: exporter={writer!r}, "
        f"bundle={bundle!r}, gate={gate!r} — every hop is fail-soft, so this "
        "mismatch would silently disable the promote-refusal for "
        "survivorship-biased runs with all suites green"
    )


def test_the_bundle_reader_consumes_the_exporters_key_for_real(tmp_path: Path) -> None:
    """Executed, not string-matched: the extraction above proves the sources
    NAME the same key; this proves the reader actually answers on it."""
    sys.path.insert(0, str(REPO_ROOT))
    from scripts.build_promotion_gate_bundle import _read_universe_survivorship_flag

    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({_writer_key(): True}), encoding="utf-8")
    assert _read_universe_survivorship_flag(manifest) is True

    manifest.write_text(json.dumps({"renamed_key": True}), encoding="utf-8")
    assert _read_universe_survivorship_flag(manifest) is None, (
        "the documented fail-soft: a missing key omits the stamp — this test "
        "exists so the string-equality above is what catches the rename, not "
        "a production promote decision"
    )


def test_a_missing_staged_manifest_is_at_least_said_out_loud() -> None:
    """promotion-gate-daily's UNIV_MANIFEST glob is fail-soft (2>/dev/null):
    a staging failure built the bundle without --universe-manifest and the
    gate's survivorship refusal input vanished from a promote decision with
    no line in the log. The step must warn when the glob comes back empty —
    the EVENTS_POOL twin above it already does."""
    body = _WORKFLOW.read_text(encoding="utf-8")
    glob_at = body.index("UNIV_MANIFEST=")
    # The bare script name also sits in the file's HEADER comment (offset ~936)
    # — anchor on the invocation, or this ordering check compares against prose.
    bundle_at = body.index("python scripts/build_promotion_gate_bundle.py")
    warning_at = body.index("no databento export manifest in the staged artifact")
    assert glob_at < warning_at < bundle_at, (
        "the empty-manifest warning must sit between the glob and the bundle "
        "build, or the silent-provenance-loss path is back"
    )
