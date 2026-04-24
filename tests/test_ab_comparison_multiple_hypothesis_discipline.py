"""Regression pin: ``scripts/run_ab_comparison.py`` must keep its
multiple-hypothesis-testing discipline.

The script *already* implements Benjamini–Hochberg FDR correction in two
places (per-family layer and per-cell calibration layer). This pin
freezes that fact so that a future refactor cannot silently drop the BH
correction and start emitting raw p-values as accept/reject decisions —
which would re-introduce inflated false-discovery rate at the experiment
gate.

It is deliberately a *symbol-presence* / *counterpart-pair* pin and not
a behavioural pin: numerical correctness of the BH algorithm is already
covered by ``tests/test_benjamini_hochberg_property.py``,
``tests/test_run_ab_comparison_fdr.py``, and
``tests/test_run_ab_comparison_calibration_fdr.py``.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "run_ab_comparison.py"


def _src() -> str:
    assert SCRIPT.exists(), f"missing target script: {SCRIPT}"
    return SCRIPT.read_text(encoding="utf-8")


def test_benjamini_hochberg_helper_is_present() -> None:
    src = _src()
    assert re.search(r"\bdef\s+benjamini_hochberg\s*\(", src), (
        "scripts/run_ab_comparison.py must define a benjamini_hochberg() "
        "helper. If you removed/renamed it, you have either broken multiple-"
        "hypothesis discipline or you must update this pin together with the "
        "rename."
    )


def test_family_and_calibration_fdr_layers_are_wired() -> None:
    src = _src()
    for marker in ("_family_fdr_layer", "_calibration_fdr_layer"):
        assert marker in src, (
            f"scripts/run_ab_comparison.py must keep its {marker} layer. "
            f"Both per-family and per-calibration-cell BH-FDR layers are "
            f"required to control the false-discovery rate of the A/B gate."
        )
    assert '"method": "benjamini_hochberg"' in src, (
        "The FDR digest must self-identify as method=benjamini_hochberg so "
        "downstream consumers can audit the correction."
    )


def test_every_p_value_field_has_an_adjusted_p_value_sibling() -> None:
    """Wherever the digest emits a raw ``p_value`` field, it must also
    emit an ``adjusted_p_value`` field — otherwise the consumer cannot
    distinguish raw from BH-corrected significance and may use the wrong
    one for promotion decisions."""
    src = _src()
    p_value_count = len(re.findall(r'"p_value"\s*:', src))
    adjusted_count = len(re.findall(r'"adjusted_p_value"\s*:', src))
    assert p_value_count >= 1 and adjusted_count >= p_value_count, (
        f"Found {p_value_count} `\"p_value\":` field emissions but only "
        f"{adjusted_count} `\"adjusted_p_value\":` siblings. Every raw p-value "
        f"in the digest must be accompanied by its BH-adjusted counterpart "
        f"so consumers cannot accidentally use uncorrected significance for "
        f"promotion decisions."
    )
