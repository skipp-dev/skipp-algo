"""Plan 2.8 README badge markdown emitter.

Emits a single-line markdown badge referencing a shields.io
*endpoint* badge (JSON at ``--endpoint-url``). Pairs with
``scripts/plan_2_8_runcard_badge.py`` output hosted at a stable URL.

Output shape (single line plus trailing newline)::

    ![plan 2.8](https://img.shields.io/endpoint?url=<encoded>)

Pure stdlib.
"""

from __future__ import annotations

from scripts.smc_atomic_write import atomic_write_text

import argparse
import sys
import urllib.parse
from pathlib import Path


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


def main(argv: list[str] | None = None) -> int:
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
