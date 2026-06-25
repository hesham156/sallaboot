"""
comment_ai.py
─────────────────────────────────────────────────────────────────────────────
One-shot AI for public social comments: a SINGLE structured LLM call that both
classifies a comment and drafts a grounded public reply.

Why one call (not the conversational agent.chat):
  • Comments are public, one-shot, and high-volume — we want minimal latency
    and token cost, and a structured result we can gate on (confidence,
    sentiment, spam, lead score), not a free-form chat turn.
  • It still reuses everything that makes replies accurate: the store's
    configured LLM provider/key/model (via the cached agent) and the same
    knowledge block the chatbot uses (store_brain).

Public API:
    await classify_and_reply(store_id, text, settings) -> dict
        {
          "sentiment":  "positive"|"neutral"|"negative",
          "intent":     str,         # pricing|complaint|support|lead|product|booking|other
          "category":   str,         # sales|support|complaint|spam|question|feedback
          "is_spam":    bool,
          "lead_score": int,         # 0-100
          "lead_temp":  "hot"|"warm"|"cold",
          "confidence": float,       # 0.0-1.0 — how sure the model is of the reply
          "reply":      str,         # grounded public reply (may be "")
        }
    Never raises — returns a safe neutral default on any failure (the caller
    then routes to human approval).
"""
from __future__ import annotations

import json
import re

import store_brain
import store_manager as sm

# Safe default — used on any error. confidence 0 + empty reply means the caller
# will queue the comment for human approval rather than auto-post anything.
DEFAULT_RESULT: dict = {
    "sentiment": "neutral", "intent": "other", "category": "question",
    "is_spam": False, "lead_score": 0, "lead_temp": "cold",
    "confidence": 0.0, "reply": "",
}

# Brand-voice presets → a short Arabic tone instruction. The merchant picks one
# (or supplies a custom prompt) in the Automation settings panel.
_PERSONALITY_PRESETS: dict[str, str] = {
    "professional": "نبرة احترافية ومهذبة ومباشرة.",
    "friendly":     "نبرة ودودة ومرحبة وقريبة من العميل، مع لمسة بسيطة.",
    "luxury":       "نبرة راقية وفاخرة تعكس تجربة مميزة وحصرية.",
    "medical":      "نبرة موثوقة وحذرة؛ لا تقدّم تشخيصاً أو وعوداً علاجية.",
    "real_estate":  "نبرة واثقة تركّز على القيمة والموقع وسهولة التواصل.",
    "ecommerce":    "نبرة عملية تركّز على المنتج والسعر والتوصيل.",
    "automotive":   "نبرة خبيرة تركّز على المواصفات والخدمة وما بعد البيع.",
}

_VALID_SENTIMENT = {"positive", "neutral", "negative"}
_VALID_TEMP      = {"hot", "warm", "cold"}


def _personality_instruction(settings: dict) -> str:
    pers = settings.get("comment_personality") or {}
    if isinstance(pers, str):
        pers = {"preset": pers}
    custom = (pers.get("custom_prompt") or "").strip()
    if custom:
        return custom
    preset = (pers.get("preset") or "friendly").strip()
    return _PERSONALITY_PRESETS.get(preset, _PERSONALITY_PRESETS["friendly"])


async def _build_prompt(store_id: str, text: str, settings: dict) -> tuple[str, str]:
    """Return (system, user) prompts for the structured classify+reply call."""
    try:
        knowledge = await store_brain.get_knowledge_for_prompt_async(store_id)
    except Exception:
        knowledge = ""
    tone = _personality_instruction(settings)
    forbidden = settings.get("comment_forbidden_topics") or []
    forbidden_line = (
        "مواضيع محظورة (لا تُجب عنها إطلاقاً، اجعل reply فارغاً واخفض confidence): "
        + "، ".join(forbidden)
        if forbidden else ""
    )

    system = (
        "أنت مساعد يدير التعليقات العامة على صفحات فيسبوك/إنستقرام لمتجر. "
        "مهمتك: تحليل التعليق وصياغة ردّ عام قصير (جملة أو جملتين) بنفس لغة التعليق.\n"
        f"نبرة الردّ: {tone}\n"
        "قواعد صارمة:\n"
        "- لا تكشف بيانات شخصية ولا أرقام طلبات في ردّ عام؛ وجّه العميل للخاص عند الحاجة.\n"
        "- لا تخترع أسعاراً أو معلومات غير موجودة في معرفة المتجر.\n"
        "- إن كان التعليق شكوى أو حساساً أو غير واضح، اخفض confidence ليتولّاه موظف.\n"
        f"{forbidden_line}\n\n"
        "معرفة المتجر:\n" + (knowledge or "(لا تتوفر معرفة بعد)") + "\n\n"
        "أعد فقط JSON صالحاً بهذا الشكل بدون أي نص إضافي:\n"
        '{"sentiment":"positive|neutral|negative","intent":"pricing|complaint|support|'
        'lead|product|booking|other","category":"sales|support|complaint|spam|question|'
        'feedback","is_spam":true|false,"lead_score":0-100,"lead_temp":"hot|warm|cold",'
        '"confidence":0.0-1.0,"reply":"..."}'
    )
    user = f"التعليق:\n{text.strip()}"
    return system, user


