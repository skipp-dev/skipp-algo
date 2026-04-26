"""Sprint X3 — RunManifest schema + round-trip + CI conformance tests."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from governance import run_manifest as rm
from governance.run_manifest import (
    MANIFEST_SCHEMA_VERSION,
    REQUIRED_FIELDS,
    attach,
    build_manifest,
    extract,
    fingerprint_data,
    fingerprint_path,
    validate,
)


def _base_manifest() -> dict:
    return dict(
        build_manifest(
            sprint="C2",
            seed=42,
            dataset_fingerprint="abc123",
            wf_scheme="expanding",
            wf_embargo=2,
        )
    )


def test_build_manifest_has_all_required_fields() -> None:
    m = build_manifest(sprint="X3", seed=0, dataset_fingerprint="zzz")
    for k in REQUIRED_FIELDS:
        assert k in m, k
    assert m["schema_version"] == MANIFEST_SCHEMA_VERSION


def test_build_manifest_validates_inputs() -> None:
    with pytest.raises(ValueError, match="sprint"):
        build_manifest(sprint="", seed=0, dataset_fingerprint="x")
    with pytest.raises(ValueError, match="seed"):
        build_manifest(sprint="X", seed=-1, dataset_fingerprint="x")


def test_validate_missing_field_raises() -> None:
    bad = _base_manifest()
    bad.pop("git_sha")
    with pytest.raises(ValueError, match="missing required"):
        validate(bad)


def test_validate_unsupported_schema_version_raises() -> None:
    bad = _base_manifest()
    bad["schema_version"] = 9999
    with pytest.raises(ValueError, match="schema_version"):
        validate(bad)


def test_validate_seed_type_check() -> None:
    bad = _base_manifest()
    bad["seed"] = "not-an-int"  # type: ignore[assignment]
    with pytest.raises(ValueError, match="seed must be int"):
        validate(bad)


def test_attach_extract_round_trip() -> None:
    m = build_manifest(sprint="C4", seed=7, dataset_fingerprint="fp")
    payload = {"results": [1, 2, 3], "metric": 0.42}
    enriched = attach(payload, m)
    assert "run_manifest" in enriched
    assert enriched["results"] == [1, 2, 3]
    back = extract(enriched)
    assert back["sprint"] == "C4"
    assert back["seed"] == 7


def test_attach_does_not_mutate_input() -> None:
    m = build_manifest(sprint="X", seed=0, dataset_fingerprint="x")
    payload = {"a": 1}
    attach(payload, m)
    assert "run_manifest" not in payload


def test_attach_rejects_non_dict_payload() -> None:
    m = build_manifest(sprint="X", seed=0, dataset_fingerprint="x")
    with pytest.raises(TypeError, match="payload must be a dict"):
        attach([1, 2, 3], m)  # type: ignore[arg-type]


def test_extract_missing_key_raises() -> None:
    with pytest.raises(ValueError, match="no 'run_manifest'"):
        extract({"foo": "bar"})


def test_attach_refuses_to_overwrite_by_default() -> None:
    m = build_manifest(sprint="X", seed=0, dataset_fingerprint="x")
    payload = attach({}, m)
    m2 = build_manifest(sprint="Y", seed=1, dataset_fingerprint="y")
    with pytest.raises(ValueError, match="already has"):
        attach(payload, m2)
    out = attach(payload, m2, overwrite=True)
    assert out["run_manifest"]["sprint"] == "Y"


def test_validate_rejects_non_mapping() -> None:
    from governance.run_manifest import REQUIRED_FIELDS, validate

    with pytest.raises(ValueError, match="must be a mapping"):
        validate(list(REQUIRED_FIELDS))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="must be a mapping"):
        extract({"run_manifest": list(REQUIRED_FIELDS)})


def test_serialization_round_trip(tmp_path: Path) -> None:
    m = build_manifest(sprint="C6", seed=1, dataset_fingerprint="fp")
    payload = attach({"x": [1.0, 2.5]}, m)
    path = tmp_path / "out.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    loaded = json.loads(path.read_text(encoding="utf-8"))
    back = extract(loaded)
    assert back["dataset_fingerprint"] == "fp"


def test_fingerprint_data_deterministic() -> None:
    a = fingerprint_data({"x": 1, "y": [2, 3]})
    b = fingerprint_data({"y": [2, 3], "x": 1})  # different key order
    assert a == b
    assert len(a) == 64


def test_fingerprint_data_distinguishes_payloads() -> None:
    assert fingerprint_data({"x": 1}) != fingerprint_data({"x": 2})


def test_fingerprint_path(tmp_path: Path) -> None:
    p = tmp_path / "data.bin"
    p.write_bytes(b"hello world")
    fp = fingerprint_path(p)
    assert len(fp) == 64
    assert (
        fp == "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"
    )


def test_extras_round_trip() -> None:
    m = build_manifest(
        sprint="X", seed=0, dataset_fingerprint="x",
        extras={"reviewer": "agent", "notes": "ok"},
    )
    payload = attach({"r": 1}, m)
    back = extract(payload)
    assert back["extras"] == {"reviewer": "agent", "notes": "ok"}


def test_module_exports() -> None:
    for name in (
        "build_manifest", "validate", "attach", "extract",
        "fingerprint_data", "fingerprint_path",
        "RunManifest", "REQUIRED_FIELDS", "MANIFEST_SCHEMA_VERSION",
    ):
        assert hasattr(rm, name), name
