"""Plan 2.8 README badge markdown emitter.

Emits a single-line markdown badge referencing a shields.io
*endpoint* badge (JSON at ``--endpoint-url``). Pairs with
``scripts/plan_2_8_runcard_badge.py`` output hosted at a stable URL.

Output shape (single line plus trailing newline)::

    ![plan 2.8](https://img.shields.io/endpoint?url=<encoded>)

Pure stdlib.
"""

from __future__ import annotations

import argparse
import sys
import urllib.parse
from pathlib import Path

from scripts.smc_atomic_write import atomic_write_text


def render(
    endpoint_url: str,
    *,
    label: str = "plan 2.8",
    link_url: str | None = None,
) -> str:
    if not isinstance(endpoint_url, str) or not endpoint_url:
        raise ValueError("endpoint_url must be a non-empty string")
    encoded = urllib.parse.quote(endpoint_url, safe="")
    badge = f"https://img.shields.io/endpoint?url={encoded}"
    alt = label.replace("]", "")  # keep markdown well-formed
    if link_url:
        return f"[![{alt}]({badge})]({link_url})\n"
    return f"![{alt}]({badge})\n"

# F-V6-A1.1 (2026-05-02): bootstrap root logging so the logger.info(...)
# progress messages this entry point emits actually surface in CI logs
# (default WARNING-only handler would drop them). Extends F-V5-A1-2 / #2012
# from the priority entry-point set to plan_2_8 aggregators + showcase.
try:
    from scripts._logging_init import init_cli_logging
except ImportError:  # script-style invocation: `python scripts/X.py`
    import sys as _v6a11_sys
    from pathlib import Path as _v6a11_Path

    _v6a11_sys.path.insert(0, str(_v6a11_Path(__file__).resolve().parents[1]))
    from scripts._logging_init import init_cli_logging  # type: ignore[no-redef]




def main(argv: list[str] | None = None) -> int:
    init_cli_logging()  # F-V6-A1.1 (2026-05-02)
    parser = argparse.ArgumentParser(
        description="Emit a README markdown line for the Plan 2.8 "
                    "shields.io endpoint badge.",
    )
    parser.add_argument("--endpoint-url", required=True,
                        help="URL to the endpoint badge JSON file")
    parser.add_argument("--label", default="plan 2.8")
    parser.add_argument("--link-url", default=None,
                        help="optional click-through URL")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    try:
        body = render(
            args.endpoint_url, label=args.label, link_url=args.link_url,
        )
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(body, args.output)
    print(body, end="")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
