"""Schema- und Disziplin-Tests fuer proof_ledger.toml."""

from __future__ import annotations

import datetime as dt

import pytest

from scripts.proof_ledger import (
    MERGE_STATES,
    ProofLedgerError,
    class_floors,
    declared_unreachable_branches,
    load_entries,
)


def test_every_entry_carries_owner_deadline_and_a_known_state():
    for entry in load_entries():
        assert entry.state in MERGE_STATES, entry.id
        assert entry.owner, entry.id
        dt.date.fromisoformat(entry.due_by)


def test_a_fix_entry_names_its_witness_and_version_probe():
    """Ohne Zeuge und Versionsprobe ist ein Urteil nicht zurechenbar."""
    fixes = [e for e in load_entries() if e.kind == "fix"]
    assert fixes, "Ledger ohne fix-Eintrag — Positivkontrolle leer"
    for entry in fixes:
        assert entry.witness, entry.id
        assert entry.witness_job, entry.id
        assert entry.evidence_source in {"artifact", "job_log"}, entry.id
        assert entry.version_probe, entry.id
        if entry.version_probe == "KEINE":
            assert entry.raw.get("version_probe_reason"), (
                f"{entry.id}: 'KEINE' braucht einen Grund, kein Schweigen"
            )


def test_a_pass_entry_says_whether_it_was_lived_or_drilled():
    for entry in load_entries():
        if entry.state != "PASS":
            continue
        assert entry.pass_kind in {"live", "drill"}, entry.id
        if entry.pass_kind == "live":
            assert entry.witness_run, f"{entry.id}: live-PASS ohne Lauf-Id"


def test_dormant_and_unreachable_need_a_repo_coupled_reason():
    """SCHLAFEND ist ein Durchgangszustand, kein Ruhekissen."""
    for entry in load_entries():
        if entry.state in {"SCHLAFEND", "UNERREICHBAR"}:
            assert entry.unreachable_because, entry.id
            assert entry.unreachable_because.startswith(("symbol:", "path:")), entry.id


def test_the_class_floors_are_positive():
    floors = class_floors()
    assert set(floors) == {"workflows", "referenced_code", "derived_class"}
    for name, value in floors.items():
        assert value >= 1, name


def test_every_declared_unreachable_branch_carries_a_reason():
    for judge, branch, reason in declared_unreachable_branches():
        assert judge and branch, (judge, branch)
        assert len(reason.strip()) >= 40, (
            f"{judge}.{branch}: ein Einzeiler ist keine Begruendung"
        )


def test_a_malformed_entry_is_refused_loudly(tmp_path, monkeypatch):
    """Mutationsprobe: ein Eintrag ohne owner darf nicht still durchrutschen."""
    import scripts.proof_ledger as mod

    broken = tmp_path / "proof_ledger.toml"
    broken.write_text(
        '[class_floors]\nworkflows = 1\nreferenced_code = 1\nderived_class = 1\n\n'
        '[[proof]]\nid = "x"\nkind = "defect"\nclaim = "c"\n'
        'state = "OFFEN"\ndue_by = "2026-09-06"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(mod, "_LEDGER_PATH", broken)
    mod._load.cache_clear()
    with pytest.raises(ProofLedgerError, match="owner"):
        mod.load_entries()
    mod._load.cache_clear()
