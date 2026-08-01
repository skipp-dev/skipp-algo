"""The automated save must not un-attest an R1 source.

#4286 guards the pull-request path. The 2026-08-01 un-attestation did not take
it: ``smc-library-refresh`` succeeded, the chained ``tv-save-consumer-source``
pushed the new Event Overlay source, and the source the evidence attests
stopped existing. No diff, no gate.

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

from scripts.smc_r1_rollout_contract import ROOT, build_rollout_contract
from scripts.tv_attested_source_holdback import (
    DEFAULT_CONFIG,
    attested_sources,
    drifted_attested_targets,
    holdback_names,
)

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


def test_agreement_holds_nothing_back() -> None:
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


def test_a_source_the_evidence_does_not_attest_is_not_this_guard_s_business() -> None:
    drifted = drifted_attested_targets(targets=_TARGETS, sources={})

    assert drifted == []


def test_holdback_is_intersected_with_what_this_config_would_actually_save(
    tmp_path: Path,
) -> None:
    """Holding back a name the rollout never writes would report a hold that did not happen."""
    drifted = drifted_attested_targets(
        targets=_TARGETS,
        sources=_sources(**{"SMC Event Overlay": _DRIFTED, "SMC Exit Signal": _DRIFTED}),
    )

    both = _config(tmp_path, ["SMC Event Overlay", "SMC Exit Signal", "SMC Long-Dip Suite"])
    assert holdback_names(both, drifted) == ["SMC Event Overlay", "SMC Exit Signal"]

    one = _config(tmp_path, ["SMC Exit Signal", "SMC Long-Dip Suite"])
    assert holdback_names(one, drifted) == ["SMC Exit Signal"]

    none = _config(tmp_path, ["SMC Long-Dip Suite"])
    assert holdback_names(none, drifted) == []


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
            f"{name} disagrees with the registered evidence; the holdback guard would "
            "hold it back on every run"
        )


def test_stdout_is_only_the_machine_value_so_the_shell_can_append_it_verbatim() -> None:
    """The workflow does ``echo "TV_ATTESTED_HOLDBACK=$(...)" >> $GITHUB_ENV``.

    Any prose on stdout would land in the environment file and break the run,
    so the human-readable remedy goes to stderr. Checked as a subprocess
    because that is the interface the workflow actually uses -- calling main()
    in-process would not catch a stray print.
    """
    result = subprocess.run(
        [sys.executable, "-m", "scripts.tv_attested_source_holdback"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    assert isinstance(json.loads(result.stdout.strip()), list)
    assert result.stdout.count("\n") == 1, f"stdout carried more than the value: {result.stdout!r}"
    assert result.stderr.strip(), "the human-readable line must still be emitted, on stderr"
