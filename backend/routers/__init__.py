"""
Router package — one module per feature area.

Each module exposes a `router: APIRouter` that main.py picks up via
`app.include_router(...)`. The split was done in Phase 2 to keep main.py
from drifting back into the 4,000-line monolith it used to be.

Conventions:
  • Path prefixes stay on the routes themselves, NOT on APIRouter — the
    legacy URLs (/admin/{store_id}/foo, /chat, /webhook/salla) must
    remain byte-identical to what was there before so existing widgets
    + the React admin SPA don't break.
  • Routers import from models, auth, database, store_manager, etc — but
    NOT from each other (except deps.py which is the shared helpers module).
  • Cross-router constants/helpers live in routers/deps.py.
"""
