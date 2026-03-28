"""Streamlit UI layer for the SMC Microstructure Base Generator.

Extracted from ``smc_microstructure_base_runtime`` to reduce scope creep.
All public helpers are re-exported from the runtime module for backward
compatibility.
"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from databento_provider import list_accessible_datasets
from databento_utils import PREFERRED_DATABENTO_DATASETS, choose_default_dataset


# ── UI helpers ──────────────────────────────────────────────────────


def _resolve_ui_dataset_options(
    databento_api_key: str, requested_dataset: str | None
) -> tuple[list[str], str, str | None]:
    fallback_options = list(
        dict.fromkeys(
            [*(str(dataset) for dataset in PREFERRED_DATABENTO_DATASETS), "DBEQ.BASIC"]
        )
    )
    requested = str(requested_dataset or "").strip() or "DBEQ.BASIC"
    if not databento_api_key:
        selected = choose_default_dataset(fallback_options, requested_dataset=requested)
        return fallback_options, selected, None
    try:
        available = list_accessible_datasets(databento_api_key)
    except Exception as exc:
        selected = choose_default_dataset(fallback_options, requested_dataset=requested)
        warning = f"Could not load Databento datasets from metadata; using fallback list ({exc})."
        return fallback_options, selected, warning
    options = [str(dataset).strip() for dataset in available if str(dataset).strip()]
    if not options:
        selected = choose_default_dataset(fallback_options, requested_dataset=requested)
        return (
            fallback_options,
            selected,
            "Databento metadata returned no datasets; using fallback list.",
        )
    selected = choose_default_dataset(options, requested_dataset=requested)
    return options, selected, None


def list_generated_base_csvs(export_dir: Path) -> list[Path]:
    return sorted(
        export_dir.glob("*__smc_microstructure_base_*.csv"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )


def resolve_base_csv_selection(
    candidates: list[Path], selected_label: str | None
) -> Path | None:
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    selected = str(selected_label or "").strip()
    if not selected:
        return None
    return next((path for path in candidates if path.name == selected), None)


def resolve_base_csv_action_target(
    candidates: list[Path], selected_label: str | None
) -> tuple[Path | None, str | None]:
    selected = resolve_base_csv_selection(candidates, selected_label)
    if not candidates:
        return None, "No generated base CSV found yet. Run the SMC base scan first."
    if len(candidates) > 1 and selected is None:
        return (
            None,
            "Select an explicit generated base CSV before generating or publishing Pine artifacts.",
        )
    return selected, None


# ── Streamlit app entry point ───────────────────────────────────────


def run_streamlit_micro_base_app() -> None:
    import os

    import streamlit as st
    from dotenv import load_dotenv

    from scripts.smc_micro_publish_guard import (
        evaluate_micro_library_publish_guard,
        publish_micro_library_to_tradingview,
    )
    from scripts.smc_microstructure_base_runtime import (
        generate_pine_library_from_base,
        run_databento_base_scan_pipeline,
    )

    repo_root = Path(__file__).resolve().parents[1]
    load_dotenv(repo_root / ".env", override=True)

    st.set_page_config(page_title="SMC Microstructure Base Generator", layout="wide")
    st.title("SMC Microstructure Base Generator")
    st.caption(
        "Runs the full Databento universe scan, creates Parquet and manifest artifacts, derives the daily base snapshot, and optionally generates the Pine library."
    )

    if "smc_base_logs" not in st.session_state:
        st.session_state["smc_base_logs"] = []
    if "smc_base_result" not in st.session_state:
        st.session_state["smc_base_result"] = None
    if "smc_pine_result" not in st.session_state:
        st.session_state["smc_pine_result"] = None
    if "smc_publish_result" not in st.session_state:
        st.session_state["smc_publish_result"] = None

    def add_log(message: str) -> None:
        timestamp = datetime.now(UTC).isoformat(timespec="seconds")
        st.session_state["smc_base_logs"] = [
            *st.session_state["smc_base_logs"],
            f"{timestamp} {message}",
        ][-100:]

    default_export_dir = repo_root / "artifacts" / "smc_microstructure_exports"
    with st.sidebar:
        databento_api_key = st.text_input(
            "Databento API Key",
            value=os.getenv("DATABENTO_API_KEY", ""),
            type="password",
        )
        fmp_api_key = st.text_input(
            "FMP API Key (optional)",
            value=os.getenv("FMP_API_KEY", ""),
            type="password",
        )
        export_dir_raw = st.text_input(
            "Export directory", value=str(default_export_dir)
        )
        dataset_options, dataset_default, dataset_warning = (
            _resolve_ui_dataset_options(
                databento_api_key,
                os.getenv("DATABENTO_DATASET", "DBEQ.BASIC"),
            )
        )
        dataset = st.selectbox(
            "Databento dataset",
            options=dataset_options,
            index=dataset_options.index(dataset_default),
            help="Open-focused scan: keep DBEQ.BASIC for broad coverage, or switch to XNAS.BASIC/XNAS.ITCH when your signal quality depends mainly on Nasdaq open behavior.",
        )
        if dataset_warning:
            st.caption(dataset_warning)
        st.caption(
            "Open/first-hours mode: default to DBEQ.BASIC for broad base generation; use XNAS.BASIC or XNAS.ITCH only when you intentionally bias the base toward Nasdaq open behavior."
        )
        lookback_days = st.number_input(
            "Trading days", min_value=5, max_value=90, value=30
        )
        bullish_score_profile = st.text_input(
            "Bullish score profile", value="balanced"
        )
        smc_base_only = st.checkbox(
            "SMC base-only export mode",
            value=True,
            help="Disables the preopen 04:00 seed selection and the fixed 10:00 ET outcome snapshot when the export is used only to derive the SMC microstructure base.",
        )
        write_xlsx = st.checkbox("Write Base workbook (.xlsx)", value=True)
        library_owner = st.text_input("TradingView owner", value="preuss_steffen")
        library_version = st.number_input(
            "TradingView library version", min_value=1, max_value=99, value=1
        )
        st.divider()
        st.subheader("Enrichment")
        enrich_regime = st.checkbox(
            "Regime (VIX, Macro, Sectors)",
            value=bool(fmp_api_key),
            help="Fügt MARKET_REGIME, VIX_LEVEL, MACRO_BIAS, SECTOR_BREADTH hinzu. Benötigt FMP API Key.",
            disabled=not bool(fmp_api_key),
        )
        enrich_news = st.checkbox(
            "News/Sentiment",
            value=bool(fmp_api_key),
            help="Fügt NEWS_BULLISH_TICKERS, NEWS_BEARISH_TICKERS, TICKER_HEAT_MAP hinzu. Benötigt FMP API Key.",
            disabled=not bool(fmp_api_key),
        )
        enrich_calendar = st.checkbox(
            "Earnings/Macro Calendar",
            value=bool(fmp_api_key),
            help="Fügt EARNINGS_TODAY_TICKERS, HIGH_IMPACT_MACRO_TODAY hinzu. Benötigt FMP API Key.",
            disabled=not bool(fmp_api_key),
        )
        enrich_layering = st.checkbox(
            "Pre-computed Layering",
            value=bool(fmp_api_key),
            help="Fügt GLOBAL_HEAT, GLOBAL_STRENGTH, TONE, TRADE_STATE hinzu. Benötigt Regime + News.",
            disabled=not bool(fmp_api_key),
        )
        if not fmp_api_key and any(
            [enrich_regime, enrich_news, enrich_calendar, enrich_layering]
        ):
            st.caption("⚠️ FMP API Key erforderlich für Enrichment.")
        st.caption(
            "SMC_Core_Engine.pine is already wired to import the generated TradingView library path."
        )

    export_dir = Path(export_dir_raw).expanduser()
    from scripts.smc_schema_resolver import resolve_microstructure_schema_path

    schema_path = resolve_microstructure_schema_path()
    overrides_path = repo_root / "data" / "input" / "microstructure_overrides.csv"
    try:
        publish_guard = evaluate_micro_library_publish_guard(
            repo_root=repo_root,
            library_owner=str(library_owner),
            library_version=int(library_version),
        )
    except Exception as exc:
        publish_guard = {
            "can_publish": False,
            "message": f"Publish guard evaluation failed: {exc}",
            "severity": "error",
            "contract": {},
        }
    base_csv_candidates = list_generated_base_csvs(export_dir)
    base_csv_option_labels = [path.name for path in base_csv_candidates]
    base_csv_requires_explicit_selection = len(base_csv_candidates) > 1
    selected_base_csv_label = (
        st.selectbox(
            "Base snapshot for Pine generation",
            options=base_csv_option_labels,
            index=None if base_csv_requires_explicit_selection else 0,
            placeholder="Select a generated base CSV"
            if base_csv_requires_explicit_selection
            else None,
            disabled=not base_csv_candidates,
            help="Select the exact generated base CSV to convert into Pine artifacts. This avoids silently using the most recently modified file.",
        )
        if base_csv_candidates
        else None
    )
    selected_base_csv = resolve_base_csv_selection(
        base_csv_candidates, selected_base_csv_label
    )
    if base_csv_requires_explicit_selection and selected_base_csv is None:
        st.info(
            "Multiple generated base snapshots were found. Select the exact base CSV before generating or publishing Pine artifacts."
        )
    action_base_csv, action_base_csv_error = resolve_base_csv_action_target(
        base_csv_candidates, selected_base_csv_label
    )

    action_cols = st.columns(4)
    run_base_scan = action_cols[0].button("Run SMC Base Scan", type="primary")
    refresh_base_scan = action_cols[1].button("Refresh Data")
    generate_pine = action_cols[2].button("Generate Pine Library")
    publish_pine = action_cols[3].button(
        "Publish To TradingView",
        disabled=not bool(publish_guard["can_publish"])
        or action_base_csv_error is not None,
    )

    if publish_guard["severity"] == "error":
        st.error(str(publish_guard["message"]))
    elif publish_guard["severity"] == "warning":
        st.warning(str(publish_guard["message"]))
    else:
        st.success(str(publish_guard["message"]))

    contract = publish_guard["contract"]
    if isinstance(contract, dict):
        st.caption(
            "Configured publish target: "
            f"owner={str(library_owner).strip() or 'n/a'}, "
            f"version={int(library_version)}"
        )
        st.caption(
            "Generated manifest contract: "
            f"owner={contract.get('owner') or 'n/a'}, "
            f"version={contract.get('version') if contract.get('version') is not None else 'n/a'}, "
            f"import={contract.get('import_path') or 'n/a'}"
        )
        st.caption(
            "Publish guard status: "
            f"owner_version_ready={bool(contract.get('owner_version_ready'))}, "
            f"full_contract_ready={bool(contract.get('full_contract_ready'))}"
        )
        st.caption(f"Generated manifest path: {contract.get('manifest_path')}")

    if run_base_scan or refresh_base_scan:
        if not databento_api_key:
            st.error("Databento API key is required for the base scan.")
        else:
            effective_force_refresh = bool(refresh_base_scan)
            status_label = (
                "Refreshing SMC base data..."
                if effective_force_refresh
                else "Starting SMC base scan..."
            )
            status = st.status(status_label, expanded=True)

            def _progress(message: str) -> None:
                status.update(label=message)
                status.write(message)
                add_log(message)

            try:
                result = run_databento_base_scan_pipeline(
                    databento_api_key=databento_api_key,
                    fmp_api_key=fmp_api_key,
                    dataset=dataset,
                    export_dir=export_dir,
                    schema_path=schema_path,
                    lookback_days=int(lookback_days),
                    force_refresh=effective_force_refresh,
                    cache_dir=repo_root
                    / "artifacts"
                    / "databento_volatility_cache",
                    use_file_cache=True,
                    display_timezone="Europe/Berlin",
                    bullish_score_profile=str(bullish_score_profile),
                    smc_base_only=bool(smc_base_only),
                    write_xlsx=write_xlsx,
                    library_owner=str(library_owner),
                    library_version=int(library_version),
                    progress_callback=_progress,
                )
            except Exception as exc:
                add_log(f"SMC base scan failed: {type(exc).__name__}: {exc}")
                status.update(
                    label="SMC base scan failed.", state="error", expanded=True
                )
                st.error(f"SMC base scan failed: {type(exc).__name__}: {exc}")
            else:
                st.session_state["smc_base_result"] = result
                completion_label = (
                    "SMC base data refresh complete."
                    if effective_force_refresh
                    else "SMC base scan complete."
                )
                success_message = (
                    "SMC base snapshot created from a forced-refresh Databento export run."
                    if effective_force_refresh
                    else "SMC base snapshot created from a fresh Databento export run."
                )
                status.update(
                    label=completion_label, state="complete", expanded=True
                )
                st.success(success_message)

    if generate_pine:
        if action_base_csv is None:
            st.error(str(action_base_csv_error))
        else:
            enrichment = None
            if any(
                [enrich_regime, enrich_news, enrich_calendar, enrich_layering]
            ):
                with st.spinner(
                    "Collecting enrichment data (Regime, News, Calendar)..."
                ):
                    try:
                        from scripts.generate_smc_micro_base_from_databento import (
                            build_enrichment,
                        )

                        base_df = pd.read_csv(action_base_csv)
                        symbols = (
                            sorted(
                                base_df["symbol"].dropna().unique().tolist()
                            )
                            if "symbol" in base_df.columns
                            else []
                        )
                        manifest_path = (
                            repo_root
                            / "pine"
                            / "generated"
                            / "smc_micro_profiles_generated.json"
                        )
                        enrichment = build_enrichment(
                            fmp_api_key=str(fmp_api_key),
                            symbols=symbols,
                            enrich_regime=enrich_regime,
                            enrich_news=enrich_news,
                            enrich_calendar=enrich_calendar,
                            enrich_layering=enrich_layering,
                            base_snapshot=base_df,
                            manifest_path=manifest_path,
                        )
                        add_log(
                            f"Enrichment collected: {list(enrichment.keys()) if enrichment else 'none'}"
                        )
                    except Exception as exc:
                        add_log(
                            f"Enrichment failed (continuing without): {exc}"
                        )
                        st.warning(
                            f"Enrichment partially failed: {exc}. Library will use defaults."
                        )
                        enrichment = None

            try:
                pine_result = generate_pine_library_from_base(
                    base_csv_path=action_base_csv,
                    schema_path=schema_path,
                    output_root=repo_root,
                    overrides_path=overrides_path
                    if overrides_path.exists()
                    else None,
                    library_owner=str(library_owner),
                    library_version=int(library_version),
                    enrichment=enrichment,
                )
            except Exception as exc:
                add_log(
                    f"Pine generation failed: {type(exc).__name__}: {exc}"
                )
                st.error(
                    f"Pine generation failed: {type(exc).__name__}: {exc}"
                )
            else:
                st.session_state["smc_pine_result"] = pine_result
                add_log(f"Pine library generated from {action_base_csv}")
                st.success(
                    "Pine library artifacts generated. TradingView publish can now be triggered from this UI."
                )

    if publish_pine:
        report_path = (
            repo_root
            / "automation"
            / "tradingview"
            / "reports"
            / f"publish-micro-library-{datetime.now(UTC).strftime('%Y-%m-%dT%H-%M-%S-%fZ')}.json"
        )
        status = st.status(
            "Publishing micro-library to TradingView...", expanded=True
        )
        status.write(
            "Step 1/3: Verifying manifest, generated snippet, and SMC core import contract..."
        )
        add_log("TradingView micro-library publish started.")
        try:
            if action_base_csv is None:
                raise RuntimeError(str(action_base_csv_error))
            if not publish_guard["can_publish"]:
                raise RuntimeError(str(publish_guard["message"]))
            publish_result = publish_micro_library_to_tradingview(
                repo_root=repo_root,
                report_path=report_path,
            )
        except Exception as exc:
            add_log(
                f"TradingView publish failed: {type(exc).__name__}: {exc}"
            )
            status.update(
                label="TradingView micro-library publish failed.",
                state="error",
                expanded=True,
            )
            st.error(
                f"TradingView publish failed: {type(exc).__name__}: {exc}"
            )
        else:
            st.session_state["smc_publish_result"] = publish_result
            add_log(
                "TradingView micro-library publish succeeded; core import contract and post-publish core validation were rechecked."
            )
            status.write("Step 2/3: TradingView library publish completed.")
            status.write(
                "Step 3/3: Core-only TradingView preflight stayed green against the generated import path."
            )
            status.update(
                label="TradingView micro-library publish complete.",
                state="complete",
                expanded=True,
            )
            st.success(
                "TradingView micro-library published and validated. Versioning remains explicit: owner/version changes require regenerating the library artifacts first."
            )

    base_result = st.session_state.get("smc_base_result")
    if isinstance(base_result, dict):
        mapping_payload = base_result.get("mapping_payload", {})
        output_paths = base_result.get("output_paths", {})
        for warning in base_result.get("warnings", []):
            st.warning(str(warning))
        metrics = st.columns(4)
        metrics[0].metric(
            "Base rows", str(mapping_payload.get("row_count", "n/a"))
        )
        metrics[1].metric(
            "Direct fields",
            str(len(mapping_payload.get("direct_fields", []))),
        )
        metrics[2].metric(
            "Derived fields",
            str(len(mapping_payload.get("derived_fields", []))),
        )
        metrics[3].metric(
            "Missing fields",
            str(len(mapping_payload.get("missing_fields", []))),
        )
        if output_paths:
            st.subheader("Base Artifacts")
            output_table = pd.DataFrame(
                [
                    {"artifact": name, "path": str(path)}
                    for name, path in output_paths.items()
                    if name != "session_minute_parquet"
                ]
            )
            st.dataframe(output_table, hide_index=True, use_container_width=True)

    pine_result = st.session_state.get("smc_pine_result")
    if isinstance(pine_result, dict):
        st.subheader("Pine Artifacts")
        pine_table = pd.DataFrame(
            [
                {"artifact": name, "path": str(path)}
                for name, path in pine_result.items()
            ]
        )
        st.dataframe(pine_table, hide_index=True, use_container_width=True)
        st.info(
            "Publish path: the generated library can now be pushed from this UI. The import version stays explicit in the core import path, so owner/version bumps remain the operator's responsibility."
        )

    publish_result = st.session_state.get("smc_publish_result")
    if isinstance(publish_result, dict):
        st.subheader("TradingView Publish Result")
        publish_table = pd.DataFrame(
            [
                {
                    "field": "publish_status",
                    "value": str(
                        publish_result.get("publishStatus", "n/a")
                    ),
                },
                {
                    "field": "expected_import_path",
                    "value": str(
                        publish_result.get("expectedImportPath", "n/a")
                    ),
                },
                {
                    "field": "expected_version",
                    "value": str(
                        publish_result.get("expectedVersion", "n/a")
                    ),
                },
                {
                    "field": "published_version",
                    "value": str(
                        publish_result.get("publishedVersion", "n/a")
                    ),
                },
                {
                    "field": "published_script_verified",
                    "value": str(
                        publish_result.get(
                            "publishedScriptVerified", "n/a"
                        )
                    ),
                },
                {
                    "field": "repo_core_validation_report",
                    "value": str(
                        publish_result.get(
                            "repoCoreValidationReport",
                            publish_result.get(
                                "coreValidationReport", "n/a"
                            ),
                        )
                    ),
                },
                {
                    "field": "release_manifest_path",
                    "value": str(
                        publish_result.get("releaseManifestPath", "n/a")
                    ),
                },
                {
                    "field": "publish_report_path",
                    "value": str(
                        publish_result.get("report_path", "n/a")
                    ),
                },
            ]
        )
        st.dataframe(
            publish_table, hide_index=True, use_container_width=True
        )
        if publish_result.get("error"):
            st.warning(str(publish_result["error"]))
        st.caption(
            "Post-publish validation checks two things: the local contract must match exactly across manifest, generated import snippet, and SMC_Core_Engine, and a core-only TradingView preflight must still compile against that exact import path."
        )

    with st.expander("Run Logs", expanded=False):
        logs = st.session_state.get("smc_base_logs", [])
        if logs:
            st.text("\n".join(logs))
        else:
            st.caption(
                "No base-generation actions executed in this session yet."
            )
