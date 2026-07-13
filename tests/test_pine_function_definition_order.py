"""Pine consumer scripts: user functions must be DEFINED before referenced.

Incident 2026-07-13 (CE10271 / "Could not find function or function
reference"): ``SMC_Dashboard.pine``'s ``dashboard_compact_main_blocker_text``
referenced ``decode_event_risk_text`` and ``decode_volume_data_text`` ~250
lines ABOVE their definitions. Pine resolves user-function references
lexically at compile time, so the script failed to compile on TradingView —
silently, for weeks: the saved TV script showed a red (!) study, its settings
dialog rendered inputs-less (which the post-release validation could not
handle until #3590), and the operator-facing dashboard was simply broken.

This is a HEURISTIC static tripwire, deliberately narrow to stay
false-positive-free on the current corpus:

* a "definition" is a top-level (column-0) ``name(args) =>`` line;
* a "reference" is ``name(`` (not preceded by ``.`` or a word char, so
  library-namespaced calls like ``mp.foo(`` don't count) on any earlier
  non-comment line.

It cannot see calls inside strings (accepted noise risk: none in the current
corpus) and does not model Pine scoping beyond that — it exists to catch the
one mistake class that already burned us, at zero TradingView cost.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Root-level consumer scripts (published/saved on TradingView by hand).
#: Libraries under SMC++/ and pine/generated/ use export/method syntax and a
#: generator pipeline with its own checks — out of scope here.
CONSUMER_PINE_GLOB = "*.pine"

_DEF_RE = re.compile(r"^([a-z_][A-Za-z0-9_]*)\s*\(.*\)\s*=>\s*$")


def _use_before_definition_violations(path: Path) -> list[tuple[str, int, int]]:
    source_lines = path.read_text(encoding="utf-8").splitlines()
    definitions: dict[str, int] = {}
    for lineno, line in enumerate(source_lines, 1):
        match = _DEF_RE.match(line)
        if match:
            definitions.setdefault(match.group(1), lineno)

    violations: list[tuple[str, int, int]] = []
    for name, def_line in definitions.items():
        call_re = re.compile(r"(?<![\w.])" + re.escape(name) + r"\s*\(")
        for lineno, line in enumerate(source_lines, 1):
            if lineno >= def_line:
                break
            if line.lstrip().startswith("//"):
                continue
            if call_re.search(line) and not _DEF_RE.match(line):
                violations.append((name, def_line, lineno))
                break
    return violations


def test_root_pine_scripts_define_functions_before_use() -> None:
    checked = 0
    problems: list[str] = []
    for path in sorted(REPO_ROOT.glob(CONSUMER_PINE_GLOB)):
        checked += 1
        for name, def_line, use_line in _use_before_definition_violations(path):
            problems.append(
                f"{path.name}: '{name}' used at line {use_line} but defined at "
                f"line {def_line} — Pine cannot compile this "
                f"(CE10271-class); move the definition above its first use."
            )
    assert checked >= 15, f"glob sanity: expected >=15 root .pine files, saw {checked}"
    assert problems == [], "\n".join(problems)


def test_dashboard_decode_helpers_stay_above_blocker_text() -> None:
    # Regression pin for the concrete incident: the two decoders must stay
    # ABOVE dashboard_compact_main_blocker_text.
    source = (REPO_ROOT / "SMC_Dashboard.pine").read_text(encoding="utf-8")
    blocker = source.index("dashboard_compact_main_blocker_text(int")
    assert source.index("decode_volume_data_text(int row_code) =>") < blocker
    assert source.index("decode_event_risk_text(int row_code) =>") < blocker

_IMPORT_RE = re.compile(r"^import preuss_steffen/smc_micro_profiles_generated/(\d+)\b", re.MULTILINE)
_TITLE_RE = re.compile(r"^(?:indicator|strategy)\(\s*\"[^\"]*\"\s*,\s*\"([^\"]*)\"", re.MULTILINE)


def test_consumer_library_imports_pin_one_real_version() -> None:
    """Incident 2026-07-13 (CE10272): every consumer pinned `/1` — TradingView
    increments the library version per publish (v164 at incident time), but the
    repin step read the generator manifest's HARDCODED `library_version: 1` and
    rewrote all imports back to the 2026-03 first publish. All consumers must
    pin the SAME version and never the stale-sentinel 1."""
    versions: dict[str, int] = {}
    for path in sorted(REPO_ROOT.glob(CONSUMER_PINE_GLOB)):
        match = _IMPORT_RE.search(path.read_text(encoding="utf-8"))
        if match:
            versions[path.name] = int(match.group(1))
    assert len(versions) >= 10, f"expected >=10 importing consumers, saw {len(versions)}"
    assert all(v != 1 for v in versions.values()), (
        f"consumers pinned to the stale v1 March library: "
        f"{[n for n, v in versions.items() if v == 1]}"
    )
    assert len(set(versions.values())) == 1, f"consumers pin diverging library versions: {versions}"


def test_root_pine_shorttitles_within_tradingview_limit() -> None:
    """TradingView rejects shorttitles longer than 10 characters
    (SHORT_TITLE_TOO_LONG) — latent until the script is next recompiled, which
    is exactly how 3 consumers accumulated over-long shorttitles unnoticed."""
    problems: list[str] = []
    for path in sorted(REPO_ROOT.glob(CONSUMER_PINE_GLOB)):
        for shorttitle in _TITLE_RE.findall(path.read_text(encoding="utf-8")):
            if len(shorttitle) > 10:
                problems.append(f"{path.name}: shorttitle {shorttitle!r} has {len(shorttitle)} chars (max 10)")
    assert problems == [], "\n".join(problems)

