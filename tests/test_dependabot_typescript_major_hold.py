"""Dependabot must not auto-bump a package whose API this repo parses with.

Measured 2026-08-04. #4426 proposed ``typescript`` 5.9.3 -> 7.0.2 as part of the
grouped npm update and turned four checks red at once — fast-gates, Windows x64,
macOS Intel, macOS Apple Silicon.

TypeScript 7 removes the compiler API from the package root. Its ``exports`` map
resolves ``"."`` to ``./lib/version.cjs`` — the version string and nothing else —
so ``import ts from "typescript"`` in ``scripts/detect_vacuous_claims_ts.ts``
returns a module with no ``ScriptTarget``. At runtime that is
``Cannot read properties of undefined (reading 'Latest')``; under ``tsc`` it is
every ``ts.*`` reported as missing from namespace ``typescript/lib/version``.

The API moved to ``typescript/unstable/*``, and that surface does not carry this
script. Probed against the real 7.0.2 install: ``forEachChild`` exists in NO
subpath (``unstable/ast/visitor`` has only ``forEachChildOfJSDoc*``,
``visitEachChild``, ``visitNode``), and the only ``createSourceFile`` is the
FACTORY one in ``unstable/ast/factory``, which builds a node rather than parsing
text. Porting the vacuity detector would mean rewriting it onto a surface
upstream itself labels "unstable", for a guard that gates merges.

DERIVED, not hand-maintained: the hold is only demanded while something in the
repo actually imports the compiler API. Delete or rewrite that import and this
guard stops asking — the same shape as
``tests/test_dependabot_local_version_pins.py``, which generalises rather than
naming one package forever.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import yaml

# `import ts from "typescript"` / `import * as ts from 'typescript'` /
# `require("typescript")` -- the root import, which is exactly the one TS7 broke.
# A subpath import (`typescript/unstable/...`) deliberately does NOT match: that
# is what a port to the new surface would look like, and it would retire this.
_ROOT_TS_IMPORT = re.compile(
    r"""(?:from\s*|require\(\s*)["']typescript["']""",
)

_MAJOR = "version-update:semver-major"


def _repo_root() -> Path:
    return Path(
        subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    )


def _sources_importing_typescript_root() -> list[Path]:
    root = _repo_root()
    hits: list[Path] = []
    for directory in ("scripts", "automation"):
        base = root / directory
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.ts")):
            if "node_modules" in path.parts:
                continue
            if _ROOT_TS_IMPORT.search(path.read_text(encoding="utf-8", errors="ignore")):
                hits.append(path)
    return hits


def _npm_ecosystem_blocks() -> list[dict]:
    config = yaml.safe_load((_repo_root() / ".github" / "dependabot.yml").read_text(encoding="utf-8"))
    return [u for u in (config.get("updates") or []) if u.get("package-ecosystem") == "npm"]


def test_the_repo_still_imports_the_compiler_api() -> None:
    """The premise, asserted rather than assumed.

    If this fails, nothing imports ``typescript`` at the root any more and the
    hold below is obsolete: drop the ``ignore`` entry and this file together
    instead of carrying a rule whose reason has gone.
    """
    importers = _sources_importing_typescript_root()
    assert importers, (
        "no .ts file under scripts/ or automation/ imports the typescript "
        "package root any more. The TS7 incompatibility this guard holds open "
        "no longer applies — remove the dependabot ignore entry and this file."
    )


def test_npm_ecosystem_holds_typescript_majors() -> None:
    """Every npm ecosystem entry must ignore typescript majors.

    Per entry, not once globally: ``ignore`` is scoped to the ecosystem block it
    sits in, so a second npm block added later (a new directory) would be
    unguarded while this file still passed.
    """
    blocks = _npm_ecosystem_blocks()
    assert blocks, "dependabot.yml declares no npm ecosystem at all"

    unguarded: list[str] = []
    for block in blocks:
        dirs = block.get("directories") or [block.get("directory", "?")]
        entries = [
            entry
            for entry in (block.get("ignore") or [])
            if entry.get("dependency-name") == "typescript"
        ]
        if not entries:
            unguarded.append(f"{dirs}: no ignore entry for typescript")
            continue
        if not any(_MAJOR in (entry.get("update-types") or []) for entry in entries):
            unguarded.append(f"{dirs}: typescript is ignored, but not for {_MAJOR}")

    assert not unguarded, (
        "typescript majors are not held in every npm ecosystem block, so "
        "Dependabot can propose TypeScript 7 again. It removes the compiler API "
        "from the package root (exports '.' -> ./lib/version.cjs), which breaks "
        "scripts/detect_vacuous_claims_ts.ts and with it the TypeScript vacuity "
        "guard on the required path:\n  " + "\n  ".join(unguarded)
    )


def test_the_hold_is_narrow() -> None:
    """Only the MAJOR is held. Minor and patch updates must keep flowing.

    A blanket ``dependency-name: typescript`` with no ``update-types`` would
    also silence 5.9.x security and bugfix releases, and would still pass the
    test above's first branch — so the narrowness is asserted separately.

    Counted, because a loop over a filtered list is exactly the shape that
    reports green having looked at nothing: with no typescript entry anywhere
    the body below never runs. The repo's own vacuity guard caught this test in
    that state on 2026-08-04, before it was ever pushed.
    """
    blocks = _npm_ecosystem_blocks()
    assert blocks, "dependabot.yml declares no npm ecosystem, so this loop would pass vacuously"

    checked = 0
    for block in blocks:
        for entry in block.get("ignore") or []:
            if entry.get("dependency-name") != "typescript":
                continue
            checked += 1
            types = entry.get("update-types")
            assert types, (
                "the typescript ignore entry has no update-types, so it blocks "
                "MINOR and PATCH updates too — including security fixes on the "
                "5.9 line this repo runs."
            )
            assert set(types) == {_MAJOR}, (
                f"the typescript hold covers {sorted(types)}; it must cover "
                f"exactly [{_MAJOR}] — the incompatibility is the major, and "
                "nothing else is known to break."
            )
    assert checked, (
        "no typescript ignore entry was examined at all, so this test proved "
        "nothing about how narrow the hold is."
    )
