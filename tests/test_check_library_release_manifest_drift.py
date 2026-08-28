"""Tests for ``scripts/check_library_release_manifest_drift.py``.

Ensures the TradingView library release manifest does not silently fall
out of sync with the files it references (source manifest, snippet,
consumers, product-cut mainline files, product-cut manifest path). See
the script docstring for the protected invariants.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "check_library_release_manifest_drift.py"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "check_library_release_manifest_drift", SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["check_library_release_manifest_drift"] = mod
    spec.loader.exec_module(mod)
    return mod


CHECK = _load_module()


def _minimal_manifest() -> dict:
    return {
        "library": {
            "sourceManifest": "pine/generated/lib.json",
            "sourceSnippet": "pine/generated/snippet.pine",
        },
        "consumers": [
            {"file": "Core.pine", "scriptName": "Core"},
            {"file": "Dashboard.pine", "scriptName": "Dashboard"},
        ],
        "productCut": {
            "manifestPath": "artifacts/tradingview/cut.json",
            "mainlineFiles": ["Core.pine", "Dashboard.pine"],
        },
    }


def _materialize(root: Path, paths: list[str]) -> None:
    for rel in paths:
        full = root / rel
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text("// stub\n", encoding="utf-8")


def _write_manifest(root: Path, manifest: dict) -> Path:
    target = root / "library_release_manifest.json"
    target.write_text(json.dumps(manifest), encoding="utf-8")
    return target


class TestCollectReferencedPaths:
    def test_collects_all_pointer_kinds(self):
        refs = CHECK.collect_referenced_paths(_minimal_manifest())
        pointers = [p for p, _ in refs]
        assert "library.sourceManifest" in pointers
        assert "library.sourceSnippet" in pointers
        assert "consumers[0].file" in pointers
        assert "consumers[1].file" in pointers
        assert "productCut.manifestPath" in pointers
        assert "productCut.mainlineFiles[0]" in pointers
        assert "productCut.mainlineFiles[1]" in pointers
        assert len(refs) == 7

    def test_skips_missing_or_non_string_entries(self):
        manifest = {
            "library": {"sourceManifest": "x.json"},
            "consumers": [{"scriptName": "no_file"}, "not_a_dict"],
            "productCut": {"mainlineFiles": [None, "OK.pine"]},
        }
        refs = CHECK.collect_referenced_paths(manifest)
        pointers = [p for p, _ in refs]
        assert pointers == ["library.sourceManifest", "productCut.mainlineFiles[1]"]

    def test_empty_manifest_yields_no_refs(self):
        assert CHECK.collect_referenced_paths({}) == []


class TestFindMissing:
    def test_returns_only_absent_files(self, tmp_path):
        _materialize(tmp_path, ["a.pine"])
        refs = [("library.x", "a.pine"), ("library.y", "missing.pine")]
        missing = CHECK.find_missing(refs, tmp_path)
        assert missing == [("library.y", "missing.pine")]


class TestMainExitCodes:
    def test_passes_when_all_files_exist(self, tmp_path, capsys):
        _materialize(
            tmp_path,
            [
                "pine/generated/lib.json",
                "pine/generated/snippet.pine",
                "Core.pine",
                "Dashboard.pine",
                "artifacts/tradingview/cut.json",
            ],
        )
        manifest_path = _write_manifest(tmp_path, _minimal_manifest())
        rc = CHECK.main(["--root", str(tmp_path), "--manifest", str(manifest_path)])
        out = capsys.readouterr().out
        assert rc == 0
        assert "OK" in out
        assert "7 referenced paths" in out

    def test_fails_when_source_manifest_missing(self, tmp_path, capsys):
        _materialize(
            tmp_path,
            [
                "pine/generated/snippet.pine",
                "Core.pine",
                "Dashboard.pine",
                "artifacts/tradingview/cut.json",
            ],
        )
        manifest_path = _write_manifest(tmp_path, _minimal_manifest())
        rc = CHECK.main(["--root", str(tmp_path), "--manifest", str(manifest_path)])
        out = capsys.readouterr().out
        assert rc == 1
        assert "library.sourceManifest" in out
        assert "pine/generated/lib.json" in out

    def test_fails_when_consumer_renamed(self, tmp_path, capsys):
        _materialize(
            tmp_path,
            [
                "pine/generated/lib.json",
                "pine/generated/snippet.pine",
                "Core.pine",
                "artifacts/tradingview/cut.json",
            ],
        )
        # Dashboard.pine intentionally not created
        manifest_path = _write_manifest(tmp_path, _minimal_manifest())
        rc = CHECK.main(["--root", str(tmp_path), "--manifest", str(manifest_path)])
        out = capsys.readouterr().out
        assert rc == 1
        assert "consumers[1].file" in out
        assert "Dashboard.pine" in out
        # productCut.mainlineFiles also references Dashboard.pine -> double report
        assert "productCut.mainlineFiles[1]" in out

    def test_fails_when_manifest_has_no_refs(self, tmp_path, capsys):
        manifest_path = _write_manifest(tmp_path, {"library": {}, "consumers": []})
        rc = CHECK.main(["--root", str(tmp_path), "--manifest", str(manifest_path)])
        out = capsys.readouterr().out
        assert rc == 1
        assert "no referenced paths" in out

    def test_missing_manifest_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            CHECK.main(
                [
                    "--root",
                    str(tmp_path),
                    "--manifest",
                    str(tmp_path / "does_not_exist.json"),
                ]
            )

    def test_real_repo_manifest_is_in_sync(self):
        """Lock-down: the live ``library_release_manifest.json`` must
        match real filesystem state. If this fails, either restore the
        renamed/removed file or update the manifest. This is the
        regression guard for the B follow-up to PR #105.
        """
        rc = CHECK.main([])
        assert rc == 0


def _scoped_product_cut(titles: list[str], contracts: list[str]) -> dict:
    return {
        "manifestPath": "artifacts/tradingview/cut.json",
        "mainlineFiles": [],
        "contracts": {key: ["BUS X"] for key in contracts},
        "preflightScopes": {
            "smcMainline": [
                {
                    "file": "Core.pine",
                    "bindingLabelGroups": [
                        {"label": f"BUS {i}", "group": "g", "groupTitle": title}
                        for i, title in enumerate(titles)
                    ],
                }
            ]
        },
    }


class TestEmbeddedProductCutDrift:
    """The 2026-08-28 review finding: the embedded productCut copy carried
    42x 'Lifecycle BUS' 16 days after #4639 renamed the settings groups, and
    nothing compared the snapshot back to the canonical artifact. The check
    WARNS (exit 0) by deliberate decision — see the function docstring."""

    def _fixture(self, tmp_path, embedded: dict, canonical: dict) -> dict:
        cut = tmp_path / "artifacts" / "tradingview" / "cut.json"
        cut.parent.mkdir(parents=True, exist_ok=True)
        cut.write_text(json.dumps(canonical), encoding="utf-8")
        return {"productCut": embedded}

    def test_agreeing_copies_report_nothing(self, tmp_path):
        cut = _scoped_product_cut(["Decision State"], ["engine"])
        manifest = self._fixture(tmp_path, cut, cut)
        assert CHECK.embedded_product_cut_drift(manifest, tmp_path) == []

    def test_the_review_signature_is_reported(self, tmp_path):
        """A stale snapshot still speaking 'Lifecycle BUS' must be named."""
        embedded = _scoped_product_cut(["Lifecycle BUS"], ["engine"])
        canonical = _scoped_product_cut(["Decision State"], ["engine"])
        manifest = self._fixture(tmp_path, embedded, canonical)
        problems = CHECK.embedded_product_cut_drift(manifest, tmp_path)
        assert any("Lifecycle BUS" in p for p in problems), problems
        assert any("Decision State" in p for p in problems), problems

    def test_a_diverged_contracts_key_set_is_reported(self, tmp_path):
        embedded = _scoped_product_cut(["Decision State"], ["engine"])
        canonical = _scoped_product_cut(
            ["Decision State"], ["engine", "mobileBindings"]
        )
        manifest = self._fixture(tmp_path, embedded, canonical)
        problems = CHECK.embedded_product_cut_drift(manifest, tmp_path)
        assert any("mobileBindings" in p for p in problems), problems

    def test_an_empty_canonical_census_is_not_a_pass(self, tmp_path):
        """Vacuity control: a structure change must not read as agreement."""
        embedded = _scoped_product_cut(["Decision State"], ["engine"])
        canonical = {"contracts": {"engine": ["BUS X"]}, "preflightScopes": {}}
        manifest = self._fixture(tmp_path, embedded, canonical)
        problems = CHECK.embedded_product_cut_drift(manifest, tmp_path)
        assert any("EMPTY groupTitle census" in p for p in problems), problems

    def test_drift_warns_but_does_not_fail_the_lane(self, tmp_path, capsys):
        """The deliberate WARN decision, executed: rc 0 with the warning."""
        _materialize(
            tmp_path,
            [
                "pine/generated/lib.json",
                "pine/generated/snippet.pine",
                "Core.pine",
                "Dashboard.pine",
            ],
        )
        canonical = _scoped_product_cut(["Decision State"], ["engine"])
        embedded = _scoped_product_cut(["Lifecycle BUS"], ["engine"])
        cut = tmp_path / "artifacts" / "tradingview" / "cut.json"
        cut.parent.mkdir(parents=True, exist_ok=True)
        cut.write_text(json.dumps(canonical), encoding="utf-8")
        manifest = _minimal_manifest()
        manifest["productCut"].update(
            {k: v for k, v in embedded.items() if k != "manifestPath"}
        )
        manifest_path = _write_manifest(tmp_path, manifest)
        rc = CHECK.main(["--root", str(tmp_path), "--manifest", str(manifest_path)])
        out = capsys.readouterr().out
        assert rc == 0
        assert "::warning" in out
        assert "Lifecycle BUS" in out
        assert "self-heals" in out
