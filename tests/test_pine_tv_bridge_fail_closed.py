"""Fail-closed guards for ``SMC_TV_Bridge.pine``.

The bridge ingests *untrusted* JSON from an external backend and renders it
on-chart. Two safety properties must hold and never silently regress:

1. **Network stays opt-in / disabled by default.** ``request.get`` must not
   appear in live (un-commented) code — the placeholder ``na`` fetch keeps
   the bridge inert until an operator deliberately wires a real endpoint.
2. **Parsing fails closed.** Empty, missing, or malformed payloads must yield
   neutral output: empty fields (no drawings), and numeric values fall back to
   explicit ``str.tonumber(..., <default>)`` defaults rather than ``na``.

Because Pine cannot be executed here, property (1) and the structural pieces
of (2) are asserted statically against the source, and the field-extraction
semantics are pinned by a faithful Python reference port of ``f_getField``
exercised against malformed-JSON inputs.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_BRIDGE = _REPO_ROOT / "SMC_TV_Bridge.pine"


@pytest.fixture(scope="module")
def bridge_src() -> str:
    # The bridge is a required active-suite file; its absence is a hard
    # failure, not a skip (a skip here would silently disable every
    # fail-closed guard below and slip past the pytest-skip budget).
    assert _BRIDGE.exists(), f"required active-suite file missing: {_BRIDGE}"
    return _BRIDGE.read_text(encoding="utf-8", errors="replace")


# ── (1) network disabled by default ───────────────────────────────────

def _strip_comments(src: str) -> str:
    """Drop ``//`` line comments so we only inspect live code."""
    out_lines = []
    for line in src.splitlines():
        idx = line.find("//")
        out_lines.append(line if idx < 0 else line[:idx])
    return "\n".join(out_lines)


def test_request_get_is_not_live(bridge_src: str) -> None:
    live = _strip_comments(bridge_src)
    assert "request.get" not in live, (
        "SMC_TV_Bridge.pine activates request.get in live code. The bridge "
        "must stay inert (na placeholder) until an operator deliberately "
        "enables a vetted endpoint — fail closed, not open."
    )


def test_fetch_has_na_placeholder(bridge_src: str) -> None:
    # The stubbed fetch path must still resolve to a defined neutral value.
    assert re.search(r"^\s*na\b", bridge_src, re.MULTILINE), (
        "Expected an 'na' placeholder in the stubbed fetch path so the "
        "bridge yields an empty body instead of an undefined fetch result."
    )


# ── (2a) numeric reads carry explicit defaults ────────────────────────

@pytest.mark.parametrize("var_default", [("techStr", "0.5"), ("newsStr", "0.0")])
def test_numeric_reads_have_defaults(bridge_src: str, var_default) -> None:
    var, default = var_default
    pattern = re.compile(
        rf"str\.tonumber\(\s*{re.escape(var)}\s*,\s*{re.escape(default)}\s*\)"
    )
    assert pattern.search(bridge_src), (
        f"Expected fail-closed default str.tonumber({var}, {default}); a bare "
        "str.tonumber without a default would propagate na on malformed input."
    )


# ── (2b) drawings are guarded by non-empty payload checks ─────────────

@pytest.mark.parametrize(
    "field_var", ["bosStr", "obStr", "fvgStr", "sweepStr"]
)
def test_draw_blocks_guard_empty_payload(bridge_src: str, field_var: str) -> None:
    # Each drawing block must be gated on a non-empty extracted field so an
    # empty/absent payload draws nothing.
    pattern = re.compile(rf"barstate\.islast\s+and\s+{re.escape(field_var)}\s*!=\s*\"\"")
    assert pattern.search(bridge_src), (
        f"Drawing block for {field_var} is not guarded by a non-empty check "
        f"('{field_var} != \"\"'); a missing payload could still attempt to "
        "render stale/empty data."
    )


# ── (2c) reference port of f_getField pinned against malformed JSON ───
#
# Faithful Python mirror of the Pine ``f_getField`` extractor. Kept in lock-
# step with the .pine implementation; if the Pine logic changes, update this
# reference and its expectations together.

def _ref_get_field(src: str, key: str) -> str:
    prefix = '"' + key + '":'
    start = src.find(prefix)
    if start < 0:
        return ""
    frm = start + len(prefix)
    rest = src[frm:]
    if rest.startswith('"'):
        inner = rest[1:]
        q_end = inner.find('"')
        return inner[:q_end] if q_end >= 0 else ""
    c_end = rest.find(",")
    b_end = rest.find("}")
    if c_end >= 0 and (b_end < 0 or c_end < b_end):
        end_pos = c_end
    else:
        end_pos = b_end
    return rest[:end_pos] if end_pos >= 0 else rest


