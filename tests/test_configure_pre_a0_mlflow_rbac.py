from __future__ import annotations

from dataclasses import dataclass

import pytest

from scripts import configure_pre_a0_mlflow_rbac as rbac


@dataclass
class _User:
    username: str
    is_admin: bool = False


@dataclass
class _Role:
    id: int
    name: str
    workspace: str = "default"


@dataclass
class _Permission:
    id: int
    resource_type: str
    resource_pattern: str
    permission: str


class _MissingError(Exception):
    error_code = "RESOURCE_DOES_NOT_EXIST"


class _Client:
    def __init__(self):
        self.users = {}
        self.roles = []
        self.permissions = {}
        self.assignments = {}

    def get_user(self, username):
        if username not in self.users:
            raise _MissingError()
        return self.users[username]

    def create_user(self, username, _password):
        self.users[username] = _User(username)
        return self.users[username]

    def list_all_roles(self):
        return self.roles

    def create_role(self, workspace, name, _description):
        role = _Role(len(self.roles) + 1, name, workspace)
        self.roles.append(role)
        return role

    def list_role_permissions(self, role_id):
        return self.permissions.get(role_id, [])

    def add_role_permission(self, role_id, resource_type, pattern, permission):
        item = _Permission(
            sum(len(value) for value in self.permissions.values()) + 1,
            resource_type,
            pattern,
            permission,
        )
        self.permissions.setdefault(role_id, []).append(item)
        return item

    def update_role_permission(self, permission_id, value):
        for permissions in self.permissions.values():
            for permission in permissions:
                if permission.id == permission_id:
                    permission.permission = value
                    return permission
        raise AssertionError(permission_id)

    def list_user_roles(self, username):
        return self.assignments.get(username, [])

    def assign_role(self, username, role_id):
        role = next(role for role in self.roles if role.id == role_id)
        self.assignments.setdefault(username, []).append(role)


def test_role_specs_separate_writer_and_monitor() -> None:
    writer, monitor = rbac._specs("1", "skipp-pre-a0")
    assert ("experiment", "1", "EDIT") in writer.permissions
    assert ("registered_model", "skipp-pre-a0", "EDIT") in writer.permissions
    assert ("experiment", "1", "READ") in monitor.permissions
    assert ("registered_model", "skipp-pre-a0", "READ") in monitor.permissions
    assert all(permission[2] != "EDIT" for permission in monitor.permissions)


def test_idempotent_role_user_permission_and_assignment(monkeypatch) -> None:
    client = _Client()
    monkeypatch.setenv("PRE_A0_MLFLOW_WRITER_PASSWORD", "w" * 32)
    monkeypatch.setenv("PRE_A0_MLFLOW_MONITOR_PASSWORD", "m" * 32)
    for spec in rbac._specs("1", "skipp-pre-a0"):
        _user, user_action = rbac._ensure_user(client, spec, _MissingError)
        role, role_action = rbac._ensure_role(client, spec, workspace="default")
        first_permissions = rbac._ensure_permissions(client, role, spec)
        first_assignment = rbac._ensure_assignment(client, spec.username, role)
        assert user_action == role_action == first_assignment == "created"
        assert all(action.startswith("created:") for action in first_permissions)

        _user, user_action = rbac._ensure_user(client, spec, _MissingError)
        role, role_action = rbac._ensure_role(client, spec, workspace="default")
        second_permissions = rbac._ensure_permissions(client, role, spec)
        second_assignment = rbac._ensure_assignment(client, spec.username, role)
        assert user_action == role_action == second_assignment == "existing"
        assert all(action.startswith("existing:") for action in second_permissions)


def test_unexpected_permission_fails_closed(monkeypatch) -> None:
    client = _Client()
    spec = rbac._specs("1", "skipp-pre-a0")[1]
    role, _action = rbac._ensure_role(client, spec, workspace="default")
    client.add_role_permission(role.id, "registered_model", "*", "MANAGE")
    with pytest.raises(RuntimeError, match="unexpected permissions"):
        rbac._ensure_permissions(client, role, spec)


def test_unexpected_role_assignment_fails_closed() -> None:
    client = _Client()
    spec = rbac._specs("1", "skipp-pre-a0")[1]
    role, _action = rbac._ensure_role(client, spec, workspace="default")
    extra = client.create_role("default", "extra-role", "unexpected")
    client.assign_role(spec.username, extra.id)
    with pytest.raises(RuntimeError, match="unexpected roles"):
        rbac._ensure_assignment(client, spec.username, role)


def test_tracking_uri_and_password_validation(monkeypatch) -> None:
    assert rbac._tracking_uri("https://mlflow.example.test/") == "https://mlflow.example.test"
    with pytest.raises(ValueError):
        rbac._tracking_uri("http://mlflow.example.test")
    spec = rbac._specs("1", "skipp-pre-a0")[1]
    monkeypatch.setenv("PRE_A0_MLFLOW_MONITOR_PASSWORD", "short")
    with pytest.raises(ValueError, match="32"):
        rbac._password(spec)
