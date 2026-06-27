"""Async PostgreSQL persistence layer, split into a package by domain.

`_core` owns the asyncpg pool, schema init, and shared helpers; each domain
module imports the pool live via ``_core._pool``. Every public name is
re-exported here so the historical ``import database as db`` surface is
unchanged, and ``__getattr__`` forwards live module state (notably ``_pool``,
reassigned by ``init()``) so ``database._pool`` always reflects the current pool.
"""
from . import _core
from . import (
    ops, stores, linking, conversations, queues, carts, employees,
    marketing, blog, comments,
)

_SUBMODULES = (_core, ops, stores, linking, conversations, queues, carts,
               employees, marketing, blog, comments)

for _mod in _SUBMODULES:
    for _name in dir(_mod):
        if not _name.startswith("__") and _name != "_pool":
            globals().setdefault(_name, getattr(_mod, _name))
del _mod, _name


def __getattr__(name):
    # Forward live mutable module state (e.g. _pool, reassigned by init()) and
    # anything else defined on _core that wasn't statically re-exported.
    return getattr(_core, name)
