"""Default-Surface visual budget (ENG-WS3-02).

Realises ticket ``ENG-WS3-02`` from
``docs/engineering-program/smc_deep_review_2026-04-20_engineering_backlog.md``
("Default-Surface auf Compact Detail reduzieren").

The Pine dashboard already exposes five view modes plus a separate
``Compact Dashboard`` toggle and defaults to ``Decision Brief``. This
module pins the **visual budget** and the **default-vocabulary
contract** so future changes cannot silently re-grow the default
surface or smuggle BUS / operator-only terminology back into the first
reading level.

The contract lives next to the Hero Information Architecture
(``scripts/smc_hero_information_architecture``); together they form
the WS3 surface spec.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from types import MappingProxyType

# ── Default view mode ────────────────────────────────────────────────
# The Pine ``surface_mode`` input must default to this view mode. Any
# change here is a product-level decision that should fail this test
# loudly so the change is reviewed deliberately.
DEFAULT_VIEW_MODE: str = "Decision Brief"


# ── Visual budget per view mode ──────────────────────────────────────
# Maximum number of visible product rows each view mode may render.
# Keep these in sync with the tooltip in ``SMC_Dashboard.pine``.
_VISUAL_BUDGET: Mapping[str, int] = MappingProxyType({
    "Focus": 3,
    "Hero": 7,
    "Decision Brief": 7,
    "Explain": 8,
    "Audit View": 30,
    # Synthetic mode mirroring the Compact Dashboard toggle.
    "Mobile": 5,
})

VISUAL_BUDGET: Mapping[str, int] = _VISUAL_BUDGET


def visual_budget_for(view_mode: str) -> int:
    """Return the maximum number of visible rows allowed for ``view_mode``."""
    if view_mode not in VISUAL_BUDGET:
        raise KeyError(f"Unknown view mode: {view_mode!r}")
    return VISUAL_BUDGET[view_mode]


# ── Forbidden default-surface vocabulary ─────────────────────────────
# Substrings that must never appear in a row label that the Default
# (Decision Brief / Focus / Hero / Mobile) surface renders. They are
# operator-only or BUS-internal tokens.
FORBIDDEN_DEFAULT_TOKENS: tuple[str, ...] = (
    "BUS_",
    "PACK_",
    "PACKED_BUS",
    "ENSEMBLE_",
    "OPERATOR_",
    "TIER_PRIVATE",
    "RAW_PROOF",
    "DIAG_",
)

# View modes that the user sees by default (no opt-in expert mode). Any
# row a view in this set surfaces is bound by the forbidden-vocabulary
# contract.
_DEFAULT_FACING_VIEWS: frozenset[str] = frozenset({
    "Focus",
    "Hero",
    "Decision Brief",
    "Mobile",
})


def default_facing_views() -> frozenset[str]:
    """Return the set of user-default view modes (no opt-in expert mode)."""
    return _DEFAULT_FACING_VIEWS


def forbidden_tokens_in(label: str) -> tuple[str, ...]:
    """Return the forbidden tokens that appear in ``label`` (case-insensitive)."""
    upper = label.upper()
    return tuple(token for token in FORBIDDEN_DEFAULT_TOKENS if token in upper)


def validate_default_visible_rows(
    view_mode: str,
    row_labels: Iterable[str],
) -> None:
    """Validate visible row labels against the WS3-02 contract.

    Raises ``ValueError`` when:

    * the view mode is unknown,
    * the visible row count exceeds the visual budget,
    * a row label contains forbidden default-surface vocabulary
      (only enforced for default-facing views).
    """
    if view_mode not in VISUAL_BUDGET:
        raise ValueError(f"Unknown view mode: {view_mode!r}")

    labels = list(row_labels)
    budget = VISUAL_BUDGET[view_mode]
    if len(labels) > budget:
        raise ValueError(
            f"View {view_mode!r} renders {len(labels)} rows, exceeds visual budget {budget}"
        )

    if view_mode in _DEFAULT_FACING_VIEWS:
        offenders = []
        for label in labels:
            tokens = forbidden_tokens_in(label)
            if tokens:
                offenders.append((label, tokens))
        if offenders:
            details = "; ".join(f"{lbl!r} contains {toks}" for lbl, toks in offenders)
            raise ValueError(
                f"View {view_mode!r} contains forbidden default-surface vocabulary: {details}"
            )


__all__ = [
    "DEFAULT_VIEW_MODE",
    "FORBIDDEN_DEFAULT_TOKENS",
    "VISUAL_BUDGET",
    "default_facing_views",
    "forbidden_tokens_in",
    "validate_default_visible_rows",
    "visual_budget_for",
]
