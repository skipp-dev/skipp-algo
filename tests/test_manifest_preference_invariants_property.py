"""Property invariants for ``smc_integration.manifest_preference``.

Pins the manifest-preferred artifact resolution policy (ENG-WS5-01):
manifest > shadow > scratch, with stable original-order tie-breaking and
auditable reason strings. Tier-2 contract test for the policy module that
sits above the tier-1 primitives.
"""
from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from smc_integration.manifest_preference import (
    ArtifactCandidate,
    ArtifactSource,
    ResolutionResult,
    resolve_preferred,
)


# ---------------------------------------------------------------------------
# ArtifactSource enum
# ---------------------------------------------------------------------------
class TestArtifactSourceEnum:
    def test_exact_membership(self) -> None:
        assert {s.value for s in ArtifactSource} == {"manifest", "shadow", "scratch"}

    def test_string_values_lowercase(self) -> None:
        assert ArtifactSource.MANIFEST.value == "manifest"
        assert ArtifactSource.SHADOW.value == "shadow"
        assert ArtifactSource.SCRATCH.value == "scratch"

    def test_is_str_enum(self) -> None:
        # StrEnum members are strings.
        assert isinstance(ArtifactSource.MANIFEST, str)
        assert ArtifactSource.MANIFEST == "manifest"

    def test_size_pinned(self) -> None:
        assert len(list(ArtifactSource)) == 3


# ---------------------------------------------------------------------------
# Priority ordering
# ---------------------------------------------------------------------------
class TestPriorityOrdering:
    def test_manifest_priority(self) -> None:
        c = ArtifactCandidate(path=Path("x"), source=ArtifactSource.MANIFEST)
        assert c.priority == 100

    def test_shadow_priority(self) -> None:
        c = ArtifactCandidate(path=Path("x"), source=ArtifactSource.SHADOW)
        assert c.priority == 50

    def test_scratch_priority(self) -> None:
        c = ArtifactCandidate(path=Path("x"), source=ArtifactSource.SCRATCH)
        assert c.priority == 0

    def test_strict_ordering_manifest_beats_shadow(self) -> None:
        m = ArtifactCandidate(path=Path("m"), source=ArtifactSource.MANIFEST)
        s = ArtifactCandidate(path=Path("s"), source=ArtifactSource.SHADOW)
        assert m.priority > s.priority

    def test_strict_ordering_shadow_beats_scratch(self) -> None:
        s = ArtifactCandidate(path=Path("s"), source=ArtifactSource.SHADOW)
        sc = ArtifactCandidate(path=Path("sc"), source=ArtifactSource.SCRATCH)
        assert s.priority > sc.priority

    def test_scratch_priority_is_lowest_non_negative(self) -> None:
        c = ArtifactCandidate(path=Path("x"), source=ArtifactSource.SCRATCH)
        assert c.priority == 0


# ---------------------------------------------------------------------------
# Frozen-ness
# ---------------------------------------------------------------------------
class TestFrozenDataclasses:
    def test_candidate_is_frozen(self) -> None:
        c = ArtifactCandidate(path=Path("x"), source=ArtifactSource.MANIFEST)
        with pytest.raises(dataclasses.FrozenInstanceError):
            c.label = "renamed"  # type: ignore[misc]

    def test_result_is_frozen(self) -> None:
        result = resolve_preferred([])
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.reason = "tampered"  # type: ignore[misc]

    def test_candidate_default_label_empty(self) -> None:
        c = ArtifactCandidate(path=Path("x"), source=ArtifactSource.SHADOW)
        assert c.label == ""


# ---------------------------------------------------------------------------
# resolve_preferred — empty
# ---------------------------------------------------------------------------
class TestResolveEmpty:
    def test_empty_iterable_returns_none_chosen(self) -> None:
        r = resolve_preferred([])
        assert r.chosen is None
        assert r.rejected == ()
        assert r.reason == "no candidates"

    def test_empty_generator_returns_none_chosen(self) -> None:
        r = resolve_preferred(c for c in ())
        assert r.chosen is None
        assert r.reason == "no candidates"


# ---------------------------------------------------------------------------
# resolve_preferred — single candidate
# ---------------------------------------------------------------------------
class TestResolveSingle:
    def test_single_manifest_chosen(self) -> None:
        c = ArtifactCandidate(path=Path("/a/m.json"), source=ArtifactSource.MANIFEST)
        r = resolve_preferred([c])
        assert r.chosen is c
        assert r.rejected == ()
        assert "manifest" in r.reason
        assert "/a/m.json" in r.reason or "m.json" in r.reason

    def test_single_shadow_chosen_with_shadow_reason(self) -> None:
        c = ArtifactCandidate(path=Path("/a/s.json"), source=ArtifactSource.SHADOW)
        r = resolve_preferred([c])
        assert r.chosen is c
        assert "shadow" in r.reason
        assert "no manifest-backed artifact available" in r.reason

    def test_single_scratch_chosen_with_scratch_reason(self) -> None:
        c = ArtifactCandidate(path=Path("/a/scratch.json"), source=ArtifactSource.SCRATCH)
        r = resolve_preferred([c])
        assert r.chosen is c
        assert "only scratch candidate" in r.reason
        assert "no manifest-backed artifact found" in r.reason


