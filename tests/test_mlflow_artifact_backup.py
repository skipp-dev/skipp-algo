from __future__ import annotations

import io
import json

import pytest

from scripts import mlflow_artifact_backup as backup


class _Paginator:
    def __init__(self, client):
        self.client = client

    def paginate(self, **kwargs):
        bucket = kwargs["Bucket"]
        prefix = kwargs["Prefix"]
        return [
            {
                "Contents": [
                    {"Key": key, "Size": len(value["Body"])}
                    for key, value in self.client.objects.get(bucket, {}).items()
                    if key.startswith(prefix)
                ]
            }
        ]


class _S3:
    def __init__(self):
        self.objects = {}

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        return _Paginator(self)

    def get_object(self, **kwargs):
        item = self.objects[kwargs["Bucket"]][kwargs["Key"]]
        return {"Body": io.BytesIO(item["Body"]), "Metadata": item.get("Metadata", {})}

    def put_object(self, **kwargs):
        bucket = kwargs.pop("Bucket")
        key = kwargs.pop("Key")
        body = kwargs.pop("Body")
        payload = body.read() if hasattr(body, "read") else bytes(body)
        self.objects.setdefault(bucket, {})[key] = {"Body": payload, **kwargs}

    def head_object(self, **kwargs):
        if kwargs["Key"] not in self.objects.get(kwargs["Bucket"], {}):
            error = RuntimeError("not found")
            error.response = {"Error": {"Code": "404"}}
            raise error
        return {}


def _store(bucket: str) -> backup.Store:
    return backup.Store("https://s3.example", "ams", "key", "secret", bucket)


def test_backup_verify_and_isolated_restore(monkeypatch) -> None:
    clients = {name: _S3() for name in ("source", "backup", "restore")}
    clients["source"].put_object(Bucket="source", Key="mlflow/a.json", Body=b"alpha")
    clients["source"].put_object(Bucket="source", Key="mlflow/b.bin", Body=b"beta")
    monkeypatch.setattr(backup, "_client", lambda store: clients[store.bucket])

    result = backup.backup(
        _store("source"),
        _store("backup"),
        backup_id="20260718T120000Z",
        source_prefix="mlflow/",
        apply=True,
    )
    assert result["object_count"] == 2
    assert result["total_bytes"] == 9
    manifest = json.loads(
        clients["backup"].objects["backup"]["backups/20260718T120000Z/manifest.json"]["Body"]
    )
    assert len(manifest["objects"]) == 2
    assert backup.verify(_store("backup"), backup_id="20260718T120000Z")["verified"]

    restored = backup.restore(
        _store("backup"),
        _store("restore"),
        backup_id="20260718T120000Z",
        destination_prefix="restore-drills/20260718/",
        apply=True,
    )
    assert restored["object_count"] == 2
    assert clients["restore"].objects["restore"]["restore-drills/20260718/mlflow/a.json"]["Body"] == b"alpha"


def test_backup_and_verify_combines_write_and_readback(monkeypatch) -> None:
    clients = {name: _S3() for name in ("source", "backup")}
    clients["source"].put_object(Bucket="source", Key="mlflow/a.json", Body=b"alpha")
    monkeypatch.setattr(backup, "_client", lambda store: clients[store.bucket])

    result = backup.backup_and_verify(
        _store("source"),
        _store("backup"),
        backup_id="20260718T120000Z",
        source_prefix="mlflow/",
        apply=True,
    )

    assert result["backup"]["object_count"] == 1
    assert result["verification"]["verified"] is True
    assert result["verification"]["checked_bytes"] == 5


def test_restore_refuses_canonical_or_root_destination(monkeypatch) -> None:
    monkeypatch.setattr(backup, "_client", lambda _store: _S3())
    with pytest.raises(ValueError, match="isolated"):
        backup.restore(
            _store("backup"),
            _store("restore"),
            backup_id="20260718T120000Z",
            destination_prefix="mlflow/",
            apply=False,
        )


def test_backup_and_restore_refuse_overwrite(monkeypatch) -> None:
    clients = {name: _S3() for name in ("source", "backup", "restore")}
    clients["source"].put_object(Bucket="source", Key="mlflow/a.json", Body=b"alpha")
    monkeypatch.setattr(backup, "_client", lambda store: clients[store.bucket])
    kwargs = {
        "backup_id": "20260718T120000Z",
        "source_prefix": "mlflow/",
        "apply": True,
    }
    backup.backup(_store("source"), _store("backup"), **kwargs)
    with pytest.raises(FileExistsError, match="manifest already exists"):
        backup.backup(_store("source"), _store("backup"), **kwargs)

    clients["restore"].put_object(
        Bucket="restore",
        Key="restore-drills/20260718/mlflow/a.json",
        Body=b"existing",
    )
    with pytest.raises(FileExistsError, match="already contains"):
        backup.restore(
            _store("backup"),
            _store("restore"),
            backup_id="20260718T120000Z",
            destination_prefix="restore-drills/20260718/",
            apply=True,
        )
    assert (
        clients["restore"].objects["restore"]["restore-drills/20260718/mlflow/a.json"]["Body"]
        == b"existing"
    )


def test_store_requires_https_and_all_credentials(monkeypatch) -> None:
    prefix = "MLFLOW_SOURCE_"
    values = {
        "ENDPOINT": "http://s3.example",
        "REGION": "ams",
        "ACCESS_KEY_ID": "key",
        "SECRET_ACCESS_KEY": "secret",
        "BUCKET": "bucket",
    }
    for name, value in values.items():
        monkeypatch.setenv(prefix + name, value)
    with pytest.raises(ValueError, match="HTTPS"):
        backup._store("SOURCE")
    monkeypatch.setenv(prefix + "ENDPOINT", "https://s3.example")
    assert backup._store("SOURCE").bucket == "bucket"


def test_manifest_id_is_strict() -> None:
    assert backup._manifest_key("20260718T120000Z") == "backups/20260718T120000Z/manifest.json"
    with pytest.raises(ValueError, match="YYYYMMDD"):
        backup._manifest_key("latest")
