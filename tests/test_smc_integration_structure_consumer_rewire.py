from __future__ import annotations

import json

import scripts.export_smc_snapshot_watchlist_bundles as consumer


def test_watchlist_export_script_calls_structure_batch_path(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []

    def _fake_load_symbols(source: str) -> list[str]:
        assert source == "auto"
        return ["AAPL", "MSFT"]

    def _fake_structure_batch(*, workbook, timeframe, symbols, output_dir, generated_at):
        calls.append(
            (
                "structure",
                {
                    "workbook": str(workbook),
                    "timeframe": timeframe,
                    "symbols": list(symbols),
                    "output_dir": str(output_dir),
                    "generated_at": generated_at,
                },
            )
        )
        return {
            "schema_version": "1.0.0",
            "timeframe": timeframe,
            "counts": {"symbols_requested": 2, "artifacts_written": 2, "errors": 0},
            "artifacts": [],
            "errors": [],
            "manifest_path": "reports/smc_structure_artifacts/manifest_15m.json",
        }

    def _fake_snapshot_batch(symbols, timeframe, *, source, output_dir, generated_at):
        calls.append(
            (
                "snapshot",
                {
                    "symbols": list(symbols),
                    "timeframe": timeframe,
                    "source": source,
                    "output_dir": str(output_dir),
                    "generated_at": generated_at,
                },
            )
        )
        return {
            "schema_version": "1.0.0",
            "timeframe": timeframe,
            "counts": {"symbols_requested": 2, "symbols_built": 2, "errors": 0},
            "bundles": [],
            "errors": [],
            "manifest_path": "reports/smc_snapshot_bundles/manifest_15m.json",
        }

    monkeypatch.setattr(consumer, "load_symbols_from_source", _fake_load_symbols)
    monkeypatch.setattr(consumer, "write_structure_artifacts_from_workbook", _fake_structure_batch)
    monkeypatch.setattr(consumer, "write_snapshot_bundles_for_symbols", _fake_snapshot_batch)

    rc = consumer.main(
        [
            "--timeframe",
            "15m",
            "--source",
            "auto",
            "--output-dir",
            "reports/smc_snapshot_bundles",
            "--structure-output-dir",
            "reports/smc_structure_artifacts",
            "--generated-at",
            "1709254000.0",
        ]
    )

    assert rc == 0
    assert [name for name, _ in calls] == ["structure", "snapshot"]
    assert calls[0][1]["symbols"] == ["AAPL", "MSFT"]
    assert calls[1][1]["symbols"] == ["AAPL", "MSFT"]


def test_watchlist_export_script_embeds_structure_manifest(monkeypatch, capsys) -> None:
    monkeypatch.setattr(consumer, "load_symbols_from_source", lambda source: ["AAPL"])
    monkeypatch.setattr(
        consumer,
        "write_structure_artifacts_from_workbook",
        lambda **kwargs: {
            "schema_version": "1.0.0",
            "timeframe": kwargs["timeframe"],
            "counts": {"symbols_requested": 1, "artifacts_written": 1, "errors": 0},
            "artifacts": [],
            "errors": [],
            "manifest_path": "reports/smc_structure_artifacts/manifest_15m.json",
        },
    )
    monkeypatch.setattr(
        consumer,
        "write_snapshot_bundles_for_symbols",
        lambda symbols, timeframe, **kwargs: {
            "schema_version": "1.0.0",
            "timeframe": timeframe,
            "counts": {"symbols_requested": 1, "symbols_built": 1, "errors": 0},
            "bundles": [],
            "errors": [],
            "manifest_path": "reports/smc_snapshot_bundles/manifest_15m.json",
        },
    )

    rc = consumer.main(["--timeframe", "15m", "--source", "auto"])
    assert rc == 0

    out = capsys.readouterr().out
    payload = json.loads(out)
    assert "structure_manifest" in payload
    assert payload["structure_manifest"]["manifest_path"].endswith("manifest_15m.json")
