"""Analytics routes: store analytics, ROI, weekly report, insights."""
import datetime as _dt

from fastapi import APIRouter

import database as db
import store_manager as sm
import conversation_store as cs

router = APIRouter()


# ── Helpers ───────────────────────────────────────────────────────────────────

# Channels we break analytics out by. "widget" is the default (store
# website embed) and the catch-all for anything unrecognised.
CHANNELS = ("widget", "whatsapp", "telegram", "messenger", "instagram")

# session_id prefix → channel. The webhooks build sessions as
# wa:/tg:/msgr:/ig: (see routers/webhooks.py). Keep in sync with them.
_PREFIX_CHANNEL = {
    "wa:":   "whatsapp",
    "tg:":   "telegram",
    "msgr:": "messenger",
    "ig:":   "instagram",
}


def _conv_channel(session_id: str, conv: dict) -> str:
    for prefix, channel in _PREFIX_CHANNEL.items():
        if session_id.startswith(prefix):
            return channel
    # Fall back to the channel stamped on customer_info (set by the
    # webhook handlers). widget conversations have no prefix and usually
    # no channel tag.
    ch = ((conv.get("customer_info") or {}).get("channel") or "").lower()
    if ch in CHANNELS:
        return ch
    return "widget"


def _empty_channel_stats(now_utc) -> dict:
    daily: dict = {}
    for i in range(14):
        d = (now_utc - _dt.timedelta(days=i)).strftime("%Y-%m-%d")
        daily[d] = 0
    return {
        "_daily": daily,
        "conversations": {
            "total": 0, "today": 0, "this_week": 0,
            "bot_handled": 0, "admin_takeover": 0,
            "avg_messages": 0,
            "daily_counts": [],
            "hourly_distribution": [0] * 24,
        },
        "messages": {"total": 0, "user": 0, "bot": 0, "admin": 0},
        "ratings": {"count": 0, "avg": 0, "distribution": [0, 0, 0, 0, 0], "_sum": 0},
    }


def _accumulate_conv(stats: dict, conv: dict, now_utc) -> None:
    c = stats["conversations"]
    c["total"] += 1

    created_str = conv.get("created_at", "")
    try:
        created = _dt.datetime.fromisoformat(created_str)
        delta   = now_utc - created
        if delta.days == 0:
            c["today"] += 1
        if delta.days < 7:
            c["this_week"] += 1
        date_key = created.strftime("%Y-%m-%d")
        if date_key in stats["_daily"]:
            stats["_daily"][date_key] += 1
        c["hourly_distribution"][created.hour] += 1
    except Exception:
        pass

    if not conv.get("bot_enabled", True):
        c["admin_takeover"] += 1
    else:
        c["bot_handled"] += 1

    m = stats["messages"]
    for msg in conv.get("messages", []):
        m["total"] += 1
        role = msg.get("role", "")
        if role == "user":
            m["user"] += 1
        elif role == "assistant":
            m["bot"] += 1
        elif role == "admin":
            m["admin"] += 1

    try:
        r = int(conv.get("rating") or 0)
    except (TypeError, ValueError):
        r = 0
    if 1 <= r <= 5:
        stats["ratings"]["count"]               += 1
        stats["ratings"]["_sum"]                += r
        stats["ratings"]["distribution"][r - 1] += 1


def _finalise_channel_stats(stats: dict) -> dict:
    c = stats["conversations"]
    m = stats["messages"]
    r = stats["ratings"]

    c["avg_messages"] = round(m["total"] / c["total"], 1) if c["total"] else 0
    c["daily_counts"] = [
        {"date": d, "count": stats["_daily"][d]}
        for d in sorted(stats["_daily"].keys())
    ]
    # Deflection rate: share of conversations the bot resolved without a
    # human taking over. The headline "is the bot saving me work?" number.
    c["deflection_rate"] = (
        round(c["bot_handled"] / c["total"] * 100, 1) if c["total"] else 0
    )
    # Busiest hour of the day (0–23) — for staffing. -1 when no data.
    hd = c["hourly_distribution"]
    c["peak_hour"] = hd.index(max(hd)) if c["total"] and max(hd) > 0 else -1
    r["avg"] = round(r["_sum"] / r["count"], 1) if r["count"] else 0
    stats.pop("_daily", None)
    r.pop("_sum", None)
    return stats


