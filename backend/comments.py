"""
comments.py
─────────────────────────────────────────────────────────────────────────────
Facebook Page + Instagram Business **comment** transport.

Sibling of messenger.py. Where messenger.py handles Meta *Direct messages*
(`messaging` webhook events, replied via the Send API), this module handles
public *comments* on Page posts and Instagram media:

    object = "page"       , changes[].field = "feed"     , value.item = "comment"
    object = "instagram"  , changes[].field = "comments" | "mentions"

They arrive on the SAME /meta/webhook URL as DMs (told apart by `object` +
`changes` vs `messaging`). Replies use the **comment edge**, not the Send API:

    Facebook  reply   → POST /{comment_id}/comments
    Facebook  hide    → POST /{comment_id}              (is_hidden=true)
    Facebook  privateDM→ POST /{comment_id}/private_replies
    Instagram reply   → POST /{ig_comment_id}/replies
    Instagram hide    → POST /{ig_comment_id}           (hide=true)

All authenticated with the store's long-lived **Page access token**
(ai_config.page_token). Inbound comments are routed to the owning store via
entry.id (page_id for FB, ig_id for IG) using store_manager.find_store_by_page_id
(which already matches ig_id too).
"""
from __future__ import annotations

import os
import httpx

import messenger as _ms

GRAPH_VERSION = os.getenv("META_GRAPH_VERSION", os.getenv("WHATSAPP_GRAPH_VERSION", "v21.0"))
_GRAPH = f"https://graph.facebook.com/{GRAPH_VERSION}"

# Comment-reply length caps (well under Meta's limits; long AI replies are
# truncated by the caller, not split — a single public comment shouldn't be a
# multi-part thread).
COMMENT_TEXT_LIMIT = 1000

# Page webhook fields for comment automation.
#   feed       → Page post comments (Facebook)
#   mention    → someone @-mentions the Page
#
# CRITICAL: POST /{page}/subscribed_apps REPLACES the page's subscribed_fields
# (it does NOT merge). The connect flow calls subscribe_page (messaging) and
# then subscribe_page_comments — so whichever runs LAST must carry the FULL
# union, otherwise it silently clobbers the other and that channel goes dark.
# We therefore subscribe the union of messaging + comment fields here.
COMMENT_PAGE_FIELDS = _ms._PAGE_SUBSCRIBE_FIELDS + ",feed,mention"
# Instagram fields are subscribed on the linked IG account via the Page sub.
COMMENT_IG_FIELDS = "comments,mentions"


def extract_comments(payload: dict) -> list[dict]:
    """
    Parse a Page/Instagram webhook payload into a flat list of inbound comment
    dicts. Returns dicts shaped:

        {
          "platform":     "facebook" | "instagram",
          "object_type":  "comment" | "mention",
          "recipient_id": "<page_id or ig_id>",   # entry.id — finds the store
          "comment_id":   "<external comment id>",
          "parent_id":    "<parent comment id, if a reply>",
          "post_id":      "<post / media id>",
          "author_id":    "<commenter id>",
          "author_name":  "<commenter name/username>",
          "text":         "<comment text>",
          "permalink":    "<url, if provided>",
        }

    Only `add`/`edited` comment events are surfaced. The store's OWN comments
    (author id == page/ig id) are filtered out so the bot never replies to
    itself (infinite-loop guard). Deletes/hides and non-comment feed events
    (likes, reactions, status posts) are ignored.
    """
    out: list[dict] = []
    obj = payload.get("object", "")
    platform = "instagram" if obj == "instagram" else "facebook"
    try:
        for entry in payload.get("entry", []) or []:
            recipient_id = str(entry.get("id", "") or "")
            for ch in entry.get("changes", []) or []:
                field = ch.get("field", "")
                value = ch.get("value", {}) or {}

                if platform == "facebook":
                    # Page feed: only comment items, only add/edited verbs.
                    if field == "feed":
                        if value.get("item") != "comment":
                            continue
                        if value.get("verb") not in (None, "add", "edited"):
                            continue
                        object_type = "comment"
                    elif field == "mention":
                        object_type = "mention"
                    else:
                        continue
                    frm        = value.get("from") or {}
                    author_id  = str(frm.get("id", "") or "")
                    comment_id = str(value.get("comment_id", "") or value.get("id", "") or "")
                    text       = (value.get("message") or "").strip()
                    parent_id  = str(value.get("parent_id", "") or "")
                    post_id    = str(value.get("post_id", "") or "")
                    permalink  = value.get("permalink_url", "") or ""
                    author_nm  = frm.get("name", "") or ""
                else:  # instagram
                    if field == "comments":
                        object_type = "comment"
                    elif field == "mentions":
                        object_type = "mention"
                    else:
                        continue
                    frm        = value.get("from") or {}
                    author_id  = str(frm.get("id", "") or "")
                    comment_id = str(value.get("id", "") or value.get("comment_id", "") or "")
                    text       = (value.get("text") or "").strip()
                    parent_id  = str(value.get("parent_id", "") or "")
                    media      = value.get("media") or {}
                    post_id    = str(media.get("id", "") or value.get("media_id", "") or "")
                    permalink  = ""
                    author_nm  = frm.get("username", "") or ""

                if not comment_id:
                    continue
                # Self-comment guard: never act on the Page/IG account's own comments.
                if author_id and author_id == recipient_id:
                    continue

                out.append({
                    "platform":     platform,
                    "object_type":  object_type,
                    "recipient_id": recipient_id,
                    "comment_id":   comment_id,
                    "parent_id":    parent_id,
                    "post_id":      post_id,
                    "author_id":    author_id,
                    "author_name":  author_nm,
                    "text":         text,
                    "permalink":    permalink,
                })
    except Exception as exc:
        print(f"[comments] extract_comments error: {exc}")
    return out


