"""Tests for ``scripts/analyze_publish_cadence.py``.

Stubs the ``git_log`` runner so no real git invocation is needed -- the
tests run entirely off synthetic commit timelines.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from scripts.analyze_publish_cadence import (
    CadenceReport,
    _parse_path_spec,
    analyze_all,
    analyze_path,
    main,
)

NOW = datetime(2026, 5, 29, 12, 0, 0, tzinfo=UTC)


def _fake_log(commits_age_days: list[float]):
    """Return a runner producing one line per (age_days_from_NOW) entry,
    newest-first as `git log` does."""

    def runner(path: str) -> str:
        lines = []
        for i, age in enumerate(commits_age_days):
            ts = int((NOW - timedelta(days=age)).timestamp())
            lines.append(f"{ts}\t{i:07x}abc")
        return "\n".join(lines) + ("\n" if lines else "")

    return runner


# -- analyze_path -----------------------------------------------------------


def test_fresh_when_last_commit_within_budget(tmp_path: Path) -> None:
    r = analyze_path(
        path="pine/generated",
        budget_days=7.0,
        repo_root=tmp_path,
        now=NOW,
        git_log=_fake_log([1.0, 5.0, 12.0]),
    )
    assert r.status == "fresh"
    assert r.age_days == 1.0
    assert r.commit_count == 3
    assert r.last_commit_sha is not None
    assert r.max_gap_days == 7.0  # gap between 5d and 12d


def test_stale_when_last_commit_older_than_budget(tmp_path: Path) -> None:
    r = analyze_path(
        path="pine/generated",
        budget_days=7.0,
        repo_root=tmp_path,
        now=NOW,
        git_log=_fake_log([45.0, 50.0]),  # 5-week silence -- the #2415 shape
    )
    assert r.status == "stale"
    assert r.age_days == 45.0


def test_max_gap_reported_even_when_fresh(tmp_path: Path) -> None:
    """The historical max-gap is informational; report it regardless."""
    r = analyze_path(
        path="pine/generated",
        budget_days=7.0,
        repo_root=tmp_path,
        now=NOW,
        git_log=_fake_log([1.0, 36.0, 100.0]),  # huge old gap, fresh today
    )
    assert r.status == "fresh"
    assert r.max_gap_days == 64.0
    # The pair tuple identifies which commits bracket the gap.
    assert r.max_gap_between is not None
    older_sha, newer_sha = r.max_gap_between
    assert older_sha != newer_sha


def test_missing_when_no_commits_touched_path(tmp_path: Path) -> None:
    r = analyze_path(
        path="never/published",
        budget_days=7.0,
        repo_root=tmp_path,
        now=NOW,
        git_log=lambda p: "",
    )
    assert r.status == "missing"
    assert r.commit_count == 0
    assert r.detail is not None
    assert r.age_days is None


def test_missing_when_git_log_raises(tmp_path: Path) -> None:
    def broken(p: str) -> str:
        raise RuntimeError("git log failed for path 'x': fatal")

    r = analyze_path(
        path="x",
        budget_days=7.0,
        repo_root=tmp_path,
        now=NOW,
        git_log=broken,
    )
    assert r.status == "missing"
    assert "fatal" in (r.detail or "")


def test_single_commit_has_zero_max_gap(tmp_path: Path) -> None:
    r = analyze_path(
        path="x",
        budget_days=30.0,
        repo_root=tmp_path,
        now=NOW,
        git_log=_fake_log([3.0]),
    )
    assert r.status == "fresh"
    assert r.commit_count == 1
    assert r.max_gap_days == 0.0
    assert r.max_gap_between is None


def test_garbage_lines_skipped_silently(tmp_path: Path) -> None:
    def runner(p: str) -> str:
        # First line is garbage; second is valid.
        ts = int((NOW - timedelta(days=2)).timestamp())
        return f"not-a-number\tdeadbee\n{ts}\tabc1234\n"

    r = analyze_path(
        path="x",
        budget_days=7.0,
        repo_root=tmp_path,
        now=NOW,
        git_log=runner,
    )
    assert r.status == "fresh"
    assert r.commit_count == 1
    assert r.last_commit_sha == "abc1234"


# -- analyze_all aggregation ------------------------------------------------


def test_overall_fresh_when_all_paths_fresh(tmp_path: Path) -> None:
    report = analyze_all(
        paths=[("a", 7.0), ("b", 7.0)],
        repo_root=tmp_path,
        now=NOW,
        git_log=_fake_log([1.0, 4.0]),
    )
    assert report.overall == "fresh"
    assert report.stale_count == 0 and report.missing_count == 0


def test_overall_stale_when_any_stale_or_missing(tmp_path: Path) -> None:
    state = {"i": 0}
    fresh = _fake_log([1.0])
    stale = _fake_log([60.0])

    def runner(p: str) -> str:
        idx = state["i"]
        state["i"] += 1
        return (fresh if idx == 0 else stale)(p)

    report = analyze_all(
        paths=[("a", 7.0), ("b", 7.0)],
        repo_root=tmp_path,
        now=NOW,
        git_log=runner,
    )
    assert report.overall == "stale"
    assert report.stale_count == 1


def test_overall_stale_when_path_missing(tmp_path: Path) -> None:
    report = analyze_all(
        paths=[("a", 7.0)],
        repo_root=tmp_path,
        now=NOW,
        git_log=lambda p: "",
    )
    assert report.overall == "stale"
    assert report.missing_count == 1


# -- spec parser ------------------------------------------------------------


def test_parse_path_spec_ok() -> None:
    assert _parse_path_spec("pine/generated=7") == ("pine/generated", 7.0)
    assert _parse_path_spec("a/b/c.txt=1.5") == ("a/b/c.txt", 1.5)


def test_parse_path_spec_accepts_equals_in_filename() -> None:
    # rpartition means the last `=` is the separator; rare paths with
    # an `=` in them still parse.
    assert _parse_path_spec("weird=name=7") == ("weird=name", 7.0)


@pytest.mark.parametrize(
    "raw",
    ["no-equals", "path=zero", "path=-1", "path=0", "=7"],
)
def test_parse_path_spec_rejects(raw: str) -> None:
    import argparse as _ap

    with pytest.raises(_ap.ArgumentTypeError):
        _parse_path_spec(raw)


# -- CLI integration --------------------------------------------------------


def _patch(monkeypatch: pytest.MonkeyPatch, report: CadenceReport) -> None:
    monkeypatch.setattr(
        "scripts.analyze_publish_cadence.analyze_all",
        lambda **kwargs: report,
    )


def test_cli_returns_zero_on_fresh(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    _patch(monkeypatch, CadenceReport(overall="fresh"))
    out = tmp_path / "r.json"
    rc = main(["pine/generated=7", "--repo-root", str(tmp_path), "--output", str(out)])
    assert rc == 0
    assert json.loads(out.read_text(encoding="utf-8"))["overall"] == "fresh"


def test_cli_returns_two_on_stale(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    _patch(monkeypatch, CadenceReport(overall="stale", stale_count=1))
    rc = main(["pine/generated=7", "--repo-root", str(tmp_path)])
    assert rc == 2


def test_cli_rejects_non_git_root(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["pine/generated=7", "--repo-root", str(tmp_path)])
    assert rc == 1
    assert "not look like a git repo" in capsys.readouterr().err


# -- integration against a real ephemeral git repo --------------------------


def test_end_to_end_against_real_git_repo(tmp_path: Path) -> None:
    """Smoke test: build a tiny git repo with one commit touching a
    path and one that doesn't. Verify _run_git_log returns the right
    shape without stubbing."""
    import os
    import subprocess

    # `cwd=` is NOT isolation. Git resolves its repository from the environment
    # FIRST — $GIT_DIR / $GIT_INDEX_FILE outrank the working directory — and
    # git EXPORTS both into every hook it runs, which is where this suite
    # executes (the pre-push hook). Measured 2026-08-04 against a decoy repo:
    # under that environment this fixture committed twice into the decoy and
    # staged its tracked files as deleted, while reporting `1 passed`. The
    # scrub drops the whole GIT_* namespace so a variable git adds later cannot
    # reopen it; GIT_CEILING_DIRECTORIES is then set POSITIVELY so `git init`
    # cannot discover a repository above $TMPDIR either.
    #
    # And the identity goes in per invocation with `-c`, never `git config`.
    # `git config` WRITES: under the hijack above it wrote `user.email` into
    # the REAL repository's config, which is what turned one bad commit into
    # every later commit being authored by an address
    # scripts/check_commit_authors.py does not approve. `-c` writes nothing, so
    # even a total isolation failure cannot outlive the process.
    # Same contract as tests/test_smc_library_refresh_workflow.py.
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    # A STRICT ancestor: git stops its upward search *below* a ceiling entry,
    # so naming tmp_path itself (the repo directory) is a no-op — measured
    # 2026-08-04. The sibling fixture in test_smc_library_refresh_workflow.py
    # uses the parent for the same reason.
    env["GIT_CEILING_DIRECTORIES"] = str(tmp_path.parent)
    identity = (
        "-c", "user.email=fixture@example.invalid",
        "-c", "user.name=fixture",
        "-c", "commit.gpgsign=false",
    )

    def run(*args: str) -> None:
        subprocess.run(
            ("git", *identity, *args),
            cwd=tmp_path,
            check=True,
            capture_output=True,
            env=env,
        )

    run("init", "-q")
    (tmp_path / "pine").mkdir()
    (tmp_path / "pine" / "x.txt").write_text("v1", encoding="utf-8")
    run("add", "pine/x.txt")
    run("commit", "-q", "-m", "first")
    (tmp_path / "other.txt").write_text("o", encoding="utf-8")
    run("add", "other.txt")
    run("commit", "-q", "-m", "unrelated")

    r = analyze_path(
        path="pine",
        budget_days=365.0,
        repo_root=tmp_path,
        now=NOW,
    )
    assert r.status == "fresh"
    assert r.commit_count == 1

    r2 = analyze_path(
        path="never-existed",
        budget_days=365.0,
        repo_root=tmp_path,
        now=NOW,
    )
    assert r2.status == "missing"


def _persisted_identity(config_path: Path) -> dict[str, str]:
    """Identity keys really stored in a git config file, asked of git itself.

    NOT a substring search. ``git config user.email x`` writes::

        [user]
            email = x

    so the literal ``"user.email"`` never appears in the file, and
    ``assert "user.email" not in config_text`` can never fail. That assertion
    shipped in this file on 2026-08-04 and was caught the same day by executing
    the mutation it claimed to catch — the file stayed green with a real
    ``git config`` call restored. Ask git, which knows the section syntax.
    """
    import subprocess

    found = {}
    for key in ("user.email", "user.name"):
        result = subprocess.run(
            ["git", "config", "--file", str(config_path), "--get", key],
            capture_output=True,
            text=True,
            env={"PATH": os.environ.get("PATH", "")},
        )
        if result.returncode == 0 and result.stdout.strip():
            found[key] = result.stdout.strip()
    return found


def test_the_real_git_fixture_cannot_escape_into_an_ambient_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Prove the isolation above instead of asserting it in a comment.

    ``test_end_to_end_against_real_git_repo`` is the only test in this file that
    shells out to a real git, and it used to pass ``cwd=`` with no ``env=``. On
    2026-08-04 that fixture committed a temporary tree into the real repository
    and left ``user.email`` in the ``.git/config`` every worktree shares, so
    later commits were authored by an address
    ``scripts/check_commit_authors.py`` rejects -- while the suite reported
    passing throughout.

    An ambient ``$GIT_DIR`` / ``$GIT_INDEX_FILE`` reproduces that damage
    exactly, and this test drives it: a decoy repository is wired into both, the
    fixture is re-run, and the decoy must come out with no commits. Remove the
    ``env=`` scrub and it goes red on that assertion.

    **What this test does NOT establish, stated rather than implied.** An
    earlier version of this docstring claimed "put ``git config`` back, and this
    goes red". That is false, and measured: with the scrub in place ``git
    config`` writes into the sandbox, never into the decoy, so restoring it
    leaves this file green. The ``-c`` discipline is worth keeping -- it is what
    makes even a total isolation failure survivable -- so it gets its own
    witness below, against the sandbox rather than the decoy.

    ``GIT_WORK_TREE`` is deliberately NOT set. Setting it made ``git add`` fail
    with exit 128 before either assertion was reached: the test was red under
    the mutation, but for the wrong reason, which is indistinguishable from a
    guard that works until the day the error message changes.
    """
    import contextlib
    import os
    import subprocess

    clean = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}

    decoy = tmp_path / "decoy"
    decoy.mkdir()
    subprocess.run(
        ["git", "init", "-q"], cwd=decoy, check=True, capture_output=True, env=clean
    )

    for name, value in (
        ("GIT_DIR", str(decoy / ".git")),
        ("GIT_INDEX_FILE", str(decoy / ".git" / "index")),
    ):
        monkeypatch.setenv(name, value)

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    # The analyzer under test legitimately honours $GIT_DIR — it is a git tool,
    # and one that ignored the environment would itself be the bug. So its
    # verdict about the workspace may differ under the hijack, and that is not
    # what is being witnessed here. What must hold no matter what: the fixture
    # WROTE nothing into a repository it was never pointed at.
    with contextlib.suppress(AssertionError):
        test_end_to_end_against_real_git_repo(workspace)

    log = subprocess.run(
        ["git", "log", "--oneline"],
        cwd=decoy,
        capture_output=True,
        text=True,
        env=clean,
    )
    assert log.stdout.strip() == "", (
        "the fixture committed into a repository it was never pointed at: "
        f"{log.stdout.strip()!r}. $GIT_DIR outranks cwd=, so the git calls in "
        "test_end_to_end_against_real_git_repo must pass a GIT_*-scrubbed env="
    )

    assert _persisted_identity(decoy / ".git" / "config") == {}, (
        "the fixture wrote an identity into a foreign .git/config; use "
        "`git -c user.email=...` per invocation, never `git config`, which "
        f"persists:\n{(decoy / '.git' / 'config').read_text(encoding='utf-8')}"
    )


