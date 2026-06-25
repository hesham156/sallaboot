"""
Public, unauthenticated routes — landing pages (SPA shell), health
probes, widget.js delivery, Salla snippet helper, env diagnostics.

Extracted from main.py in Phase 2. URLs are unchanged.
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, Response

import auth as _auth
import database as db
import store_manager as sm


router = APIRouter()


# ── SPA shell paths (one handler, many routes) ───────────────────────────
# Static React app is mounted under /assets; these endpoints serve the
# index.html so client-side routing (BrowserRouter) takes over. main.py
# owns the actual file paths (_ADMIN_DIST_IDX, _ADMIN_HTML) — we import
# the helper from there so a future move of the dist folder only touches
# one place.

def _serve_react_or_legacy() -> HTMLResponse:
    """
    Serve the new React app if built; fall back to legacy admin.html.
    Mirrors the original main._serve_react_or_legacy; same file probe
    so the deploy story (no `assets/` dir → falls back to legacy) is
    unchanged.

    Cache headers
    ─────────────
    index.html MUST NOT be cached by the browser. Each Vite build emits
    new content-hashed chunk filenames (StoreDashboard-XYZ.js), and
    index.html is the manifest that tells the browser which hashes to
    request. If a CDN/browser serves yesterday's index.html, the script
    tags reference yesterday's chunks — which the new deploy already
    deleted → 404 → ErrorBoundary 500 page. The /assets/* files ARE
    safe to cache (their filename includes the content hash, so a new
    deploy means new filenames; old content stays addressable by old
    URLs as long as the CDN keeps them).
    """
    base = Path(__file__).resolve().parents[1]
    admin_dist_idx = base / "admin-dist" / "index.html"
    admin_html     = base / "admin.html"
    html = (
        admin_dist_idx.read_text(encoding="utf-8")
        if admin_dist_idx.exists()
        else admin_html.read_text(encoding="utf-8")
    )
    return HTMLResponse(
        html,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma":        "no-cache",
        },
    )


def _is_browser_nav(request: Request) -> bool:
    """
    True when the caller is a person hard-navigating/refreshing a URL in the
    browser address bar, rather than the SPA's fetch() wrapper.

    A few `/admin/<name>` paths are BOTH a client-side SPA route AND a JSON API
    endpoint (e.g. /admin/audit-log, /admin/platform-ops). For XHR we want the
    JSON; for a hard refresh we want the SPA shell so React Router can render
    the page (which then makes the authenticated XHR itself). The api.ts
    fetch wrapper never sends `Accept: text/html`, so this is a clean signal.
    """
    if request.method != "GET":
        return False
    return "text/html" in (request.headers.get("Accept") or "").lower()


@router.get("/", response_class=HTMLResponse)
async def root_index():
    return _serve_react_or_legacy()


@router.get("/landing", response_class=HTMLResponse)
async def landing_page():
    return _serve_react_or_legacy()


@router.get("/login", response_class=HTMLResponse)
async def login_page():
    return _serve_react_or_legacy()


@router.get("/privacy", response_class=HTMLResponse)
async def privacy_page():
    return _serve_react_or_legacy()


@router.get("/terms", response_class=HTMLResponse)
async def terms_page():
    return _serve_react_or_legacy()


@router.get("/data-deletion", response_class=HTMLResponse)
async def data_deletion_page():
    return _serve_react_or_legacy()


@router.get("/blog", response_class=HTMLResponse)
async def blog_index():
    return _serve_react_or_legacy()


@router.get("/blog/{slug}", response_class=HTMLResponse)
async def blog_post(slug: str):
    return _serve_react_or_legacy()


@router.get("/admin", response_class=HTMLResponse)
async def admin_index():
    return _serve_react_or_legacy()


@router.get("/store/{store_id}", response_class=HTMLResponse)
async def store_spa(store_id: str):
    return _serve_react_or_legacy()


@router.get("/store/{store_id}/{rest:path}", response_class=HTMLResponse)
async def store_spa_sub(store_id: str, rest: str):
    return _serve_react_or_legacy()


# ── SEO: robots.txt + sitemap.xml ────────────────────────────────────────
# Served straight from the backend so they always reflect the current
# BASE_URL and route list, without bundling stale files into the SPA.
# Google Search Console reads these to crawl the marketing pages while
# staying out of the auth-gated dashboard.

@router.get("/robots.txt", response_class=PlainTextResponse)
async def robots_txt():
    base = os.getenv("BASE_URL", "https://7ayak.app").rstrip("/")
    return (
        "User-agent: *\n"
        "Allow: /\n"
        "Allow: /landing\n"
        "Allow: /blog\n"
        "Allow: /privacy\n"
        "Allow: /terms\n"
        "Allow: /data-deletion\n"
        # Auth-gated SPA + API surfaces: no SEO value, would waste crawl budget
        # and risk leaking store-scoped URLs into search results.
        "Disallow: /admin\n"
        "Disallow: /admin/\n"
        "Disallow: /store/\n"
        "Disallow: /auth/\n"
        "Disallow: /webhook/\n"
        "Disallow: /chat\n"
        "Disallow: /chat/\n"
        "Disallow: /upload\n"
        "Disallow: /file/\n"
        "Disallow: /uploads/\n"
        "Disallow: /env-check\n"
        "\n"
        f"Sitemap: {base}/sitemap.xml\n"
    )


@router.get("/sitemap.xml")
async def sitemap_xml():
    """Static pages + every published blog post pulled live from the DB.
    Editing the post list no longer requires a deploy — publishing a
    post in the admin instantly updates the sitemap for the next crawl.
    """
    base = os.getenv("BASE_URL", "https://7ayak.app").rstrip("/")
    # (path, changefreq, priority, lastmod_iso_or_None)
    urls: list[tuple[str, str, str, str | None]] = [
        ("/",              "weekly", "1.0", None),
        ("/landing",       "weekly", "0.9", None),
        ("/blog",          "weekly", "0.8", None),
        ("/privacy",       "yearly", "0.5", None),
        ("/terms",         "yearly", "0.5", None),
        ("/data-deletion", "yearly", "0.5", None),
    ]
    # Live from DB: only published posts, newest first.
    try:
        posts = await db.blog_list_public()
    except Exception:
        posts = []
    for p in posts:
        slug    = p.get("slug", "")
        pub_at  = p.get("published_at")
        lastmod = pub_at.isoformat() if pub_at and hasattr(pub_at, "isoformat") else None
        urls.append((f"/blog/{slug}", "monthly", "0.7", lastmod))

    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for path, freq, prio, lastmod in urls:
        lines += ["  <url>", f"    <loc>{base}{path}</loc>"]
        if lastmod:
            lines.append(f"    <lastmod>{lastmod}</lastmod>")
        lines += [
            f"    <changefreq>{freq}</changefreq>",
            f"    <priority>{prio}</priority>",
            "  </url>",
        ]
    lines.append("</urlset>")
    return Response(content="\n".join(lines), media_type="application/xml")


# ── Web App Manifest (PWA + richer favicons/app icons) ───────────────────
# Served dynamically so the icon always points at the live /logo.png and the
# brand colours stay in one place. Referenced from index.html.

@router.get("/manifest.webmanifest")
async def web_manifest():
    import json as _json
    manifest = {
        "name":             "حياك — مساعد ذكي لمتاجر سلة",
        "short_name":       "حياك",
        "description":      "بوت ذكاء اصطناعي يربط متجر سلة بواتساب وانستقرام وماسنجر — خدمة عملاء ٢٤/٧.",
        "start_url":        "/",
        "scope":            "/",
        "display":          "standalone",
        "background_color": "#f8f9fe",
        "theme_color":      "#14b8a6",
        "lang":             "ar",
        "dir":              "rtl",
        "icons": [
            {"src": "/favicon.svg", "sizes": "any",     "type": "image/svg+xml", "purpose": "any"},
            {"src": "/favicon.png", "sizes": "512x512", "type": "image/png",     "purpose": "any"},
            {"src": "/favicon.png", "sizes": "512x512", "type": "image/png",     "purpose": "maskable"},
            {"src": "/apple-touch-icon.png", "sizes": "180x180", "type": "image/png"},
        ],
    }
    return Response(
        content=_json.dumps(manifest, ensure_ascii=False),
        media_type="application/manifest+json",
        headers={"Cache-Control": "public, max-age=86400"},
    )


# ── Health / diagnostics ─────────────────────────────────────────────────

@router.get("/health")
async def health():
    stores = sm.list_stores()
    total_products = sum(s.get("products_count", 0) for s in stores)
    db_ok = db.available()
    return {
        "status":         "ok" if db_ok else "degraded",
        "service":        "salla-printing-chatbot",
        "version":        "2.0.0",
        "stores_count":   len(stores),
        "total_products": total_products,
        "db":             "ok" if db_ok else "unavailable",
    }


@router.get("/env-check")
async def env_check(request: Request):
    """
    Health / diagnostics endpoint.
    Basic info is public (needed to debug widget issues).
    Security-sensitive flags (default password, ADMIN_SECRET stability)
    are ONLY returned to authenticated super-admins to avoid leaking the
    security posture to unauthenticated callers.
    """
    db_status = db.get_status()

    if not db_status["connected"]:
        if not db_status["database_url"]:
            print("[startup] ⚠️  DATABASE_URL not set — store data will be LOST on every deploy!")
        else:
            print("[startup] ⚠️  DATABASE_URL is set but DB connection failed — check Railway logs")

    # Public surface: only coarse health flags a widget needs to self-diagnose.
    # The tenant inventory (store ids + names) and the security posture (which
    # providers/secrets are configured) are NOT public — an unauthenticated
    # caller must never be able to enumerate every merchant on the platform or
    # probe its configuration (M1). Those move behind the super-admin gate below.
    result: dict = {
        "DATABASE_URL":  db_status["database_url"],
        "DB_CONNECTED":  db_status["connected"],
        "BASE_URL":      os.getenv("BASE_URL", "not set"),
    }

    token  = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    claims = _auth.verify_token(token)
    if claims and claims.get("su"):
        stores = sm.list_stores()
        store_agents = []
        for s in stores:
            sid = s["store_id"]
            a   = sm.get_agent(sid)
            store_agents.append({
                "store_id":   sid,
                "store_name": s.get("store_name", ""),
                "agent_ok":   a is not None,
                "has_ai_cfg": s.get("has_ai_config", False),
            })

        super_pass = os.getenv("SUPER_ADMIN_PASSWORD", "admin")
        result.update({
            "GROQ_API_KEY":         bool(os.getenv("GROQ_API_KEY")),
            "ANTHROPIC_API_KEY":    bool(os.getenv("ANTHROPIC_API_KEY")),
            "SALLA_ACCESS_TOKEN":   bool(os.getenv("SALLA_ACCESS_TOKEN")),
            "SALLA_WEBHOOK_SECRET": bool(os.getenv("SALLA_WEBHOOK_SECRET")),
            "stores_registered":    len(stores),
            "stores":               store_agents,
            "ADMIN_SECRET_STABLE":             _auth.ADMIN_SECRET_STABLE,
            "SUPER_ADMIN_PASSWORD_IS_DEFAULT": (super_pass == "admin"),
        })
        try:
            import backup as _bk
            result["BACKUP"] = _bk.get_status()
        except Exception:
            result["BACKUP"] = {"enabled": False, "error": "backup module unavailable"}

    return result


# ── Widget delivery ──────────────────────────────────────────────────────

@router.get("/widget.js")
async def serve_widget():
    widget_path = Path(__file__).resolve().parents[1] / "widget.js"
    return FileResponse(widget_path, media_type="application/javascript")


# ── Snippet helper (Salla Partners Portal copy/paste) ────────────────────

@router.get("/snippet")
async def snippet_guide():
    """
    Public page — shows the exact Salla Snippets code the app developer
    needs to paste in the Partners Portal. Salla resolves {{ merchant.id }}
    server-side for every store that installs the app.
    """
    base = os.getenv("BASE_URL", "http://localhost:8000")
    snippet_code = (
        f"<!-- Salla Chat Bot — paste this in Partners Portal → App → Snippets -->\n"
        f"<script>\n"
        f"window.SallaChatConfig = {{\n"
        f'  apiUrl:       "{base}",\n'
        f'  platform:     "salla",\n'
        f'  storeId:      "{{{{ merchant.id }}}}",\n'
        f'  storeName:    "{{{{ store.name }}}}",\n'
        f'  primaryColor: "#1a56db",\n'
        f'  position:     "left"\n'
        f"}};\n"
        f"</script>\n"
        f'<script src="{base}/widget.js" defer></script>'
    )
    html = f"""<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Salla Snippets — كود التضمين التلقائي</title>
<link href="https://fonts.googleapis.com/css2?family=Tajawal:wght@400;700;800&display=swap" rel="stylesheet">
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:'Tajawal',sans-serif;background:#f1f5f9;color:#1e293b;padding:32px;direction:rtl}}
  .card{{background:#fff;border-radius:16px;padding:28px 32px;max-width:820px;margin:0 auto;box-shadow:0 2px 16px rgba(0,0,0,.08)}}
  h1{{font-size:22px;font-weight:800;margin-bottom:6px}}
  .sub{{color:#64748b;font-size:14px;margin-bottom:24px}}
  .steps{{counter-reset:step;display:flex;flex-direction:column;gap:12px;margin-bottom:24px}}
  .step{{display:flex;gap:12px;align-items:flex-start;font-size:14px;line-height:1.6}}
  .step::before{{counter-increment:step;content:counter(step);min-width:26px;height:26px;border-radius:50%;background:#3b82f6;color:#fff;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:12px;flex-shrink:0;margin-top:1px}}
  code{{background:#f1f5f9;padding:2px 7px;border-radius:4px;font-size:13px;font-family:monospace}}
  .code-box{{background:#0f172a;color:#e2e8f0;border-radius:10px;padding:20px;font-family:monospace;font-size:13px;line-height:1.7;white-space:pre;overflow-x:auto;position:relative;margin-bottom:16px}}
  .copy-btn{{background:#3b82f6;color:#fff;border:none;border-radius:8px;padding:9px 20px;font-family:'Tajawal',sans-serif;font-size:14px;font-weight:700;cursor:pointer;transition:.15s}}
  .copy-btn:hover{{background:#2563eb}}
  .alert{{background:#f0fdf4;border:1px solid #bbf7d0;color:#14532d;border-radius:8px;padding:12px 16px;font-size:13px;line-height:1.6}}
  a{{color:#3b82f6}}
</style>
</head>
<body>
<div class="card">
  <h1>🧩 Salla Snippets — تضمين تلقائي للبوت</h1>
  <p class="sub">هذا الكود يُضاف مرة واحدة في Partners Portal وسلة تحقنه تلقائياً في كل متجر يثبّت تطبيقك</p>

  <div class="steps">
    <div class="step">افتح <a href="https://salla.partners" target="_blank">salla.partners</a> ← تطبيقاتي ← تطبيقك ← Snippets</div>
    <div class="step">اضغط <strong>إنشاء Snippet جديد</strong></div>
    <div class="step">اختر الموضع: <code>Body End</code> (قبل نهاية &lt;body&gt;)</div>
    <div class="step">الصق الكود التالي كاملاً ثم احفظ</div>
    <div class="step">عند تثبيت أي متجر للتطبيق، البوت يظهر تلقائياً بدون أي إعداد إضافي ✅</div>
  </div>

  <div class="code-box" id="snippet-code">{snippet_code}</div>
  <button class="copy-btn" onclick="copySnippet()">📋 نسخ الكود</button>

  <hr style="border:none;border-top:1px solid #e2e8f0;margin:24px 0">
  <div class="alert">
    💡 <strong>ملاحظة:</strong> <code>{{{{ merchant.id }}}}</code> و <code>{{{{ store.name }}}}</code>
    يُستبدلان تلقائياً بسلة بمعرّف وباسم المتجر الحقيقي — لا تغيّر هذه القيم يدوياً.
    <br>يمكنك تغيير <code>primaryColor</code> و <code>position</code> حسب تصميم تطبيقك.
  </div>
</div>

<script>
function copySnippet() {{
  var code = document.getElementById('snippet-code').textContent;
  navigator.clipboard.writeText(code).then(function() {{
    var btn = document.querySelector('.copy-btn');
    btn.textContent = '✅ تم النسخ!';
    setTimeout(function(){{ btn.textContent = '📋 نسخ الكود'; }}, 2000);
  }});
}}
</script>
</body>
</html>"""
    return HTMLResponse(html)


@router.get("/test-widget/{store_id}", response_class=HTMLResponse)
async def test_widget_page(store_id: str):
    """
    Quick test page — embeds the widget with the *real* store_id so
    developers can test the bot without going through Salla Snippets.
    Linked from the admin dashboard 'Test Bot' button.
    """
    import html as _html
    import json as _json
    import re as _re
    # Reflected-XSS guard (finding H-1): this page echoes store_id into both an
    # HTML and an inline-JS context. Validate against a strict allowlist, then
    # encode per context — html.escape for markup, json.dumps for the script.
    if not _re.match(r"^[A-Za-z0-9_-]{1,64}$", store_id or ""):
        raise HTTPException(404, "store not found")
    base   = os.getenv("BASE_URL", "http://localhost:8000")
    info   = sm.get_store_info(store_id)
    name   = info.get("store_name", f"متجر {store_id}")
    e_sid  = _html.escape(store_id)
    e_name = _html.escape(name)
    j_sid  = _json.dumps(store_id)
    j_name = _json.dumps(name)
    j_base = _json.dumps(base)
    return HTMLResponse(f"""<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>اختبار بوت — {e_name}</title>
<link href="https://fonts.googleapis.com/css2?family=Tajawal:wght@400;700&display=swap" rel="stylesheet">
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:'Tajawal',sans-serif;background:#f1f5f9;display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:100vh;padding:24px}}
  .card{{background:#fff;border-radius:16px;padding:28px 32px;max-width:480px;width:100%;box-shadow:0 4px 24px rgba(0,0,0,.10);text-align:center}}
  h1{{font-size:20px;font-weight:800;margin-bottom:8px;color:#1e293b}}
  .sub{{color:#64748b;font-size:14px;margin-bottom:24px}}
  .info{{background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:12px 16px;font-size:13px;color:#475569;text-align:right;margin-bottom:16px}}
  .info b{{color:#1e293b}}
  .hint{{font-size:12px;color:#94a3b8;margin-top:16px}}
</style>
</head>
<body>
<div class="card">
  <h1>🧪 وضع الاختبار</h1>
  <p class="sub">البوت يعمل بـ store_id الحقيقي — اضغط أيقونة الدردشة أسفل الشاشة</p>
  <div class="info">
    <div><b>المتجر:</b> {e_name}</div>
    <div><b>Store ID:</b> {e_sid}</div>
  </div>
  <p class="hint">💡 هذه الصفحة للاختبار فقط — لا تشاركها مع العملاء</p>
</div>
<script>
window.SallaChatConfig = {{
  storeId:      {j_sid},
  storeName:    {j_name},
  primaryColor: "#1a56db",
  position:     "left",
  apiUrl:       {j_base},
}};
</script>
<script src="{base}/widget.js" defer></script>
</body>
</html>""")


# ── Super-admin: Salla merchant↔account diagnostics + repair ─────────────
# Account-preserving linking maps a Salla merchant_id → a 7ayak account and
# deletes the merchant store row; the storefront widget resolves through that
# map. These let a super admin SEE the current binding and force-repair it when
# a merchant got orphaned (e.g. the map write didn't land during linking).

def _require_super(request: Request) -> None:
    token  = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    claims = _auth.verify_token(token)
    if not claims or not claims.get("su"):
        raise HTTPException(403, "مصرح للمدير العام فقط")


@router.get("/admin/salla/diag")
async def salla_diag(request: Request, merchant: str = ""):
    """What does the platform think owns this Salla merchant_id?"""
    _require_super(request)
    merchant = (merchant or "").strip()
    return {
        "merchant":            merchant,
        "kv_map":              await db.get_app_setting(f"salla_merchant:{merchant}") if merchant else None,
        "by_salla_merchant_id": await db.find_account_by_salla_merchant(merchant) if merchant else None,
        "resolved":            await db.resolve_merchant_to_account(merchant) if merchant else None,
        "salla_stores":        await db.list_salla_stores(),
    }


@router.post("/admin/salla/bind")
async def salla_bind(request: Request):
    """Force-bind a Salla merchant_id to a 7ayak account: write the KV map AND
    stamp salla_merchant_id on the account so the widget resolves. Body:
    {"merchant": "...", "account": "..."}."""
    _require_super(request)
    body     = await request.json()
    merchant = str(body.get("merchant", "")).strip()
    account  = str(body.get("account", "")).strip()
    if not merchant or not account:
        raise HTTPException(400, "merchant and account are required")
    if not sm.is_registered(account):
        await sm.sync_one_from_db(account)
    if not sm.is_registered(account):
        raise HTTPException(404, f"account {account!r} not found")
    await db.set_salla_merchant_map(merchant, account)
    await db.set_store_salla_merchant_id(account, merchant)
    # Keep the in-memory registry coherent on this process.
    info = dict(sm.get_store_info(account) or {})
    info["salla_merchant_id"] = merchant
    sm.update_store_info(account, info)
    sm.reset_agent(account)
    print(f"[admin] 🔗 force-bound salla merchant {merchant!r} → account {account!r}")
    return {"ok": True, "merchant": merchant, "account": account,
            "resolved": await db.resolve_merchant_to_account(merchant)}


# ── Super-admin: force DB sync ───────────────────────────────────────────
# Kept on the public router because it shares the bearer-auth-check style
# of /env-check rather than the middleware-protected /admin/{id}/* pattern.

@router.post("/admin/force-db-sync")
async def force_db_sync(request: Request):
    """
    Super-admin: force-save every in-memory store to PostgreSQL.
    Use after first connecting a DB, or to recover from a registration
    that landed while the DB was down.
    """
    token  = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    claims = _auth.verify_token(token)
    if not claims or not claims.get("su"):
        raise HTTPException(403, "مصرح للمدير العام فقط")

    if not db.available():
        raise HTTPException(503, "قاعدة البيانات غير متصلة. تأكد من إعداد DATABASE_URL في Railway.")

    stores_data = []
    for s in sm.list_stores():
        sid    = s["store_id"]
        tokens = sm.get_store_info(sid)
        if tokens:
            stores_data.append({"store_id": sid, "tokens": tokens})

    saved = await db.force_save_all_stores(stores_data)
    print(f"[admin] force-db-sync: saved {saved}/{len(stores_data)} stores to DB")
    return {
        "status":  "ok",
        "saved":   saved,
        "total":   len(stores_data),
        "message": f"تم حفظ {saved} متجر في قاعدة البيانات بنجاح ✅",
    }


# ── /admin/stores list (super-admin protected by middleware) ─────────────
# Sits here rather than in routers/stores.py because (a) middleware.py
# matches `^/admin/stores$` for super-admin auth, (b) it's a read-only
# list and conceptually a diagnostic, (c) routers/stores.py would be a
# one-route file otherwise.

@router.get("/admin/stores")
async def admin_list_stores():
    """Return JSON list of all registered stores (super-admin only)."""
    return {"stores": sm.list_stores()}


# ── Platform Operations dashboard (super-admin) ──────────────────────────
# Aggregate health snapshot for the platform owner. NO customer data, NO
# secrets — counters, error counts, top-N error lists. Authorised inline
# (rather than via middleware regex) because the path is at the same
# level as /admin/stores and follows the same auth pattern.

import asyncio as _asyncio


def _store_uses_widget(s: dict) -> bool:
    """Conservative heuristic: a registered store always supports widget."""
    return bool(s.get("store_id"))


def _store_uses_whatsapp(s: dict) -> bool:
    ai = s.get("ai_config") or {}
    return bool(ai.get("whatsapp_enabled") and (ai.get("whatsapp_token") or "").strip())


def _token_status_label(s: dict) -> str:
    """Coarse buckets for the dashboard chip — never reveals the token."""
    exp = (s.get("expires_at") or "").strip()
    if not exp:
        return "unknown"
    try:
        import datetime as _dtt
        when = _dtt.datetime.fromisoformat(exp.replace("Z", ""))
    except Exception:
        return "unknown"
    delta = (when - _dtt.datetime.utcnow()).total_seconds()
    if delta < 0:
        return "expired"
    if delta < 86_400 * 2:    # < 2 days
        return "expiring"
    return "valid"


@router.get("/admin/platform-ops")
async def platform_ops(request: Request):
    """
    Super-admin operational snapshot.

    Sections:
      • totals      — active store count, conv/msg counters, token totals
      • queues      — inbox + outbox status counts (pending/failed/dead)
      • errors      — webhook errors (24h), failed logins, sig failures
      • near_budget — stores at ≥ 80% of their daily LLM budget
      • top_errors  — stores with the most webhook errors / dead outbox rows
      • stores      — one row per registered store with status flags +
                      coarse token status (no actual tokens / keys)
    """
    # Hard refresh / typed URL on this dual-purpose path → serve the SPA shell
    # (no Bearer header is attached on a browser navigation, so the auth check
    # below would otherwise 401 the page itself, not just the data).
    if _is_browser_nav(request):
        return _serve_react_or_legacy()

    token  = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    claims = _auth.verify_token(token)
    if not claims or not claims.get("su"):
        raise HTTPException(401, "يرجى تسجيل الدخول كمدير عام")

    if not db.available():
        raise HTTPException(503, "قاعدة البيانات غير متصلة")

    # Run independent aggregates in parallel — saves ~half a second on a
    # slow DB. asyncio.gather propagates exceptions so each call's own
    # error handler keeps it from killing the whole snapshot.
    (
        inbox_counts,
        outbox_counts,
        tokens_today,
        active_convs,
        webhook_errors,
        outbox_dead_top,
        login_fails,
    ) = await _asyncio.gather(
        db.inbox_count_by_status(),
        db.outbox_count_by_status(),
        db.llm_tokens_today_all_stores(),
        db.conversations_active_today(),
        db.webhook_error_counts(window_hours=24),
        db.outbox_dead_top_stores(limit=5),
        db.login_failures_24h(),
    )

    # Per-store rows — registry is in-memory so this is cheap.
    stores_raw = sm.list_stores()
    today_by_store = {p["store_id"]: p for p in tokens_today["per_store"]}

    # Resolve effective budget the same way main._daily_token_budget does,
    # without importing main (would create a circular import).
    import os as _os
    try:
        env_budget = max(0, int(_os.getenv("LLM_DAILY_TOKEN_BUDGET", "500000")))
    except ValueError:
        env_budget = 500_000

    near_budget: list[dict] = []
    store_rows:  list[dict] = []
    for s in stores_raw:
        sid = s["store_id"]
        # Coarse store metadata only — never the raw access_token or keys.
        ai_cfg   = s.get("ai_config") or {}
        override = ai_cfg.get("daily_token_budget")
        try:
            store_budget = int(override) if override is not None else env_budget
        except (TypeError, ValueError):
            store_budget = env_budget
        used = int((today_by_store.get(sid) or {}).get("tokens_total", 0))
        pct  = (used / store_budget * 100.0) if store_budget > 0 else None

        # Coarse provider label — names which AI provider is configured,
        # but NEVER the key. "—" when nothing configured (env-fallback or
        # unconfigured store).
        if ai_cfg.get("groq_api_key"):       provider = "groq"
        elif ai_cfg.get("anthropic_api_key"): provider = "anthropic"
        elif ai_cfg.get("openai_api_key"):    provider = "openai"
        else:                                  provider = "—"

        row = {
            "store_id":      sid,
            "store_name":    s.get("store_name") or "",
            "connected_at":  s.get("connected_at") or "",
            "last_activity": s.get("last_sync") or s.get("connected_at") or "",
            "bot_enabled":   bool(s.get("bot_enabled", True)),
            "channels": {
                "widget":   _store_uses_widget(s),
                "whatsapp": _store_uses_whatsapp(s),
            },
            "token_status":  _token_status_label(s),
            "provider":      provider,
            "products_count": int(s.get("products_count") or 0),
            "tokens_today":   used,
            "budget":         store_budget,
            "percent_used":   round(pct, 1) if pct is not None else None,
        }
        store_rows.append(row)

        if pct is not None and pct >= 80:
            near_budget.append({
                "store_id":     sid,
                "store_name":   s.get("store_name") or "",
                "tokens_today": used,
                "budget":       store_budget,
                "percent_used": round(pct, 1),
            })

    near_budget.sort(key=lambda r: r["percent_used"], reverse=True)

    return {
        "totals": {
            "stores_registered": len(stores_raw),
            "stores_active_today": active_convs["active_sessions"],
            "messages_today":      active_convs["messages_today_estimate"],
            "tokens_today":        tokens_today["total_tokens"],
            "llm_requests_today":  tokens_today["total_requests"],
        },
        "queues": {
            "inbox":  inbox_counts,
            "outbox": outbox_counts,
        },
        "errors": {
            "webhook_errors_24h":      webhook_errors["errors_24h"],
            "webhook_sig_failures_24h": webhook_errors["signature_failures_24h"],
            "login_failures_24h":      login_fails,
        },
        "near_budget":     near_budget,
        "top_error_stores": webhook_errors["top_stores"],
        "outbox_dead_top":  outbox_dead_top,
        "stores": store_rows,
    }


# NOTE: the SPA deep-link catch-all for `/admin/{store_id}` is intentionally
# NOT defined here. A path parameter route registered in this router would
# shadow every literal `/admin/<name>` JSON endpoint declared after it
# (audit-log below, plus conversations/db-test/registry-vs-db/products/debug in
# other routers included later). main.py registers that catch-all LAST, after
# all API routers, so the literal endpoints always win for XHR calls.


# ── Audit log viewers ────────────────────────────────────────────────────
# Two reads. The global one is super-admin only — by definition it shows
# rows from every store. The per-store one is the owner's own ledger.

@router.get("/admin/audit-log")
async def audit_log_global(request: Request, limit: int = 200, offset: int = 0,
                            action: str | None = None,
                            store_id: str | None = None):
    """Super-admin: every sensitive action across all stores."""
    # Hard refresh / typed URL on this dual-purpose path (it's also the SPA
    # route /admin/audit-log) → serve the SPA shell; React Router renders the
    # page and re-fetches this endpoint with the Bearer header attached.
    if _is_browser_nav(request):
        return _serve_react_or_legacy()

    token  = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    claims = _auth.verify_token(token)
    if not claims or not claims.get("su"):
        raise HTTPException(401, "يرجى تسجيل الدخول كمدير عام")
    rows = await db.audit_list(
        store_id = store_id or None,
        action   = action   or None,
        limit    = limit,
        offset   = offset,
    )
    return {"count": len(rows), "rows": rows}
