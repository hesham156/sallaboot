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
    whatsapp_enabled:  Optional[bool] = None


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