async def reply_to_comment(token: str, comment_id: str, text: str,
                           platform: str = "facebook") -> bool:
    """
    Publicly reply to a comment. Facebook posts to /{comment_id}/comments;
    Instagram posts to /{comment_id}/replies. Returns True on success; never
    raises.
    """
    if not (token and comment_id and text):
        return False
    edge = "replies" if platform == "instagram" else "comments"
    url  = f"{_GRAPH}/{comment_id}/{edge}"
    body = {"message": text[:COMMENT_TEXT_LIMIT]}
    return await _post(url, token, body, f"{platform} reply")


async def hide_comment(token: str, comment_id: str, platform: str = "facebook",
                       hidden: bool = True) -> bool:
    """
    Hide (or unhide) a comment. Facebook uses the `is_hidden` field; Instagram
    uses `hide`. Returns True on success; never raises.
    """
    if not (token and comment_id):
        return False
    url  = f"{_GRAPH}/{comment_id}"
    body = {"hide": bool(hidden)} if platform == "instagram" else {"is_hidden": bool(hidden)}
    return await _post(url, token, body, f"{platform} hide")


async def private_reply(token: str, comment_id: str, text: str) -> bool:
    """
    Send a one-time private message (DM) in response to a comment. Facebook
    Pages only (POST /{comment_id}/private_replies). Returns True on success.
    """
    if not (token and comment_id and text):
        return False
    url = f"{_GRAPH}/{comment_id}/private_replies"
    return await _post(url, token, {"message": text[:COMMENT_TEXT_LIMIT]}, "private_reply")


async def subscribe_page_comments(page_token: str, page_id: str) -> bool:
    """
    Subscribe THIS app to a Page's comment webhooks (feed + mentions on the
    Page; comments + mentions on the linked IG account flow through the same
    Page subscription). Additive to messenger.subscribe_page's messaging
    fields. Idempotent. Returns True; never raises.
    """
    if not (page_token and page_id):
        return False
    url = f"{_GRAPH}/{page_id}/subscribed_apps"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(url, headers={"Authorization": f"Bearer {page_token}"},
                                  params={"subscribed_fields": COMMENT_PAGE_FIELDS})
            if r.status_code >= 400:
                print(f"[comments] subscribe_page_comments {r.status_code}: {r.text[:200]}")
                return False
            return True
    except Exception as exc:
        print(f"[comments] subscribe_page_comments error: {exc}")
        return False


async def _post(url: str, token: str, body: dict, label: str) -> bool:
    """Shared Graph POST with bearer auth. Logs + returns False on any failure."""
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(url, headers=headers, json=body)
            if r.status_code >= 400:
                print(f"[comments] {label} failed {r.status_code}: {r.text[:300]}")
                return False
            return True
    except Exception as exc:
        print(f"[comments] {label} error: {exc}")
        return False
