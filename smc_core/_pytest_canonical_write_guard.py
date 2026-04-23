"""Shared pytest-time guard against silent canonical-repo artifact writes.

When a test forgets to redirect an output path to ``tmp_path``, production
code can silently overwrite the real repo's canonical artifact tree
(e.g. ``reports/smc_snapshot_bundles/manifest_15m.json``,
``artifacts/ci/measurement_benchmark/.../manifest.json``). The poisoned
manifests then leak ``pytest-of-<user>`` provenance into downstream
measurement-benchmark runs and trip the rolling-bench fail-loud guard.

This helper is the canonical implementation. ``smc_integration/structure_batch.py``
ships an inline equivalent introduced in PR #33; once that lands it will be
migrated to import from here.
"""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def guard_against_canonical_repo_write_under_pytest(
    output_dir: Path | str,
    *,
    canonical_relative_paths: tuple[str, ...],
    caller: str,
) -> None:
    """Raise ``RuntimeError`` if writing into a canonical repo path under pytest.

    Parameters
    ----------
    output_dir:
        Path the caller is about to write to.
    canonical_relative_paths:
        One or more repo-relative paths (e.g. ``"reports/smc_snapshot_bundles"``)
        that must never be overwritten by tests. ``output_dir`` is forbidden if
        it equals or is nested under any of these.
    caller:
        Name of the calling function (used for the error message).
    """
    if "PYTEST_CURRENT_TEST" not in os.environ:
        return
    try:
        candidate = Path(output_dir).expanduser().resolve()
    except OSError:
        return
    for relative in canonical_relative_paths:
        canonical = (REPO_ROOT / relative).resolve()
        try:
            candidate.relative_to(canonical)
        except ValueError:
            continue
        raise RuntimeError(
            f"{caller} refused to write into the canonical repo path "
            f"'{canonical}' (or a subdirectory) while pytest is active. "
            "Redirect output_dir to tmp_path in your test."
        )
