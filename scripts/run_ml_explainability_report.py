from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import numpy as np
from ml.training import LGBMFamilyTrainer, LogisticBaseline, XGBFamilyTrainer
from scripts.ml_research_common import (
    build_dataset_bundle,
    iso_now,
    parse_families,
)
from scripts.smc_atomic_write import atomic_write_text

REPO_ROOT = Path(__file__).resolve().parents[1]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a SHAP explainability report for synthetic ml/ family models.")
    parser.add_argument("--backend", choices=["logistic", "xgboost", "lightgbm"], default=os.getenv("SKIPP_ML_BACKEND", "xgboost"))
    parser.add_argument("--device", choices=["auto", "cpu", "cuda"], default=os.getenv("SKIPP_ML_DEVICE", "auto"))
    parser.add_argument("--families", default="BOS,OB,FVG,SWEEP")
    parser.add_argument("--samples-per-family", type=int, default=900)
    parser.add_argument("--feature-count", type=int, default=16)
    parser.add_argument("--background-samples", type=int, default=128)
    parser.add_argument("--analysis-samples", type=int, default=256)
    parser.add_argument("--top-k", type=int, default=8)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument(
        "--output-path",
        default=str(REPO_ROOT / "artifacts" / "ml" / "research" / "explainability" / "latest.json"),
    )
    parser.add_argument(
        "--markdown-path",
        default=str(REPO_ROOT / "artifacts" / "ml" / "research" / "explainability" / "latest.md"),
    )
    return parser


def _load_shap() -> Any:
    try:
        import shap  # type: ignore
    except Exception as exc:  # pragma: no cover - dependency guard
        raise RuntimeError(
            "shap is not installed. Install via 'pip install -r requirements-ml.txt' to run explainability reports."
        ) from exc
    return shap


def _build_trainer(*, backend: str, device: str, seed: int):
    if backend == "logistic":
        return LogisticBaseline(seed=seed, max_iter=400)
    if backend == "xgboost":
        return XGBFamilyTrainer(seed=seed, device=device, n_estimators=160)
    if backend == "lightgbm":
        return LGBMFamilyTrainer(seed=seed, device=device, n_estimators=160)
    raise ValueError(f"unsupported backend {backend!r}")


def _device_metadata(*, backend: str, trainer, requested_device: str) -> tuple[str, str | None]:
    resolved = str(getattr(trainer, "resolved_device", "cpu"))
    fallback = getattr(trainer, "device_fallback_reason", None)
    if backend == "logistic" and requested_device != "cpu":
        fallback = "logistic_cpu_only"
    return resolved, fallback


def _build_explainer(shap_module: Any, payload: Any, background: np.ndarray):
    try:
        return shap_module.Explainer(payload, background)
    except Exception:
        if hasattr(shap_module, "TreeExplainer"):
            return shap_module.TreeExplainer(payload)
        raise


def _coerce_shap_values(explainer: Any, X: np.ndarray) -> np.ndarray:
    try:
        result = explainer(X)
    except Exception:
        if not hasattr(explainer, "shap_values"):
            raise
        result = explainer.shap_values(X)
    values = getattr(result, "values", result)
    arr = np.asarray(values, dtype=float)
    if arr.ndim == 3:
        arr = arr[..., -1]
    if arr.ndim != 2:
        raise ValueError(f"expected SHAP values with rank 2, got shape {arr.shape}")
    return arr


def _rank_features(feature_names: tuple[str, ...], shap_values: np.ndarray, *, top_k: int) -> list[dict[str, object]]:
    mean_abs = np.abs(shap_values).mean(axis=0)
    ranked_idx = np.argsort(-mean_abs)
    rows: list[dict[str, object]] = []
    for rank, feature_idx in enumerate(ranked_idx[:top_k], start=1):
        rows.append(
            {
                "rank": rank,
                "feature": feature_names[int(feature_idx)],
                "mean_abs_shap": float(mean_abs[int(feature_idx)]),
            }
        )
    return rows


