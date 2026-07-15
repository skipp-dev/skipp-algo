"""Pin: the live context library's structural contract (bus-v3 track).

Background
==========

``SMC++/smc_context_engine_private.pine`` imports ``smc_profile_engine`` even
though it is not a profile consumer. That import exists for exactly one reason:
``eng.OrderBlock`` declares a ``pe.Profile profile`` field, and Pine refuses to
compile a script that *uses* a type without importing every library referenced by
that type's fields (CE10293) — the same reason ``smc_draw`` is imported for
``eng.FVG``.

That exception was granted in ``test_pine_library_import_permissions.py`` on the
explicit condition that it stays a **type-resolution edge** and never becomes a
third functional user of the profile engine. This module is what makes that
condition enforceable rather than aspirational: if anyone ever calls a ``pe.*``
function here, the allowlist entry silently stops meaning what its comment claims.
That drift is exactly what trips RED below.

The remaining checks pin the parts of the frame contract that are checkable from
source: import order (dependencies before the engine — the CE10293 fix), the
declared frame fields, and the ``ob_bias`` / ``zone_bias`` separation.

What this file deliberately does NOT do
---------------------------------------
It does not verify that the library *compiles*, and it cannot: transitive Pine
type resolution is only provable on TradingView. Compile validation is a manual
operator gate, not something a Python test may claim to have covered.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
LIB_PATH = REPO_ROOT / "SMC++" / "smc_context_engine_private.pine"
GOLDEN_PATH = REPO_ROOT / "tests" / "fixtures" / "smc_context_golden.json"

# Golden thresholds with NO Pine counterpart, each with the reason it is absent.
# An entry here is a *decision on record*, not a gap: the parity test below fails
# on any frozen threshold that is neither implemented in Pine nor listed here, so
# a newly added threshold cannot slip past unnoticed.
_NOT_IN_PINE: dict[str, str] = {
    "FULL_MIT_PCT": (
        "delegated to the engine: eng.FVG.filled is the full-mitigation SSOT and "
        "the library never recomputes mit_pct >= 1.0"
    ),
    # --- sweeps: not ported yet (phase 3.2b-1) --------------------------------
    # NOTE when porting: SWEEP_DEPTH_STOP_HUNT_PCT must be written in Pine as
    # ``SWEEP_DEPTH_MIN_PCT * 3``, NOT as a literal 0.3. The reference computes
    # 0.1*3 == 0.30000000000000004, so a clean 0.3 flips the classification at a
    # depth of exactly 0.3 (see test_stop_hunt_depth_gate_is_derived_not_a_clean_
    # three_tenths in tests/test_smc_context_golden.py).
    "SWEEP_DEPTH_MIN_PCT": "sweep frame not ported yet (phase 3.2b-1)",
    "SWEEP_DEPTH_STOP_HUNT_PCT": "sweep frame not ported yet (phase 3.2b-1)",
    "SWEEP_RECLAIM_MAX_BARS": "sweep frame not ported yet (phase 3.2b-1)",
    "SWEEP_VOLUME_RATIO_MIN": "sweep frame not ported yet (phase 3.2b-1)",
    # --- pools: not ported yet (phase 3.2b-1) ---------------------------------
    "IMBALANCE_SIG_THRESHOLD": "pool frame not ported yet (phase 3.2b-1)",
    "PROXIMITY_NEAR_PCT": "pool frame not ported yet (phase 3.2b-1)",
    "CLUSTER_STRONG_COUNT": "pool frame not ported yet (phase 3.2b-1)",
}

_PINE_CONST_RE = re.compile(
    r"^const\s+(?:float|int)\s+(?P<name>\w+)\s*=\s*(?P<value>-?[0-9]+(?:\.[0-9]+)?)\s*(?://.*)?$",
    re.MULTILINE,
)


def _pine_consts() -> dict[str, float]:
    return {
        m.group("name"): float(m.group("value"))
        for m in _PINE_CONST_RE.finditer(LIB_PATH.read_text(encoding="utf-8"))
    }


def _golden_thresholds() -> dict[str, float]:
    meta = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))["_meta"]["thresholds"]
    flat: dict[str, float] = {}
    for domain in meta.values():
        flat.update(domain)
    return flat

# Dependencies must be imported BEFORE the engine that pulls them into its types.
# This order mirrors SMC_Long_Dip_Suite.pine and is the fix for the CE10293
# cascade hit while building the structure/imbalance slice.
_EXPECTED_IMPORT_ORDER: tuple[str, ...] = (
    "smc_core_types",
    "smc_utils",
    "smc_draw",
    "smc_profile_engine",
    "smc_engine_private",
)

# Libraries imported purely so Pine can resolve fields of a used engine type.
# Nothing in the library may call into them.
_TYPE_ONLY_ALIASES: tuple[str, ...] = ("pe",)

_IMPORT_RE = re.compile(
    r"^\s*import\s+preuss_steffen/(?P<lib>[A-Za-z0-9_]+)/\d+\s+as\s+(?P<alias>\w+)",
    re.MULTILINE,
)


def _source() -> str:
    return LIB_PATH.read_text(encoding="utf-8")


def _code_lines() -> list[tuple[int, str]]:
    """Source lines with comments and import lines stripped out.

    Pine comments start with ``//``. We only need to spot *calls*, so dropping any
    line whose content begins with ``//`` is enough — and we must drop them,
    because the header comments legitimately mention ``pe.Profile`` and ``pe.*``
    while explaining why the import exists.
    """
    out: list[tuple[int, str]] = []
    for lineno, raw in enumerate(_source().splitlines(), start=1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("//"):
            continue
        if _IMPORT_RE.match(raw):
            continue
        # Trailing comment on a code line: keep the code part only.
        code = raw.split("//", 1)[0]
        if code.strip():
            out.append((lineno, code))
    return out


def test_library_exists() -> None:
    assert LIB_PATH.exists(), f"context library missing at {LIB_PATH}"


def test_type_only_imports_are_never_called() -> None:
    """``pe`` may be imported for type resolution but never invoked.

    This is the condition the smc_profile_engine allowlist entry rests on.
    """
    violations: list[str] = []
    for alias in _TYPE_ONLY_ALIASES:
        call_re = re.compile(rf"\b{re.escape(alias)}\.")
        for lineno, code in _code_lines():
            if call_re.search(code):
                violations.append(f"{LIB_PATH.name}:{lineno}: {code.strip()}")
    assert not violations, (
        "The context library references a type-resolution-only alias in code.\n"
        f"Aliases that must never be called: {_TYPE_ONLY_ALIASES}\n"
        "Offending lines:\n  " + "\n  ".join(violations) + "\n\n"
        "The smc_profile_engine import is allowlisted ONLY as a CE10293 type edge "
        "for eng.OrderBlock.profile. Actually using pe.* makes the context library "
        "a functional profile consumer, which the allowlist comment in "
        "tests/test_pine_library_import_permissions.py explicitly denies. Either "
        "drop the call or re-open that boundary decision with the owner."
    )


def test_imports_are_ordered_dependencies_before_engine() -> None:
    found = [m.group("lib") for m in _IMPORT_RE.finditer(_source())]
    assert found == list(_EXPECTED_IMPORT_ORDER), (
        f"Import order drifted.\n  expected: {list(_EXPECTED_IMPORT_ORDER)}\n"
        f"  found:    {found}\n"
        "Pine resolves a used type's field libraries at import time, so every "
        "dependency must be imported before smc_engine_private (CE10293)."
    )


def test_zone_frame_declares_the_specified_fields() -> None:
    """ZoneFrame must match docs/smc-context-semantics.md § Zone frame."""
    src = _source()
    block = re.search(r"^export type ZoneFrame\n((?:    .*\n)+)", src, re.MULTILINE)
    assert block, "export type ZoneFrame not found"
    fields = {
        m.group(1)
        for m in re.finditer(r"^    \w+\s+(\w+)", block.group(1), re.MULTILINE)
    }
    expected = {
        "bull_ob_active", "bear_ob_active",
        "bull_ob_id", "bear_ob_id",
        "bull_ob_top", "bull_ob_bottom",
        "bear_ob_top", "bear_ob_bottom",
        "bull_ob_count", "bear_ob_count",
        "bull_ob_new", "bear_ob_new",
        "bull_ob_broken", "bear_ob_broken",
        "ob_bias", "state",
    }
    assert fields == expected, (
        f"ZoneFrame fields drifted from the spec.\n"
        f"  missing: {sorted(expected - fields)}\n"
        f"  extra:   {sorted(fields - expected)}\n"
        "Update docs/smc-context-semantics.md § Zone frame in the same change."
    )


def test_zone_frame_is_direction_neutral() -> None:
    """Every bull field has a bear twin.

    Direction neutrality is the entire justification for this frame: the v2 engine
    bus already carries the product's best *bull* OB geometry. A bull-only ZoneFrame
    would duplicate v2 instead of adding the side it lacks.
    """
    src = _source()
    block = re.search(r"^export type ZoneFrame\n((?:    .*\n)+)", src, re.MULTILINE)
    assert block
    fields = {
        m.group(1)
        for m in re.finditer(r"^    \w+\s+(\w+)", block.group(1), re.MULTILINE)
    }
    unpaired = [
        f for f in fields
        if f.startswith("bull_") and f.replace("bull_", "bear_", 1) not in fields
    ]
    assert not unpaired, f"bull-side ZoneFrame fields without a bear twin: {unpaired}"


def test_ob_bias_and_zone_bias_stay_separate_fields() -> None:
    """``ob_bias`` (order blocks) must never be merged into ``zone_bias`` (FVGs).

    Same ±2 count-delta shape, different domain. Aliasing them would silently
    reinterpret one domain's bias as the other's.
    """
    src = _source()
    imbalance = re.search(r"^export type ImbalanceFrame\n((?:    .*\n)+)", src, re.MULTILINE)
    zone = re.search(r"^export type ZoneFrame\n((?:    .*\n)+)", src, re.MULTILINE)
    assert imbalance and zone
    assert re.search(r"^    int\s+zone_bias", imbalance.group(1), re.MULTILINE), (
        "ImbalanceFrame.zone_bias (the FVG count-delta bias) disappeared."
    )
    assert re.search(r"^    int\s+ob_bias", zone.group(1), re.MULTILINE), (
        "ZoneFrame.ob_bias (the OB count-delta bias) disappeared."
    )
    assert not re.search(r"^    int\s+zone_bias", zone.group(1), re.MULTILINE), (
        "ZoneFrame must not declare zone_bias — that name belongs to the FVG "
        "count-delta rule on ImbalanceFrame. Use ob_bias."
    )


def test_zone_builder_keeps_profile_features_off() -> None:
    """The ``pe`` type edge only stays inert while no Profile is ever built.

    ``eng.track_obs`` creates a ``pe.Profile`` when any of capture_profile /
    align_edge_to_value_area / align_break_price_to_poc is true. The zone builder
    must leave all three at their ``false`` defaults — passing one enables profile
    construction and turns the nominal import into a real dependency.
    """
    offenders = [
        f"{lineno}: {code.strip()}"
        for lineno, code in _code_lines()
        if "eng.track_obs" in code
        and any(
            f"{arg} = true" in code.replace(" =true", " = true")
            for arg in (
                "capture_profile",
                "align_edge_to_value_area",
                "align_break_price_to_poc",
            )
        )
    ]
    assert not offenders, (
        "build_zone_frame enables an engine profile feature:\n  "
        + "\n  ".join(offenders)
        + "\nThat makes eng.track_obs construct a pe.Profile, which would make the "
        "smc_profile_engine import a functional dependency rather than the type "
        "edge its allowlist entry documents."
    )


def test_public_builders_are_exported() -> None:
    src = _source()
    for builder in ("build_structure_frame", "build_imbalance_frame", "build_zone_frame"):
        assert re.search(rf"^export {builder}\(", src, re.MULTILINE), (
            f"{builder} is not exported"
        )


def test_pine_thresholds_match_the_frozen_golden() -> None:
    """Every golden threshold implemented in Pine must carry the frozen value.

    This is the mechanical Python->Pine link that did not exist before. The golden
    tests only ever compared Python against Python: a reference threshold could
    move, ``gen_smc_context_golden`` would regenerate, every Python test would stay
    green — and this library would keep the old number, silently.
    """
    consts = _pine_consts()
    frozen = _golden_thresholds()

    mismatched = [
        f"{name}: pine={consts[name]!r} golden={value!r}"
        for name, value in frozen.items()
        if name in consts and consts[name] != value
    ]
    assert not mismatched, (
        "Pine rule-layer constants drifted from the frozen golden:\n  "
        + "\n  ".join(mismatched)
        + "\n\nThe Python reference is authoritative. Update the const in "
        "SMC++/smc_context_engine_private.pine to match, and re-publish the "
        "library to TradingView — the repo alone does not move the live script."
    )


def test_every_golden_threshold_is_either_ported_or_explicitly_deferred() -> None:
    """No frozen threshold may be silently absent from Pine.

    A threshold is either implemented as a Pine const of the same name, or listed
    in ``_NOT_IN_PINE`` with a reason. Adding one to the golden without doing
    either trips RED here rather than quietly leaving the port incomplete.
    """
    consts = _pine_consts()
    frozen = _golden_thresholds()
    unaccounted = sorted(set(frozen) - set(consts) - set(_NOT_IN_PINE))
    assert not unaccounted, (
        f"Golden thresholds neither implemented in Pine nor deferred: {unaccounted}.\n"
        "Either add a `const` of the same name to the context library, or add an "
        "entry to _NOT_IN_PINE stating why it does not belong there."
    )


def test_deferred_thresholds_are_not_secretly_implemented() -> None:
    """``_NOT_IN_PINE`` must not rot once a threshold actually lands in Pine."""
    consts = _pine_consts()
    stale = sorted(set(_NOT_IN_PINE) & set(consts))
    assert not stale, (
        f"These thresholds are declared in Pine but still listed as deferred: {stale}. "
        "Remove them from _NOT_IN_PINE so the parity check governs them."
    )


def test_thresholds_are_named_consts_not_inlined_magic_numbers() -> None:
    """The rule layer must reference the named consts, not repeat their literals.

    A literal at the use-site is invisible to the parity check above — that is
    exactly how the pre-existing drift hole worked. ``CLUSTER_STRONG_COUNT`` in the
    Python pool scorer was the same failure: a named threshold that governed
    nothing because the rule used a bare ``3``.
    """
    offenders: list[str] = []
    for lineno, raw in enumerate(LIB_PATH.read_text(encoding="utf-8").splitlines(), 1):
        code = raw.split("//", 1)[0]
        if not code.strip() or code.lstrip().startswith("const "):
            continue
        if re.search(r"mit\s*>=\s*0\.5", code) or re.search(r"mid,\s*2\.0\)", code):
            offenders.append(f"{lineno}: {code.strip()}")
        if re.search(r"count_delta\s*[<>]=\s*-?2\b", code):
            offenders.append(f"{lineno}: {code.strip()}")
    assert not offenders, (
        "Rule-layer threshold literals found at use-sites instead of the named "
        "consts:\n  " + "\n  ".join(offenders)
    )


# ── Rule-layer semantics: pins that survive a mutated builder ────────────────
#
# The threshold pins above compare *constants*. They do not observe what the
# builders compute. Verified 2026-07-15 against origin/main@a19e44348: mutating
# ImbalanceFrame.state to a constant 0 and StructureFrame.trend to a constant 1
# each left this module fully green (12 passed either way). The pins below are
# what make those two mutations fail.
#
# Scope, unchanged from this module's header: these read the Pine SOURCE. They
# claim no compile or runtime coverage — that stays a manual operator gate.


def _builder_body(name: str) -> str:
    """Source of one exported builder, up to the next top-level export.

    Scoping matters: ZoneFrame (3.2a) and ImbalanceFrame each declare a `state`
    field with a *different* ladder, so a whole-file regex reads whichever comes
    first and silently pins the wrong one.
    """
    src = _source()
    start = re.search(rf"^export {name}\(", src, re.MULTILINE)
    assert start, f"{name} not found"
    rest = src[start.end() :]
    nxt = re.search(r"^export ", rest, re.MULTILINE)
    return rest[: nxt.start()] if nxt else rest


def _builder_signature(name: str) -> str:
    m = re.search(rf"^export {name}\((?P<args>[^)]*)\)", _source(), re.MULTILINE)
    assert m, f"{name} signature not found"
    return m.group("args")


def _effective_terminal_fill_ratio() -> float:
    """The fill_target_ratio the builder actually hands the engine.

    Resolves the *call-site* argument, following one hop through either a
    builder parameter default or a named Pine const. Reading only the public
    signature default would miss a perfectly good fix that drops the parameter
    and pins the ratio at the call site, or moves it into a named const — the
    test would then keep reporting the old violation forever.
    """
    call = re.search(
        r"eng\.fvgs_objects\((?P<args>[^)]*)\)", _builder_body("build_imbalance_frame")
    )
    assert call, "build_imbalance_frame no longer calls eng.fvgs_objects"
    m = re.search(r"fill_target_ratio\s*=\s*(?P<val>[\w.]+)", call.group("args"))
    assert m, (
        "build_imbalance_frame calls eng.fvgs_objects without passing "
        "fill_target_ratio, so the engine's own 0.5 default applies and the FVG "
        "is still retired at the gap midpoint."
    )
    val = m.group("val")
    try:
        return float(val)
    except ValueError:
        pass
    param_default = re.search(
        rf"\b{re.escape(val)}\s*=\s*(-?[0-9]+(?:\.[0-9]+)?)",
        _builder_signature("build_imbalance_frame"),
    )
    if param_default:
        return float(param_default.group(1))
    consts = _pine_consts()
    assert val in consts, (
        f"cannot resolve the fill_target_ratio argument {val!r} to a value: it is "
        "neither a literal, nor a build_imbalance_frame parameter with a default, "
        "nor a named const in this library."
    )
    return consts[val]


@pytest.mark.xfail(
    strict=True,
    reason=(
        "KNOWN VIOLATION (F1). _NOT_IN_PINE records FULL_MIT_PCT as 'delegated to "
        "the engine: eng.FVG.filled is the full-mitigation SSOT'. That delegation "
        "is only true if the builder asks the engine for a TERMINAL fill target. "
        "It asks for 0.5, so eng.FVG.filled fires at the gap MIDPOINT and "
        "clear_filled() drops the FVG from the active buffer at half mitigation. "
        "Consequences: the golden state FULL_MITIGATION=false + "
        "PARTIAL_MITIGATION=true is unreachable in Pine, bull_fvg_partial is only "
        "reachable on an exact-midpoint tick, and count/BPR/zone_bias/state are "
        "computed from a truncated set. Un-xfail together with the fix; "
        "strict=True fails the suite the moment the source is corrected."
    ),
)
def test_engine_fill_delegation_holds_its_precondition() -> None:
    """Delegating FULL_MIT_PCT to the engine requires a terminal fill target."""
    expected = _golden_thresholds()["FULL_MIT_PCT"]
    actual = _effective_terminal_fill_ratio()
    assert actual == expected, (
        f"build_imbalance_frame effectively passes fill_target_ratio={actual} to "
        f"the engine, but _NOT_IN_PINE delegates FULL_MIT_PCT ({expected}) to "
        "eng.FVG.filled. The engine sets `filled` once price crosses "
        "top - ratio*size, so any ratio below 1.0 makes that delegation false: "
        "the flag then means 'partially filled', not 'fully mitigated'."
    )


def test_imbalance_state_precedence_is_the_documented_ladder() -> None:
    """`state` must stay the BPR > VOID > FVG_BULL > FVG_BEAR > NONE ladder.

    Collapsing it to a constant is one of the two mutations this module missed.
    """
    m = re.search(
        r"int state = (?P<expr>.+)$", _builder_body("build_imbalance_frame"), re.MULTILINE
    )
    assert m, "the ImbalanceFrame state expression is gone"
    expr = m.group("expr")
    codes = [int(c) for c in re.findall(r"\b(\d)\b", expr)]
    assert codes == [3, 4, 1, 2, 0], (
        f"state ladder drifted: emits {codes}, expected [3, 4, 1, 2, 0] "
        "(BPR > VOID > FVG_BULL > FVG_BEAR > NONE)"
    )
    for predicate in ("bpr_active", "void_active", "has_bull", "has_bear"):
        assert predicate in expr, (
            f"ImbalanceFrame.state no longer depends on {predicate} — it cannot "
            "be a constant or a subset of the ladder"
        )


def test_structure_trend_flows_from_the_engine_detector() -> None:
    """`StructureFrame.trend` must derive from the engine's trend, not a literal.

    Pinning trend to a constant is the other mutation this module missed.

    Deliberately NOT pinned to the bare identifier: the engine bootstraps
    `var trend = 1`, so a correct warm-up fix will wrap it (e.g.
    ``structure_available ? trend : 0``). Demanding the raw value would block
    that fix and cement today's bullish bootstrap as the contract. The rule is
    only: it must depend on the engine's trend and must not be a literal.
    """
    body = _builder_body("build_structure_frame")
    assert re.search(r"\[trend,[^\]]*\]\s*=\s*eng\.detect_structure\(", body), (
        "build_structure_frame no longer destructures trend from "
        "eng.detect_structure"
    )
    m = re.search(r"StructureFrame\.new\((?P<args>[^)]*)\)", body)
    assert m, "StructureFrame.new construction not found"
    first_arg = m.group("args").split(",", 1)[0].strip()
    assert not re.fullmatch(r"-?\d+(?:\.\d+)?", first_arg), (
        f"StructureFrame.trend is built from the literal {first_arg!r}. It must "
        "carry the engine's trend (optionally neutralised during warm-up), not "
        "a hardcoded direction."
    )
    assert re.search(r"\btrend\b", first_arg), (
        f"StructureFrame.trend is built from {first_arg!r}, which does not "
        "reference the engine's `trend` value at all."
    )


def test_imbalance_frame_is_direction_neutral() -> None:
    """Every bull-side ImbalanceFrame field needs a bear twin (as for ZoneFrame)."""
    block = re.search(
        r"^export type ImbalanceFrame\n((?:    .*\n)+)", _source(), re.MULTILINE
    )
    assert block, "export type ImbalanceFrame not found"
    fields = {
        m.group(1)
        for m in re.finditer(r"^    \w+\s+(\w+)", block.group(1), re.MULTILINE)
    }
    unpaired = [
        f for f in fields
        if f.startswith("bull_") and f.replace("bull_", "bear_", 1) not in fields
    ]
    assert not unpaired, (
        f"bull-side ImbalanceFrame fields without a bear twin: {unpaired}"
    )
