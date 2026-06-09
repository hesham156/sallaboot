"""
Tests for the HMAC-signed stream-ticket helpers in main.py.

These tickets gate SSE access to per-store admin streams. They replaced
an in-process dict that broke across web replicas; the contract here is:

  • Stateless verification — any process holding ADMIN_SECRET validates
    a ticket without coordination.
  • Bound to one store — a ticket for store A must not work for store B.
  • TTL-respected — expired tickets reject.
  • Tamper-evident — any byte flipped in the payload invalidates the sig.
"""
from __future__ import annotations

import time

import main


def test_roundtrip_valid_ticket() -> None:
    ticket = main._issue_stream_ticket("store-42")
    assert main._consume_stream_ticket(ticket, "store-42") is True


def test_ticket_is_stateless_across_processes() -> None:
    """
    Simulate a different web replica: issue, then validate against the
    same logic without any shared in-memory state. The function is pure
    (depends only on ADMIN_SECRET + the ticket bytes), so a second call
    with the same args must accept.
    """
    ticket = main._issue_stream_ticket("store-77")
    # Same ticket can be consumed twice — the old single-use property is
    # intentionally dropped; the 5-min TTL + store binding is the gate.
    assert main._consume_stream_ticket(ticket, "store-77") is True
    assert main._consume_stream_ticket(ticket, "store-77") is True


def test_wrong_store_rejected() -> None:
    ticket = main._issue_stream_ticket("store-A")
    assert main._consume_stream_ticket(ticket, "store-B") is False


def test_tampered_signature_rejected() -> None:
    ticket = main._issue_stream_ticket("store-x")
    # Flip the last char of the signature — must fail HMAC compare.
    flipped = ticket[:-1] + ("0" if ticket[-1] != "0" else "1")
    assert main._consume_stream_ticket(flipped, "store-x") is False


def test_tampered_store_in_payload_rejected() -> None:
    """
    Attempt to swap the bound store inside the payload without re-signing.
    The signature is over the full payload string, so this must fail
    even if the attacker matches the format.
    """
    ticket = main._issue_stream_ticket("store-a")
    parts = ticket.split(":", 3)
    forged = "store-b" + ":" + ":".join(parts[1:])
    assert main._consume_stream_ticket(forged, "store-b") is False


def test_expired_ticket_rejected(monkeypatch) -> None:
    """
    Issue a ticket, then jump the clock past its TTL. _consume must
    reject. We patch time inside main's _stream_time alias so the issue
    path uses one time and the consume path uses another.
    """
    ticket = main._issue_stream_ticket("store-exp")

    real_time = time.time
    monkeypatch.setattr(
        main._stream_time, "time",
        lambda: real_time() + main._TICKET_TTL_SECONDS + 10,
    )
    assert main._consume_stream_ticket(ticket, "store-exp") is False


def test_malformed_ticket_rejected() -> None:
    assert main._consume_stream_ticket("", "store-x")            is False
    assert main._consume_stream_ticket("not-a-ticket", "store-x") is False
    # Too few separators.
    assert main._consume_stream_ticket("a:b:c", "store-x")       is False
    # Too many.
    assert main._consume_stream_ticket("a:b:c:d:e", "store-x")   is False
    # exp not an int.
    assert main._consume_stream_ticket("store-x:notanint:abc:sig", "store-x") is False