def test_the_real_git_fixture_never_persists_an_identity(tmp_path: Path) -> None:
    """The identity goes in per invocation, so nothing outlives the process.

    Separate from the decoy test above, and asserted against the SANDBOX,
    because that is where the difference is observable: with the ``GIT_*``
    scrub in place a stray ``git config`` writes into the sandbox's own config,
    not into any ambient repository, so the decoy cannot witness it.

    Why keep the discipline at all if the scrub already contains the damage:
    ``git config`` PERSISTS and ``-c`` does not. The scrub is one line that a
    future edit can drop; ``-c`` means that even then the blast radius is a
    single command rather than every commit made in that repository afterwards.
    Defence in depth, and this is the layer that measures it.
    """
    import subprocess

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    test_end_to_end_against_real_git_repo(workspace)

    persisted = _persisted_identity(workspace / ".git" / "config")
    assert persisted == {}, (
        "the fixture persisted an identity into its own .git/config, so it "
        "used `git config` rather than `git -c user.email=...`. Under an "
        "isolation failure that write lands in the real repository and outlives "
        f"the test. Found: {persisted}"
    )

    # ...and the commits it made really do carry the intended identity, so the
    # assertion above cannot be satisfied by a fixture that stopped committing.
    log = subprocess.run(
        ["git", "log", "--format=%an <%ae>"],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=True,
        env={"PATH": os.environ.get("PATH", ""), "HOME": str(tmp_path)},
    )
    authors = set(log.stdout.split("\n")) - {""}
    assert authors == {"fixture <fixture@example.invalid>"}, (
        f"expected every commit authored by the per-invocation identity; got {authors}"
    )
