"""Fail closed when Composio prod/dev or read/write identities are reused."""

from __future__ import annotations

import json
import os

TOOLKITS = ("SLACK", "GITHUB", "OUTLOOK", "NOTION")


def audit() -> list[str]:
    errors = []
    prod_key = os.getenv("COMPOSIO_PROD_API_KEY", "").strip()
    dev_key = os.getenv("COMPOSIO_DEV_API_KEY", "").strip()
    if prod_key and dev_key and prod_key == dev_key:
        errors.append("prod and dev project keys must differ")
    for toolkit in TOOLKITS:
        read = os.getenv(f"COMPOSIO_{toolkit}_READ_ACCOUNT_ID", "").strip()
        write = os.getenv(f"COMPOSIO_{toolkit}_WRITE_ACCOUNT_ID", "").strip()
        if read and write and read == write:
            errors.append(f"{toolkit}: read and write connected accounts must differ")
        read_auth = os.getenv(f"COMPOSIO_{toolkit}_READ_AUTH_CONFIG_ID", "").strip()
        write_auth = os.getenv(f"COMPOSIO_{toolkit}_WRITE_AUTH_CONFIG_ID", "").strip()
        if read_auth and write_auth and read_auth == write_auth:
            errors.append(f"{toolkit}: read and write auth configs must differ")
    return errors


def main() -> int:
    errors = audit()
    print(json.dumps({"ok": not errors, "errors": errors}, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
