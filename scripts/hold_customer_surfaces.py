#!/usr/bin/env python3
"""Hold customer surfaces at current-main content unless the change is pin-only.

Why this exists (incident 2026-08-12, PR #4646 / refresh run 1192): the library
refresh checks out ``main`` when it starts and can run for up to a day while it
waits for the TradingView publish. Committing a customer surface out of that
stale tree reverts whatever merged in between — #4639's operator-vocabulary
removal came back 59 seconds after its own merge, on a green bot PR, because
``bot/*`` diffs that touch only data + ``.pine`` skip the heavy gates.

Two mechanisms already answer parts of this, and this module is deliberately a
third, narrower one:

* ``scripts/check_pine_consumer_repin.py`` proves the BUMP step itself changed
  only the pin line — but it runs inside that step, so a later step that
  writes a customer surface is outside its window, and on a violation it can
  only fail a run whose library is already published (the committed-vs-
  published divergence the commit step documents).
* ``scripts/hold_r1_attested_sources.py`` restores the R1-attested companions
  unconditionally — even a pin bump is taken back, because an attested source
  may only move together with new evidence. Customer surfaces must NOT get
  that treatment: their pins have to keep advancing at refresh cadence.

So the customer surfaces get the hold PATTERN with a pin-only door: right
before the refresh commits, each surface is classified against CURRENT main
(the caller materialises ``git show FETCH_HEAD:<file>`` into ``--base-dir``,
exactly like the repin check — reading stays with the caller so this script
starts no process). A change that is ``identical`` or ``pin-only`` passes; an
``other`` change is restored to the current-main content and reported, which
keeps the refresh PR both honest and mergeable instead of red-after-publish.

The roster is NOT the R1 roster. ``attested_paths()`` membership carries
attestation duties (``scripts/check_r1_attested_sources.py`` compares every
contract target's hash against registered evidence, and every legitimate edit
then costs a mutating TradingView re-attestation session). Customer surfaces
carry no evidence artifacts, so they get a parallel roster here: the caller
passes every candidate its enumeration produced, this module excludes the
R1-held companions (their own, stricter hold owns them) and refuses to run
unless every rewritable customer surface named by
``scripts.check_customer_surface_vocabulary`` (the single source for
"customer surface") is present — an empty or shrunken roster is UNKNOWN,
never an all-clear.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Final

from scripts.smc_atomic_write import atomic_write_text

ROOT: Final = Path(__file__).resolve().parents[1]

#: One full import-pin line, any preuss_steffen library. The alias is optional
#: because Pine permits the alias-less form and the ownership guard
#: (tests/test_pine_pin_repin_ownership.py) measured that an alias-mandatory
#: pattern lets such a pin escape. Anything trailing the alias (a comment, a
#: second token) deliberately does NOT match: an unrecognised pin line makes
#: the reconstruction fail and the file is held — fail closed, never through.
_PIN_LINE_RE: Final = re.compile(
    r"^(?P<head>import[ \t]+preuss_steffen/(?P<lib>[A-Za-z0-9_]+)/)"
    r"(?P<version>\d+)"
    r"(?P<tail>(?:[ \t]+as[ \t]+(?P<alias>\w+))?[ \t]*)$",
    re.MULTILINE,
)


#: What ANY automated publish path may rewrite, restated as a per-file test.
#: Both writers rewrite exclusively owner import-pin lines (the refresh
#: bump's PIN_PATTERN in smc-library-publish.yml and repinAllConsumers in
#: scripts/tv_publish_hand_authored_libraries.ts), so "carries an owner
#: import" is exactly "some publish path can write this file". Loose on
#: purpose — bare prefix, no version shape: a pin form the classifier cannot
#: reconstruct must still make the file required, where it is then held on
#: any change (fail closed), never silently out of scope. Until 2026-08-28
#: this tested only the generated-library pin (the refresh bump's own
#: filter); the handlibs publish rewrites hand-library pins in surfaces
#: without any generated pin (SMC_Breakout_Overlay.pine pins only
#: smc_engine_private), and those ran unheld — the #5145 gap.
_OWNER_IMPORT_RE: Final = re.compile(
    r"^import[ \t]+preuss_steffen/", re.MULTILINE
)

#: The four surfaces of the paid 2026-08-12 incident (#4646). The derivation
#: below must never lose one of them — a hard floor under the derived list,
#: because a derived list without a floor cannot catch its own drift.
_INCIDENT_SURFACES: Final = frozenset({
    "SMC_Long_Dip_Suite.pine",
    "SMC_Long_Dip_Dashboard.pine",
    "SMC_Long_Dip_Mobile.pine",
    "SMC_Long_Dip_Alerts.pine",
})


def required_customer_surfaces(repo: Path = ROOT) -> list[str]:
    """The customer surfaces this hold must never run without.

    Derived (2026-08-28), not restated: start from the vocabulary guard's
    roster (``PINE_FILES``, the single definition of "customer surface" — 4
    files until the Chart-Link completion grew it to 8), keep the surfaces
    some publish path can actually rewrite (they carry an owner import pin
    in the tree this run operates on — see ``_OWNER_IMPORT_RE`` for why the
    generated-pin-only filter was the #5145 gap), and drop the R1-attested
    companions, which the stricter unconditional hold owns. Without the pin
    filter the floor check would demand surfaces no enumeration can produce
    (``SMC_Setup_Check.pine`` imports nothing) and every refresh would die on
    a fail-closed error about a file it could not have touched.
    """
    # Imported here rather than at module scope for the same reason as in
    # scripts/hold_r1_attested_sources.py: the workflow runs this file as
    # ``python -m scripts.hold_customer_surfaces`` from the checkout root, so
    # the package import works without touching sys.path.
    from scripts.check_customer_surface_vocabulary import PINE_FILES
    from scripts.hold_r1_attested_sources import attested_paths

    attested = set(attested_paths())
    required = []
    for name in sorted(PINE_FILES):
        if name in attested:
            continue
        surface = repo / name
        if not surface.is_file():
            # Not in this tree (possible mid-run rename on main): the fresh
            # candidate enumeration still covers it; it cannot be required
            # of a tree that does not carry it.
            continue
        if _OWNER_IMPORT_RE.search(surface.read_text(encoding="utf-8")):
            required.append(name)
    missing_floor = _INCIDENT_SURFACES - set(required)
    if missing_floor:
        raise ValueError(
            "derived customer-surface roster lost incident surface(s) "
            + ", ".join(sorted(missing_floor))
            + " — refusing to run with a floor below the #4646 population"
        )
    return required


def held_customer_surfaces(candidates: list[str], repo: Path = ROOT) -> list[str]:
    """The roster this run will hold: candidates minus the R1-attested set.

    The R1 companions have their own, STRICTER hold (unconditional restore,
    ``scripts/hold_r1_attested_sources.py``) that runs in the same workflows;
    classifying them here as ``pin-only`` would re-open the door that hold
    closes. Fails closed when the four customer surfaces are not all present:
    a roster that silently lost a surface would report a clean all-clear for
    a file it never looked at.
    """
    from scripts.hold_r1_attested_sources import attested_paths

    attested = set(attested_paths())
    roster = sorted({c for c in candidates if c not in attested})
    missing = [s for s in required_customer_surfaces(repo) if s not in roster]
    if missing:
        raise ValueError(
            "customer-surface roster is missing "
            + ", ".join(missing)
            + " — refusing to hold a population that lost a customer surface"
        )
    return roster


def _pin_map(text: str) -> dict[tuple[str, str | None], str] | None:
    """``{(library, alias): version}`` — or None when the map is ambiguous."""
    pins: dict[tuple[str, str | None], str] = {}
    for match in _PIN_LINE_RE.finditer(text):
        key = (match.group("lib"), match.group("alias"))
        if key in pins and pins[key] != match.group("version"):
            return None
        pins[key] = match.group("version")
    return pins


def classify_pin_only_change(base_text: str, current_text: str) -> str:
    """``identical`` | ``pin-only`` | ``other`` — by reconstruction, not diff.

    The same pattern as ``classify_event_overlay_change`` in
    ``scripts/smc_r1_generate_attestation.py``, generalised: that classifier
    knows the Event Overlay's single micro-profile pin, while a customer
    surface carries between one and ten ``import preuss_steffen/...`` pins
    (SMC_Long_Dip_Suite.pine has ten). ``pin-only`` holds exactly when
    swapping every current pin back to the base's version for the same
    (library, alias) reproduces the base text byte for byte. Everything else —
    a changed line, an added or removed line, an added or removed import, a
    pin line this pattern does not recognise — is ``other``.
    """
    if current_text == base_text:
        return "identical"
    base_pins = _pin_map(base_text)
    if not base_pins:
        # No pin in the base: not a consumer, nothing a refresh may change.
        # An ambiguous base (same library+alias at two versions) lands here
        # too — reconstruction would have to guess, and a guess is not proof.
        return "other"

    unknown_pin = False

    def _swap_back(match: re.Match[str]) -> str:
        nonlocal unknown_pin
        key = (match.group("lib"), match.group("alias"))
        if key not in base_pins:
            unknown_pin = True
            return match.group(0)
        return f"{match.group('head')}{base_pins[key]}{match.group('tail')}"

    reconstructed = _PIN_LINE_RE.sub(_swap_back, current_text)
    if unknown_pin:
        return "other"
    return "pin-only" if reconstructed == base_text else "other"


def hold(
    paths: list[str], *, base_dir: Path, repo: Path
) -> tuple[list[str], list[str]]:
    """Restore every non-pin-only surface to its base content.

    Returns ``(held, advanced)``: ``held`` are the files restored to the
    ``--base-dir`` content (current main), ``advanced`` the files whose change
    was pin-only and therefore kept. A candidate missing from ``base_dir`` is
    a caller bug — the caller derived the candidates FROM the base ref — and
    raises rather than being skipped as if it had been checked.
    """
    held: list[str] = []
    advanced: list[str] = []
    for path in paths:
        base_file = base_dir / path
        if not base_file.is_file():
            raise FileNotFoundError(
                f"{path} has no base copy under {base_dir} — the caller "
                "derived the candidates from the base ref, so a missing base "
                "means the materialisation step is broken, not that the file "
                "is clean"
            )
        base_text = base_file.read_text(encoding="utf-8")
        work_file = repo / path
        if not work_file.is_file():
            # A refresh never deletes a customer surface; restore it.
            atomic_write_text(base_text, work_file)
            held.append(path)
            continue
        verdict = classify_pin_only_change(
            base_text, work_file.read_text(encoding="utf-8")
        )
        if verdict == "pin-only":
            advanced.append(path)
        elif verdict == "other":
            atomic_write_text(base_text, work_file)
            held.append(path)
    return held, advanced


def render_notice(held: list[str]) -> str:
    listed = "\n".join(f"- `{path}`" for path in held)
    return (
        "## Customer surfaces held at current-main content\n"
        "\n"
        "This refresh changed the file(s) below beyond the library import\n"
        "pin(s), so they were restored to the content of current `main`\n"
        "(measured at hold time) and are NOT advanced by this PR:\n"
        "\n"
        f"{listed}\n"
        "\n"
        "A library refresh may change exactly one thing in a customer\n"
        "surface: the pinned import version. Anything else in its working\n"
        "tree is either another change merged to `main` mid-run (committing\n"
        "the stale copy would revert it — the 2026-08-12 #4646 incident) or\n"
        "an unexpected write by a workflow step. Holding keeps this PR\n"
        "honest and mergeable; the held file simply advances its pin with\n"
        "the next refresh.\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-dir",
        required=True,
        type=Path,
        help="directory holding the current-main copies the caller wrote via "
        "`git show FETCH_HEAD:<file>` — reading stays with the caller so this "
        "script starts no process (same seam as check_pine_consumer_repin.py)",
    )
    parser.add_argument(
        "--repo",
        default=str(ROOT),
        help="repository working tree to operate on (default: this checkout)",
    )
    parser.add_argument(
        "--github-output",
        default=os.environ.get("GITHUB_OUTPUT"),
        help="write `held` / `notice` outputs here (default: $GITHUB_OUTPUT)",
    )
    parser.add_argument("candidates", nargs="+")
    args = parser.parse_args(argv)

    try:
        roster = held_customer_surfaces(
            args.candidates, repo=Path(args.repo).resolve()
        )
    except ValueError as error:
        print(f"::error::{error}", file=sys.stderr)
        return 1

    held, advanced = hold(
        roster, base_dir=args.base_dir.resolve(), repo=Path(args.repo).resolve()
    )
    for path in advanced:
        print(f"pin-only change kept: {path}")
    if not held:
        print(f"No customer surface held ({len(roster)} checked).")
    else:
        for path in held:
            print(f"held at current-main content: {path}")

    if args.github_output:
        notice = render_notice(held) if held else ""
        with Path(args.github_output).open("a", encoding="utf-8") as handle:
            handle.write(f"held={json.dumps(held)}\n")
            # Heredoc with a delimiter grown past any collision, exactly as in
            # hold_r1_attested_sources: the notice is multi-line.
            delimiter = "SURFACEHOLD_EOF"
            while delimiter in notice:
                delimiter += "_X"
            handle.write(f"notice<<{delimiter}\n{notice}\n{delimiter}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
