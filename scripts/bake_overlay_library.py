#!/usr/bin/env python3
"""Bake the FAST overlay Pine library from the slow micro-profiles artifact.

Step-3 fast/slow split (Option A — coarse 2-library split). The heavy
structural micro-profile library ``smc_micro_profiles_generated`` (imported as
``mp``) stays on its slow publish cadence, while this module derives a
lightweight companion library ``smc_overlay_generated`` (imported as ``ov``)
that carries ONLY the high-cadence macro / news / calendar / layering fields.
The overlay can then be republished intraday through its own TradingView
publisher without reshipping the heavy structural ticker lists.

Design notes
------------
* The overlay is DERIVED from the already-generated main ``.pine`` artifact, so
  its baked values are byte-identical to the source library (no drift between
  the two libraries for shared fields).
* It does NOT re-run enrichment. Deriving from the source artifact alone means
  the overlay values only change when the source library is re-baked. For
  intraday-fresh overlay data the overlay enrichment would additionally need to
  be wired to the fast cadence — that is a deliberate, documented follow-on and
  is intentionally out of scope here so the proven generation / publish pipeline
  (``scripts/generate_smc_micro_profiles.py`` + ``scripts/smc_micro_publisher.py``)
  is left completely untouched.
* This module is self-contained: it imports nothing from the generation
  pipeline, so it carries zero regression risk to the slow path.

Usage
-----
    python -m scripts.bake_overlay_library \
        --source-pine pine/generated/smc_micro_profiles_generated.pine \
        --source-manifest pine/generated/smc_micro_profiles_generated.json \
        --out-pine pine/generated/smc_overlay_generated.pine \
        --out-manifest pine/generated/smc_overlay_generated.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path

OVERLAY_LIBRARY_NAME = "smc_overlay_generated"
DEFAULT_OWNER = "preuss_steffen"

# Section headers (verbatim from the generated library) whose fields make up
# the fast overlay. They appear CONTIGUOUSLY in emission order, terminated by
# the first non-overlay section ("// ── Provider Status ──").
OVERLAY_SECTION_MARKERS: tuple[str, ...] = (
    "// ── Market Regime ──",
    "// ── News Sentiment ──",
    "// ── Earnings & Macro Calendar ──",
    "// ── Layering / Global Tone ──",
)

# Human-readable section names (marker decoration stripped) for the manifest.
OVERLAY_SECTION_NAMES: tuple[str, ...] = tuple(
    m.strip("/ ").replace("── ", "").replace(" ──", "") for m in OVERLAY_SECTION_MARKERS
)

# Watermark fields lifted from the source Core/Meta section so the overlay
# library is self-describing about its bake freshness.
WATERMARK_FIELDS: tuple[str, ...] = ("ASOF_DATE", "ASOF_TIME")

# Expected overlay field set — the split contract. Kept explicit so the
# drift-guard test fails loudly if a field is added to / removed from an overlay
# section without a conscious update here. The bake itself is lenient (it copies
# whatever the overlay sections contain); this constant is the reviewed contract
# that tests assert against.
OVERLAY_FIELDS: frozenset[str] = frozenset(
    {
        # Market Regime
        "MARKET_REGIME",
        "VIX_LEVEL",
        "MACRO_BIAS",
        "MACRO_BIAS_RAW",
        "MACRO_BIAS_PE_ADJUSTMENT",
        "MARKET_PE_FORWARD",
        "MARKET_PE_REGIME",
        "SECTOR_BREADTH",
        # News Sentiment
        "NEWS_BULLISH_TICKERS",
        "NEWS_BEARISH_TICKERS",
        "NEWS_NEUTRAL_TICKERS",
        "NEWS_HEAT_GLOBAL",
        "TICKER_HEAT_MAP",
        "NEWS_CATEGORY_MAP",
        "NEWS_COUNT_MAP",
        "BREAKING_NEWS_TICKERS",
        "HIGH_IMPACT_NEWS_COUNT",
        "MOST_MENTIONED_TICKER",
        # Earnings & Macro Calendar
        "EARNINGS_TODAY_TICKERS",
        "EARNINGS_TOMORROW_TICKERS",
        "EARNINGS_BMO_TICKERS",
        "EARNINGS_AMC_TICKERS",
        "HIGH_IMPACT_MACRO_TODAY",
        "MACRO_EVENT_NAME",
        "MACRO_EVENT_TIME",
        # Layering / Global Tone
        "GLOBAL_HEAT",
        "GLOBAL_STRENGTH",
        "TONE",
        "TRADE_STATE",
    }
)

_SECTION_RE = re.compile(r"^// ── .+ ──\s*$")
_EXPORT_RE = re.compile(r"^export const \w+ (?P<field>[A-Z][A-Z0-9_]*) =")


def _find_export_line(lines: list[str], field: str) -> str | None:
    pat = re.compile(rf"^export const \w+ {re.escape(field)} =")
    for line in lines:
        if pat.match(line):
            return line
    return None


def _overlay_header(owner: str, version: int) -> list[str]:
    import_path = f"{owner}/{OVERLAY_LIBRARY_NAME}/{version}"
    return [
        "//@version=6",
        f'library("{OVERLAY_LIBRARY_NAME}")',
        "",
        "// ── Usage ──────────────────────────────────────────────────────",
        "// FAST overlay companion to smc_micro_profiles_generated (mp).",
        "//",
        f"// import {import_path} as ov",
        "//",
        "// Carries ONLY the high-cadence macro / news / calendar / layering",
        "// fields so it can be republished intraday without reshipping the",
        "// heavy structural micro-profile lists. Read fields as ov.FIELD_NAME,",
        "// e.g. ov.NEWS_HEAT_GLOBAL, ov.VIX_LEVEL, ov.TRADE_STATE.",
        "//",
        "// ASOF_DATE / ASOF_TIME mirror the source library bake watermark so",
        "// consumers can detect staleness. Generated artifact — do not edit.",
        "// ───────────────────────────────────────────────────────────────",
    ]


def select_overlay_lines(
    main_pine_text: str, *, owner: str = DEFAULT_OWNER, version: int = 1
) -> list[str]:
    """Derive the overlay ``.pine`` line list from the main library text.

    Pure function: walks the source library section by section and copies only
    the lines belonging to the overlay sections, prefixed with a fresh overlay
    header and the bake watermark. Raises ``ValueError`` if the source structure
    is unrecognisable (no overlay fields collected, or a watermark field is
    missing) so a malformed bake never silently ships an empty library.
    """
    src = main_pine_text.splitlines()
    out: list[str] = _overlay_header(owner, version)

    # Watermark first, in its own mini-section.
    out.append("")
    out.append("// ── Bake Watermark ──")
    for field in WATERMARK_FIELDS:
        line = _find_export_line(src, field)
        if line is None:
            raise ValueError(
                f"source library is missing required watermark field {field!r}"
            )
        out.append(line)

    current: str | None = None
    collected: set[str] = set()
    for line in src:
        if _SECTION_RE.match(line):
            current = line.strip()
            if current in OVERLAY_SECTION_MARKERS:
                out.append("")
                out.append(line)
            continue
        if current in OVERLAY_SECTION_MARKERS:
            match = _EXPORT_RE.match(line)
            if match:
                out.append(line)
                collected.add(match.group("field"))
            elif line.strip():
                # Preserve any non-blank, non-export line inside an overlay
                # section (defensive — current sections are export-only).
                out.append(line)
            # Intra-section blank lines are dropped; spacing is re-added per
            # section above for deterministic output.

    if not collected:
        raise ValueError(
            "no overlay fields collected — the source library section layout "
            "may have changed; check OVERLAY_SECTION_MARKERS"
        )

    out.append("")
    return out


def overlay_fields(overlay_lines: list[str]) -> set[str]:
    """Return the set of exported field names found in ``overlay_lines``.

    Includes the watermark fields; callers wanting only the split-contract
    fields should subtract :data:`WATERMARK_FIELDS`.
    """
    found: set[str] = set()
    for line in overlay_lines:
        match = _EXPORT_RE.match(line)
        if match:
            found.add(match.group("field"))
    return found


def build_overlay_manifest(
    main_manifest: dict,
    overlay_field_names: set[str],
    *,
    owner: str,
    version: int,
    out_pine: Path,
    source_pine: Path,
    source_manifest: Path,
) -> dict:
    """Build the overlay manifest mirroring the shape of the source manifest."""
    contract_fields = sorted(overlay_field_names - set(WATERMARK_FIELDS))
    return {
        "schema_version": main_manifest.get("schema_version"),
        "library_name": OVERLAY_LIBRARY_NAME,
        "library_owner": owner,
        "library_version": version,
        "recommended_import_path": f"{owner}/{OVERLAY_LIBRARY_NAME}/{version}",
        "pine_library": _as_posix(out_pine),
        "core_import_snippet": f"import {owner}/{OVERLAY_LIBRARY_NAME}/{version} as ov",
        "cadence_class": "fast_overlay",
        "derived_from_source_artifact": True,
        "source_library": main_manifest.get(
            "library_name", "smc_micro_profiles_generated"
        ),
        "source_pine_library": _as_posix(source_pine),
        "source_manifest": _as_posix(source_manifest),
        "asof_date": main_manifest.get("asof_date", ""),
        "asof_time": main_manifest.get("asof_time", ""),
        "overlay_sections": list(OVERLAY_SECTION_NAMES),
        "overlay_field_count": len(contract_fields),
        "overlay_fields": contract_fields,
        "watermark_fields": list(WATERMARK_FIELDS),
        "freshness_note": (
            "Overlay values mirror the source library bake (asof_date). For "
            "intraday-fresh overlay data, wire the overlay enrichment to the "
            "fast publish cadence; deriving from the source artifact alone does "
            "not refresh values between slow-cadence bakes."
        ),
    }


def _as_posix(path: Path | str) -> str:
    return str(path).replace("\\", "/")


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def bake(
    *,
    source_pine: Path,
    source_manifest: Path,
    out_pine: Path,
    out_manifest: Path,
    owner: str | None = None,
    version: int = 1,
) -> dict:
    """Derive and write the overlay ``.pine`` + manifest from the source pair."""
    source_pine = Path(source_pine)
    source_manifest = Path(source_manifest)
    out_pine = Path(out_pine)
    out_manifest = Path(out_manifest)

    main_text = source_pine.read_text(encoding="utf-8")
    main_manifest = json.loads(source_manifest.read_text(encoding="utf-8"))
    resolved_owner = owner or main_manifest.get("library_owner", DEFAULT_OWNER)

    overlay_lines = select_overlay_lines(
        main_text, owner=resolved_owner, version=version
    )
    field_names = overlay_fields(overlay_lines)
    contract_fields = field_names - set(WATERMARK_FIELDS)

    # Soft drift signal: never break the bake, but make the log loud so CI
    # surfaces a section/contract mismatch for review.
    missing = OVERLAY_FIELDS - contract_fields
    extra = contract_fields - OVERLAY_FIELDS
    if missing or extra:
        print(
            "WARNING: overlay field contract drift detected "
            f"(missing={sorted(missing)} extra={sorted(extra)}); "
            "update OVERLAY_FIELDS in scripts/bake_overlay_library.py",
            file=sys.stderr,
        )

    _atomic_write_text(out_pine, "\n".join(overlay_lines) + "\n")
    manifest = build_overlay_manifest(
        main_manifest,
        field_names,
        owner=resolved_owner,
        version=version,
        out_pine=out_pine,
        source_pine=source_pine,
        source_manifest=source_manifest,
    )
    _atomic_write_text(out_manifest, json.dumps(manifest, indent=2) + "\n")

    print(
        f"overlay: wrote {out_pine} ({len(overlay_lines)} lines, "
        f"{len(contract_fields)} fields) + {out_manifest} "
        f"(asof_date={manifest['asof_date'] or '<none>'})",
        file=sys.stderr,
    )
    return manifest


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Bake the fast overlay Pine library from the micro-profiles artifact."
    )
    parser.add_argument(
        "--source-pine",
        default="pine/generated/smc_micro_profiles_generated.pine",
        help="Path to the generated micro-profiles .pine library (default: %(default)s).",
    )
    parser.add_argument(
        "--source-manifest",
        default="pine/generated/smc_micro_profiles_generated.json",
        help="Path to the generated micro-profiles manifest (default: %(default)s).",
    )
    parser.add_argument(
        "--out-pine",
        default="pine/generated/smc_overlay_generated.pine",
        help="Output path for the overlay .pine library (default: %(default)s).",
    )
    parser.add_argument(
        "--out-manifest",
        default="pine/generated/smc_overlay_generated.json",
        help="Output path for the overlay manifest (default: %(default)s).",
    )
    parser.add_argument(
        "--library-owner",
        default=None,
        help="Override the TradingView library owner (default: from source manifest).",
    )
    parser.add_argument(
        "--library-version",
        type=int,
        default=1,
        help="Overlay library version number (default: %(default)s).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        bake(
            source_pine=args.source_pine,
            source_manifest=args.source_manifest,
            out_pine=args.out_pine,
            out_manifest=args.out_manifest,
            owner=args.library_owner,
            version=args.library_version,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
