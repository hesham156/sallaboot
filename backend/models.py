"""
Pydantic request/response models for the FastAPI app.

Lifted from main.py during Phase 2 modularisation. Keep this file
limited to schema definitions — no business logic, no DB access. The
goal is that any router or test can `from models import ChatRequest`
without dragging in the FastAPI app or its dependencies.
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


# ── Chat (public widget surface) ─────────────────────────────────────────

class ChatRequest(BaseModel):
    # message length is enforced in the handler (>4000 → 413) to preserve that
    # error contract; the auxiliary fields get schema-level upper bounds (#9) so
    # an unauthenticated caller can't push unbounded strings into storage/lookup.
    message: str
    session_id: Optional[str] = Field(default=None, max_length=200)
    store_id: Optional[str] = Field(default="default", max_length=120)
    # Salla storefront SDK passes the logged-in customer's ID here. When
    # present, the backend looks up the customer's profile from Salla
    # (name, phone, email, city, gender) and links any future conversation
    # to it — so the same customer's chat history follows them across
    # devices and re-opens.
    customer_id: Optional[str] = Field(default=None, max_length=64)
    customer_name: Optional[str] = Field(default=None, max_length=200)   # widget hint when SDK has it
    # Backend-issued signed session token from a previous turn. The ONLY trusted
    # carrier of identity; `customer_id` above is a personalization hint only.
    session_token: Optional[str] = Field(default=None, max_length=4096)


class ChatResponse(BaseModel):
    reply: str
    session_id: str
    bot_enabled: bool = True
    components: Optional[list] = None   # rich UI components (product cards, cart, checkout…)
    cart_count: int = 0                 # current cart item count for badge
    # Signed session token the widget should persist and echo back next turn.
    session_token: Optional[str] = None


class RateRequest(BaseModel):
    session_id: str = Field(max_length=200)
    store_id:   str = Field(default="default", max_length=120)
    rating:     int          # 1 – 5 (range enforced in the handler → 400)
    comment:    str = Field(default="", max_length=2000)


# ── Admin (authenticated) ────────────────────────────────────────────────

class AdminReplyRequest(BaseModel):
    message: str


class AddNoteRequest(BaseModel):
    # Internal staff note (never sent to the customer). @mentions are resolved
    # backend-side from the text against the store's employees.
    message: str


class BotToggleRequest(BaseModel):
    enabled: bool


class EndConversationRequest(BaseModel):
    farewell:  Optional[str] = ""        # employee farewell text
    skip_csat: Optional[bool] = False    # if true, don't post the CSAT survey


# ── Auth ─────────────────────────────────────────────────────────────────

# Upper bounds below are generous safety caps (#9): they sit far above any
# legitimate value and exist only to stop unbounded-input abuse. Capping
# `password` length in particular blocks an argon2-hashing CPU-DoS from a
# multi-megabyte password. Semantic checks (email format, password >= 8) still
# run in the handlers and keep their existing error messages.

class LoginRequest(BaseModel):
    password: str = Field(max_length=1024)
    email: Optional[str] = Field(default="", max_length=320)
    # "Remember this device" token from a previous OTP-verified login. When valid
    # for this email, login skips the OTP step (finding: email 2FA, 30-day trust).
    device_token: Optional[str] = Field(default="", max_length=4096)


class OtpVerifyRequest(BaseModel):
    """Second step of OTP-gated signup/login: the user submits the emailed code
    plus the signed challenge and the original credentials (re-checked server-side)."""
    email:           str = Field(max_length=320)
    code:            str = Field(max_length=12)
    challenge:       str = Field(max_length=4096)
    purpose:         str = Field(max_length=16)   # "signup" | "login"
    password:        str = Field(max_length=1024)
    name:            Optional[str] = Field(default="", max_length=200)     # signup only
    remember_device: Optional[bool] = True  # issue a 30-day device-trust token


class EmployeeLoginRequest(BaseModel):
    email:    str = Field(max_length=320)
    password: str = Field(max_length=1024)


class SignupRequest(BaseModel):
    """Self-service merchant signup — creates a platform-independent 7ayak
    account that can later link Salla / Shopify / Zid from the dashboard."""
    name:     str = Field(max_length=200)
    email:    str = Field(max_length=320)
    password: str = Field(max_length=1024)


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password:     str


class AccountEmailRequest(BaseModel):
    email: str


class AccountEmailVerifyRequest(BaseModel):
    email:     str
    challenge: str
    code:      str


# ── Settings ─────────────────────────────────────────────────────────────

class AIConfigRequest(BaseModel):
    groq_api_key:      Optional[str] = ""
    anthropic_api_key: Optional[str] = ""
    openai_api_key:    Optional[str] = ""  # sk-proj-...
    ai_model:          Optional[str] = ""  # e.g. "gpt-4o", "llama-3.3-70b-versatile", "claude-sonnet-4-6"
    bot_name:          Optional[str] = ""
    store_type:        Optional[str] = None  # "printing" | "general" — gates printing features
    # Category names hidden from the bot — products in these categories are never
    # surfaced in discovery/knowledge paths. None = leave unchanged; [] = clear.
    excluded_categories: Optional[List[str]] = None
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
