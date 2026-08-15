"""A published binding baseline must never be replaced by a reading that is empty.

`bot/live-tradingview-bindings` carries the last CI observation of the
TradingView consumer bindings. Two workflows publish onto it, and both read it
back as the comparison baseline for out-of-band drift. Whatever is on that
branch therefore decides whether `scripts/tv_batch_consumer_rollout.ts` can
answer "did a second writer touch TradingView" at all.

Measured 2026-08-14, and this is the whole reason the guard exists:

* run 31823203037 (tv-save-consumer-source, write mode) threw
  `Library publish drift: the manifest says smc_micro_profiles_generated is
  published at version 243, but TradingView lists 244` after **one second** --
  before the pre-mutation observation. Its report said
  `"bindings": []`, `"sources": 0`, `outOfBandDrift: "the pre-mutation
  observation has not run yet"`, and the publish step pushed exactly that over
  a full baseline;
* run 31824430346 (the automated R1 re-attestation, one minute later) loaded
  it, found the baseline covered none of its nine verify targets, and reported
  out-of-band drift as `unknown`;
* `scripts/smc_r1_generate_attestation` accepts only `clean`
  (`ValueError: out-of-band drift is not clean: unknown`), so the run saved all
  eleven sources to TradingView and could not attest `SMC Event Overlay`. The
  re-pin never reached the repository.

Both publish steps already gate on their rollout step's *conclusion*. That is a
different question: run 31823203037's step DID run and DID fail, so the gate let
it through. Only the report says whether anything was observed.

The rule is over the POPULATION -- every step that pushes to that branch -- not
a pin on the two files that happen to exist today. A third producer joining the
branch inherits the same duty, and this test tells it so.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"

_BRANCH_NAME = "bot/live-tradingview-bindings"
# The force-with-lease idiom both publishers share. Discovery below does NOT
# key on it (2026-08-15 review finding: an idiom is an implementation choice,
# and a publisher written differently would silently escape a discovery
# anchored on it) — it is asserted PER discovered publisher instead, so a
# divergent one fails loudly rather than dropping out of the population.
_LEASE_IDIOM = 'remote_ref="refs/heads/bot/live-tradingview-bindings"'
_OBSERVATION_GATE = (
    '(.tradingViewObserved.bindings // []) | if type == "array" then length else error'
)

# The seam each publisher exposes so its body can be executed against a
# throwaway repository instead of github.com. Keyed by step name so a renamed
# step fails loudly here rather than silently dropping out of the executed
# half of this file.
_REMOTE_SEAM = {
    "Publish latest binding snapshot": "TV_SNAPSHOT_REMOTE",
    "Publish latest R4 binding snapshot": "R4_SNAPSHOT_REMOTE",
}


def _sandbox_env(home: Path, **extra: str) -> dict[str, str]:
    """An environment with NO ambient git state in it.

    Inheriting ``os.environ`` here is not a style question. The pre-push hook
    runs this suite with ``GIT_DIR``/``GIT_WORK_TREE`` pointing at the
    developer's own repository, and those override cwd-based discovery: an
    inherited environment sends every fixture command there instead of into
    ``tmp_path``. Measured twice on 2026-08-14 -- once it committed a tree-wide
    deletion onto the branch under test, once it created a stray branch -- so
    this file passes an explicit environment to every single git call.
    """
    return {"PATH": os.environ["PATH"], "HOME": str(home), **extra}


@pytest.fixture(autouse=True)
def _the_repository_running_these_tests_must_not_move():
    """Fail loudly if anything in this file wrote into the real checkout.

    The damage from the two 2026-08-14 incidents showed up a step LATER (a
    rejected commit author, a stray branch), which is exactly why this asserts
    on identity as well as HEAD.
    """

    def state() -> tuple[str, str]:
        def ask(*args: str) -> str:
            done = subprocess.run(
                ["git", *args],
                cwd=REPO_ROOT,
                env={"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", "")},
                capture_output=True,
                text=True,
            )
            return done.stdout.strip()

        return ask("rev-parse", "HEAD"), ask("config", "--get", "user.email")

    head_before, identity_before = state()
    yield
    head_after, identity_after = state()
    assert head_after == head_before, (
        "a test in this file moved the real repository's HEAD "
        f"({head_before} -> {head_after})"
    )
    assert identity_after == identity_before, (
        "a test in this file rewrote the real repository's commit identity "
        f"({identity_before!r} -> {identity_after!r}) -- the commit-author gate "
        "rejects the NEXT commit, so this must fail here instead"
    )


def _baseline_publishers() -> list[tuple[str, str, str]]:
    """(workflow filename, step name, run body) for every push to the branch.

    Discovered from the workflow corpus, not listed: a new publisher must be
    covered the moment it lands, and a renamed one must not silently vanish.

    The discovery keys on what makes a step a PUBLISHER — a ``git push`` and
    the branch name in one body — not on the shared ``remote_ref=…`` idiom.
    Measured 2026-08-15 over the corpus: this conjunction matches exactly the
    two publish steps; the two baseline *readers* fetch over the API and carry
    no ``git push``. A publisher written in a different shape is therefore
    still discovered, and the idiom is enforced on it separately (see
    test_every_publisher_carries_the_lease_idiom_and_a_test_seam).
    """
    found: list[tuple[str, str, str]] = []
    for path in sorted(WORKFLOW_DIR.glob("*.yml")) + sorted(WORKFLOW_DIR.glob("*.yaml")):
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            continue
        for job in (document.get("jobs") or {}).values():
            if not isinstance(job, dict):
                continue
            for step in job.get("steps") or []:
                if not isinstance(step, dict):
                    continue
                body = step.get("run")
                if isinstance(body, str) and "git push" in body and _BRANCH_NAME in body:
                    found.append((path.name, step.get("name", "<unnamed>"), body))
    return found


def test_the_publisher_corpus_has_not_collapsed() -> None:
    """A discovery bug that finds nothing would make every test below vacuous."""
    workflow_count = len(list(WORKFLOW_DIR.glob("*.yml"))) + len(
        list(WORKFLOW_DIR.glob("*.yaml"))
    )
    assert workflow_count >= 30, (
        f"only {workflow_count} workflow files found — the corpus glob is broken, "
        "so the population rule below would pass over almost nothing"
    )
    publishers = _baseline_publishers()
    assert len(publishers) >= 2, (
        "expected at least the two known publishers onto "
        f"bot/live-tradingview-bindings, found {publishers}"
    )
    assert {name for _, name, _ in publishers} == set(_REMOTE_SEAM), (
        "a publisher was added or renamed: give it a *_SNAPSHOT_REMOTE test seam "
        "and register it in _REMOTE_SEAM so its body is EXECUTED here, not just read"
    )


def test_every_publisher_carries_the_lease_idiom_and_a_test_seam() -> None:
    """A discovered publisher that diverges from the shared shape fails HERE.

    The executed tests below run each body against a local repository through
    its ``*_SNAPSHOT_REMOTE`` seam and rely on the force-with-lease idiom for
    the seed-then-replace dance. Discovery deliberately does not key on either
    (a divergent publisher must still be found) — so this test is where the
    divergence surfaces as a named failure instead of a silent drop-out.
    """
    for workflow, step_name, body in _baseline_publishers():
        assert _LEASE_IDIOM in body, (
            f"{workflow} :: {step_name} pushes to {_BRANCH_NAME} without the "
            "shared force-with-lease idiom — adopt it (see the two existing "
            "publishers) so a concurrent publish loses the race instead of "
            "silently overwriting the other producer's commit"
        )
        seam = _REMOTE_SEAM.get(step_name)
        assert seam is not None and "${" + seam in body, (
            f"{workflow} :: {step_name} has no functional *_SNAPSHOT_REMOTE test "
            "seam in its body (the EXPANSION counts, a comment naming it does "
            "not) — without it the executed tests below would push at github.com "
            "instead of a throwaway repository"
        )


@pytest.mark.parametrize(
    "workflow, step_name, body",
    [pytest.param(*p, id=f"{p[0]}::{p[1]}") for p in _baseline_publishers()],
)
def test_every_publisher_refuses_a_reading_that_observed_nothing(
    workflow: str, step_name: str, body: str
) -> None:
    """The gate must exist, and it must sit BEFORE the copy that overwrites."""
    assert _OBSERVATION_GATE in body, (
        f"{workflow} :: {step_name} pushes to bot/live-tradingview-bindings without "
        "checking that its report observed anything — an empty reading would replace "
        "the last real baseline and turn out-of-band drift into 'unknown' for every "
        "run that follows"
    )
    gate_index = body.index(_OBSERVATION_GATE)
    copy_index = body.index('cp "${snapshot}"')
    assert gate_index < copy_index, (
        "the observation check must run before the snapshot is copied into the "
        "shared directory — checking afterwards still stages the empty reading"
    )


def _publisher_body(step_name: str) -> str:
    matches = [b for _, name, b in _baseline_publishers() if name == step_name]
    assert len(matches) == 1, f"expected exactly one {step_name!r}, got {len(matches)}"
    # Checked HERE, immediately before a body is handed to bash: if the seam
    # ever disappears from the step, the executed tests must fail offline
    # rather than discover it by pushing at github.com with a dummy token.
    # The probe is the EXPANSION (`${SEAM`), not the bare name — both steps
    # mention their seam in a comment, so a name-match stays satisfied after
    # the functional seam is gone (measured 2026-08-15: exactly that mutation
    # sailed past a name-match and hit the network before failing).
    assert "${" + _REMOTE_SEAM[step_name] in matches[0], (
        f"{step_name} lost its {_REMOTE_SEAM[step_name]} seam — refusing to "
        "execute a body that would target the real remote"
    )
    return matches[0]


def _snapshot_path(body: str) -> str:
    line = next(ln for ln in body.splitlines() if ln.strip().startswith("snapshot="))
    return line.split("=", 1)[1].strip().strip('"')


def _git(*args: str, cwd: Path, env: dict[str, str]) -> str:
    done = subprocess.run(
        ["git", *args], cwd=cwd, env=env, capture_output=True, text=True
    )
    assert done.returncode == 0, f"git {' '.join(args)}: {done.stderr}"
    return done.stdout.strip()


def _published_files(origin: Path, env: dict[str, str]) -> list[str]:
    done = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", "refs/heads/bot/live-tradingview-bindings"],
        cwd=origin,
        env=env,
        capture_output=True,
        text=True,
    )
    return done.stdout.split() if done.returncode == 0 else []


_FULL_READING = {
    "tradingViewObserved": {
        "bindings": [{"scriptName": "SMC Event Overlay", "selections": []}]
    }
}
_EMPTY_READING = {
    "tradingViewObserved": {"bindings": [], "sources": []},
    "outOfBandDrift": {
        "status": "unknown",
        "reason": "the pre-mutation observation has not run yet",
    },
}


@pytest.mark.parametrize("step_name", sorted(_REMOTE_SEAM))
def test_an_empty_reading_leaves_the_published_baseline_untouched(
    step_name: str, tmp_path: Path
) -> None:
    """EXECUTED, both publishers: publish a real reading, then try an empty one.

    Run 31823203037's report shape verbatim. A string match on the gate cannot
    tell whether the step actually stops -- a mis-spelled jq filter, a missing
    `exit 0`, or a gate placed after the copy all read fine and all still
    clobber the branch. This runs the body and looks at the branch.
    """
    body = _publisher_body(step_name)
    env = _sandbox_env(tmp_path)
    origin = tmp_path / "origin"
    work = tmp_path / "work"
    origin.mkdir()
    work.mkdir()
    _git("init", "--bare", "-b", "main", ".", cwd=origin, env=env)
    _git("init", "-b", "main", ".", cwd=work, env=env)
    _git("config", "user.email", "t@example.invalid", cwd=work, env=env)
    _git("config", "user.name", "t", cwd=work, env=env)
    (work / "README.md").write_text("proposal\n", encoding="utf-8")
    _git("add", "README.md", cwd=work, env=env)
    _git("commit", "-m", "seed", cwd=work, env=env)

    snapshot = work / _snapshot_path(body)
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    run_env = _sandbox_env(
        tmp_path,
        GH_TOKEN="test-token",
        GITHUB_REPOSITORY="skipp-dev/skipp-algo",
        **{_REMOTE_SEAM[step_name]: str(origin)},
    )

    def publish() -> subprocess.CompletedProcess[str]:
        done = subprocess.run(
            ["/bin/bash", "-c", body],
            cwd=work,
            env=run_env,
            capture_output=True,
            text=True,
        )
        assert done.returncode == 0, done.stdout + done.stderr
        return done

    # 1. A real reading reaches the branch — without this the test below could
    #    pass by breaking the publisher outright.
    snapshot.write_text(json.dumps(_FULL_READING), encoding="utf-8")
    publish()
    published_path = next(
        f for f in _published_files(origin, env) if f.startswith("artifacts/monitoring/latest/")
    )
    good_tip = _git("rev-parse", "refs/heads/bot/live-tradingview-bindings", cwd=origin, env=env)
    good_content = _git("show", f"refs/heads/bot/live-tradingview-bindings:{published_path}", cwd=origin, env=env)
    assert json.loads(good_content) == _FULL_READING

    # 2. The empty reading must change nothing at all.
    snapshot.write_text(json.dumps(_EMPTY_READING), encoding="utf-8")
    done = publish()
    assert "observed no TradingView bindings" in done.stdout, (
        "the step must SAY it declined, or an operator reading the log cannot "
        f"tell a skipped publish from a successful one (stdout: {done.stdout!r})"
    )
    assert (
        _git("rev-parse", "refs/heads/bot/live-tradingview-bindings", cwd=origin, env=env)
        == good_tip
    ), "an empty reading advanced the branch"
    assert (
        _git("show", f"refs/heads/bot/live-tradingview-bindings:{published_path}", cwd=origin, env=env)
        == good_content
    ), "an empty reading replaced the last real observation"


@pytest.mark.parametrize(
    "bad_payload",
    [
        pytest.param("{not json at all", id="malformed-json"),
        # 2026-08-15 review finding: a bare `length` accepts non-array garbage
        # — jq's length of the number 7 is 7, of a string its character count
        # — and would publish it as an "observation". Unreachable while the
        # report comes from tv_batch_consumer_rollout.ts (typed as an array),
        # so the type check exists for the day something else writes the file.
        pytest.param('{"tradingViewObserved": {"bindings": 7}}', id="non-array-bindings"),
    ],
)
@pytest.mark.parametrize("step_name", sorted(_REMOTE_SEAM))
def test_an_unreadable_report_fails_loudly_instead_of_declining_quietly(
    step_name: str, bad_payload: str, tmp_path: Path
) -> None:
    """"Observed nothing" and "the check itself broke" must not look the same.

    Written as `if ! jq -e ...` the guard would answer both by exiting 0 and
    publishing nothing — a missing jq or a malformed report would freeze the
    baseline permanently with no red anywhere, which is the same
    green-without-observation shape this guard exists to remove. Counting under
    `set -e` makes the broken case fail the step.
    """
    body = _publisher_body(step_name)
    env = _sandbox_env(tmp_path)
    work = tmp_path / "work"
    work.mkdir()
    _git("init", "-b", "main", ".", cwd=work, env=env)
    _git("config", "user.email", "t@example.invalid", cwd=work, env=env)
    _git("config", "user.name", "t", cwd=work, env=env)
    (work / "README.md").write_text("proposal\n", encoding="utf-8")
    _git("add", "README.md", cwd=work, env=env)
    _git("commit", "-m", "seed", cwd=work, env=env)

    snapshot = work / _snapshot_path(body)
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_text(bad_payload, encoding="utf-8")

    done = subprocess.run(
        ["/bin/bash", "-c", body],
        cwd=work,
        env=_sandbox_env(
            tmp_path,
            GH_TOKEN="test-token",
            GITHUB_REPOSITORY="skipp-dev/skipp-algo",
            **{_REMOTE_SEAM[step_name]: str(tmp_path / "no-such-origin")},
        ),
        capture_output=True,
        text=True,
    )
    assert done.returncode != 0, (
        "an unreadable report must fail the publish step, not be mistaken for "
        f"'this run observed nothing' (stdout: {done.stdout!r})"
    )
    assert "observed no TradingView bindings" not in done.stdout


@pytest.mark.parametrize("step_name", sorted(_REMOTE_SEAM))
def test_a_reading_that_observed_bindings_still_publishes(
    step_name: str, tmp_path: Path
) -> None:
    """The guard must not turn into a blanket refusal.

    A snapshot whose rollout FAILED after observing is still the freshest truth
    about TradingView, and run 30700389375 is why `failure` stays in the step's
    `if:` at all. Only the observation decides, not `ok`.
    """
    body = _publisher_body(step_name)
    env = _sandbox_env(tmp_path)
    origin = tmp_path / "origin"
    work = tmp_path / "work"
    origin.mkdir()
    work.mkdir()
    _git("init", "--bare", "-b", "main", ".", cwd=origin, env=env)
    _git("init", "-b", "main", ".", cwd=work, env=env)
    _git("config", "user.email", "t@example.invalid", cwd=work, env=env)
    _git("config", "user.name", "t", cwd=work, env=env)
    (work / "README.md").write_text("proposal\n", encoding="utf-8")
    _git("add", "README.md", cwd=work, env=env)
    _git("commit", "-m", "seed", cwd=work, env=env)

    snapshot = work / _snapshot_path(body)
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    failed_but_observed = {"ok": False, **_FULL_READING}
    snapshot.write_text(json.dumps(failed_but_observed), encoding="utf-8")

    done = subprocess.run(
        ["/bin/bash", "-c", body],
        cwd=work,
        env=_sandbox_env(
            tmp_path,
            GH_TOKEN="test-token",
            GITHUB_REPOSITORY="skipp-dev/skipp-algo",
            **{_REMOTE_SEAM[step_name]: str(origin)},
        ),
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    published_path = next(
        f for f in _published_files(origin, env) if f.startswith("artifacts/monitoring/latest/")
    )
    assert json.loads(
        _git("show", f"refs/heads/bot/live-tradingview-bindings:{published_path}", cwd=origin, env=env)
    ) == failed_but_observed, (
        "a failed-but-observed run must still publish — this is the freshest "
        "reading anyone has, and refusing it would freeze the baseline forever"
    )
