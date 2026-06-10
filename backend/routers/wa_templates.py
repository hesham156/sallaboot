"""
WhatsApp Template Messages — manage and send Meta-approved templates.

Endpoints:
  GET    /admin/{store_id}/whatsapp/templates          — list saved templates
  POST   /admin/{store_id}/whatsapp/templates          — save/upsert a template
  DELETE /admin/{store_id}/whatsapp/templates/{name}   — remove a template
  POST   /admin/{store_id}/whatsapp/templates/{name}/send  — send to a phone number
  GET    /admin/{store_id}/whatsapp/templates/meta     — fetch from Meta API directly
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

import database as db
import store_manager as sm
import whatsapp as wa

router = APIRouter()


def _wa_cfg(store_id: str) -> tuple[str, str, str]:
    """Return (token, phone_id, waba_id) or raise 400 if not configured."""
    cfg      = sm.get_ai_config(store_id) or {}
    token    = (cfg.get("whatsapp_token")    or "").strip()
    phone_id = (cfg.get("whatsapp_phone_id") or "").strip()
    waba_id  = (cfg.get("whatsapp_waba_id")  or "").strip()
    if not token:
        raise HTTPException(400, "whatsapp_token غير محدد في إعدادات المتجر")
    if not phone_id:
        raise HTTPException(400, "whatsapp_phone_id غير محدد في إعدادات المتجر")
    return token, phone_id, waba_id


# ── List saved templates ───────────────────────────────────────────────────────

@router.get("/admin/{store_id}/whatsapp/templates")
async def list_templates(store_id: str):
    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")
    templates = await db.wa_template_list(store_id)
    return {"templates": templates, "count": len(templates)}


# ── Save / upsert a template ───────────────────────────────────────────────────

@router.post("/admin/{store_id}/whatsapp/templates")
async def save_template(store_id: str, request: Request):
    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")
    body = await request.json()

    name = (body.get("name") or "").strip().replace(" ", "_").lower()
    if not name:
        raise HTTPException(400, "name مطلوب")
    body_text = (body.get("body_text") or "").strip()
    if not body_text:
        raise HTTPException(400, "body_text مطلوب")

    tpl = {
        "name":        name,
        "language":    body.get("language", "ar"),
        "category":    body.get("category", "MARKETING").upper(),
        "header_type": body.get("header_type", ""),
        "header_text": body.get("header_text", ""),
        "body_text":   body_text,
        "footer_text": body.get("footer_text", ""),
        "buttons":     body.get("buttons", []),
        "variables":   body.get("variables", []),
        "status":      body.get("status", "approved"),
        "notes":       body.get("notes", ""),
    }
    saved = await db.wa_template_save(store_id, tpl)
    if not saved:
        raise HTTPException(500, "فشل الحفظ في قاعدة البيانات")
    return {"status": "ok", "template": saved}


# ── Delete a template ──────────────────────────────────────────────────────────

@router.delete("/admin/{store_id}/whatsapp/templates/{name}")
async def delete_template(store_id: str, name: str):
    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")
    ok = await db.wa_template_delete(store_id, name)
    if not ok:
        raise HTTPException(404, f"القالب '{name}' غير موجود")
    return {"status": "ok"}


# ── Send a template to a phone number ─────────────────────────────────────────

@router.post("/admin/{store_id}/whatsapp/templates/{name}/send")
async def send_template(store_id: str, name: str, request: Request):
    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")

    body = await request.json()
    to   = (body.get("to") or body.get("phone") or "").strip().replace(" ", "")
    if not to:
        raise HTTPException(400, "to (رقم الهاتف) مطلوب")

    token, phone_id, _ = _wa_cfg(store_id)

    # Load template to get language + variable names
    templates = await db.wa_template_list(store_id)
    tpl = next((t for t in templates if t["name"] == name), None)
    if not tpl:
        raise HTTPException(404, f"القالب '{name}' غير موجود")

    if tpl["status"] != "approved":
        raise HTTPException(400, f"القالب '{name}' غير معتمد من Meta (الحالة: {tpl['status']})")

    # Variables values supplied by the caller as a dict {var_name: value}
    var_values: dict = body.get("variables", {})
    var_names: list  = tpl.get("variables", [])

    body_params  = [str(var_values.get(v, "")) for v in var_names] if var_names else None
    header_params = None
    if tpl.get("header_type") == "TEXT" and tpl.get("header_text"):
        import re
        hv = re.findall(r"\{\{(\d+)\}\}", tpl["header_text"])
        if hv:
            header_params = [str(var_values.get(f"header_{i}", "")) for i in range(len(hv))]

    ok = await wa.send_template(
        token        = token,
        phone_id     = phone_id,
        to           = to,
        template_name= name,
        language     = tpl.get("language", "ar"),
        header_params= header_params,
        body_params  = body_params,
    )
    if not ok:
        raise HTTPException(500, "فشل إرسال القالب — تحقق من الـ token وصلاحيته")
    return {"status": "ok", "message": f"✅ تم إرسال القالب '{name}' إلى {to}"}


# ── Fetch templates from Meta API directly ────────────────────────────────────

@router.get("/admin/{store_id}/whatsapp/templates/meta")
async def fetch_meta_templates(store_id: str):
    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")
    token, _, waba_id = _wa_cfg(store_id)
    if not waba_id:
        raise HTTPException(400,
            "whatsapp_waba_id غير محدد — أضفه من إعدادات WhatsApp "
            "(هو الـ WhatsApp Business Account ID من Meta Business Manager)"
        )
    templates = await wa.list_meta_templates(token, waba_id)
    return {"templates": templates, "count": len(templates)}


# ── Import approved templates from Meta into local DB ─────────────────────────

@router.post("/admin/{store_id}/whatsapp/templates/import-from-meta")
async def import_from_meta(store_id: str):
    """Fetch all APPROVED templates from Meta and upsert them into the local DB."""
    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")
    token, _, waba_id = _wa_cfg(store_id)
    if not waba_id:
        raise HTTPException(400, "whatsapp_waba_id غير محدد")

    meta_templates = await wa.list_meta_templates(token, waba_id)
    imported = 0
    for mt in meta_templates:
        if mt.get("status", "").upper() != "APPROVED":
            continue
        # Extract variables from body text ({{1}}, {{2}}, ...)
        import re
        vars_found = re.findall(r"\{\{(\w+)\}\}", mt.get("body", ""))
        body_comp  = next((c for c in mt.get("components", []) if c.get("type") == "BODY"), {})
        header_comp= next((c for c in mt.get("components", []) if c.get("type") == "HEADER"), {})
        footer_comp= next((c for c in mt.get("components", []) if c.get("type") == "FOOTER"), {})
        btn_comp   = [c for c in mt.get("components", []) if c.get("type") == "BUTTONS"]

        tpl = {
            "name":        mt["name"],
            "language":    mt.get("language", "ar"),
            "category":    mt.get("category", "MARKETING"),
            "header_type": header_comp.get("format", ""),
            "header_text": header_comp.get("text", ""),
            "body_text":   body_comp.get("text", mt.get("body", "")),
            "footer_text": footer_comp.get("text", ""),
            "buttons":     btn_comp[0].get("buttons", []) if btn_comp else [],
            "variables":   vars_found,
            "status":      "approved",
            "notes":       "مستورد من Meta",
        }
        saved = await db.wa_template_save(store_id, tpl)
        if saved:
            imported += 1

    return {
        "status":   "ok",
        "imported": imported,
        "total":    len(meta_templates),
        "message":  f"✅ تم استيراد {imported} قالب معتمد من Meta",
    }