def _render_markdown(payload: dict[str, object]) -> str:
    lines = [
        "# ML Explainability Report",
        "",
        f"- generated_at: `{payload['generated_at']}`",
        f"- backend: `{payload['backend']}`",
        f"- requested_device: `{payload['requested_device']}`",
        f"- resolved_devices: `{', '.join(payload['resolved_devices'])}`",
        f"- families: `{', '.join(payload['families'])}`",
        "",
        "## Aggregate top features",
        "",
        "| rank | feature | total mean abs SHAP |",
        "| --- | --- | ---: |",
    ]
    for item in payload["aggregate_top_features"]:
        lines.append(f"| {item['rank']} | `{item['feature']}` | {item['total_mean_abs_shap']:.6f} |")

    for family_report in payload["family_reports"]:
        lines.extend(
            [
                "",
                f"## {family_report['family']}",
                "",
                f"- model_version: `{family_report['model_version']}`",
                f"- resolved_device: `{family_report['resolved_device']}`",
                f"- auc: `{family_report['auc']:.6f}`",
                f"- brier: `{family_report['brier']:.6f}`",
                "",
                "| rank | feature | mean abs SHAP |",
                "| --- | --- | ---: |",
            ]
        )
        for row in family_report["top_features"]:
            lines.append(f"| {row['rank']} | `{row['feature']}` | {row['mean_abs_shap']:.6f} |")
    lines.append("")
    return "\n".join(lines)


def generate_report(
    *,
    backend: str,
    device: str,
    families_raw: str,
    samples_per_family: int,
    feature_count: int,
    background_samples: int,
    analysis_samples: int,
    top_k: int,
    seed: int,
) -> dict[str, object]:
    shap_module = _load_shap()
    families = parse_families(families_raw)
    datasets = build_dataset_bundle(
        families,
        n_samples=samples_per_family,
        n_features=feature_count,
        seed=seed,
    )

    family_reports: list[dict[str, object]] = []
    aggregate_scores: dict[str, float] = {}
    for idx, family in enumerate(families):
        dataset = datasets[family]
        trainer = _build_trainer(backend=backend, device=device, seed=seed + idx)
        fitted, report = trainer.fit(dataset)
        bg_rows = max(8, min(background_samples, dataset.X.shape[0]))
        eval_rows = max(16, min(analysis_samples, dataset.X.shape[0]))
        background = dataset.X[:bg_rows]
        eval_X = dataset.X[:eval_rows]
        explainer = _build_explainer(shap_module, fitted.payload, background)
        shap_values = _coerce_shap_values(explainer, eval_X)
        top_features = _rank_features(dataset.feature_names, shap_values, top_k=top_k)
        for row in top_features:
            aggregate_scores[row["feature"]] = aggregate_scores.get(row["feature"], 0.0) + float(row["mean_abs_shap"])
        resolved_device, fallback_reason = _device_metadata(
            backend=backend,
            trainer=trainer,
            requested_device=device,
        )
        family_reports.append(
            {
                "family": family,
                "model_version": report.model_version,
                "resolved_device": resolved_device,
                "device_fallback_reason": fallback_reason,
                "brier": report.brier,
                "log_loss": report.log_loss,
                "auc": report.auc,
                "top_features": top_features,
            }
        )

    aggregate_top_features = [
        {
            "rank": rank,
            "feature": feature,
            "total_mean_abs_shap": score,
        }
        for rank, (feature, score) in enumerate(
            sorted(aggregate_scores.items(), key=lambda item: (-item[1], item[0]))[:top_k],
            start=1,
        )
    ]
    return {
        "generated_at": iso_now(),
        "mode": "explainability",
        "backend": backend,
        "requested_device": device,
        "resolved_devices": sorted({str(item["resolved_device"]) for item in family_reports}),
        "families": list(families),
        "samples_per_family": samples_per_family,
        "feature_count": feature_count,
        "aggregate_top_features": aggregate_top_features,
        "family_reports": family_reports,
    }


def main() -> int:
    args = build_parser().parse_args()
    payload = generate_report(
        backend=str(args.backend),
        device=str(args.device),
        families_raw=str(args.families),
        samples_per_family=int(args.samples_per_family),
        feature_count=int(args.feature_count),
        background_samples=int(args.background_samples),
        analysis_samples=int(args.analysis_samples),
        top_k=int(args.top_k),
        seed=int(args.seed),
    )
    output_path = Path(args.output_path).expanduser()
    markdown_path = Path(args.markdown_path).expanduser()
    atomic_write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", output_path)
    atomic_write_text(_render_markdown(payload), markdown_path)

    top_feature = payload["aggregate_top_features"][0]["feature"] if payload["aggregate_top_features"] else "none"
    print(f"mode={payload['mode']}")
    print(f"backend={payload['backend']}")
    print(f"requested_device={payload['requested_device']}")
    print(f"resolved_devices={','.join(payload['resolved_devices'])}")
    print(f"top_feature={top_feature}")
    print(f"artifact={output_path.as_posix()}")
    print(f"markdown={markdown_path.as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())