class TestFieldExtractorFailClosed:
    def test_empty_body_yields_empty(self) -> None:
        assert _ref_get_field("", "bos") == ""

    def test_missing_key_yields_empty(self) -> None:
        assert _ref_get_field('{"ob":"1|2|BULL"}', "bos") == ""

    def test_unterminated_string_yields_empty(self) -> None:
        # Closing quote missing → fail closed to empty, not partial garbage.
        assert _ref_get_field('{"regime":"HOLIDAY', "regime") == ""

    def test_garbage_body_yields_empty(self) -> None:
        assert _ref_get_field("not even json", "tech") == ""

    def test_valid_string_field_extracts(self) -> None:
        assert _ref_get_field('{"regime":"TREND"}', "regime") == "TREND"

    def test_valid_numeric_field_extracts(self) -> None:
        assert _ref_get_field('{"tech":0.73,"news":0.1}', "tech") == "0.73"

    def test_numeric_field_before_brace(self) -> None:
        assert _ref_get_field('{"news":0.4}', "news") == "0.4"


# ── (2d) f_getField drift tripwire ────────────────────────────────────
#
# The Python ``_ref_get_field`` port above must stay in lock-step with the
# Pine ``f_getField``. Pine cannot be executed here, so we fingerprint the
# Pine function body: if it changes, this tripwire fails and forces a human
# to re-verify the port and re-pin the hash. This converts a silent semantic
# drift into a loud, reviewable failure.

# sha256 of the normalised Pine ``f_getField`` body. Regenerate (and re-verify
# that ``_ref_get_field`` still mirrors the logic) whenever f_getField changes.
_FGETFIELD_FINGERPRINT = "98829dd38d93a2046b5f4cf47168e77637bf88287b69a19cc3736f2a038c9fdd"


def _extract_pine_function(src: str, name: str) -> str:
    """Return the normalised body of a Pine ``name(...) =>`` function.

    Collects the signature line plus every following indented/blank line up to
    the next top-level (column-0, non-blank) statement. Lines are right-stripped
    and joined with ``\\n`` so the fingerprint is insensitive to trailing
    whitespace and line-ending differences but sensitive to any logic change.
    """
    lines = src.splitlines()
    out: list[str] = []
    capturing = False
    for line in lines:
        if not capturing:
            if re.match(rf"^{re.escape(name)}\s*\(", line):
                capturing = True
                out.append(line.rstrip())
            continue
        # Stop at the next top-level statement (no leading whitespace, non-blank).
        if line.strip() and not line[:1].isspace():
            break
        out.append(line.rstrip())
    # Drop trailing blank lines.
    while out and not out[-1].strip():
        out.pop()
    return "\n".join(out)


def test_f_getfield_port_in_lockstep(bridge_src: str) -> None:
    body = _extract_pine_function(bridge_src, "f_getField")
    assert body, "could not locate f_getField in SMC_TV_Bridge.pine"
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    assert digest == _FGETFIELD_FINGERPRINT, (
        "f_getField in SMC_TV_Bridge.pine changed (fingerprint "
        f"{digest}). Re-verify that the Python reference port "
        "`_ref_get_field` still mirrors the new logic, then update "
        "_FGETFIELD_FINGERPRINT to this value. Do NOT bump the hash "
        "without re-checking the port — that is the whole point of this guard."
    )


# ── (3) suite-wide network-egress fail-closed guard ───────────────────
#
# Generalises the bridge's network-inert property to the entire active Pine
# suite: no active script may ship a *live* external HTTP egress
# (``request.get``/``request.post``). request.security/security_lower_tf are
# legitimate market-data reads and are NOT external egress, so they are allowed.

_ACTIVE_PINE = sorted(
    set(_REPO_ROOT.glob("*.pine")) | set(_REPO_ROOT.glob("pine/skipp_*.pine"))
)
_EGRESS_RE = re.compile(r"request\.(get|post)\s*\(")


@pytest.mark.parametrize("pine_path", _ACTIVE_PINE, ids=lambda p: p.name)
def test_no_live_external_http_egress(pine_path: Path) -> None:
    live = _strip_comments(pine_path.read_text(encoding="utf-8", errors="replace"))
    hit = _EGRESS_RE.search(live)
    assert hit is None, (
        f"{pine_path.name} activates live external HTTP egress "
        f"({hit.group(0) if hit else ''}). Active suite scripts must stay "
        "network-inert (fail closed); gate any external fetch behind a "
        "commented placeholder until an operator deliberately enables a "
        "vetted endpoint."
    )