def _parse_result(raw: str) -> dict:
    """Tolerant JSON extraction + validation/clamping. Falls back to DEFAULT."""
    if not raw:
        return dict(DEFAULT_RESULT)
    # Pull the first {...} block — models sometimes wrap JSON in prose/fences.
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return dict(DEFAULT_RESULT)
    try:
        data = json.loads(m.group(0))
    except Exception:
        return dict(DEFAULT_RESULT)

    out = dict(DEFAULT_RESULT)
    sent = str(data.get("sentiment", "")).lower()
    if sent in _VALID_SENTIMENT:
        out["sentiment"] = sent
    out["intent"]   = str(data.get("intent", "other"))[:40] or "other"
    out["category"] = str(data.get("category", "question"))[:40] or "question"
    out["is_spam"]  = bool(data.get("is_spam", False))
    try:
        out["lead_score"] = max(0, min(100, int(data.get("lead_score", 0))))
    except (TypeError, ValueError):
        out["lead_score"] = 0
    temp = str(data.get("lead_temp", "cold")).lower()
    out["lead_temp"] = temp if temp in _VALID_TEMP else "cold"
    try:
        out["confidence"] = max(0.0, min(1.0, float(data.get("confidence", 0.0))))
    except (TypeError, ValueError):
        out["confidence"] = 0.0
    out["reply"] = str(data.get("reply", "")).strip()
    return out


async def _complete(agent, system: str, user: str) -> tuple[str, int, int]:
    """
    Single non-streaming completion using the store agent's already-configured
    provider/client/model. Returns (text, tokens_in, tokens_out). Reuses the
    agent so we never re-implement provider/key selection.
    """
    prov = getattr(agent, "provider", "")
    if prov == "anthropic":
        r = await agent.ai.messages.create(
            model=agent._anthropic_model, max_tokens=600,
            system=system, messages=[{"role": "user", "content": user}],
        )
        text = "".join(getattr(b, "text", "") for b in r.content
                        if getattr(b, "type", "") == "text")
        usage = getattr(r, "usage", None)
        return text, getattr(usage, "input_tokens", 0) or 0, getattr(usage, "output_tokens", 0) or 0

    if prov == "groq":
        client, model = agent.groq_client, agent._groq_model
    else:  # openai | naraya
        client = agent.openai_client
        model  = agent._naraya_model if prov == "naraya" else agent._openai_model

    r = await client.chat.completions.create(
        model=model, max_tokens=600, temperature=0.3,
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": user}],
    )
    text  = (r.choices[0].message.content or "") if r.choices else ""
    usage = getattr(r, "usage", None)
    return text, getattr(usage, "prompt_tokens", 0) or 0, getattr(usage, "completion_tokens", 0) or 0


async def classify_and_reply(store_id: str, text: str, settings: dict | None = None) -> dict:
    """Classify a comment and draft a grounded reply. Never raises."""
    if not (text or "").strip():
        return dict(DEFAULT_RESULT)
    settings = settings or {}
    try:
        agent = sm.get_agent(store_id)
        if agent is None:
            return dict(DEFAULT_RESULT)
        system, user = await _build_prompt(store_id, text, settings)
        raw, tin, tout = await _complete(agent, system, user)
        # Best-effort usage metering (shares the chatbot's llm_usage ledger).
        try:
            import database as db
            if tin or tout:
                await db.llm_usage_record(store_id, tin, tout)
        except Exception:
            pass
        return _parse_result(raw)
    except Exception as exc:
        print(f"[comment_ai] classify_and_reply error (store={store_id!r}): {exc}")
        return dict(DEFAULT_RESULT)
