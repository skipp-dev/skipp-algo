#!/usr/bin/env python3
"""Versioned, hash-verified S3 backup and non-overwriting restore for MLflow artifacts."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import io
import json
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

_BACKUP_ID = re.compile(r"^[0-9]{8}T[0-9]{6}Z$")


@dataclass(frozen=True, slots=True)
class Store:
    endpoint: str
    region: str
    access_key_id: str
    secret_access_key: str
    bucket: str


def _store(prefix: str) -> Store:
    values = {
        name: os.environ.get(f"MLFLOW_{prefix}_{name}", "").strip()
        for name in ("ENDPOINT", "REGION", "ACCESS_KEY_ID", "SECRET_ACCESS_KEY", "BUCKET")
    }
    missing = sorted(name for name, value in values.items() if not value)
    if missing:
        raise ValueError(f"missing {prefix} store settings: {missing}")
    if not values["ENDPOINT"].startswith("https://"):
        raise ValueError(f"{prefix} endpoint must use HTTPS")
    return Store(
        values["ENDPOINT"],
        values["REGION"],
        values["ACCESS_KEY_ID"],
        values["SECRET_ACCESS_KEY"],
        values["BUCKET"],
    )


def _client(store: Store) -> Any:
    boto3 = importlib.import_module("boto3")
    return boto3.client(
        "s3",
        endpoint_url=store.endpoint,
        region_name=store.region,
        aws_access_key_id=store.access_key_id,
        aws_secret_access_key=store.secret_access_key,
    )


def _hash_body(body: Any) -> tuple[bytes, str]:
    digest = hashlib.sha256()
    buffer = io.BytesIO()
    while chunk := body.read(1024 * 1024):
        digest.update(chunk)
        buffer.write(chunk)
    return buffer.getvalue(), digest.hexdigest()


def _list_keys(client: Any, bucket: str, prefix: str) -> list[dict[str, Any]]:
    pages = client.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix)
    return [item for page in pages for item in page.get("Contents", [])]


def _manifest_key(backup_id: str) -> str:
    if not _BACKUP_ID.fullmatch(backup_id):
        raise ValueError("backup ID must use YYYYMMDDTHHMMSSZ")
    return f"backups/{backup_id}/manifest.json"


def _object_exists(client: Any, bucket: str, key: str) -> bool:
    try:
        client.head_object(Bucket=bucket, Key=key)
    except Exception as exc:
        response = getattr(exc, "response", {})
        code = str(response.get("Error", {}).get("Code", ""))
        if code in {"404", "NoSuchKey", "NotFound"}:
            return False
        raise
    return True


def backup(source: Store, target: Store, *, backup_id: str, source_prefix: str, apply: bool) -> dict[str, Any]:
    manifest_key = _manifest_key(backup_id)
    if not source_prefix or source_prefix.startswith("/"):
        raise ValueError("source prefix must be a non-root S3 key prefix")
    if source.endpoint == target.endpoint and source.bucket == target.bucket:
        raise ValueError("backup target must be a different bucket from the source")
    source_client = _client(source)
    target_client = _client(target)
    objects = _list_keys(source_client, source.bucket, source_prefix)
    plan: dict[str, Any] = {
        "contract_version": "mlflow-artifact-backup-v1",
        "backup_id": backup_id,
        "source_prefix": source_prefix,
        "source_bucket": source.bucket,
        "target_bucket": target.bucket,
        "object_count": len(objects),
        "total_bytes": sum(int(item["Size"]) for item in objects),
        "applied": apply,
        "objects": [],
    }
    if not apply:
        return plan
    if _object_exists(target_client, target.bucket, manifest_key):
        raise FileExistsError(f"backup manifest already exists: {manifest_key}")
    for item in objects:
        key = str(item["Key"])
        response = source_client.get_object(Bucket=source.bucket, Key=key)
        payload, sha256 = _hash_body(response["Body"])
        backup_key = f"backups/{backup_id}/objects/{key}"
        target_client.put_object(
            Bucket=target.bucket,
            Key=backup_key,
            Body=payload,
            Metadata={"sha256": sha256},
        )
        plan["objects"].append(
            {"source_key": key, "backup_key": backup_key, "size": len(payload), "sha256": sha256}
        )
    target_client.put_object(
        Bucket=target.bucket,
        Key=manifest_key,
        Body=json.dumps(plan, sort_keys=True, separators=(",", ":")).encode(),
        ContentType="application/json",
    )
    return plan


def _load_manifest(client: Any, store: Store, backup_id: str) -> dict[str, Any]:
    response = client.get_object(Bucket=store.bucket, Key=_manifest_key(backup_id))
    payload = json.loads(response["Body"].read())
    if payload.get("contract_version") != "mlflow-artifact-backup-v1":
        raise ValueError("unsupported backup manifest contract")
    if payload.get("backup_id") != backup_id or not payload.get("applied"):
        raise ValueError("backup manifest identity mismatch")
    if payload.get("target_bucket") != store.bucket:
        raise ValueError("backup manifest belongs to another bucket")
    return payload


def verify(store: Store, *, backup_id: str) -> dict[str, Any]:
    client = _client(store)
    manifest = _load_manifest(client, store, backup_id)
    failures: list[str] = []
    checked_bytes = 0
    for item in manifest.get("objects", []):
        response = client.get_object(Bucket=store.bucket, Key=item["backup_key"])
        payload, sha256 = _hash_body(response["Body"])
        checked_bytes += len(payload)
        if len(payload) != int(item["size"]) or sha256 != item["sha256"]:
            failures.append(str(item["backup_key"]))
    return {
        "backup_id": backup_id,
        "verified": not failures,
        "object_count": len(manifest.get("objects", [])),
        "checked_bytes": checked_bytes,
        "failures": failures,
    }


def backup_and_verify(
    source: Store,
    target: Store,
    *,
    backup_id: str,
    source_prefix: str,
    apply: bool,
) -> dict[str, Any]:
    backup_result = backup(
        source,
        target,
        backup_id=backup_id,
        source_prefix=source_prefix,
        apply=apply,
    )
    verification = verify(target, backup_id=backup_id) if apply else None
    if verification is not None and not verification["verified"]:
        raise RuntimeError("new artifact backup failed verification")
    return {"backup": backup_result, "verification": verification}


def restore(
    backup_store: Store,
    restore_store: Store,
    *,
    backup_id: str,
    destination_prefix: str,
    apply: bool,
) -> dict[str, Any]:
    if (
        not destination_prefix.startswith("restore-drills/")
        or not destination_prefix.endswith("/")
        or ".." in destination_prefix
        or "//" in destination_prefix
    ):
        raise ValueError("restore destination must be an isolated restore-drills/.../ prefix")
    if backup_store.endpoint == restore_store.endpoint and backup_store.bucket == restore_store.bucket:
        raise ValueError("restore target must be a different bucket from the backup")
    backup_client = _client(backup_store)
    restore_client = _client(restore_store)
    manifest = _load_manifest(backup_client, backup_store, backup_id)
    result = {
        "backup_id": backup_id,
        "destination_prefix": destination_prefix,
        "object_count": len(manifest.get("objects", [])),
        "applied": apply,
    }
    if not apply:
        return result
    restore_keys = [
        destination_prefix + str(item["source_key"])
        for item in manifest.get("objects", [])
    ]
    collisions = [
        key for key in restore_keys if _object_exists(restore_client, restore_store.bucket, key)
    ]
    if collisions:
        raise FileExistsError(f"restore destination already contains objects: {collisions}")
    for item, restore_key in zip(manifest.get("objects", []), restore_keys, strict=True):
        response = backup_client.get_object(Bucket=backup_store.bucket, Key=item["backup_key"])
        payload, sha256 = _hash_body(response["Body"])
        if len(payload) != int(item["size"]) or sha256 != item["sha256"]:
            raise ValueError(f"backup object failed verification: {item['backup_key']}")
        restore_client.put_object(
            Bucket=restore_store.bucket,
            Key=restore_key,
            Body=payload,
            Metadata={"sha256": sha256, "backup-id": backup_id},
        )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    backup_parser = subparsers.add_parser("backup")
    backup_parser.add_argument("--backup-id", default=datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"))
    backup_parser.add_argument("--source-prefix", default="mlflow/")
    backup_parser.add_argument("--apply", action="store_true")
    backup_verify_parser = subparsers.add_parser("backup-verify")
    backup_verify_parser.add_argument(
        "--backup-id", default=datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    )
    backup_verify_parser.add_argument("--source-prefix", default="mlflow/")
    backup_verify_parser.add_argument("--apply", action="store_true")
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--backup-id", required=True)
    restore_parser = subparsers.add_parser("restore")
    restore_parser.add_argument("--backup-id", required=True)
    restore_parser.add_argument("--destination-prefix", required=True)
    restore_parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.command == "backup":
        result = backup(
            _store("SOURCE"),
            _store("BACKUP"),
            backup_id=args.backup_id,
            source_prefix=args.source_prefix,
            apply=args.apply,
        )
    elif args.command == "backup-verify":
        result = backup_and_verify(
            _store("SOURCE"),
            _store("BACKUP"),
            backup_id=args.backup_id,
            source_prefix=args.source_prefix,
            apply=args.apply,
        )
    elif args.command == "verify":
        result = verify(_store("BACKUP"), backup_id=args.backup_id)
    else:
        result = restore(
            _store("BACKUP"),
            _store("RESTORE"),
            backup_id=args.backup_id,
            destination_prefix=args.destination_prefix,
            apply=args.apply,
        )
    print(json.dumps(result, sort_keys=True))
    verification = result.get("verification")
    verified = result.get("verified", True) if verification is None else verification["verified"]
    return 0 if verified else 1


if __name__ == "__main__":
    raise SystemExit(main())
