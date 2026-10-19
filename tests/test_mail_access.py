"""The two gates in front of Gmail: an encrypted token, and school senders only."""

import pytest

from lifepilot.mail import allowlist, vault

SCHOOL = ["office@demo-school.invalid"]


def test_token_round_trips_through_fernet(monkeypatch):
    from cryptography.fernet import Fernet

    monkeypatch.setenv(vault.KEY_ENV, Fernet.generate_key().decode())
    blob = vault.seal({"refresh_token": "abc", "expiry": "2026-10-10"})

    assert b"abc" not in blob
    assert vault.unseal(blob)["refresh_token"] == "abc"


def test_a_token_sealed_with_another_key_is_refused(monkeypatch):
    from cryptography.fernet import Fernet

    monkeypatch.setenv(vault.KEY_ENV, Fernet.generate_key().decode())
    blob = vault.seal({"refresh_token": "abc"})

    monkeypatch.setenv(vault.KEY_ENV, Fernet.generate_key().decode())
    with pytest.raises(vault.CannotDecrypt):
        vault.unseal(blob)


def test_no_key_is_named_not_guessed(monkeypatch):
    monkeypatch.delenv(vault.KEY_ENV, raising=False)
    with pytest.raises(vault.NoEncryptionKey):
        vault.seal({"refresh_token": "abc"})


def test_every_query_carries_a_sender_filter():
    assert allowlist.query(SCHOOL).startswith("from:(office@demo-school.invalid)")


def test_a_query_without_senders_cannot_be_built():
    with pytest.raises(allowlist.NoAllowlist):
        allowlist.query([])


def test_query_limits_by_date_when_asked():
    from datetime import date

    assert "after:2026/10/01" in allowlist.query(SCHOOL, after=date(2026, 10, 1))


def test_display_names_and_case_do_not_defeat_the_check():
    assert allowlist.permitted("Demo School <Office@Demo-School.invalid>", SCHOOL)


def test_a_stranger_is_never_permitted():
    assert not allowlist.permitted("spam@elsewhere.invalid", SCHOOL)
    assert not allowlist.permitted("", SCHOOL)


def test_a_lookalike_sender_is_not_the_school():
    assert not allowlist.permitted("office@demo-school.invalid.evil.test", SCHOOL)
