"""CI guard: detect new layer violations (smc_integration importing from scripts/).

Run as: python scripts/check_layer_violations.py
Exit code 1 if new violations found beyond the known allowlist.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SMC_INTEGRATION = ROOT / "smc_integration"

# Known remaining layer violations that have not yet been migrated.
# Each entry is (file_relative_to_smc_integration, module_imported).
KNOWN_VIOLATIONS: set[tuple[str, str]] = {
    ("service.py", "scripts.load_databento_export_bundle"),
    ("service.py", "scripts.smc_bus_manifest"),
    ("service.py", "scripts.smc_structure_qualifiers"),
    ("measurement_evidence.py", "scripts.explicit_structure_from_bars"),
    ("measurement_evidence.py", "scripts.load_databento_export_bundle"),
    ("measurement_evidence.py", "scripts.smc_event_risk_builder"),
    ("measurement_evidence.py", "scripts.smc_event_risk_light"),
    ("measurement_evidence.py", "scripts.smc_signal_quality"),
    ("measurement_evidence.py", "scripts.smc_session_context_block"),
    ("measurement_evidence.py", "scripts.smc_session_context_light"),
    ("measurement_evidence.py", "scripts.smc_structure_state"),
    ("measurement_evidence.py", "scripts.smc_structure_state_light"),
    ("structure_batch.py", "scripts.explicit_structure_from_bars"),
    ("structure_batch.py", "scripts.explicit_structure_profiles"),
    ("structure_batch.py", "scripts.load_databento_export_bundle"),
    ("artifact_resolution.py", "scripts.databento_production_workbook"),
    ("sources/live_news_snapshot_json.py", "scripts.smc_news_scorer"),
}


def _collect_script_imports(py_file: Path) -> list[tuple[str, str]]:
    """Return (relative_path, module_name) for imports from scripts.*."""
    try:
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
    except SyntaxError:
        return []

    rel = py_file.relative_to(SMC_INTEGRATION).as_posix()
    violations: list[tuple[str, str]] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("scripts."):
            violations.append((rel, node.module))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("scripts."):
                    violations.append((rel, alias.name))

    return violations


def main() -> int:
    all_violations: list[tuple[str, str]] = []
    for py_file in sorted(SMC_INTEGRATION.rglob("*.py")):
        all_violations.extend(_collect_script_imports(py_file))

    new_violations = [v for v in all_violations if v not in KNOWN_VIOLATIONS]

    if new_violations:
        print("ERROR: New layer violations detected in smc_integration/:")
        for rel, mod in new_violations:
            print(f"  {rel} imports {mod}")
        print(f"\nTotal: {len(new_violations)} new violation(s).")
        print("Either migrate the module to smc_core/ or add it to the KNOWN_VIOLATIONS allowlist.")
        return 1

    removed = KNOWN_VIOLATIONS - set(all_violations)
    if removed:
        print("INFO: The following violations have been resolved and can be removed from KNOWN_VIOLATIONS:")
        for rel, mod in sorted(removed):
            print(f"  {rel} imports {mod}")

    print(f"Layer guard OK: {len(all_violations)} known violation(s), 0 new.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
