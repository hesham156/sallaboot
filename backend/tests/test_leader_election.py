"""
Phase 1F leader-election tests.

The leader_locks table coordinates periodic loops across instances.
Contract:
  • try_lead returns True for a new claimant, False for a contender
    during TTL, True again after expiry.
  • A holder can renew its own lease (same name + same holder_id).
  • release_leader frees the slot immediately.
  • Without a DB, try_lead returns True (standalone mode).
"""
from __future__ import annotations

import asyncio

import pytest


pytestmark = pytest.mark.integration


async def test_first_try_lead_wins(clean_db):
    db = clean_db
    assert await db.try_lead("job-1", "holder-A", ttl_seconds=60) is True

    locks = await db.list_leader_locks()
    assert any(l["name"] == "job-1" and l["holder"] == "holder-A" for l in locks)


async def test_second_try_lead_during_ttl_loses(clean_db):
    """The whole point — two instances racing must NOT both win."""
    db = clean_db
    won_a = await db.try_lead("job-2", "holder-A", ttl_seconds=60)
    won_b = await db.try_lead("job-2", "holder-B", ttl_seconds=60)
    assert won_a is True
    assert won_b is False, "second holder must NOT acquire while TTL is live"


async def test_holder_can_renew_its_own_lease(clean_db):
    """Renewing is the leader's primary signal-of-life. It must succeed
    even while the lease is non-expired."""
    db = clean_db
    assert await db.try_lead("job-3", "holder-A", ttl_seconds=60) is True
    # Same holder calls again before expiry → win (renewal).
    assert await db.try_lead("job-3", "holder-A", ttl_seconds=60) is True

    locks = await db.list_leader_locks()
    assert any(l["name"] == "job-3" and l["holder"] == "holder-A" for l in locks)


async def test_try_lead_after_expiry_takes_over(clean_db):
    """When the TTL lapses without renewal, the next claimant wins."""
    db = clean_db
    # Take leadership with a 1-second TTL so we don't need to sleep long.
    assert await db.try_lead("job-4", "holder-A", ttl_seconds=1) is True
    # Wait past expiry.
    await asyncio.sleep(1.2)
    # Now a different holder claims.
    assert await db.try_lead("job-4", "holder-B", ttl_seconds=60) is True

    locks = await db.list_leader_locks()
    found = next((l for l in locks if l["name"] == "job-4"), None)
    assert found is not None
    assert found["holder"] == "holder-B"


async def test_release_leader_frees_slot_immediately(clean_db):
    db = clean_db
    await db.try_lead("job-5", "holder-A", ttl_seconds=60)
    await db.release_leader("job-5", "holder-A")

    # Different holder claims right away — no TTL wait needed.
    assert await db.try_lead("job-5", "holder-B", ttl_seconds=60) is True


async def test_release_leader_by_non_holder_is_noop(clean_db):
    """Defensive: holder A's lease should NOT be released by holder B's
    delete call. This guards against a misconfigured worker stealing the
    lease just by knowing the name."""
    db = clean_db
    await db.try_lead("job-6", "holder-A", ttl_seconds=60)
    await db.release_leader("job-6", "holder-B")  # wrong holder

    # holder-A still owns the lease — holder-B trying again should lose.
    assert await db.try_lead("job-6", "holder-B", ttl_seconds=60) is False


async def test_concurrent_try_lead_only_one_wins(clean_db):
    """
    The atomicity guarantee. Race two try_lead calls and assert exactly
    one came back True.
    """
    db = clean_db
    results = await asyncio.gather(
        db.try_lead("job-race", "A", ttl_seconds=60),
        db.try_lead("job-race", "B", ttl_seconds=60),
    )
    assert sum(1 for r in results if r) == 1, \
        f"exactly one winner expected — got {results}"