def _safe_dt(s: str, fallback):
    try:
        return _dt.datetime.fromisoformat(s)
    except Exception:
        return fallback


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/admin/{store_id}/analytics")
async def store_analytics(store_id: str):
    now_utc = _dt.datetime.utcnow()
    all_convs = await cs.get_all_conversations_for_store(store_id)

    buckets = {ch: _empty_channel_stats(now_utc) for ch in CHANNELS}
    buckets["total"] = _empty_channel_stats(now_utc)

    for sid, conv in all_convs.items():
        channel = _conv_channel(sid, conv)
        _accumulate_conv(buckets[channel], conv, now_utc)
        _accumulate_conv(buckets["total"], conv, now_utc)

    for k in buckets:
        _finalise_channel_stats(buckets[k])

    carts_list = await db.load_abandoned_carts(store_id) if db.available() else []
    total_carts     = len(carts_list)
    recovered_carts = sum(1 for c in carts_list if c.get("recovered"))
    pending_carts   = total_carts - recovered_carts
    recovery_rate   = round(recovered_carts / total_carts * 100, 1) if total_carts else 0

    cache = sm.get_cache(store_id)
    total = buckets["total"]

    def _channel_view(b: dict) -> dict:
        return {
            "conversations": b["conversations"],
            "messages":      b["messages"],
            "ratings":       b["ratings"],
        }

    c = total["conversations"]
    return {
        "conversations":   c,
        "messages":        total["messages"],
        "ratings":         total["ratings"],
        # ── Headline operational metrics (was already computed, now surfaced) ──
        "deflection": {
            "bot_handled":     c["bot_handled"],
            "admin_takeover":  c["admin_takeover"],
            "rate":            c["deflection_rate"],
        },
        "trend":      c["daily_counts"],          # 14-day [{date, count}]
        "hourly":     c["hourly_distribution"],   # 24-slot conversation volume
        "peak_hour":  c["peak_hour"],
        "abandoned_carts": {
            "total":         total_carts,
            "recovered":     recovered_carts,
            "pending":       pending_carts,
            "recovery_rate": recovery_rate,
        },
        "products": {
            "count":     cache.get("products_count", 0),
            "last_sync": cache.get("last_sync", "never"),
        },
        "by_channel": {
            **{ch: _channel_view(buckets[ch]) for ch in CHANNELS},
            "total": _channel_view(total),
        },
    }


@router.get("/admin/{store_id}/analytics/roi")
async def store_roi(store_id: str, days: int = 30):
    days = max(1, min(int(days or 30), 365))
    now_utc      = _dt.datetime.utcnow()
    window_start = now_utc - _dt.timedelta(days=days)

    roi = await db.get_bot_roi(store_id, days)

    convs = await cs.get_all_conversations_for_store(store_id)
    convs_window = 0
    msgs_handled = 0
    for conv in convs.values():
        try:
            created   = _dt.datetime.fromisoformat(conv.get("created_at", ""))
            in_window = created >= window_start
        except Exception:
            in_window = True
        if in_window:
            convs_window += 1
            msgs_handled += sum(
                1 for m in conv.get("messages", [])
                if m.get("role") in ("assistant", "admin")
            )

    carts = await db.load_abandoned_carts(store_id) if db.available() else []
    carts_recovered = sum(1 for c in carts if c.get("recovered"))

    minutes_saved = convs_window * 5
    hours_saved   = round(minutes_saved / 60, 1)

    return {
        "days":             days,
        "currency":         roi["currency"],
        "revenue":          roi["revenue"],
        "orders":           roi["orders"],
        "avg_order":        roi["avg_order"],
        "revenue_all":      roi["revenue_all"],
        "orders_all":       roi["orders_all"],
        "conversations":    convs_window,
        "messages_handled": msgs_handled,
        "hours_saved":      hours_saved,
        "carts_recovered":  carts_recovered,
    }


@router.get("/admin/{store_id}/analytics/weekly")
async def store_weekly(store_id: str):
    def _pct(now_v: float, prev_v: float) -> int:
        if prev_v <= 0:
            return 100 if now_v > 0 else 0
        return round((now_v - prev_v) / prev_v * 100)

    now_utc   = _dt.datetime.utcnow()
    week_ago  = now_utc - _dt.timedelta(days=7)
    two_weeks = now_utc - _dt.timedelta(days=14)

    wroi = await db.get_weekly_roi(store_id)

    convs = await cs.get_all_conversations_for_store(store_id)
    conv_this = conv_prev = 0
    ratings: list[int] = []
    for conv in convs.values():
        try:
            created = _dt.datetime.fromisoformat(conv.get("created_at", ""))
        except Exception:
            created = now_utc
        if created >= week_ago:
            conv_this += 1
            r = conv.get("rating")
            if isinstance(r, (int, float)) and r:
                ratings.append(int(r))
        elif two_weeks <= created < week_ago:
            conv_prev += 1

    avg_rating = round(sum(ratings) / len(ratings), 1) if ratings else 0.0

    top_topic = ""
    try:
        import conversation_analyzer as ca
        recent = {sid: c for sid, c in convs.items()
                  if _safe_dt(c.get("created_at", ""), now_utc) >= week_ago}
        insights = ca.analyze_insights(list(recent.values()))
        tq = insights.get("top_questions") or []
        if tq:
            top_topic = tq[0].get("label", "")
    except Exception as exc:
        print(f"[weekly] topic analysis skipped: {exc}")

    return {
        "currency":      wroi["currency"],
        "revenue":       wroi["rev_this"],
        "revenue_delta": _pct(wroi["rev_this"], wroi["rev_prev"]),
        "orders":        wroi["ord_this"],
        "orders_delta":  _pct(wroi["ord_this"], wroi["ord_prev"]),
        "conversations": conv_this,
        "conv_delta":    _pct(conv_this, conv_prev),
        "avg_rating":    avg_rating,
        "top_topic":     top_topic,
    }


