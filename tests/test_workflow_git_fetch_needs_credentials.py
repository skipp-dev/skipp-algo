"""A ``git fetch origin`` inside a ``persist-credentials: false`` job cannot work.

``actions/checkout`` strips the auth header after checkout when
``persist-credentials: false``, so ``origin`` carries no credentials and any
later fetch against it dies with::

    fatal: could not read Username for 'https://github.com': No such device or
    address

Measured 2026-08-14, run 31793906137, exit 128: the "Bump library version in
all pine consumers" step died there, which skipped "Commit and push changes"
behind it, which is why TradingView advanced to 238 while the repository stayed
pinned at 230 and fourteen consumers drifted.

The fetch itself arrived with #4653 and was correct in intent -- read the
consumers from current ``main`` rather than from a day-old working tree. It
simply never ran: the shared TradingView queue was saturated from that merge
until 2026-08-14, so the step did not reach a runner once. A review could not
have caught it by running the suite either, because nothing checked this class.

This guard checks it over the WHOLE workflow corpus rather than the one file
that happened to break.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

_WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"

# `git fetch [flags] origin ...` -- a bare remote NAME, not a URL.
_BARE_ORIGIN_FETCH = re.compile(r"\bgit\s+fetch\b[^\n|&]*?\borigin\b")
# The two ways a step may legitimately arm the remote first.
_ARMS_REMOTE = re.compile(r"git\s+remote\s+set-url\s+origin|x-access-token")


def _workflow_files() -> list[Path]:
    files = sorted(p for p in _WORKFLOWS.glob("*.yml"))
    assert len(files) >= 30, (
        f"workflow corpus collapsed: found {len(files)} files under {_WORKFLOWS}. "
        "This guard would otherwise scan almost nothing and report green."
    )
    return files


def _jobs_without_persisted_credentials(doc: dict) -> dict[str, list[dict]]:
    """Jobs whose checkout explicitly drops credentials, with their steps."""
    out: dict[str, list[dict]] = {}
    for job_name, job in (doc.get("jobs") or {}).items():
        if not isinstance(job, dict):
            continue
        steps = job.get("steps") or []
        drops = any(
            isinstance(s, dict)
            and str(s.get("uses", "")).startswith("actions/checkout@")
            and (s.get("with") or {}).get("persist-credentials") is False
            for s in steps
        )
        if drops:
            out[job_name] = [s for s in steps if isinstance(s, dict)]
    return out


def _offending_steps(path: Path) -> list[str]:
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        return []
    offenders: list[str] = []
    for job_name, steps in _jobs_without_persisted_credentials(doc).items():
        # `git remote set-url` persists for the whole job, so an EARLIER step
        # may legitimately arm the remote for a later fetch — that is exactly
        # what smc-library-refresh's "Configure git credentials for metrics
        # push" does. Scanning one step in isolation would report it as broken.
        armed = False
        for step in steps:
            run = step.get("run")
            if not isinstance(run, str):
                continue
            if _BARE_ORIGIN_FETCH.search(run) and not armed and not _ARMS_REMOTE.search(run):
                offenders.append(f"{path.name}:{job_name}:{step.get('name', '<unnamed>')}")
            if _ARMS_REMOTE.search(run):
                armed = True
    return offenders


@pytest.mark.parametrize("path", _workflow_files(), ids=lambda p: p.name)
def test_no_unauthenticated_origin_fetch_in_a_credential_less_job(path: Path) -> None:
    offenders = _offending_steps(path)
    assert not offenders, (
        "these steps fetch from a bare `origin` inside a job whose checkout ran "
        "with persist-credentials: false, so the fetch cannot authenticate:\n  "
        + "\n  ".join(offenders)
        + "\nFetch through an explicit token URL "
        '("https://x-access-token:${GITHUB_TOKEN}@github.com/${GITHUB_REPOSITORY}.git") '
        "or arm the remote with `git remote set-url origin` first, as "
        '"Commit and push changes" already does.'
    )


def test_the_guard_actually_recognises_the_defect(tmp_path: Path) -> None:
    """Executed against a synthetic workflow, so the rule cannot rot into a no-op."""
    broken = tmp_path / "broken.yml"
    broken.write_text(
        "jobs:\n"
        "  build:\n"
        "    steps:\n"
        "      - uses: actions/checkout@v4\n"
        "        with:\n"
        "          persist-credentials: false\n"
        "      - name: fetch it\n"
        "        run: git fetch --quiet origin main\n",
        encoding="utf-8",
    )
    assert _offending_steps(broken) == ["broken.yml:build:fetch it"]

    fixed = tmp_path / "fixed.yml"
    fixed.write_text(
        "jobs:\n"
        "  build:\n"
        "    steps:\n"
        "      - uses: actions/checkout@v4\n"
        "        with:\n"
        "          persist-credentials: false\n"
        "      - name: fetch it\n"
        '        run: git fetch --quiet "https://x-access-token:${TOKEN}@github.com/o/r.git" main\n',
        encoding="utf-8",
    )
    assert _offending_steps(fixed) == []

    kept = tmp_path / "kept.yml"
    kept.write_text(
        "jobs:\n"
        "  build:\n"
        "    steps:\n"
        "      - uses: actions/checkout@v4\n"
        "      - name: fetch it\n"
        "        run: git fetch --quiet origin main\n",
        encoding="utf-8",
    )
    assert _offending_steps(kept) == [], "a job that keeps its credentials is fine"


def test_an_earlier_arming_step_in_the_same_job_counts(tmp_path: Path) -> None:
    """`git remote set-url` persists for the job, so it may live in its own step."""
    doc = tmp_path / "armed-earlier.yml"
    doc.write_text(
        "jobs:\n"
        "  build:\n"
        "    steps:\n"
        "      - uses: actions/checkout@v4\n"
        "        with:\n"
        "          persist-credentials: false\n"
        "      - name: arm it\n"
        "        run: git remote set-url origin https://x@github.com/o/r.git\n"
        "      - name: fetch it\n"
        "        run: git fetch --quiet origin main\n",
        encoding="utf-8",
    )
    assert _offending_steps(doc) == []

    reversed_order = tmp_path / "armed-after.yml"
    reversed_order.write_text(
        "jobs:\n"
        "  build:\n"
        "    steps:\n"
        "      - uses: actions/checkout@v4\n"
        "        with:\n"
        "          persist-credentials: false\n"
        "      - name: fetch it\n"
        "        run: git fetch --quiet origin main\n"
        "      - name: arm it\n"
        "        run: git remote set-url origin https://x@github.com/o/r.git\n",
        encoding="utf-8",
    )
    assert _offending_steps(reversed_order) == ["armed-after.yml:build:fetch it"], (
        "arming AFTER the fetch does not help the fetch"
    )
