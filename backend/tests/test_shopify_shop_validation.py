"""
Security regression tests for Shopify shop-domain validation (finding M-13).

_normalize_shop() used to only check endswith(".myshopify.com"), so a value
like "attacker.com#x.myshopify.com" passed but pointed https://{shop}/... at
attacker.com (SSRF / open-redirect). It now strips embedded host delimiters and
validates against a strict anchored pattern, raising 400 on anything suspicious.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from routers.integrations import _normalize_shop


pytestmark = pytest.mark.unit


# ── Valid / normalised ────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("mystore.myshopify.com",                 "mystore.myshopify.com"),
    ("MyStore.MyShopify.Com",                 "mystore.myshopify.com"),
    ("mystore",                               "mystore.myshopify.com"),   # bare handle
    ("https://mystore.myshopify.com",         "mystore.myshopify.com"),
    ("https://mystore.myshopify.com/admin",   "mystore.myshopify.com"),
    ("mystore.myshopify.com/admin?x=1",       "mystore.myshopify.com"),
    ("my-store-123.myshopify.com",            "my-store-123.myshopify.com"),
    ("  mystore.myshopify.com/  ",            "mystore.myshopify.com"),
])
def test_valid_shops_normalised(raw, expected):
    assert _normalize_shop(raw) == expected


# ── Malicious / malformed → 400 ───────────────────────────────────────────────

@pytest.mark.parametrize("raw", [
    "attacker.com#x.myshopify.com",          # fragment smuggles a host
    "https://attacker.com#.myshopify.com",
    "attacker.com",
    "evil.myshopify.com.attacker.com",       # suffix is NOT myshopify.com
    "evil.com/mystore.myshopify.com",        # path smuggles a host
    "user@evil.com",                         # userinfo
    "mystore.myshopify.com:8080",            # port
    "sub.mystore.myshopify.com",             # multi-label subdomain
    ".myshopify.com",                        # empty handle
    "",                                      # empty
    "https://evil.com",
])
def test_malicious_shops_rejected(raw):
    with pytest.raises(HTTPException) as ei:
        _normalize_shop(raw)
    assert ei.value.status_code == 400
