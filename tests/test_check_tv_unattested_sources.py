"""An automated save that un-attests an R1 source must say so.

#4286 guards the pull-request path. The 2026-08-01 un-attestation did not take
it: ``smc-library-refresh`` succeeded, the chained ``tv-save-consumer-source``
pushed the new Event Overlay source, and the source the evidence attests
stopped existing. No diff, no gate, green run.

The save itself is not blocked (operator decision, 2026-08-01): skipping the
drifted targets would freeze them on an old pinned library while the producer
moves on. What must not survive is the silence.

These tests drive real drift and real agreement through injected data rather
than reading whatever the checked-in state happens to be. A guard whose tests
skip when the repository is clean proves nothing on the day it is not -- that is
the vacuity #4267 removed.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts.check_tv_unattested_sources import (
    _REMEDY,
    DEFAULT_CONFIG,
    EXECUTION_EVIDENCE,
    RESOLUTION,
    _render,
    attested_sources,
    drifted_attested_targets,
    unattested_save_targets,
)
from scripts.smc_r1_rollout_contract import ROOT, build_rollout_contract

_ATTESTED = "a" * 64
_DRIFTED = "b" * 64

_TARGETS = [
    {"scriptName": "SMC Event Overlay", "path": "SMC_Event_Overlay.pine", "sha256": _ATTESTED},
    {"scriptName": "SMC Exit Signal", "path": "SMC_Exit_Signal.pine", "sha256": _ATTESTED},
]


def _sources(**overrides: str) -> dict:
    sources = {target["scriptName"]: {"repositorySha256": _ATTESTED} for target in _TARGETS}
    for name, sha in overrides.items():
        sources[name] = {"repositorySha256": sha}
    return sources


def _config(tmp_path: Path, names: list[str]) -> Path:
    path = tmp_path / "rollout.json"
    path.write_text(
        json.dumps({"saveTargets": [{"source": f"{n}.pine", "scriptName": n} for n in names]}),
        encoding="utf-8",
    )
    return path


def test_agreement_reports_nothing() -> None:
    assert drifted_attested_targets(targets=_TARGETS, sources=_sources()) == []


def test_a_drifted_attested_source_is_named_with_both_hashes() -> None:
    drifted = drifted_attested_targets(
        targets=_TARGETS,
        sources=_sources(**{"SMC Event Overlay": _DRIFTED}),
    )

    assert [item["scriptName"] for item in drifted] == ["SMC Event Overlay"]
    assert drifted[0]["attestedSha256"] == _DRIFTED
    assert drifted[0]["repositorySha256"] == _ATTESTED
    assert drifted[0]["path"] == "SMC_Event_Overlay.pine"


def test_every_attested_source_can_drift_independently() -> None:
    """Both, not just the one that happened to break in 2026-08-01."""
    drifted = drifted_attested_targets(
        targets=_TARGETS,
        sources=_sources(**{"SMC Event Overlay": _DRIFTED, "SMC Exit Signal": _DRIFTED}),
    )

    assert sorted(item["scriptName"] for item in drifted) == [
        "SMC Event Overlay",
        "SMC Exit Signal",
    ]


def test_an_evidence_artifact_that_records_no_hash_is_unknown_not_agreement() -> None:
    """A missing measurement may never be reported as a matching one.

    This test used to assert the opposite -- ``sources={}`` returned ``[]``
    under the name "a source the evidence does not attest is not this guard's
    business". That reading is unsupportable: every contract target is required
    to appear in the evidence (``test_every_live_target_is_covered_by_the_
    evidence`` pins exactly that), so an absent hash means the artifact is
    malformed, not that the source agrees with it.

    It had a consumer. ``smc-library-refresh.yml``'s notice step gates its
    all-clear on this function, and measured on 2026-08-04 all four shapes below
    produced "every one still hashes to what <evidence> attests" -- an
    attestation asserted over hashes that were never read. The required guard
    ``scripts/check_r1_attested_sources.py`` disagreed on the same input, which
    is how one repository held two answers to one question.
    """
    shapes = {
        "evidence has no sources at all": {},
        "the key for this source was deleted": {"SMC Exit Signal": {"repositorySha256": _ATTESTED}},
        "the source is registered as an empty object": {
            "SMC Event Overlay": {},
            "SMC Exit Signal": {"repositorySha256": _ATTESTED},
        },
        "the hash is explicitly null": {
            "SMC Event Overlay": {"repositorySha256": None},
            "SMC Exit Signal": {"repositorySha256": _ATTESTED},
        },
        "the whole source entry is null": {
            "SMC Event Overlay": None,
            "SMC Exit Signal": {"repositorySha256": _ATTESTED},
        },
    }

    for description, sources in shapes.items():
        drifted = drifted_attested_targets(targets=_TARGETS, sources=sources)
        reported = {item["scriptName"] for item in drifted}
        assert "SMC Event Overlay" in reported, (
            f"{description}: the source was reported as agreeing with an evidence "
            "artifact that records no hash for it. Absence of a measurement is "
            "not a measurement of agreement."
        )
        entry = next(i for i in drifted if i["scriptName"] == "SMC Event Overlay")
        assert entry["attestedSha256"] is None, (
            f"{description}: a fabricated attested hash was reported. Callers "
            "distinguish 'moved away from a recorded hash' from 'never had one' "
            "by this field being None."
        )


def test_the_report_says_no_hash_was_recorded_rather_than_printing_none(
    tmp_path: Path,
) -> None:
    """The rendered remedy must not read as if ``None`` were the attested hash."""
    sources = {"SMC Event Overlay": {}, "SMC Exit Signal": {"repositorySha256": _ATTESTED}}
    drifted = drifted_attested_targets(targets=_TARGETS, sources=sources)
    rendered = _render(drifted, ["SMC Event Overlay"])

    assert "records no hash for this source" in rendered, rendered
    assert "evidence attests: None" not in rendered, (
        "the report printed the literal None as though it were a hash; an "
        "operator would go looking for a re-attestation when the artifact "
        "itself is what needs repairing"
    )


def test_the_report_is_intersected_with_what_this_config_would_actually_save(
    tmp_path: Path,
) -> None:
    """Naming a script the rollout never writes would claim an un-attestation that did not happen."""
    drifted = drifted_attested_targets(
        targets=_TARGETS,
        sources=_sources(**{"SMC Event Overlay": _DRIFTED, "SMC Exit Signal": _DRIFTED}),
    )

    both = _config(tmp_path, ["SMC Event Overlay", "SMC Exit Signal", "SMC Long-Dip Suite"])
    assert unattested_save_targets(both, drifted) == ["SMC Event Overlay", "SMC Exit Signal"]

    one = _config(tmp_path, ["SMC Exit Signal", "SMC Long-Dip Suite"])
    assert unattested_save_targets(one, drifted) == ["SMC Exit Signal"]

    none = _config(tmp_path, ["SMC Long-Dip Suite"])
    assert unattested_save_targets(none, drifted) == []


def test_the_shipped_config_still_saves_both_attested_companions(tmp_path: Path) -> None:
    """The guard is only load-bearing while the rollout actually writes these two.

    If the companions ever leave saveTargets, this guard silently stops
    protecting anything -- and would keep passing.
    """
    config = json.loads(DEFAULT_CONFIG.read_text(encoding="utf-8"))
    save_targets = {target["scriptName"] for target in config["saveTargets"]}

    for name in ("SMC Event Overlay", "SMC Exit Signal"):
        assert name in save_targets, f"{name} is attested but no longer a save target"


def test_the_guard_reads_the_registered_evidence_not_a_second_copy() -> None:
    """Attested hashes must come from the evidence, so the two cannot disagree."""
    sources = attested_sources()
    targets = {target["scriptName"]: target for target in build_rollout_contract()["targets"]}

    assert set(sources) == set(targets)
    for name, target in targets.items():
        assert sources[name]["repositorySha256"] == target["sha256"], (
            f"{name} disagrees with the registered evidence; the guard would report it "
            "as un-attested on every run"
        )


def test_stdout_is_only_the_machine_value_so_the_shell_can_append_it_verbatim() -> None:
    """The workflow does ``echo "unattested=$(...)" >> $GITHUB_OUTPUT``.

    Any prose on stdout would land in the step output and reach the rollout as
    part of the value, so the human-readable remedy goes to stderr. Checked as
    a subprocess because that is the interface the workflow actually uses --
    calling main() in-process would not catch a stray print.
    """
    result = subprocess.run(
        [sys.executable, "-m", "scripts.check_tv_unattested_sources"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    assert isinstance(json.loads(result.stdout.strip()), list)
    assert result.stdout.count("\n") == 1, f"stdout carried more than the value: {result.stdout!r}"
    assert result.stderr.strip(), "the human-readable line must still be emitted, on stderr"


def test_the_shared_resolution_names_both_registration_sites() -> None:
    """The consolidated prose must not be less actionable than the copies it replaced.

    ``RESOLUTION`` is the ONE remedy two producers render — this script's
    stderr and the refresh PR body. It told the operator to register a NEW
    dated artifact "alongside the registered one" and stopped there, so the
    guard stayed red after the work was done: nothing reads an artifact the
    registration does not point at.

    And the registration is duplicated by construction. ``EXECUTION_EVIDENCE``
    in ``scripts/smc_r1_rollout_contract.py`` is the source; the generated
    ``artifacts/governance/smc_r1_live_rollout_contract.json`` carries
    ``executionEvidence``; ``tests/test_smc_r1_rollout_contract.py`` pins them
    equal. Prose that names one of the two is prose that ends in a red repo.
    """
    from scripts.smc_r1_rollout_contract import DEFAULT_OUTPUT

    rendered = RESOLUTION.format(evidence=EXECUTION_EVIDENCE.relative_to(ROOT).as_posix())

    for site in (
        "scripts/smc_r1_rollout_contract.py",
        DEFAULT_OUTPUT.relative_to(ROOT).as_posix(),
    ):
        assert site in rendered, (
            f"the shared resolution does not name {site}. Both registration "
            "sites have to be named, or an operator repoints one, watches "
            "tests/test_smc_r1_rollout_contract.py stay red, and has no text "
            "telling them why."
        )
    # Named as a pair, not as an alternative: editing either one alone is red.
    assert "EXECUTION_EVIDENCE" in rendered
    assert "tests/test_smc_r1_rollout_contract.py" in rendered


def test_the_rendered_remedy_stays_inside_eighty_columns() -> None:
    """The evidence path is ~66 chars; interpolating it mid-sentence overflows.

    Both emitters of this text wrap at 80: this script's stderr block, and the
    fenced blocks the two workflows put in a job summary / PR body, where an
    over-long line forces horizontal scrolling. Measured against the REAL path
    rather than a short stub, because a stub does not reproduce the defect --
    it was a 189-character line in the resolution and a 127-character line in
    the preamble, both invisible to any assertion that used a placeholder.
    """
    evidence = EXECUTION_EVIDENCE.relative_to(ROOT).as_posix()
    assert len(evidence) > 40, (
        f"the evidence path is only {len(evidence)} chars; this pin assumes a "
        "long path and would not reproduce the overflow it exists to catch"
    )

    prose = _REMEDY.format(
        evidence=evidence,
        resolution=RESOLUTION.format(evidence=evidence),
    )
    offenders = [line for line in prose.splitlines() if len(line) > 80]
    assert not offenders, (
        "rendered remedy lines exceed 80 columns:\n"
        + "\n".join(f"  {len(line):>3}  {line}" for line in offenders)
        + "\nKeep the {evidence} placeholder on a line of its own."
    )

    # Scoped to the prose on purpose. The per-source rows _render appends carry
    # full SHA-256 digests (64 chars + label = 88) and must print whole: a
    # wrapped hash cannot be grepped or compared by eye, which is the entire
    # point of showing both of them. Those lines are data, not prose, and are
    # excluded by measuring the constants rather than _render's output.
    assert _render(
        [
            {
                "scriptName": "SMC Event Overlay",
                "path": "SMC_Event_Overlay.pine",
                "attestedSha256": _ATTESTED,
                "repositorySha256": _DRIFTED,
            }
        ],
        ["SMC Event Overlay"],
    ).startswith(prose), "the rendered report must still open with this prose block"
