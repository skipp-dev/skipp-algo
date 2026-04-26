"""Tab: Calibration Detail — C7/T4 per-variant drill-down.

Pure-Python :func:`build_detail` produces the per-tab payloads
(walk-forward, bootstrap, permutation, regime, PSR/MinTRL) for a
single variant.  :func:`render` is the Streamlit entry point and only
imports streamlit lazily.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

__all__ = [
    "build_detail",
    "find_variant",
    "render",
]


def find_variant(
    payload: Mapping[str, Any] | None,
    variant_name: str,
) -> dict[str, Any] | None:
    """Locate a variant by name in a dashboard payload."""
    if not payload:
        return None
    for v in payload.get("variants") or []:
        if str(v.get("variant", "")) == variant_name:
            return dict(v)
    return None


def _coerce_optional_float(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def _walk_forward_block(variant: Mapping[str, Any]) -> dict[str, Any]:
    folds = variant.get("walk_forward_folds") or []
    fold_sharpes = [
        _coerce_optional_float(f.get("sharpe"))
        for f in folds
        if isinstance(f, Mapping)
    ]
    fold_sharpes = [v for v in fold_sharpes if v is not None]
    return {
        "available": bool(folds),
        "n_folds": len(folds),
        "fold_sharpes": fold_sharpes,
        "wfe": _coerce_optional_float(variant.get("walk_forward_efficiency")),
        "mode": str(variant.get("walk_forward_mode") or "anchored"),
    }


def _bootstrap_block(variant: Mapping[str, Any]) -> dict[str, Any]:
    block = variant.get("bootstrap") or {}
    return {
        "available": bool(block),
        "sharpe_samples": [
            v for v in (
                _coerce_optional_float(s) for s in block.get("sharpe_samples") or []
            ) if v is not None
        ],
        "ci_low": _coerce_optional_float(variant.get("sharpe_ci_low")),
        "ci_high": _coerce_optional_float(variant.get("sharpe_ci_high")),
        "n_bootstraps": int(block.get("n_bootstraps") or 0) if block else 0,
    }


def _permutation_block(variant: Mapping[str, Any]) -> dict[str, Any]:
    block = variant.get("permutation") or {}
    return {
        "available": bool(block),
        "p_value": _coerce_optional_float(variant.get("permutation_p_value")),
        "observed": _coerce_optional_float(block.get("observed")),
        "null_samples": [
            v for v in (
                _coerce_optional_float(s) for s in block.get("null_samples") or []
            ) if v is not None
        ],
    }


def _regime_block(variant: Mapping[str, Any]) -> dict[str, Any]:
    block = variant.get("regime_stratified") or {}
    per_regime = {
        k: dict(v) for k, v in block.items() if isinstance(v, Mapping)
    }
    return {
        "available": bool(per_regime),
        "per_regime": per_regime,
        "aggregate_freq_weighted_sharpe": _coerce_optional_float(
            block.get("aggregate_freq_weighted_sharpe"),
        ),
        "concentration_warning": bool(block.get("regime_concentration_warning")),
    }


def _psr_block(variant: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "available": variant.get("psr") is not None,
        "psr": _coerce_optional_float(variant.get("psr")),
        "min_trl": _coerce_optional_float(variant.get("min_trl")),
        "sr_star": _coerce_optional_float(variant.get("sr_star")),
    }


def build_detail(
    payload: Mapping[str, Any] | None,
    variant_name: str,
) -> dict[str, Any]:
    """Assemble the per-variant drill-down payload.

    Returns a dict with ``status`` (``ok`` or ``not_found``), the
    canonical ``variant`` name, and one block per drill-down tab.
    Blocks always carry an ``available`` flag so the renderer can
    emit a "no data" placeholder rather than crash.
    """
    v = find_variant(payload, variant_name)
    if v is None:
        return {"status": "not_found", "variant": variant_name}
    return {
        "status": "ok",
        "variant": variant_name,
        "gate_status": str(v.get("gate_status") or "unknown"),
        "walk_forward": _walk_forward_block(v),
        "bootstrap": _bootstrap_block(v),
        "permutation": _permutation_block(v),
        "regime": _regime_block(v),
        "psr_min_trl": _psr_block(v),
    }


def render(  # pragma: no cover
    payload: Mapping[str, Any] | None,
    variant_name: str,
) -> None:
    """Render the per-variant drill-down inside a Streamlit app."""
    import streamlit as st

    detail = build_detail(payload, variant_name)
    st.subheader(f"🔬 Calibration detail — {variant_name}")
    if detail["status"] == "not_found":
        st.warning(f"Variant {variant_name!r} not present in current payload.")
        return

    tab_wf, tab_bs, tab_perm, tab_reg, tab_psr = st.tabs(
        ["Walk-Forward", "Bootstrap", "Permutation", "Regime", "PSR / MinTRL"],
    )
    with tab_wf:
        block = detail["walk_forward"]
        if not block["available"]:
            st.info("No walk-forward folds available.")
        else:
            st.metric("Folds", block["n_folds"])
            st.metric("WFE", block["wfe"] or 0.0)
            st.bar_chart(block["fold_sharpes"])
    with tab_bs:
        block = detail["bootstrap"]
        if not block["available"]:
            st.info("No bootstrap samples available.")
        else:
            st.write(f"95% CI: [{block['ci_low']}, {block['ci_high']}]")
            st.bar_chart(block["sharpe_samples"])
    with tab_perm:
        block = detail["permutation"]
        if not block["available"]:
            st.info("No permutation null available.")
        else:
            st.metric("p-value", block["p_value"] or 0.0)
    with tab_reg:
        block = detail["regime"]
        if not block["available"]:
            st.info("No regime-stratified breakdown available.")
        else:
            st.dataframe(block["per_regime"])
            if block["concentration_warning"]:
                st.warning("Regime concentration warning active.")
    with tab_psr:
        block = detail["psr_min_trl"]
        if not block["available"]:
            st.info("No PSR / MinTRL data available.")
        else:
            st.metric("PSR", block["psr"] or 0.0)
            st.metric("MinTRL", block["min_trl"] or 0.0)
