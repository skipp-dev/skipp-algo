"""v3 Phase 11 — RED test pinning the fix to ``_collect_pine_mp_refs``.

The previous implementation matched ``mp.\\bFOO\\b`` against the full pine
source — including ``//`` comment lines.  ``SMC_Hold_Manager.pine`` ships
TODO notes such as

    // Quality-Sizing aus mp.HERO_QUALITY_TIER + ZONE_HR_* Hit-Rates
    // i_atr_mult per family aus mp.ZONE_CAL_OB / _FVG / _BOS / _SWEEP ableiten

which the regex matched, producing two RED failures on ``main`` HEAD:

* ``test_all_pine_mp_refs_resolve_to_generated_fields`` flagged
  ``SMC_Hold_Manager.pine -> mp.ZONE_CAL_`` as an orphan reference
  (the truncated field name ``ZONE_CAL_`` does not exist; the comment
  uses ``ZONE_CAL_OB`` etc, but the regex's greedy
  ``[A-Z_][A-Z0-9_]+`` happily stops at the underscore-suffixed token).
* ``test_reserved_pine_exports_have_no_pine_consumer_yet`` flagged
  ``HERO_QUALITY_TIER`` as having "landed" because the comment
  references it — but the comment is documentation, not a consumer.

This test pins the contract that comment-only references are
ignored.  When ``_collect_pine_mp_refs`` is fixed to skip comment
lines, the test passes; if the fix regresses, the test fails again.

found via SMC review v3 phase 11
"""

from __future__ import annotations

import textwrap
from pathlib import Path


def test_collect_pine_mp_refs_ignores_comment_only_references(tmp_path: Path) -> None:
    from tests.test_library_field_audit import _collect_pine_mp_refs

    fixture = tmp_path / "fake.pine"
    fixture.write_text(
        textwrap.dedent(
            """\
            //@version=6
            indicator("fake")
            // mp.ONLY_IN_COMMENT  -- this MUST be ignored
            real = mp.ACTUAL_CONSUMER
            // Block-comment style: mp.ALSO_IGNORED
            """
        ),
        encoding="utf-8",
    )

    import tests.test_library_field_audit as audit_mod

    original_dir = audit_mod._PINE_DIR
    try:
        audit_mod._PINE_DIR = tmp_path
        refs = _collect_pine_mp_refs()
    finally:
        audit_mod._PINE_DIR = original_dir

    assert "fake.pine" in refs, "fixture file was not collected"
    found = refs["fake.pine"]
    assert "ACTUAL_CONSUMER" in found, "real consumer must remain detected"
    assert "ONLY_IN_COMMENT" not in found, (
        "References inside ``//`` comment lines must be filtered out — "
        "comments are documentation, not Pine consumers."
    )
    assert "ALSO_IGNORED" not in found, (
        "Block-comment-style ``//`` lines must also be filtered out."
    )


def test_hold_manager_zone_cal_comment_is_not_an_orphan() -> None:
    """Regression pin: the public regression on ``main`` was caused by
    the German-language TODO comment block in ``SMC_Hold_Manager.pine``
    (lines 123 and 181). After the fix, these references must NOT
    appear in ``_collect_pine_mp_refs``'s result for that file.
    """
    from tests.test_library_field_audit import _collect_pine_mp_refs

    refs = _collect_pine_mp_refs()
    hold = refs.get("SMC_Hold_Manager.pine", set())
    assert "ZONE_CAL_" not in hold, (
        "The ``mp.ZONE_CAL_`` token only appears inside ``//`` comments "
        "in SMC_Hold_Manager.pine — comment-only refs must be filtered out."
    )
    # HERO_QUALITY_TIER is only referenced inside the TODO comment block
    # at line 182. Filter must remove it.
    assert "HERO_QUALITY_TIER" not in hold, (
        "``mp.HERO_QUALITY_TIER`` appears only inside a ``//`` comment "
        "in SMC_Hold_Manager.pine — comment-only refs must be filtered out."
    )