# ---------------------------------------------------------------------------
# resolve_preferred — priority dominance
# ---------------------------------------------------------------------------
class TestResolvePriority:
    def test_manifest_beats_scratch_regardless_of_order(self) -> None:
        manifest = ArtifactCandidate(path=Path("/m.json"), source=ArtifactSource.MANIFEST)
        scratch = ArtifactCandidate(path=Path("/scratch.json"), source=ArtifactSource.SCRATCH)
        r1 = resolve_preferred([manifest, scratch])
        r2 = resolve_preferred([scratch, manifest])
        assert r1.chosen is manifest
        assert r2.chosen is manifest

    def test_manifest_beats_shadow_regardless_of_order(self) -> None:
        manifest = ArtifactCandidate(path=Path("/m.json"), source=ArtifactSource.MANIFEST)
        shadow = ArtifactCandidate(path=Path("/sh.json"), source=ArtifactSource.SHADOW)
        r1 = resolve_preferred([manifest, shadow])
        r2 = resolve_preferred([shadow, manifest])
        assert r1.chosen is manifest
        assert r2.chosen is manifest

    def test_shadow_beats_scratch_regardless_of_order(self) -> None:
        shadow = ArtifactCandidate(path=Path("/sh.json"), source=ArtifactSource.SHADOW)
        scratch = ArtifactCandidate(path=Path("/scratch.json"), source=ArtifactSource.SCRATCH)
        r1 = resolve_preferred([shadow, scratch])
        r2 = resolve_preferred([scratch, shadow])
        assert r1.chosen is shadow
        assert r2.chosen is shadow

    def test_manifest_beats_scratch_even_when_path_sorts_lower(self) -> None:
        # Manifest path "z.json" sorts after scratch "a.json" — priority must still win.
        manifest = ArtifactCandidate(path=Path("z.json"), source=ArtifactSource.MANIFEST)
        scratch = ArtifactCandidate(path=Path("a.json"), source=ArtifactSource.SCRATCH)
        r = resolve_preferred([scratch, manifest])
        assert r.chosen is manifest

    def test_all_three_sources_manifest_wins(self) -> None:
        manifest = ArtifactCandidate(path=Path("/m"), source=ArtifactSource.MANIFEST)
        shadow = ArtifactCandidate(path=Path("/sh"), source=ArtifactSource.SHADOW)
        scratch = ArtifactCandidate(path=Path("/sc"), source=ArtifactSource.SCRATCH)
        r = resolve_preferred([scratch, shadow, manifest])
        assert r.chosen is manifest
        assert set(r.rejected) == {shadow, scratch}


# ---------------------------------------------------------------------------
# resolve_preferred — stable tie-breaking
# ---------------------------------------------------------------------------
class TestStableTieBreak:
    def test_ties_break_on_original_order_not_path(self) -> None:
        # Two manifests with paths sorting reverse-of-input.
        a = ArtifactCandidate(path=Path("z.json"), source=ArtifactSource.MANIFEST)
        b = ArtifactCandidate(path=Path("a.json"), source=ArtifactSource.MANIFEST)
        r = resolve_preferred([a, b])
        assert r.chosen is a  # original order wins, not path sort

    def test_ties_among_shadows_break_on_original_order(self) -> None:
        a = ArtifactCandidate(path=Path("z.json"), source=ArtifactSource.SHADOW)
        b = ArtifactCandidate(path=Path("a.json"), source=ArtifactSource.SHADOW)
        r = resolve_preferred([a, b])
        assert r.chosen is a

    def test_ties_among_scratches_break_on_original_order(self) -> None:
        a = ArtifactCandidate(path=Path("z.json"), source=ArtifactSource.SCRATCH)
        b = ArtifactCandidate(path=Path("a.json"), source=ArtifactSource.SCRATCH)
        r = resolve_preferred([a, b])
        assert r.chosen is a


# ---------------------------------------------------------------------------
# resolve_preferred — rejected ordering
# ---------------------------------------------------------------------------
class TestRejectedTuple:
    def test_rejected_is_tuple(self) -> None:
        manifest = ArtifactCandidate(path=Path("m"), source=ArtifactSource.MANIFEST)
        scratch = ArtifactCandidate(path=Path("s"), source=ArtifactSource.SCRATCH)
        r = resolve_preferred([manifest, scratch])
        assert isinstance(r.rejected, tuple)
        assert r.rejected == (scratch,)

    def test_chosen_not_in_rejected(self) -> None:
        manifest = ArtifactCandidate(path=Path("m"), source=ArtifactSource.MANIFEST)
        shadow = ArtifactCandidate(path=Path("sh"), source=ArtifactSource.SHADOW)
        scratch = ArtifactCandidate(path=Path("sc"), source=ArtifactSource.SCRATCH)
        r = resolve_preferred([scratch, shadow, manifest])
        assert r.chosen not in r.rejected
        assert len(r.rejected) == 2


