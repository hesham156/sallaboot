"""
OTP challenge for the account-email change flow.

The change reuses the stateless challenge helpers in auth.py with a distinct
purpose ("change_email"). These pure-unit tests verify the round-trip and,
crucially, that a challenge minted for another purpose (e.g. login) can NOT
be replayed to change the account email.
"""
from __future__ import annotations

import pytest

import auth as _auth

pytestmark = pytest.mark.unit

PURPOSE = "change_email"


def test_change_email_challenge_round_trips():
    code = _auth.generate_otp_code()
    ch   = _auth.make_otp_challenge("new@store.com", PURPOSE, code)
    assert _auth.verify_otp_challenge(ch, "new@store.com", PURPOSE, code) is True


def test_wrong_code_rejected():
    code = _auth.generate_otp_code()
    ch   = _auth.make_otp_challenge("new@store.com", PURPOSE, code)
    assert _auth.verify_otp_challenge(ch, "new@store.com", PURPOSE, "000000") is False


def test_email_must_match():
    code = _auth.generate_otp_code()
    ch   = _auth.make_otp_challenge("new@store.com", PURPOSE, code)
    assert _auth.verify_otp_challenge(ch, "other@store.com", PURPOSE, code) is False


def test_purpose_isolation_blocks_replay():
    """A login challenge must not authorise an email change (and vice-versa)."""
    code = _auth.generate_otp_code()
    login_ch = _auth.make_otp_challenge("new@store.com", "login", code)
    assert _auth.verify_otp_challenge(login_ch, "new@store.com", PURPOSE, code) is False
    change_ch = _auth.make_otp_challenge("new@store.com", PURPOSE, code)
    assert _auth.verify_otp_challenge(change_ch, "new@store.com", "login", code) is False


def test_case_insensitive_email():
    code = _auth.generate_otp_code()
    ch   = _auth.make_otp_challenge("New@Store.com", PURPOSE, code)
    assert _auth.verify_otp_challenge(ch, "new@store.com", PURPOSE, code) is True
