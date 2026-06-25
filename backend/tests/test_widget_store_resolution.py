"""
deps.resolve_store_id — pass-through.

In the canonical model store_id IS the Salla merchant_id everywhere (widget,
webhooks, agent), so a storefront-supplied id already addresses the right store.
resolve_store_id is a thin seam that returns the input unchanged (defaulting a
blank to "default").
"""
from __future__ import annotations

import pytest

from routers import deps


pytestmark = pytest.mark.unit


async def test_passthrough_returns_input():
    assert await deps.resolve_store_id("19314436") == "19314436"


async def test_blank_becomes_default():
    assert await deps.resolve_store_id("") == "default"
    assert await deps.resolve_store_id(None) == "default"
