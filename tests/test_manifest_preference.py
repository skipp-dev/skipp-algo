"""Tests for manifest-preferred artifact resolution (ENG-WS5-01)."""
from __future__ import annotations

from pathlib import Path

from smc_integration.manifest_preference import (
    ArtifactCandidate,
    ArtifactSource,
    resolve_preferred,
)


def _c(path: str, source: ArtifactSource, label: str = "") -> ArtifactCandidate:
    return ArtifactCandidate(path=Path(path), source=source, label=label)


class TestResolvePreferred:
    def test_manifest_beats_scratch(self) -> None:
        # Even when scratch is enumerated first, manifest must win.
        result = resolve_preferred([
            _c("/tmp/local/scratch.csv", ArtifactSource.SCRATCH),
            _c("/release/manifest.csv", ArtifactSource.MANIFEST, label="rel-1"),
        ])
        assert result.chosen is not None
        assert result.chosen.source is ArtifactSource.MANIFEST
        assert "manifest beats local scratch" in result.reason

    def test_manifest_beats_shadow(self) -> None:
        result = resolve_preferred([
            _c("/shadow/staging.csv", ArtifactSource.SHADOW),
            _c("/release/manifest.csv", ArtifactSource.MANIFEST),
        ])
        assert result.chosen is not None
        assert result.chosen.source is ArtifactSource.MANIFEST

    def test_shadow_beats_scratch(self) -> None:
        result = resolve_preferred([
            _c("/tmp/scratch.csv", ArtifactSource.SCRATCH),
            _c("/shadow/staging.csv", ArtifactSource.SHADOW),
        ])
        assert result.chosen is not None
        assert result.chosen.source is ArtifactSource.SHADOW

    def test_scratch_only_records_explicit_reason(self) -> None:
        result = resolve_preferred([_c("/tmp/x.csv", ArtifactSource.SCRATCH)])
        assert result.chosen is not None
        assert result.chosen.source is ArtifactSource.SCRATCH
        assert "no manifest-backed artifact found" in result.reason

    def test_no_candidates_returns_none(self) -> None:
        result = resolve_preferred([])
        assert result.chosen is None
        assert result.reason == "no candidates"

    def test_rejected_candidates_are_listed(self) -> None:
        result = resolve_preferred([
            _c("/release/manifest.csv", ArtifactSource.MANIFEST),
            _c("/tmp/scratch1.csv", ArtifactSource.SCRATCH),
            _c("/tmp/scratch2.csv", ArtifactSource.SCRATCH),
        ])
        assert len(result.rejected) == 2
        assert all(c.source is ArtifactSource.SCRATCH for c in result.rejected)

    def test_as_dict_round_trip(self) -> None:
        result = resolve_preferred([
            _c("/release/m.csv", ArtifactSource.MANIFEST, label="rel-1"),
            _c("/tmp/s.csv", ArtifactSource.SCRATCH),
        ])
        d = result.as_dict()
        assert d["chosen_source"] == "manifest"
        assert d["chosen_label"] == "rel-1"
        assert d["rejected"][0]["source"] == "scratch"
        assert "manifest" in d["reason"]
