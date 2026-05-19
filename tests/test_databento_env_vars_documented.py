"""F-003: every `DATABENTO_*` environment variable referenced by the
producer code must be mentioned in at least one Markdown file under
`docs/`.

Rationale: env vars are the configuration surface for the databento
production-export pipeline; an undocumented var is invisible to ops and
to follow-up authors. This is the same discoverability contract as
F-007 for promotion-gate thresholds.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS_DIR = ROOT / "docs"

# Files we scan for env-var references.
SOURCE_GLOBS: tuple[str, ...] = (
    "scripts/databento_*.py",
    "databento_*.py",
)

# Env-var references: ``os.environ.get("DATABENTO_X", ...)``,
# ``os.environ["DATABENTO_X"]``, ``os.getenv("DATABENTO_X", ...)``.
_ENV_RE = re.compile(
    r"""os\.(?:environ\.get|environ|getenv)\(?\s*["'](DATABENTO_[A-Z0-9_]+)["']""",
)

# Vars excluded from the docs check (test/dev-only knobs that intentionally
# do not have a production-facing doc entry). Keep this list TINY and
# document every entry with a one-line justification.
_EXEMPT: frozenset[str] = frozenset()


def _collect_env_vars() -> set[str]:
    found: set[str] = set()
    for pattern in SOURCE_GLOBS:
        for path in ROOT.glob(pattern):
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            found.update(_ENV_RE.findall(text))
    return found


def _docs_corpus() -> str:
    parts: list[str] = []
    for md in DOCS_DIR.rglob("*.md"):
        parts.append(md.read_text(encoding="utf-8", errors="replace"))
    # Include CHANGELOG.md at repo root since several DATABENTO_* knobs
    # are first documented there before being promoted to a doc.
    changelog = ROOT / "CHANGELOG.md"
    if changelog.exists():
        parts.append(changelog.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(parts)


def test_env_vars_are_actually_discovered() -> None:
    env_vars = _collect_env_vars()
    assert env_vars, (
        "regex found zero DATABENTO_* env vars - source files moved or "
        "regex broke; this test would otherwise pass vacuously"
    )


def test_every_databento_env_var_is_documented() -> None:
    env_vars = _collect_env_vars() - _EXEMPT
    corpus = _docs_corpus()
    missing = sorted(name for name in env_vars if name not in corpus)
    assert not missing, (
        "the following DATABENTO_* env vars are referenced in code but "
        "documented in NO markdown file under docs/ (or CHANGELOG.md): "
        f"{missing}. Add a one-line description to the relevant docs page "
        "(e.g. docs/DATABENTO_VOLATILITY_SUITE.md) in the same commit."
    )