# ---------------------------------------------------------------------------
# resolve_preferred — reason strings
# ---------------------------------------------------------------------------
class TestReasonStrings:
    def test_manifest_with_scratch_reason_mentions_count(self) -> None:
        manifest = ArtifactCandidate(path=Path("m.json"), source=ArtifactSource.MANIFEST)
        s1 = ArtifactCandidate(path=Path("s1.json"), source=ArtifactSource.SCRATCH)
        s2 = ArtifactCandidate(path=Path("s2.json"), source=ArtifactSource.SCRATCH)
        r = resolve_preferred([manifest, s1, s2])
        assert "ignored 2 scratch candidate(s)" in r.reason
        assert "manifest beats local scratch" in r.reason

    def test_manifest_alone_reason_omits_ignored(self) -> None:
        manifest = ArtifactCandidate(path=Path("m.json"), source=ArtifactSource.MANIFEST)
        r = resolve_preferred([manifest])
        assert "ignored" not in r.reason
        assert "manifest" in r.reason

    def test_manifest_with_shadow_no_scratch_reason(self) -> None:
        manifest = ArtifactCandidate(path=Path("m.json"), source=ArtifactSource.MANIFEST)
        shadow = ArtifactCandidate(path=Path("sh.json"), source=ArtifactSource.SHADOW)
        r = resolve_preferred([manifest, shadow])
        # No scratch present → no "ignored ... scratch" verbiage.
        assert "scratch" not in r.reason


# ---------------------------------------------------------------------------
# ResolutionResult.as_dict
# ---------------------------------------------------------------------------
class TestResolutionAsDict:
    def test_empty_serialises_none_chosen(self) -> None:
        d = resolve_preferred([]).as_dict()
        assert d["chosen_path"] is None
        assert d["chosen_source"] is None
        assert d["chosen_label"] == ""
        assert d["rejected"] == []
        assert d["reason"] == "no candidates"

    def test_single_manifest_serialises_fields(self) -> None:
        m = ArtifactCandidate(
            path=Path("/a/m.json"), source=ArtifactSource.MANIFEST, label="release-12"
        )
        d = resolve_preferred([m]).as_dict()
        assert d["chosen_path"] == str(Path("/a/m.json"))
        assert d["chosen_source"] == "manifest"
        assert d["chosen_label"] == "release-12"
        assert d["rejected"] == []

    def test_rejected_serialised_in_order(self) -> None:
        manifest = ArtifactCandidate(
            path=Path("m.json"), source=ArtifactSource.MANIFEST, label="m"
        )
        s1 = ArtifactCandidate(
            path=Path("s1.json"), source=ArtifactSource.SCRATCH, label="s1"
        )
        s2 = ArtifactCandidate(
            path=Path("s2.json"), source=ArtifactSource.SCRATCH, label="s2"
        )
        d = resolve_preferred([manifest, s1, s2]).as_dict()
        assert len(d["rejected"]) == 2
        labels = [entry["label"] for entry in d["rejected"]]
        assert labels == ["s1", "s2"]
        sources = [entry["source"] for entry in d["rejected"]]
        assert sources == ["scratch", "scratch"]

    def test_as_dict_source_is_string_value(self) -> None:
        # Ensure StrEnum is serialised as its `.value`, not as repr.
        m = ArtifactCandidate(path=Path("m"), source=ArtifactSource.MANIFEST)
        d = resolve_preferred([m]).as_dict()
        assert d["chosen_source"] == "manifest"
        assert isinstance(d["chosen_source"], str)


# ---------------------------------------------------------------------------
# Determinism & non-mutation
# ---------------------------------------------------------------------------
class TestDeterminismAndNonMutation:
    def test_repeated_calls_yield_equal_result(self) -> None:
        candidates = [
            ArtifactCandidate(path=Path("m"), source=ArtifactSource.MANIFEST),
            ArtifactCandidate(path=Path("sh"), source=ArtifactSource.SHADOW),
            ArtifactCandidate(path=Path("sc"), source=ArtifactSource.SCRATCH),
        ]
        r1 = resolve_preferred(list(candidates))
        r2 = resolve_preferred(list(candidates))
        assert r1 == r2

    def test_input_list_not_mutated(self) -> None:
        candidates = [
            ArtifactCandidate(path=Path("sc"), source=ArtifactSource.SCRATCH),
            ArtifactCandidate(path=Path("m"), source=ArtifactSource.MANIFEST),
        ]
        original = list(candidates)
        resolve_preferred(candidates)
        assert candidates == original

    def test_returns_resolution_result_instance(self) -> None:
        r = resolve_preferred([])
        assert isinstance(r, ResolutionResult)
