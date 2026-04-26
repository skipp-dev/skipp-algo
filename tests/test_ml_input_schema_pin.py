"""Schema-pin guard for the future ML layer (C10).

This test pins the SHA256 of the source-of-truth blocks that will feed
the ML-layer trainers (C10-T2 onwards). It uses **stdlib only** —
no xgboost/lightgbm/optuna/shap imports — so it does not affect the
slim-dashboard image footprint or CI install time.

Companion JSON: ``ml/schemas/v1_input_schema.json``,
``ml/schemas/v1_hero_features.json``.

Drift policy
------------
If ``smc_core/scoring.py`` (FamilyScoringMetrics or EventFamily)
changes, this test fails. The remediation is:

1. Decide whether the change is intentional and whether it breaks the
   future ML-input contract.
2. If breaking: bump ``schema_version`` to ``v2`` in the JSON, write a
   ``CHANGELOG`` entry plus an ADR, then update the SHA in this file.
3. If non-breaking (e.g. cosmetic docstring): update the SHA without
   bumping the schema version.

The same logic applies to ``scripts/smc_hero_state.py`` HERO vocab
frozensets.
"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ML_SCHEMA_DIR = REPO_ROOT / "ml" / "schemas"


def _hash_blocks(blocks: list[str]) -> str:
    joined = "\n\n".join(blocks)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def _scoring_blocks() -> list[str]:
    src = (REPO_ROOT / "smc_core" / "scoring.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    blocks: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "FamilyScoringMetrics":
            blocks["FamilyScoringMetrics"] = ast.unparse(node)
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == "EventFamily":
                    blocks["EventFamily"] = ast.unparse(node)
    # Deterministic ordering: EventFamily first, then FamilyScoringMetrics.
    return [blocks["EventFamily"], blocks["FamilyScoringMetrics"]]


def _hero_vocab_blocks() -> list[str]:
    src = (REPO_ROOT / "scripts" / "smc_hero_state.py").read_text()
    tree = ast.parse(src)
    blocks: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            name = node.target.id
            if name.startswith("HERO_") and name.endswith("_VOCAB"):
                # Use lineno for stable, source-order traversal.
                blocks.append((node.lineno, ast.unparse(node)))
    blocks.sort()
    return [block for _, block in blocks]


def test_ml_schemas_dir_exists() -> None:
    assert ML_SCHEMA_DIR.is_dir(), "ml/schemas/ must exist"


def test_input_schema_pin_matches_source() -> None:
    schema_path = ML_SCHEMA_DIR / "v1_input_schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    expected_sha = schema["pinned_source_sha256"]
    actual_sha = _hash_blocks(_scoring_blocks())
    assert actual_sha == expected_sha, (
        "FamilyScoringMetrics / EventFamily drifted relative to "
        f"ml/schemas/v1_input_schema.json. Expected SHA "
        f"{expected_sha}, got {actual_sha}. See module docstring for "
        "remediation steps."
    )


def test_hero_features_pin_matches_source() -> None:
    schema_path = ML_SCHEMA_DIR / "v1_hero_features.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    expected_sha = schema["pinned_source_sha256"]
    actual_sha = _hash_blocks(_hero_vocab_blocks())
    assert actual_sha == expected_sha, (
        "HERO vocabulary frozensets drifted relative to "
        f"ml/schemas/v1_hero_features.json. Expected SHA "
        f"{expected_sha}, got {actual_sha}. See module docstring for "
        "remediation steps."
    )


def test_input_schema_lists_four_families() -> None:
    schema = json.loads(
        (ML_SCHEMA_DIR / "v1_input_schema.json").read_text(encoding="utf-8")
    )
    assert sorted(schema["family_literal"]) == ["BOS", "FVG", "OB", "SWEEP"]


def test_input_schema_pins_known_metric_fields() -> None:
    schema = json.loads(
        (ML_SCHEMA_DIR / "v1_input_schema.json").read_text(encoding="utf-8")
    )
    field_names = [f["name"] for f in schema["family_metrics_fields"]]
    assert field_names == [
        "family",
        "n_events",
        "brier_score",
        "log_score",
        "hit_rate",
    ]
