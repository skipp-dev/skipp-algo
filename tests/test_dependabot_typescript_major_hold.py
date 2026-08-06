"""Dependabot must not auto-bump a package whose API this repo parses with.

Measured 2026-08-04. #4426 proposed ``typescript`` 5.9.3 -> 7.0.2 as part of the
grouped npm update and turned four checks red at once — fast-gates, Windows x64,
macOS Intel, macOS Apple Silicon.

The repo runs ``typescript@^6.0.3`` since 2026-08-05 — the last release built on
the JavaScript codebase, and the version upstream designates as the bridge to 7.
It still exposes the classic API at the package root, so this hold is what keeps
the 7.x major out; see ``.github/dependabot.yml`` for why the bridge is plain
``typescript@6`` rather than the ``@typescript/typescript6`` alias.

TypeScript 7 removes the compiler API from the package root. Its ``exports`` map
resolves ``"."`` to ``./lib/version.cjs`` — the version string and nothing else —
so ``import ts from "typescript"`` in ``scripts/detect_vacuous_claims_ts.ts``
returns a module with no ``ScriptTarget``. At runtime that is
``Cannot read properties of undefined (reading 'Latest')``; under ``tsc`` it is
every ``ts.*`` reported as missing from namespace ``typescript/lib/version``.

The API moved to ``typescript/unstable/*``, and a port is a rewrite rather than
a re-import. Corrected 2026-08-05 after a review re-probed the real 7.0.2
install and caught this docstring overstating its case — the earlier wording
claimed ``forEachChild`` "exists in NO subpath", which is false. What is
actually true, re-measured:

* ``forEachChild`` is no longer an exported FREE function (``unstable/ast`` does
  not export it; ``unstable/ast/visitor`` has only ``forEachChildOfJSDoc*``,
  ``visitEachChild``, ``visitNode``). It survives as a Node METHOD —
  ``dist/ast/ast.d.ts:40`` declares it and ``NodeObject.prototype.forEachChild``
  is a function — so every ``ts.forEachChild(node, cb)`` call site becomes
  ``node.forEachChild(cb)``.
* ``createSourceFile`` under ``unstable/ast/factory`` is the FACTORY, which
  builds a node from parts.
* ``isStringLiteralLike`` is renamed ``isStringLiteralLikeNode``.

How parsing actually works in 7.0.2, corrected 2026-08-05 by unpacking the
wheel. An earlier revision of this docstring asserted ``API`` → ``Project`` →
``program.getSourceFile()`` as if it were sourced; it was an inference from the
type declarations, it skipped a mandatory step, and ``API`` has no
``getSourceFile`` on it at all. ``dist/api/sync/api.d.ts`` declares:

    API → updateSnapshot() → Snapshot → getProject(configFileName)
        | getDefaultProjectForFile() → Project → .program
        → Program.getSourceFile()

Five hops, anchored on a config file, over an out-of-process client. There is
also no lighter route, which is the part that decides the size of a port: no
free-standing parse function is declared in ANY ``.d.ts`` in the wheel, and
``unstable/ast`` (``dist/ast/index.d.ts``) re-exports ast, astnav, clone, is,
jsdoc, scanner, utils and visitor — there is no parser module. ``scanner``
tokenises; it does not return a ``SourceFile``.

So the hold rests on a rewrite, not an absence. Re-proved 2026-08-05 by
installing 7.0.2 over the working tree: 25 of the 28 tests in
``automation/tradingview/tests/vacuous_claims_ts.test.ts`` fail with
``Cannot read properties of undefined (reading 'Latest')``, and
``tsc --noEmit`` reports 111 ``TS2694`` errors against namespace
``typescript/lib/version``.

Two measurements that bound how long this stays true, so nobody re-derives
them:

* The ``unstable/*`` key set is IDENTICAL across 7.0.1-rc, 7.0.2 and the
  7.1.0-dev.20260805.1 nightly (eleven subpaths — ``ast/clone`` is easy to
  miss). But ``exports["."]`` was ADDED between 7.0.1-rc and 7.0.2, a patch
  bump: the map is demonstrably edited at patch level, and upstream has
  published no semver promise about these subpaths in either direction.
* No migration aid exists to lean on. Searched 2026-08-05: upstream publishes
  no migration notes, no codemod and no shim for any of the three shape
  changes above, and ``microsoft/typescript-go#4393`` — a user reporting
  exactly this breakage against 7.0.1-rc — was closed as *Not planned*. The
  ``typescript-go`` README rates the API "not ready ... you shouldn't bother
  messing with it yet". So a port would be unassisted, which is the other half
  of why the bridge is the cheaper move.
* Nobody in the ecosystem has ported. ``@typescript-eslint/typescript-estree``
  8.66.0 declares ``peerDependencies: typescript ">=4.8.4 <6.1.0"`` — 7 is
  excluded. ``@microsoft/api-extractor`` 7.58.12 pins ``typescript: "5.9.3"``
  exactly. ``ts-morph`` 28.0.0 and ``@ts-morph/common`` 0.29.0 declare no
  ``typescript`` dependency at all — they vendor it. ``jscodeshift`` parses via
  ``@babel/preset-typescript``, and Biome and oxc-parser carry no
  ``typescript`` dependency, so all three are unaffected rather than migrated.

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
