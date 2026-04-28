"""Tests for the product-surface matrix (ENG-WS6-01)."""
from __future__ import annotations

from collections import Counter

from scripts.smc_surface_matrix import (
    SURFACE_MATRIX,
    Audience,
    SurfaceClass,
    default_for,
    historical_surfaces,
    production_surfaces,
    render_matrix_markdown,
)


class TestMatrixContract:
    def test_every_audience_has_exactly_one_production_default(self) -> None:
        # DoD: 'produktive Default-Pfade sind eindeutig'.
        for aud in (Audience.DESKTOP, Audience.MOBILE):
            defaults = [s for s in SURFACE_MATRIX
                        if s.audience is aud and s.is_default
                        and s.classification is SurfaceClass.PRODUCTION]
            assert len(defaults) == 1, f"audience {aud} must have exactly one default"

    def test_only_production_surfaces_are_marked_default(self) -> None:
        # DoD: 'historische Varianten sind nicht mehr implizit gleichrangig'.
        for s in SURFACE_MATRIX:
            if s.is_default:
                assert s.classification is SurfaceClass.PRODUCTION

    def test_historical_surfaces_are_documented(self) -> None:
        hist = historical_surfaces()
        assert len(hist) >= 1
        # CHoCH variants must appear as historical, not production.
        names = {s.name for s in hist}
        assert "CHOCH-Indicator.pine" in names
        assert "CHOCH-Strategy.pine" in names

    def test_no_duplicate_surface_names(self) -> None:
        counts = Counter(s.name for s in SURFACE_MATRIX)
        dupes = {n: c for n, c in counts.items() if c > 1}
        assert dupes == {}

    def test_all_classifications_are_known(self) -> None:
        for s in SURFACE_MATRIX:
            assert s.classification in SurfaceClass
            assert s.audience in Audience


class TestHelpers:
    def test_default_for_desktop(self) -> None:
        d = default_for(Audience.DESKTOP)
        assert d is not None
        assert d.name == "SMC_Dashboard.pine"

    def test_default_for_mobile(self) -> None:
        d = default_for(Audience.MOBILE)
        assert d is not None
        assert d.name == "SMC_Mobile_Dashboard.pine"

    def test_default_for_operator_is_none(self) -> None:
        # Operator-only surfaces are not user defaults.
        assert default_for(Audience.OPERATOR) is None

    def test_production_surfaces_exclude_historical(self) -> None:
        prod = production_surfaces()
        assert all(s.classification is SurfaceClass.PRODUCTION for s in prod)
        assert all(s.classification is not SurfaceClass.HISTORICAL for s in prod)


class TestRender:
    def test_markdown_contains_all_surfaces(self) -> None:
        md = render_matrix_markdown()
        for s in SURFACE_MATRIX:
            assert s.name in md
        assert "SMC Product-Surface Matrix" in md
        # Default marker visible.
        assert "✓" in md
