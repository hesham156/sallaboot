"""
Unit tests for the stateless email-OTP + device-trust primitives (auth.py).

These gate the new signup/login OTP flow. The challenge carries only an HMAC of
the code (keyed by ADMIN_SECRET), so a leaked challenge can't be brute-forced
offline; these tests pin the signature/expiry/binding guarantees.
"""
from __future__ import annotations

import time

import pytest

import auth as _auth


pytestmark = pytest.mark.unit


# ── code generation ───────────────────────────────────────────────────────────

def test_generate_otp_code_is_six_digits():
    for _ in range(50):
        c = _auth.generate_otp_code()
        assert len(c) == 6 and c.isdigit()


# ── OTP challenge ──────────────────────────────────────────────────────────────

def test_challenge_round_trip_case_insensitive_email():
    code = _auth.generate_otp_code()
    ch = _auth.make_otp_challenge("User@Example.com", "login", code)
    assert _auth.verify_otp_challenge(ch, "user@example.com", "login", code) is True


def test_challenge_wrong_code_rejected():
    code = _auth.generate_otp_code()
    ch = _auth.make_otp_challenge("a@b.com", "login", code)
    wrong = "000000" if code != "000000" else "111111"
    assert _auth.verify_otp_challenge(ch, "a@b.com", "login", wrong) is False


def test_challenge_wrong_email_rejected():
    code = _auth.generate_otp_code()
    ch = _auth.make_otp_challenge("a@b.com", "login", code)
    assert _auth.verify_otp_challenge(ch, "c@d.com", "login", code) is False


def test_challenge_wrong_purpose_rejected():
    code = _auth.generate_otp_code()
    ch = _auth.make_otp_challenge("a@b.com", "login", code)
    assert _auth.verify_otp_challenge(ch, "a@b.com", "signup", code) is False


def test_challenge_tampered_signature_rejected():
    code = _auth.generate_otp_code()
    ch = _auth.make_otp_challenge("a@b.com", "login", code)
    data, sig = ch.rsplit(".", 1)
    tampered = data + "." + ("f" * len(sig))
    assert _auth.verify_otp_challenge(tampered, "a@b.com", "login", code) is False


def test_challenge_expired_rejected(monkeypatch):
    code = _auth.generate_otp_code()
    ch = _auth.make_otp_challenge("a@b.com", "login", code)  # exp = now + TTL
    real = time.time
    monkeypatch.setattr(_auth.time, "time", lambda: real() + _auth.OTP_TTL_SECONDS + 5)
    assert _auth.verify_otp_challenge(ch, "a@b.com", "login", code) is False


def test_challenge_empty_inputs_rejected():
    assert _auth.verify_otp_challenge("", "a@b.com", "login", "123456") is False
    code = _auth.generate_otp_code()
    ch = _auth.make_otp_challenge("a@b.com", "login", code)
    assert _auth.verify_otp_challenge(ch, "a@b.com", "login", "") is False


# ── device-trust token ─────────────────────────────────────────────────────────

def test_device_trust_round_trip_case_insensitive():
    t = _auth.make_device_trust("User@Example.com")
    assert _auth.device_trust_valid(t, "user@example.com") is True


def test_device_trust_wrong_email_rejected():
    t = _auth.make_device_trust("a@b.com")
    assert _auth.device_trust_valid(t, "c@d.com") is False


def test_device_trust_expired_rejected(monkeypatch):
    t = _auth.make_device_trust("a@b.com")
    real = time.time
    monkeypatch.setattr(_auth.time, "time", lambda: real() + _auth.DEVICE_TRUST_TTL_SECONDS + 5)
    assert _auth.device_trust_valid(t, "a@b.com") is False


def test_device_trust_garbage_rejected():
    assert _auth.device_trust_valid("", "a@b.com") is False
    assert _auth.device_trust_valid("not-a-token", "a@b.com") is False
    # a normal session token is not a device-trust token
    assert _auth.device_trust_valid(_auth.create_token("store_a"), "a@b.com") is False


# ── a session token must not validate as an OTP challenge (type isolation) ─────

def test_session_token_is_not_a_valid_challenge():
    assert _auth.verify_otp_challenge(_auth.create_token("s"), "a@b.com", "login", "123456") is False
