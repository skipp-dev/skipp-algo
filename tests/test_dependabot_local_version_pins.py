"""Dependabot must not manage a dependency that is pinned with a local version.

Measured 2026-08-04. ``torch`` is pinned across two deliberately different lanes
in the root directory:

* ``requirements-rl.txt`` — the PyPI lane, pinning a plain ``torch==2.12.1``.
* ``requirements-rl-gpu.txt`` — the CUDA lane, carrying the repo's only approved
  non-PyPI index (the PyTorch CDN, SC-03 allowlist) and pinning
  ``torch==2.12.1+cu129``.

Dependabot resolves ``torch`` through that index and then writes the resolved
string into BOTH files. #4424 and #4427 independently produced
``torch==2.13.0+cu129`` in the PyPI lane — a PEP 440 local version that cannot
exist on PyPI (verified against the PyPI JSON API: 49 ``torch`` releases, zero
with a local version), so ``pip install -r requirements-rl.txt`` could not
resolve, and the two-lane split the file documents collapsed silently.

The repair is an ``ignore`` entry per Python ecosystem covering that directory.
This guard holds it open, and generalises: any future locally-versioned pin —
``+rocm``, ``+cpu``, a vendored build — is caught the same way, in whatever
directory it appears.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import yaml

# A pin carrying a PEP 440 local version, e.g. `torch==2.12.1+cu129`.
# The optional bracket group skips extras (`pkg[extra]==1.0+cu129`): they are
# not part of the name Dependabot ignores, and without the group such a pin
# would silently escape the guard — review finding on #4436, verified
# fail-open end-to-end before the fix.
_LOCAL_VERSION_PIN = re.compile(
    r"^(?P<name>[A-Za-z0-9._-]+)(?:\[[^\]]*\])?\s*==\s*[^\s#]*\+[^\s#]+"
)


def _normalize(name: str) -> str:
    """PEP 503 name normalization, applied to both sides of the comparison.

    Dependabot treats `foo_bar` and `foo-bar` as the same package; comparing
    raw lowercased strings would flag an ignore that actually works. The
    mismatch direction is fail-closed (a false alarm, not a silent pass), but
    a guard that cries wolf gets deleted.
    """
    return re.sub(r"[-_.]+", "-", name.lower())

# Ecosystems that resolve Python dependencies. github-actions and npm cannot
# produce a PEP 440 local version, so they are out of scope by construction.
_PYTHON_ECOSYSTEMS = frozenset({"pip", "uv"})


def _repo_root() -> Path:
    return Path(
        subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    )


def _requirements_files(root: Path) -> list[Path]:
    """Every tracked requirements file, from git rather than a directory walk.

    A walk would pick up untracked scratch files and virtualenvs; git answers
    about the tree Dependabot actually sees.

    Deliberately NOT scanned: `uv.lock` / `pyproject.toml`, the uv ecosystem's
    native manifests. Locked versions there are resolver output, not
    hand-written pins, and the measured failure (#4424/#4427) was Dependabot
    rewriting requirements files. The uv entry's torch ignore is justified by
    that measurement — do not "simplify" it away because this scan does not
    reach uv.lock.
    """
    listing = subprocess.run(
        ["git", "ls-files", "-z"],
        capture_output=True,
        text=True,
        check=True,
        cwd=root,
    ).stdout
    tracked = [entry for entry in listing.split("\0") if entry]
    return [
        root / name
        for name in tracked
        if re.fullmatch(r"(.*/)?requirements.*\.(txt|lock)", name)
    ]


def _dependabot_directory_of(path: Path, root: Path) -> str:
    """The `directory` value Dependabot uses for a manifest at ``path``."""
    parent = path.parent.relative_to(root).as_posix()
    return "/" if parent == "." else f"/{parent}"


def _local_version_pins(root: Path) -> dict[str, set[str]]:
    """Map each locally-versioned dependency to the directories it appears in."""
    found: dict[str, set[str]] = {}
    for path in _requirements_files(root):
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith(("#", "-")):
                continue
            match = _LOCAL_VERSION_PIN.match(line)
            if match:
                name = _normalize(match.group("name"))
                found.setdefault(name, set()).add(_dependabot_directory_of(path, root))
    return found


def _python_ecosystem_entries(root: Path) -> list[tuple[str, set[str], set[str]]]:
    """``(ecosystem, covered directories, ignored dependency names)`` per entry."""
    config = yaml.safe_load(
        (root / ".github" / "dependabot.yml").read_text(encoding="utf-8")
    )
    entries: list[tuple[str, set[str], set[str]]] = []
    for update in config["updates"]:
        ecosystem = update["package-ecosystem"]
        if ecosystem not in _PYTHON_ECOSYSTEMS:
            continue
        # Both spellings are legal and this file uses both: `directory` for a
        # single path, `directories` for a list.
        directories = set(update.get("directories") or [])
        if "directory" in update:
            directories.add(update["directory"])
        # Dependabot also accepts glob patterns here ("/services/*"). The
        # exact-string intersection below would go EMPTY against a glob and
        # silently stop seeing the entry as covering anything — the guard
        # would disarm itself. Fail loudly instead; whoever introduces globs
        # must teach this guard to expand them.
        globbed = sorted(d for d in directories if any(c in d for c in "*?["))
        assert not globbed, (
            f"dependabot.yml '{ecosystem}' entry uses glob directories "
            f"{globbed}; this guard matches directories exactly and would "
            "fail open. Expand the globs here before relying on them."
        )
        ignored = {
            _normalize(str(rule["dependency-name"]))
            for rule in update.get("ignore") or []
            if "dependency-name" in rule
        }
        entries.append((ecosystem, directories, ignored))
    return entries


def test_a_locally_versioned_pin_is_ignored_in_every_ecosystem_covering_it() -> None:
    """The invariant. A local version means the pin is not resolvable from PyPI."""
    root = _repo_root()
    pins = _local_version_pins(root)
    entries = _python_ecosystem_entries(root)

    unguarded: list[str] = []
    for name, directories in sorted(pins.items()):
        for ecosystem, covered, ignored in entries:
            overlap = directories & covered
            if overlap and name not in ignored:
                unguarded.append(
                    f"  {name}: pinned with a local version in "
                    f"{sorted(overlap)} but not ignored by the "
                    f"'{ecosystem}' ecosystem entry covering it"
                )

    assert not unguarded, (
        "Dependabot manages a dependency that is pinned with a PEP 440 local "
        "version:\n"
        + "\n".join(unguarded)
        + "\n\nIt resolves such a dependency through the alternate index and "
        "writes the resolved string into every manifest in the directory — "
        "including ones installed from PyPI, where a local version cannot "
        "exist. Add an `ignore: - dependency-name: <name>` entry to that "
        "ecosystem, or remove the local version from the pin."
    )


def test_the_guard_has_something_to_guard() -> None:
    """Anti-vacuity: with no locally-versioned pin the test above proves nothing.

    If this ever fails because the last local-version pin was removed, delete
    both tests and the `ignore` entries with them — a guard over an empty set
    reads as coverage it does not have.
    """
    pins = _local_version_pins(_repo_root())
    assert pins, (
        "no requirements file pins a PEP 440 local version any more, so the "
        "invariant above passes over an empty set"
    )
    assert "torch" in pins, (
        f"expected torch among the locally-versioned pins, found: {sorted(pins)}"
    )


def test_the_pypi_lane_still_pins_a_plain_torch() -> None:
    """The half that broke, guarded directly.

    ``tests/test_rl_gpu_requirements.py`` pins the CUDA lane's exact string, so
    the GPU file could not drift unnoticed. Nothing watched the PyPI lane —
    which is the file #4424 would have made unresolvable.
    """
    root = _repo_root()
    lines = (root / "requirements-rl.txt").read_text(encoding="utf-8").splitlines()
    pins = [line.strip() for line in lines if line.strip().startswith("torch==")]

    assert len(pins) == 1, f"expected exactly one torch pin, found: {pins}"
    assert "+" not in pins[0], (
        f"requirements-rl.txt pins {pins[0]!r}. This lane installs from PyPI, "
        "where no local version exists; the CUDA build is layered on top by "
        "requirements-rl-gpu.txt on the GPU runner only."
    )
