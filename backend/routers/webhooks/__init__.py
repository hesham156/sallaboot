"""Webhook routes, split by channel into a package.

`_base` owns the shared APIRouter + helpers; each channel module registers its
own routes against that router on import. Every public name from every submodule
is re-exported here so the historical ``import routers.webhooks`` attribute
surface (used by main.py, the pollers, integrations, and the tests) is unchanged.
"""
from . import _base, salla, shopify, zid, meta, comments, telegram

router = _base.router

# Re-export every top-level name (incl. single-underscore helpers that callers
# and tests reach by attribute) from each submodule, without clobbering.
for _mod in (_base, salla, shopify, zid, meta, comments, telegram):
    for _name in dir(_mod):
        if not _name.startswith("__"):
            globals().setdefault(_name, getattr(_mod, _name))
del _mod, _name