@router.get("/admin/{store_id}/analytics/insights")
async def store_insights(store_id: str):
    import conversation_analyzer as ca
    all_convs = await cs.get_all_conversations_for_store(store_id)
    return ca.analyze_insights(all_convs)


# ── Operations: response time + knowledge gaps ────────────────────────────────

# Human-readable labels for the escalation reasons the bot hands off with
# (see conversation_store.VALID_ESCALATION_REASONS). These are the "where
# does the bot get stuck?" buckets the merchant uses to improve coverage.
_ESCALATION_LABELS = {
    "unpriced_material":    "خامة بلا سعر",
    "oversize_design":      "مقاس أكبر من المتاح",
    "digital_over_500":     "ديجيتال > 500 حبة",
    "offset_under_1000":    "أوفست < 1000 حبة",
    "offset_paper_missing": "سعر ورق الأوفست ناقص",
    "box_oversize":         "علبة بمقاس كبير",
    "custom_finishing":     "تشطيب غير مسعّر",
    "vip_or_complaint":     "عميل VIP أو شكوى",
    "customer_image":       "العميل أرسل صورة",
    "customer_attachment":  "العميل أرسل مرفقاً",
    "other":                "أخرى",
}


def _first_response_seconds(messages: list) -> float | None:
    """Seconds between the first customer message and the first bot/admin
    reply that follows it. None when the pair can't be formed."""
    first_user_ts = None
    for msg in messages:
        role = msg.get("role")
        ts   = _safe_dt(msg.get("ts", ""), None)
        if ts is None:
            continue
        if role == "user" and first_user_ts is None:
            first_user_ts = ts
        elif role in ("assistant", "admin") and first_user_ts is not None:
            delta = (ts - first_user_ts).total_seconds()
            return delta if delta >= 0 else None
    return None


def _conversation_span_seconds(messages: list) -> float | None:
    """Wall-clock duration from first to last timestamped message."""
    stamps = [t for t in (_safe_dt(m.get("ts", ""), None) for m in messages) if t]
    if len(stamps) < 2:
        return None
    span = (max(stamps) - min(stamps)).total_seconds()
    return span if span >= 0 else None


@router.get("/admin/{store_id}/analytics/operations")
async def store_operations(store_id: str):
    """Operational quality metrics:
      - first-response + resolution times (responsiveness)
      - escalations grouped by reason (knowledge gaps / where the bot stalls)
      - open "needs support" count (unresolved handoffs)
    """
    all_convs = await cs.get_all_conversations_for_store(store_id)

    response_times: list[float] = []
    span_times:     list[float] = []
    gap_counts:     dict[str, int] = {}
    escalated_total = 0
    needs_support   = 0

    for conv in all_convs.values():
        msgs = conv.get("messages", []) or []

        fr = _first_response_seconds(msgs)
        if fr is not None:
            response_times.append(fr)
        sp = _conversation_span_seconds(msgs)
        if sp is not None:
            span_times.append(sp)

        esc = conv.get("escalation")
        if isinstance(esc, dict) and esc.get("reason"):
            escalated_total += 1
            reason = esc.get("reason", "other")
            gap_counts[reason] = gap_counts.get(reason, 0) + 1
            if not esc.get("resolved"):
                needs_support += 1

    def _avg(xs: list[float]) -> int:
        return round(sum(xs) / len(xs)) if xs else 0

    knowledge_gaps = sorted(
        (
            {
                "reason": r,
                "label":  _ESCALATION_LABELS.get(r, r),
                "count":  n,
            }
            for r, n in gap_counts.items()
        ),
        key=lambda x: x["count"],
        reverse=True,
    )

    return {
        "response_time": {
            "avg_first_response_sec": _avg(response_times),
            "avg_resolution_sec":     _avg(span_times),
            "sample_size":            len(response_times),
        },
        "knowledge_gaps":  knowledge_gaps,
        "escalated_total": escalated_total,
        "needs_support":   needs_support,
    }
