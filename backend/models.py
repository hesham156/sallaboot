"""
Pydantic request/response models for the FastAPI app.

Lifted from main.py during Phase 2 modularisation. Keep this file
limited to schema definitions — no business logic, no DB access. The
goal is that any router or test can `from models import ChatRequest`
without dragging in the FastAPI app or its dependencies.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


# ── Chat (public widget surface) ─────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    store_id: Optional[str] = "default"
    # Salla storefront SDK passes the logged-in customer's ID here. When
    # present, the backend looks up the customer's profile from Salla
    # (name, phone, email, city, gender) and links any future conversation
    # to it — so the same customer's chat history follows them across
    # devices and re-opens.
    customer_id: Optional[str] = None
    customer_name: Optional[str] = None   # widget hint when SDK has it


class ChatResponse(BaseModel):
    reply: str
    session_id: str
    bot_enabled: bool = True
    components: Optional[list] = None   # rich UI components (product cards, cart, checkout…)
    cart_count: int = 0                 # current cart item count for badge


class RateRequest(BaseModel):
    session_id: str
    store_id:   str = "default"
    rating:     int          # 1 – 5
    comment:    str = ""


# ── Admin (authenticated) ────────────────────────────────────────────────

class AdminReplyRequest(BaseModel):
    message: str


class BotToggleRequest(BaseModel):
    enabled: bool


class EndConversationRequest(BaseModel):
    farewell:  Optional[str] = ""        # employee farewell text
    skip_csat: Optional[bool] = False    # if true, don't post the CSAT survey


# ── Auth ─────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    password: str
    email: Optional[str] = ""


class EmployeeLoginRequest(BaseModel):
    email:    str
    password: str


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password:     str


# ── Settings ─────────────────────────────────────────────────────────────

class AIConfigRequest(BaseModel):
    groq_api_key:      Optional[str] = ""
    anthropic_api_key: Optional[str] = ""
    openai_api_key:    Optional[str] = ""  # sk-proj-...
    ai_model:          Optional[str] = ""  # e.g. "gpt-4o", "llama-3.3-70b-versatile", "claude-sonnet-4-6"
    bot_name:          Optional[str] = ""
    store_type:        Optional[str] = None  # "printing" | "general" — gates printing features
    # WhatsApp Cloud API (Meta) — per-store channel config
    whatsapp_token:    Optional[str] = None  # access token (write-only; "" keeps existing)
    whatsapp_phone_id: Optional[str] = None  # Phone Number ID
    whatsapp_waba_id:  Optional[str] = None  # WhatsApp Business Account ID
    whatsapp_enabled:  Optional[bool] = None
    # Messenger + Instagram (Facebook Page) — connection handled by
    # /meta/connect-pages; these toggles let the merchant enable/disable a
    # channel without reconnecting.
    messenger_enabled: Optional[bool] = None
    instagram_enabled: Optional[bool] = None
    # AI-issued discount coupons (opt-in — the bot can create real Salla coupons)
    coupons_enabled:           Optional[bool]  = None
    coupon_max_percent:        Optional[int]   = None  # hard cap on discount %
    coupon_max_discount_value: Optional[float] = None  # SAR cap per coupon
    coupon_min_order:          Optional[float] = None  # min order subtotal to qualify
    coupon_ttl_hours:          Optional[int]   = None  # validity window (>= 24h)
    # ── Data-access permissions ────────────────────────────────────────────────
    # Each flag gates a group of tools. None/missing = ON (backward-compatible).
    # Setting to False removes those tools from the bot so it cannot access that
    # category of Salla data even if the customer asks.
    access_orders:            Optional[bool] = None  # track_order
    access_invoices:          Optional[bool] = None  # get_order_invoice
    access_customers:         Optional[bool] = None  # lookup_customer
    access_reviews:           Optional[bool] = None  # get_product_reviews
    access_abandoned_carts:   Optional[bool] = None  # get_abandoned_carts
    access_shipments:         Optional[bool] = None  # track_shipment + estimate_shipping
    access_delivery_promises: Optional[bool] = None  # get_delivery_promises
    # ── Bot personality & response style ──────────────────────────────────────
    # These fields control how the bot speaks — language, tone, verbosity, etc.
    # They are injected into the system prompt at runtime so changes take
    # effect immediately without restarting the server.
    bot_language:        Optional[str]  = None  # "ar" | "en" | "auto"
    bot_tone:            Optional[str]  = None  # "formal" | "friendly" | "very_friendly"
    response_length:     Optional[str]  = None  # "concise" | "normal" | "detailed"
    use_emoji:           Optional[bool] = None  # False = strip all emoji from replies
    greeting_message:    Optional[str]  = None  # first message shown when widget opens
    custom_instructions: Optional[str]  = None  # merchant's extra rules injected into prompt


class CustomKnowledgeRequest(BaseModel):
    custom_knowledge: str = ""


class TrainingTextRequest(BaseModel):
    kind:    str       # 'instruction' | 'faq'
    title:   str       # short label / question
    content: str       # body / answer
    enabled: bool = True


class NotificationSettingsRequest(BaseModel):
    email_enabled:       bool  = False
    email:               str   = ""   # alias used by frontend
    email_address:       str   = ""   # legacy alias
    webhook_enabled:     bool  = False
    webhook_url:         str   = ""
    notify_new_conv:     bool  = True
    notify_low_rating:   bool  = True
    notify_llm_budget:   bool  = True
    notify_abandoned_cart: bool = True
    on_new_conversation: bool  = True   # legacy alias
    on_abandoned_cart:   bool  = True   # legacy alias
    on_low_rating:       bool  = True   # legacy alias
    quiet_hours_enabled: bool  = False
    quiet_hours_start:   int   = 22
    quiet_hours_end:     int   = 8


# ── Employees ────────────────────────────────────────────────────────────

class EmployeeCreateRequest(BaseModel):
    name:     str
    email:    str
    password: str
    role:     Optional[str] = "agent"     # 'agent' | 'manager'
    active:   Optional[bool] = True


class EmployeeUpdateRequest(BaseModel):
    name:     Optional[str]  = None
    email:    Optional[str]  = None
    password: Optional[str]  = None       # set to a new value to change it
    role:     Optional[str]  = None
    active:   Optional[bool] = None


# ── Stores (super-admin manual ops) ──────────────────────────────────────

class ManualRegisterRequest(BaseModel):
    store_id:      str
    access_token:  str
    refresh_token: Optional[str] = ""
    store_name:    Optional[str] = ""
