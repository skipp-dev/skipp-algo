"""Centralization guard for ``ENABLE_*`` feature-flag env reads (audit F-002).

Enforces that no Python source file reads ``ENABLE_*`` env vars directly
via ``os.getenv`` or ``os.environ.get`` outside of the designated SSOT
module (``open_prep/feature_flags.py``).

Any violation means a new flag was added without being wired through the
SSOT helper, which is exactly the four-callsite drift that audit-L-1 R4
(2026-05-12) was designed to prevent.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SSOT_REL = "open_prep/feature_flags.py"
_RAW_ENABLE_PATTERN = re.compile(
    r"""os\s*\.\s*(?:getenv|environ\.get)\s*\(\s*["']ENABLE_""",
)


def _python_sources():
    for path in REPO.rglob("*.py"):
        rel = path.relative_to(REPO)
        # Exclude the SSOT itself, tests, and generated/vendor dirs.
        parts = rel.parts
        if parts[0] in (".venv", "venv", ".tox", "node_modules", "build", "dist"):
            continue
        yield path, rel


def test_no_raw_enable_reads_outside_ssot():
    """No .py file outside the SSOT module may call os.getenv/environ.get
    with an ENABLE_* key directly."""
    violations: list[str] = []
    for path, rel in _python_sources():
        if str(rel) == SSOT_REL:
            continue  # SSOT is the one allowed callsite
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if _RAW_ENABLE_PATTERN.search(line):
                violations.append(f"  {rel}:{lineno}: {line.strip()}")

    assert not violations, (
        "Direct os.getenv/os.environ.get calls for ENABLE_* flags found outside "
        f"SSOT ({SSOT_REL}). Move them to open_prep/feature_flags.py:\n"
        + "\n".join(violations)
    )


def test_ssot_itself_uses_bool_env_helper():
    """The SSOT module must only parse ENABLE_* flags via ``_bool_env``,
    never via a raw ``os.getenv`` / ``os.environ.get`` call in actual code
    (docstring examples are exempt — they start with ``*`` or ``#``)."""
    ssot = REPO / SSOT_REL
    text = ssot.read_text(encoding="utf-8")
    raw_calls = [
        line.strip()
        for line in text.splitlines()
        if _RAW_ENABLE_PATTERN.search(line)
        and not line.lstrip().startswith(("*", "#", '"', "'"))
    ]
    assert not raw_calls, (
        f"{SSOT_REL} contains raw os.getenv/environ.get calls for ENABLE_* — "
        "use _bool_env() instead:\n" + "\n".join(raw_calls)
    )
