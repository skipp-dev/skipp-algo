"""Guard: every active Pine suite file declares a *valid* ``//@version`` directive.

Why this exists
---------------
Pine Script recognises the compiler version only from a directive of the
exact form ``//@version=N`` — **no space** between ``//`` and ``@version``
and nothing else on the line. A malformed variant such as ``// @version=5``
is parsed as an ordinary comment, so TradingView silently falls back to the
oldest language version and the script's v5/v6 syntax breaks at runtime.

This regression bit ``SMC_TV_Bridge.pine`` (it carried ``// @version=5``)
and was missed by two prior reviews that only ever asserted a *substring*
match. This test anchors the directive so the malformed form can never
re-enter the active suite.

Scope: the active TradingView suite as declared in ``PINE_LEGACY.md`` —
top-level ``*.pine`` files in the repo root (the user-facing scripts plus
first-party tooling) **and** the hand-authored libraries under
``pine/skipp_*.pine``. Those libraries are listed under the *active SMC
suite* in ``PINE_LEGACY.md`` ("DO NOT touch in legacy sweeps"); they ship
to TradingView and are exposed to the exact same silent-downgrade failure,
so they must carry an anchored directive too. The ``pine/legacy/`` and
``pine/generated/`` trees are intentionally excluded (legacy assets and
code-generated snippets, not part of the active hand-authored suite).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]

# Exact, anchored directive: no leading/trailing junk, no space after ``//``.
_VALID_DIRECTIVE_RE = re.compile(r"^//@version=\d+\s*$", re.MULTILINE)

# A permissive matcher used only to surface *malformed* directives in the
# failure message (e.g. ``// @version=5`` with a stray space).
_LOOSE_DIRECTIVE_RE = re.compile(r"^\s*//\s*@version\s*=\s*\d+.*$", re.MULTILINE)

# Top-level non-script fragments that legitimately carry no version directive.
_EXCLUDE_NAMES = frozenset({"test_div.pine"})


def _active_suite_files() -> list[Path]:
    root_files = (
        p
        for p in _REPO_ROOT.glob("*.pine")
        if p.name not in _EXCLUDE_NAMES
    )
    # Active hand-authored libraries declared in PINE_LEGACY.md. These ship to
    # TradingView and face the identical silent-downgrade risk, so the anchored
    # guard must cover them as well. ``pine/legacy/`` and ``pine/generated/``
    # are deliberately NOT globbed here.
    library_files = _REPO_ROOT.glob("pine/skipp_*.pine")
    return sorted(set(root_files) | set(library_files))


def test_active_suite_is_discovered() -> None:
    files = _active_suite_files()
    assert files, "No top-level .pine files discovered — wrong repo root?"
    # The user-facing suite must always include the core engine.
    assert any(p.name == "SMC_Core_Engine.pine" for p in files)
    # Guard the scope itself: the active libraries must be in range. If they
    # are ever moved and the glob silently matches nothing, this fails loudly
    # rather than letting the silent-downgrade gap quietly reopen.
    library_names = {p.name for p in files if p.parent.name == "pine"}
    assert library_names == {
        "skipp_calibration.pine",
        "skipp_indicators.pine",
        "skipp_labels.pine",
        "skipp_math.pine",
        "skipp_scoring.pine",
    }, f"active pine/ libraries drifted out of guard scope: {sorted(library_names)}"


@pytest.mark.parametrize(
    "pine_path",
    _active_suite_files(),
    ids=lambda p: p.name,
)
def test_valid_version_directive(pine_path: Path) -> None:
    text = pine_path.read_text(encoding="utf-8", errors="replace")
    if _VALID_DIRECTIVE_RE.search(text):
        return

    loose = _LOOSE_DIRECTIVE_RE.search(text)
    if loose:
        pytest.fail(
            f"{pine_path.name}: malformed version directive "
            f"{loose.group(0).strip()!r}. Pine only honours the exact form "
            "'//@version=N' (no space after '//'); the malformed form is "
            "treated as a plain comment and the script silently downgrades "
            "to the oldest language version."
        )
    pytest.fail(
        f"{pine_path.name}: no '//@version=N' directive found. Active suite "
        "scripts must declare an explicit Pine compiler version."
    )
