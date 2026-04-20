"""Tests for the shared product-language glossary (ENG-WS6-03)."""
from __future__ import annotations

import pytest

from scripts.smc_product_language import (
    INTERNAL_JARGON,
    PRODUCT_GLOSSARY,
    lint_user_copy,
    term,
    user_label,
)


class TestGlossary:
    def test_core_terms_present(self) -> None:
        keys = {t.key for t in PRODUCT_GLOSSARY}
        # DoD: 'dieselben Kernbegriffe werden konsistent verwendet'.
        assert {"action", "quality", "trust", "risk",
                "main_blocker", "freshness", "degradation"} <= keys

    def test_terms_have_both_locales(self) -> None:
        for t in PRODUCT_GLOSSARY:
            assert t.user_label
            assert t.user_label_de
            assert t.description

    def test_no_duplicate_keys(self) -> None:
        keys = [t.key for t in PRODUCT_GLOSSARY]
        assert len(keys) == len(set(keys))


class TestLookup:
    def test_term_returns_entry(self) -> None:
        t = term("action")
        assert t.user_label == "Action"
        assert t.user_label_de == "Aktion"

    def test_term_unknown_raises(self) -> None:
        with pytest.raises(KeyError):
            term("not-a-term")

    def test_user_label_locale_switch(self) -> None:
        assert user_label("trust", locale="en") == "Trust"
        assert user_label("trust", locale="de") == "Vertrauen"

    def test_user_label_defaults_to_en(self) -> None:
        assert user_label("quality") == "Setup Quality"


class TestLintUserCopy:
    def test_clean_copy_has_no_violations(self) -> None:
        copy = "Setup Quality A — Action ENTER, Trust high, Freshness fresh."
        assert lint_user_copy(copy) == []

    def test_internal_jargon_is_flagged(self) -> None:
        copy = "Quality A based on calibrated_brier 0.18 from BUS_v2 packed state"
        flagged = lint_user_copy(copy)
        assert "calibrated_brier" in flagged
        assert "BUS_v2" in flagged

    def test_empty_text_passes(self) -> None:
        assert lint_user_copy("") == []

    def test_jargon_table_is_non_trivial(self) -> None:
        # Must include at least the internal scoring tokens, otherwise
        # the lint silently does nothing.
        assert "BUS_v2" in INTERNAL_JARGON
        assert "calibrated_brier" in INTERNAL_JARGON
        assert "ensemble_score" in INTERNAL_JARGON
