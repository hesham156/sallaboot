"""
Public, unauthenticated routes — landing pages (SPA shell), health
probes, widget.js delivery, Salla snippet helper, env diagnostics.

Extracted from main.py in Phase 2. URLs are unchanged.
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse

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


@router.get("/admin", response_class=HTMLResponse)
async def admin_index():
    return _serve_react_or_legacy()


@router.get("/store/{store_id}", response_class=HTMLResponse)
async def store_spa(store_id: str):
    return _serve_react_or_legacy()


@router.get("/store/{store_id}/{rest:path}", response_class=HTMLResponse)
async def store_spa_sub(store_id: str, rest: str):
    return _serve_react_or_legacy()


# ── Health / diagnostics ─────────────────────────────────────────────────

@router.get("/health")
async def health():
    stores = sm.list_stores()
    total_products = sum(s.get("products_count", 0) for s in stores)
    return {
        "status":           "ok",
        "service":          "salla-printing-chatbot",
        "version":          "2.0.0",
        "stores_count":     len(stores),
        "total_products":   total_products,
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
    stores    = sm.list_stores()
    db_status = db.get_status()
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

    if not db_status["connected"]:
        if not db_status["database_url"]:
            print("[startup] ⚠️  DATABASE_URL not set — store data will be LOST on every deploy!")
        else:
            print("[startup] ⚠️  DATABASE_URL is set but DB connection failed — check Railway logs")

    result: dict = {
        "GROQ_API_KEY":           bool(os.getenv("GROQ_API_KEY")),
        "ANTHROPIC_API_KEY":      bool(os.getenv("ANTHROPIC_API_KEY")),
        "SALLA_ACCESS_TOKEN":     bool(os.getenv("SALLA_ACCESS_TOKEN")),
        "SALLA_WEBHOOK_SECRET":   bool(os.getenv("SALLA_WEBHOOK_SECRET")),
        "DATABASE_URL":           db_status["database_url"],
        "DB_CONNECTED":           db_status["connected"],
        "BASE_URL":               os.getenv("BASE_URL", "not set"),
        "stores_registered":      len(stores),
        "stores":                 store_agents,
    }

    token  = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    claims = _auth.verify_token(token)
    if claims and claims.get("su"):
        super_pass = os.getenv("SUPER_ADMIN_PASSWORD", "admin")
        result["ADMIN_SECRET_STABLE"]             = _auth.ADMIN_SECRET_STABLE
        result["SUPER_ADMIN_PASSWORD_IS_DEFAULT"] = (super_pass == "admin")

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
    base  = os.getenv("BASE_URL", "http://localhost:8000")
    info  = sm.get_store_info(store_id)
    name  = info.get("store_name", f"متجر {store_id}")
    return HTMLResponse(f"""<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>اختبار بوت — {name}</title>
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
    <div><b>المتجر:</b> {name}</div>
    <div><b>Store ID:</b> {store_id}</div>
  </div>
  <p class="hint">💡 هذه الصفحة للاختبار فقط — لا تشاركها مع العملاء</p>
</div>
<script>
window.SallaChatConfig = {{
  storeId:      "{store_id}",
  storeName:    "{name}",
  primaryColor: "#1a56db",
  position:     "left",
  apiUrl:       "{base}",
}};
</script>
<script src="{base}/widget.js" defer></script>
</body>
</html>""")


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


@router.get("/admin/{store_id}", response_class=HTMLResponse)
async def admin_store_page(store_id: str):
    """Per-store admin dashboard — serves the React SPA."""
    return _serve_react_or_legacy()
