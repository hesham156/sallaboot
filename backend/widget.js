(function () {
  "use strict";

  // ── Configuration ────────────────────────────────────────────────────────────
  // window.SallaChatConfig is set by the Salla Snippet before this script loads.
  // In Salla Partners Portal Snippets, {{ merchant.id }} is resolved server-side
  // so storeId is automatically the correct merchant ID for every store.
  var _ext = window.SallaChatConfig || {};
  var _defaults = {
    apiUrl:         "https://sallaboot-t.up.railway.app",
    storeId:        "default",
    primaryColor:   "#1a56db",
    position:       "left",   // "left" | "right"
    storeName:      "متجر الطباعة",
    welcomeMessage: "مرحباً! 👋 أنا مساعد متجرنا للطباعة. كيف أقدر أساعدك اليوم؟",
    placeholder:    "اكتب سؤالك هنا...",
    maxFileSizeMB:  20,
  };
  var CONFIG = Object.assign({}, _defaults, _ext);

  // Normalise storeId — if Salla's server-side template was NOT resolved
  // (widget tested directly outside Salla Snippets), "{{ merchant.id }}" is
  // passed literally.  Detect it and fall back to "default".
  var _sid = String(CONFIG.storeId || "").trim();
  if (!_sid || _sid.includes("{{") || _sid.includes("}}")) _sid = "default";
  CONFIG.storeId = _sid;

  // Same sanitisation for storeName
  var _sn = String(CONFIG.storeName || "").trim();
  if (!_sn || _sn.includes("{{") || _sn.includes("}}")) _sn = _defaults.storeName;
  CONFIG.storeName = _sn;

  // Support short alias: color → primaryColor
  if (_ext.color && !_ext.primaryColor) CONFIG.primaryColor = _ext.color;

  // ── State ─────────────────────────────────────────────────────────────────────
  var sessionId = null;
  var isOpen = false;
  var isLoading = false;
  var historyLoaded = false;      // guards one-time re-render of past messages
  var botEnabled = true;          // tracks whether AI bot is handling this session
  var pollTimer = null;           // setInterval handle for admin message polling
  var humanBannerShown = false;   // prevent duplicate "human took over" banners
  var _botReplyCount = 0;         // how many bot replies this session
  var _ratingShown = false;       // rating bar shown at least once this session
  var sallaCustomerId   = "";     // Salla customer id when the visitor is logged in
  var sallaCustomerName = "";

  // ── Salla Storefront SDK detection ───────────────────────────────────────────
  // When the widget runs inside a Salla store page, window.salla is available.
  // We use salla.cart.addItem() for real cart operations instead of our backend.
  function sallaReady() {
    return typeof window.salla !== "undefined" && window.salla && window.salla.cart;
  }

  // ── Customer identity ────────────────────────────────────────────────────────
  // Detect the logged-in Salla customer (when the storefront SDK is present)
  // OR fall back to the widget config (e.g. embedded inside the merchant's
  // own portal). We persist the session_id per-customer so the same person
  // re-opening the widget — even on a different device, after clearing
  // cookies, or weeks later — picks up exactly where they left off instead
  // of starting an empty thread.
  function detectSallaCustomer() {
    try {
      var s = window.salla;
      if (s && s.config && typeof s.config.get === "function") {
        var c = s.config.get("user.id") || s.config.get("customer.id");
        if (c) sallaCustomerId = String(c);
        var n = s.config.get("user.name") || s.config.get("customer.name");
        if (n) sallaCustomerName = String(n);
      }
      if (s && s.customer) {
        if (!sallaCustomerId && s.customer.id) {
          sallaCustomerId = String(s.customer.id);
        }
        if (!sallaCustomerName) {
          if (s.customer.name) sallaCustomerName = String(s.customer.name);
          else if (s.customer.first_name) {
            sallaCustomerName = String(s.customer.first_name)
              + (s.customer.last_name ? " " + s.customer.last_name : "");
          }
        }
      }
    } catch (e) { /* SDK not ready yet — try again on next chat */ }

    // Widget config override (when the merchant embeds outside Salla but has
    // their own auth and wants the same threading behaviour).
    if (!sallaCustomerId && CONFIG.customerId)    sallaCustomerId   = String(CONFIG.customerId);
    if (!sallaCustomerName && CONFIG.customerName) sallaCustomerName = String(CONFIG.customerName);
  }

  function sessionStorageKey() {
    // One key per (store, customer). Anonymous visitors get their own
    // single per-store thread keyed by storeId only.
    var who = sallaCustomerId ? ("c" + sallaCustomerId) : "anon";
    return "salla-chat-session::" + CONFIG.storeId + "::" + who;
  }

  function loadPersistedSession() {
    try {
      var s = localStorage.getItem(sessionStorageKey());
      if (s) sessionId = s;
    } catch (e) {}
  }
  function savePersistedSession() {
    try {
      if (sessionId) localStorage.setItem(sessionStorageKey(), sessionId);
    } catch (e) {}
  }

  // ── Styles ────────────────────────────────────────────────────────────────────
  var _side = CONFIG.position === "right" ? "right" : "left";
  var styles = `
    /* ── Isolation: prevent Shopify/3rd-party theme CSS from leaking in ── */
    #salla-chat-widget, #salla-chat-widget * {
      box-sizing: border-box !important;
      font-family: 'Segoe UI', Tahoma, Arial, sans-serif !important;
    }
    /* ─────────────────────────────────────────────────────────── */
    #salla-chat-btn {
      position: fixed !important; bottom: 24px !important; ${_side}: 24px !important; z-index: 9999 !important;
      width: 60px !important; height: 60px !important; border-radius: 50% !important;
      background: ${CONFIG.primaryColor} !important; border: none !important; cursor: pointer !important;
      box-shadow: 0 4px 20px rgba(26,86,219,0.4) !important;
      display: flex !important; align-items: center !important; justify-content: center !important;
      transition: transform 0.2s, box-shadow 0.2s !important;
      padding: 0 !important; margin: 0 !important; text-decoration: none !important;
    }
    #salla-chat-btn:hover { transform: scale(1.1) !important; box-shadow: 0 6px 28px rgba(26,86,219,0.5) !important; }
    #salla-chat-btn svg { width: 28px !important; height: 28px !important; fill: white !important; display: block !important; }
    #salla-chat-badge {
      position: absolute !important; top: -4px !important; right: -4px !important;
      background: #ef4444 !important; color: white !important; border-radius: 50% !important;
      width: 20px !important; height: 20px !important; font-size: 11px !important; font-weight: 700 !important;
      display: none !important; align-items: center !important; justify-content: center !important;
      line-height: 1 !important; padding: 0 !important; margin: 0 !important;
    }
    #salla-chat-badge.show { display: flex !important; }
    #salla-chat-panel {
      position: fixed !important; bottom: 96px !important; ${_side}: 24px !important; z-index: 9998 !important;
      width: 370px !important; height: 560px !important; border-radius: 16px !important;
      background: #fff !important; box-shadow: 0 10px 50px rgba(0,0,0,0.18) !important;
      display: flex !important; flex-direction: column !important; overflow: hidden !important;
      transform: scale(0.9) translateY(20px) !important; opacity: 0 !important;
      transition: transform 0.25s, opacity 0.25s !important; pointer-events: none !important;
      direction: rtl !important; margin: 0 !important; padding: 0 !important;
    }
    #salla-chat-panel.open {
      transform: scale(1) translateY(0) !important; opacity: 1 !important; pointer-events: all !important;
    }
    #salla-chat-header {
      background: ${CONFIG.primaryColor} !important; color: white !important; padding: 14px 16px !important;
      display: flex !important; align-items: center !important; gap: 10px !important; flex-shrink: 0 !important;
    }
    #salla-chat-header .avatar {
      width: 38px !important; height: 38px !important; border-radius: 50% !important;
      background: rgba(255,255,255,0.25) !important;
      display: flex !important; align-items: center !important; justify-content: center !important;
      font-size: 18px !important; flex-shrink: 0 !important;
    }
    #salla-chat-header .info { flex: 1 !important; overflow: hidden !important; }
    #salla-chat-header .info .name { font-weight: 700 !important; font-size: 15px !important; display: block !important; white-space: nowrap !important; overflow: hidden !important; text-overflow: ellipsis !important; }
    #salla-chat-header .info .status {
      font-size: 12px !important; opacity: 0.85 !important; display: flex !important; align-items: center !important; gap: 4px !important;
    }
    #salla-chat-header .info .status::before {
      content: '' !important; width: 7px !important; height: 7px !important; border-radius: 50% !important; display: inline-block !important;
      background: #4ade80 !important; flex-shrink: 0 !important;
    }
    #salla-chat-header .info .status.human::before { background: #fb923c !important; }
    #salla-chat-close {
      background: none !important; border: none !important; color: white !important;
      cursor: pointer !important; opacity: 0.8 !important; font-size: 22px !important;
      line-height: 1 !important; padding: 2px !important; flex-shrink: 0 !important;
    }
    #salla-chat-close:hover { opacity: 1 !important; }
    #salla-chat-messages {
      flex: 1 !important; overflow-y: auto !important; padding: 16px !important;
      display: flex !important; flex-direction: column !important; gap: 10px !important;
      background: #f8fafc !important; margin: 0 !important;
    }
    #salla-chat-messages::-webkit-scrollbar { width: 4px !important; }
    #salla-chat-messages::-webkit-scrollbar-track { background: transparent !important; }
    #salla-chat-messages::-webkit-scrollbar-thumb { background: #cbd5e1 !important; border-radius: 4px !important; }
    /* ── Message bubbles — scoped to prevent theme interference ── */
    #salla-chat-messages .chat-msg {
      display: flex !important; gap: 8px !important; max-width: 88% !important;
      margin: 0 !important; padding: 0 !important; list-style: none !important;
    }
    #salla-chat-messages .chat-msg.user { align-self: flex-start !important; flex-direction: row-reverse !important; }
    #salla-chat-messages .chat-msg.bot  { align-self: flex-end !important; }
    #salla-chat-messages .chat-msg.admin { align-self: flex-end !important; flex-direction: column !important; align-items: flex-end !important; }
    #salla-chat-messages .chat-msg.system-note { align-self: center !important; }
    #salla-chat-messages .chat-msg .bubble {
      display: block !important;
      padding: 10px 13px !important; border-radius: 14px !important;
      font-size: 14px !important; line-height: 1.55 !important;
      white-space: pre-wrap !important; word-break: break-word !important;
      overflow-wrap: break-word !important; margin: 0 !important;
    }
    #salla-chat-messages .chat-msg.user  .bubble {
      background: ${CONFIG.primaryColor} !important; color: white !important; border-bottom-right-radius: 4px !important;
    }
    #salla-chat-messages .chat-msg.bot   .bubble {
      background: white !important; color: #1e293b !important; border-bottom-left-radius: 4px !important;
      box-shadow: 0 1px 4px rgba(0,0,0,0.08) !important;
    }
    #salla-chat-messages .chat-msg.admin .bubble {
      background: #fff7ed !important; color: #92400e !important; border: 1px solid #fed7aa !important;
      border-bottom-left-radius: 4px !important; box-shadow: 0 1px 4px rgba(0,0,0,0.06) !important;
    }
    #salla-chat-messages .chat-msg.admin .agent-caption {
      font-size: 10.5px !important; font-weight: 700 !important; color: #92400e !important;
      margin: 0 4px 2px !important; opacity: 0.85 !important; text-align: right !important; display: block !important;
    }
    #salla-chat-messages .chat-msg.system-note .bubble {
      background: #f0fdf4 !important; color: #166534 !important; border: 1px solid #bbf7d0 !important;
      border-radius: 20px !important; font-size: 12px !important; padding: 6px 14px !important; text-align: center !important;
    }
    #salla-chat-messages .chat-typing {
      display: flex !important; gap: 4px !important; padding: 10px 14px !important;
      background: white !important; border-radius: 14px !important; border-bottom-left-radius: 4px !important;
      box-shadow: 0 1px 4px rgba(0,0,0,0.08) !important; align-self: flex-end !important;
    }
    #salla-chat-messages .chat-typing span {
      width: 7px !important; height: 7px !important; background: #94a3b8 !important;
      border-radius: 50% !important; display: inline-block !important;
      animation: salla-bounce 1.2s infinite !important;
    }
    #salla-chat-messages .chat-typing span:nth-child(2) { animation-delay: 0.2s !important; }
    #salla-chat-messages .chat-typing span:nth-child(3) { animation-delay: 0.4s !important; }
    @keyframes salla-bounce { 0%,60%,100% { transform: translateY(0); } 30% { transform: translateY(-6px); } }
    /* ── Human support banner ────────────────────────────────── */
    #salla-human-banner {
      background: #fff7ed !important; border-top: 2px solid #fb923c !important;
      padding: 8px 14px !important; font-size: 12px !important; color: #92400e !important;
      display: none !important; align-items: center !important; gap: 6px !important; flex-shrink: 0 !important;
    }
    #salla-human-banner.visible { display: flex !important; }
    #salla-human-banner .dot {
      width: 8px !important; height: 8px !important; border-radius: 50% !important;
      background: #fb923c !important; flex-shrink: 0 !important; display: inline-block !important;
      animation: salla-pulse-dot 1.5s infinite !important;
    }
    @keyframes salla-pulse-dot { 0%,100% { opacity:1; } 50% { opacity:0.4; } }
    /* ── Footer ──────────────────────────────────────────────── */
    #salla-chat-footer {
      padding: 10px 12px !important; border-top: 1px solid #e2e8f0 !important;
      background: white !important; flex-shrink: 0 !important;
    }
    #salla-chat-upload-bar {
      display: none !important; gap: 6px !important; margin-bottom: 8px !important;
    }
    #salla-chat-upload-bar.visible { display: flex !important; }
    #salla-chat-widget .upload-btn {
      flex: 1 !important; padding: 7px 10px !important; border: 1.5px dashed #cbd5e1 !important;
      border-radius: 8px !important; background: #f8fafc !important; color: #64748b !important;
      font-size: 13px !important; cursor: pointer !important; text-align: center !important;
      display: flex !important; align-items: center !important; justify-content: center !important; gap: 6px !important;
    }
    #salla-chat-widget .upload-btn:hover { border-color: ${CONFIG.primaryColor} !important; color: ${CONFIG.primaryColor} !important; }
    #salla-file-input { display: none !important; }
    #salla-chat-input-row {
      display: flex !important; gap: 8px !important; align-items: flex-end !important;
    }
    #salla-chat-input {
      flex: 1 !important; resize: none !important; border: 1.5px solid #e2e8f0 !important;
      border-radius: 10px !important; padding: 9px 13px !important; font-size: 14px !important;
      color: #1e293b !important; outline: none !important; line-height: 1.4 !important;
      max-height: 100px !important; overflow-y: auto !important; direction: rtl !important;
      background: white !important;
    }
    #salla-chat-input:focus { border-color: ${CONFIG.primaryColor} !important; }
    #salla-chat-input::placeholder { color: #94a3b8 !important; }
    #salla-chat-send {
      width: 40px !important; height: 40px !important; border-radius: 10px !important;
      background: ${CONFIG.primaryColor} !important; border: none !important; cursor: pointer !important;
      display: flex !important; align-items: center !important; justify-content: center !important;
      flex-shrink: 0 !important; padding: 0 !important;
    }
    #salla-chat-send:hover { opacity: 0.9 !important; }
    #salla-chat-send:disabled { opacity: 0.5 !important; cursor: not-allowed !important; }
    #salla-chat-send svg { width: 18px !important; height: 18px !important; fill: white !important; transform: rotate(180deg) !important; display: block !important; }
    #salla-chat-widget .chat-attach-btn {
      width: 40px !important; height: 40px !important; border-radius: 10px !important;
      background: #f1f5f9 !important; border: none !important; cursor: pointer !important;
      display: flex !important; align-items: center !important; justify-content: center !important;
      flex-shrink: 0 !important; padding: 0 !important;
    }
    #salla-chat-widget .chat-attach-btn:hover { background: #e2e8f0 !important; }
    #salla-chat-widget .chat-attach-btn svg { width: 20px !important; height: 20px !important; fill: #64748b !important; display: block !important; }
    #salla-chat-widget .file-preview {
      background: #f0f9ff !important; border: 1px solid #bae6fd !important; border-radius: 8px !important;
      padding: 8px 12px !important; display: flex !important; align-items: center !important;
      gap: 8px !important; font-size: 13px !important; color: #0369a1 !important; margin-bottom: 8px !important;
    }
    #salla-chat-widget .file-preview .remove {
      margin-right: auto !important; cursor: pointer !important; color: #94a3b8 !important; font-size: 16px !important;
    }
    #salla-chat-widget .file-preview .remove:hover { color: #ef4444 !important; }
    @media (max-width: 420px) {
      #salla-chat-panel { width: calc(100vw - 16px) !important; ${_side}: 8px !important; bottom: 80px !important; height: 70vh !important; }
    }
    /* ── Quick action buttons ────────────────────────────────── */
    #salla-chat-messages .quick-actions-row { align-self: stretch !important; max-width: 100% !important; }
    #salla-chat-messages .quick-actions-title {
      font-size: 11px !important; color: #94a3b8 !important; text-align: center !important;
      margin: 4px 0 6px !important; font-weight: 600 !important; display: block !important;
    }
    #salla-chat-messages .quick-actions-grid {
      display: grid !important; grid-template-columns: 1fr 1fr !important; gap: 8px !important;
    }
    #salla-chat-messages .qa-btn {
      display: flex !important; flex-direction: column !important; align-items: center !important;
      gap: 4px !important; justify-content: center !important; padding: 12px 6px !important;
      border-radius: 12px !important; cursor: pointer !important; font-size: 12px !important;
      font-weight: 700 !important; border: 1.5px solid !important;
      text-align: center !important; line-height: 1.2 !important;
    }
    #salla-chat-messages .qa-btn:hover { transform: translateY(-2px) !important; box-shadow: 0 4px 14px rgba(0,0,0,0.10) !important; }
    #salla-chat-messages .qa-btn:active { transform: translateY(0) !important; }
    #salla-chat-messages .qa-btn .qa-icon { font-size: 20px !important; line-height: 1 !important; }
    #salla-chat-messages .qa-blue   { color: #1e40af !important; border-color: #bfdbfe !important; background: #eff6ff !important; }
    #salla-chat-messages .qa-blue:hover   { border-color: #3b82f6 !important; background: #dbeafe !important; }
    #salla-chat-messages .qa-green  { color: #166534 !important; border-color: #bbf7d0 !important; background: #f0fdf4 !important; }
    #salla-chat-messages .qa-green:hover  { border-color: #22c55e !important; background: #dcfce7 !important; }
    #salla-chat-messages .qa-purple { color: #6b21a8 !important; border-color: #e9d5ff !important; background: #faf5ff !important; }
    #salla-chat-messages .qa-purple:hover { border-color: #a855f7 !important; background: #f3e8ff !important; }
    #salla-chat-messages .qa-amber  { color: #92400e !important; border-color: #fde68a !important; background: #fffbeb !important; }
    #salla-chat-messages .qa-amber:hover  { border-color: #f59e0b !important; background: #fef3c7 !important; }
    /* ── Cart badge on header ─────────────────────────────────── */
    #salla-cart-badge {
      background: #ef4444 !important; color: white !important; border-radius: 20px !important;
      font-size: 11px !important; font-weight: 700 !important; padding: 1px 7px !important;
      margin-right: auto !important; display: none !important;
    }
    #salla-cart-badge.visible { display: inline-block !important; }
    /* ── Product cards component ──────────────────────────────── */
    #salla-chat-messages .chat-component { width: 100% !important; margin-top: 4px !important; }
    #salla-chat-messages .product-cards-wrap {
      display: flex !important; gap: 8px !important; overflow-x: auto !important; padding-bottom: 4px !important;
      scrollbar-width: thin; scrollbar-color: #cbd5e1 transparent;
    }
    #salla-chat-messages .product-cards-wrap::-webkit-scrollbar { height: 4px !important; }
    #salla-chat-messages .product-cards-wrap::-webkit-scrollbar-thumb { background: #cbd5e1 !important; border-radius: 4px !important; }
    #salla-chat-messages .product-card {
      flex: 0 0 140px !important; background: white !important; border-radius: 12px !important;
      box-shadow: 0 2px 10px rgba(0,0,0,0.1) !important; overflow: hidden !important;
      display: flex !important; flex-direction: column !important;
    }
    #salla-chat-messages .product-card:hover { box-shadow: 0 4px 18px rgba(0,0,0,0.15) !important; }
    #salla-chat-messages .product-card img {
      width: 100% !important; height: 100px !important; object-fit: cover !important; background: #f1f5f9 !important; display: block !important;
    }
    #salla-chat-messages .product-card .card-body {
      padding: 8px 10px !important; flex: 1 !important; display: flex !important; flex-direction: column !important; gap: 4px !important;
    }
    #salla-chat-messages .product-card .card-name { font-size: 12px !important; font-weight: 600 !important; color: #1e293b !important; line-height: 1.3 !important; }
    #salla-chat-messages .product-card .card-price { font-size: 12px !important; color: ${CONFIG.primaryColor} !important; font-weight: 700 !important; }
    #salla-chat-messages .product-card .card-price del { color: #94a3b8 !important; font-weight: 400 !important; margin-left: 4px !important; font-size: 11px !important; }
    #salla-chat-messages .product-card .card-unavail { font-size: 11px !important; color: #ef4444 !important; }
    #salla-chat-messages .product-card .card-add {
      margin-top: auto !important; width: 100% !important; padding: 6px 0 !important;
      background: ${CONFIG.primaryColor} !important; color: white !important; border: none !important;
      border-radius: 8px !important; font-size: 12px !important; font-weight: 600 !important; cursor: pointer !important;
    }
    #salla-chat-messages .product-card .card-add:hover { opacity: 0.88 !important; }
    #salla-chat-messages .product-card .card-add:disabled { background: #cbd5e1 !important; cursor: not-allowed !important; }
    /* ── Cart component ───────────────────────────────────────── */
    #salla-chat-messages .cart-component {
      background: white !important; border-radius: 12px !important;
      box-shadow: 0 2px 10px rgba(0,0,0,0.09) !important;
      padding: 12px 14px !important; display: flex !important; flex-direction: column !important;
      gap: 8px !important; width: 100% !important;
    }
    #salla-chat-messages .cart-component .cart-title { font-size: 13px !important; font-weight: 700 !important; color: #1e293b !important; }
    #salla-chat-messages .cart-item {
      display: flex !important; align-items: center !important; gap: 8px !important; font-size: 12px !important; color: #475569 !important;
    }
    #salla-chat-messages .cart-item img { width: 36px !important; height: 36px !important; border-radius: 6px !important; object-fit: cover !important; flex-shrink: 0 !important; }
    #salla-chat-messages .cart-item .ci-name { flex: 1 !important; font-weight: 500 !important; color: #1e293b !important; }
    #salla-chat-messages .cart-item .ci-qty { color: #64748b !important; }
    #salla-chat-messages .cart-item .ci-sub { font-weight: 600 !important; color: ${CONFIG.primaryColor} !important; }
    #salla-chat-messages .cart-total {
      display: flex !important; justify-content: space-between !important; border-top: 1px solid #e2e8f0 !important;
      padding-top: 8px !important; font-size: 13px !important; font-weight: 700 !important; color: #1e293b !important;
    }
    #salla-chat-messages .cart-checkout-btn {
      width: 100% !important; padding: 9px 0 !important; background: #16a34a !important; color: white !important;
      border: none !important; border-radius: 10px !important; font-size: 13px !important; font-weight: 700 !important; cursor: pointer !important;
    }
    #salla-chat-messages .cart-checkout-btn:hover { opacity: 0.88 !important; }
    /* ── Checkout component ───────────────────────────────────── */
    #salla-chat-messages .checkout-component {
      background: linear-gradient(135deg, #f0fdf4, #dcfce7) !important; border: 1px solid #86efac !important;
      border-radius: 12px !important; padding: 14px 16px !important; display: flex !important;
      flex-direction: column !important; gap: 8px !important; width: 100% !important;
    }
    #salla-chat-messages .checkout-component .co-title { font-size: 13px !important; font-weight: 700 !important; color: #166534 !important; }
    #salla-chat-messages .checkout-component .co-ref { font-size: 12px !important; color: #166534 !important; }
    #salla-chat-messages .checkout-component .co-total { font-size: 14px !important; font-weight: 700 !important; color: #15803d !important; }
    #salla-chat-messages .checkout-pay-btn {
      width: 100% !important; padding: 10px 0 !important; background: #16a34a !important; color: white !important;
      border: none !important; border-radius: 10px !important; font-size: 14px !important; font-weight: 700 !important;
      cursor: pointer !important; text-decoration: none !important; display: block !important; text-align: center !important;
    }
    #salla-chat-messages .checkout-pay-btn:hover { opacity: 0.88 !important; }
    /* ── Checkout fallback ────────────────────────────────────── */
    #salla-chat-messages .checkout-fallback {
      background: #fff7ed !important; border: 1px solid #fed7aa !important; border-radius: 12px !important;
      padding: 12px 14px !important; display: flex !important; flex-direction: column !important; gap: 6px !important; width: 100% !important;
    }
    #salla-chat-messages .checkout-fallback .cf-title { font-size: 13px !important; font-weight: 700 !important; color: #92400e !important; }
    #salla-chat-messages .checkout-fallback a { color: ${CONFIG.primaryColor} !important; font-size: 12px !important; }
    /* ── CSAT survey card ────────────────────────────────────── */
    #salla-chat-messages .csat-card {
      background: white !important; border: 1px solid #99f6e4 !important; border-radius: 14px !important;
      padding: 12px 14px !important; display: flex !important; flex-direction: column !important;
      gap: 10px !important; width: 100% !important; box-shadow: 0 2px 10px rgba(13,148,136,0.08) !important;
    }
    #salla-chat-messages .csat-card .csat-title { font-size: 12px !important; font-weight: 700 !important; color: #0f766e !important; text-align: center !important; }
    #salla-chat-messages .csat-options { display: grid !important; grid-template-columns: 1fr 1fr !important; gap: 6px !important; }
    #salla-chat-messages .csat-options.cols-3 { grid-template-columns: 1fr 1fr 1fr !important; }
    #salla-chat-messages .csat-btn {
      padding: 8px 6px !important; border-radius: 10px !important; cursor: pointer !important;
      font-size: 12px !important; font-weight: 700 !important;
      border: 1.5px solid #99f6e4 !important; background: #f0fdfa !important; color: #0f766e !important;
    }
    #salla-chat-messages .csat-btn:hover { background: #ccfbf1 !important; border-color: #2dd4bf !important; transform: translateY(-1px) !important; }
    #salla-chat-messages .csat-btn.picked { background: #14b8a6 !important; color: white !important; border-color: #14b8a6 !important; }
    #salla-chat-messages .csat-thanks { font-size: 12px !important; font-weight: 700 !important; color: #0f766e !important; text-align: center !important; padding: 6px 0 !important; }
    /* ── Rating bar ──────────────────────────────────────────── */
    #salla-rating-bar {
      padding: 10px 16px 8px !important; text-align: center !important;
      border-top: 1px solid #e8efff !important; background: #f5f8ff !important; flex-shrink: 0 !important;
      animation: salla-ratingSlide .3s ease !important;
    }
    @keyframes salla-ratingSlide { from { opacity:0; transform:translateY(5px); } to { opacity:1; transform:translateY(0); } }
    #salla-rating-bar .r-label { font-size: 12px !important; color: #64748b !important; margin-bottom: 6px !important; display: block !important; }
    #salla-rating-bar .r-stars { display: flex !important; gap: 4px !important; justify-content: center !important; }
    #salla-rating-bar .r-stars button {
      background: none !important; border: none !important; font-size: 24px !important;
      cursor: pointer !important; padding: 2px 3px !important; opacity: .25 !important;
      line-height: 1 !important;
    }
    #salla-rating-bar .r-stars button:hover,
    #salla-rating-bar .r-stars button.lit { opacity: 1 !important; transform: scale(1.18) !important; }
    #salla-rating-bar .r-thanks {
      font-size: 13px !important; color: #16a34a !important; font-weight: 600 !important;
      padding: 4px 0 2px !important; animation: salla-ratingSlide .3s ease !important;
    }
    /* ── Order status component ───────────────────────────────── */
    #salla-chat-messages .order-status-card {
      background: white !important; border-radius: 12px !important;
      box-shadow: 0 2px 10px rgba(0,0,0,0.09) !important;
      padding: 12px 14px !important; display: flex !important; flex-direction: column !important;
      gap: 8px !important; width: 100% !important;
    }
    #salla-chat-messages .order-status-card .os-header { display: flex !important; justify-content: space-between !important; align-items: center !important; }
    #salla-chat-messages .order-status-card .os-ref { font-weight: 700 !important; font-size: 13px !important; color: #1e293b !important; }
    #salla-chat-messages .order-status-card .os-badge {
      background: #eff6ff !important; color: #1d4ed8 !important; border-radius: 20px !important;
      font-size: 11px !important; font-weight: 700 !important; padding: 3px 9px !important;
    }
    #salla-chat-messages .order-status-card .os-row { font-size: 12px !important; color: #64748b !important; display: flex !important; gap: 6px !important; }
    #salla-chat-messages .order-status-card .os-row strong { color: #1e293b !important; }
    #salla-chat-messages .order-status-card .os-track {
      display: block !important; text-align: center !important; padding: 7px 0 !important;
      background: ${CONFIG.primaryColor} !important; color: white !important; border-radius: 8px !important;
      font-size: 12px !important; font-weight: 700 !important; text-decoration: none !important; margin-top: 4px !important;
    }
    #salla-chat-messages .order-status-card .os-track:hover { opacity: .88 !important; }
  `;

  // ── DOM Builder ───────────────────────────────────────────────────────────────
  function buildWidget() {
    var styleEl = document.createElement("style");
    styleEl.textContent = styles;
    document.head.appendChild(styleEl);

    var wrapper = document.createElement("div");
    wrapper.id = "salla-chat-widget";

    wrapper.innerHTML = `
      <button id="salla-chat-btn" aria-label="فتح المحادثة">
        <div id="salla-chat-badge">1</div>
        <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
          <path d="M20 2H4a2 2 0 00-2 2v18l4-4h14a2 2 0 002-2V4a2 2 0 00-2-2zm-2 11H6v-2h12v2zm0-3H6V8h12v2z"/>
        </svg>
      </button>
      <div id="salla-chat-panel" role="dialog" aria-label="نافذة المحادثة">
        <div id="salla-chat-header">
          <div class="avatar">🖨️</div>
          <div class="info">
            <div class="name">${CONFIG.storeName}</div>
            <div class="status" id="salla-status-text">متاح الآن</div>
          </div>
          <span id="salla-cart-badge" title="السلة">🛒 <span id="salla-cart-count">0</span></span>
          <button id="salla-chat-close" aria-label="إغلاق">✕</button>
        </div>
        <div id="salla-human-banner">
          <div class="dot"></div>
          <span>جارٍ التواصل مع فريق الدعم... سيرد عليك أحد المتخصصين قريباً</span>
        </div>
        <div id="salla-chat-messages"></div>
        <div id="salla-rating-bar" style="display:none"></div>
        <div id="salla-chat-footer">
          <div id="salla-file-preview" style="display:none"></div>
          <div id="salla-chat-input-row">
            <button class="chat-attach-btn" id="salla-attach-btn" title="إرفاق ملف تصميم">
              <svg viewBox="0 0 24 24"><path d="M16.5 6v11.5a4 4 0 01-8 0V5a2.5 2.5 0 015 0v10.5a1 1 0 01-2 0V6H10v9.5a2.5 2.5 0 005 0V5a4 4 0 00-8 0v12.5a5.5 5.5 0 0011 0V6h-1.5z"/></svg>
            </button>
            <textarea id="salla-chat-input" rows="1" placeholder="${CONFIG.placeholder}" dir="rtl"></textarea>
            <button id="salla-chat-send" disabled aria-label="إرسال">
              <svg viewBox="0 0 24 24"><path d="M2 21l21-9L2 3v7l15 2-15 2v7z"/></svg>
            </button>
          </div>
          <input type="file" id="salla-file-input"
            accept=".pdf,.ai,.eps,.psd,.png,.jpg,.jpeg,.svg,.tiff,.tif,.cdr,.zip">
        </div>
      </div>
    `;

    document.body.appendChild(wrapper);
  }

  // ── Message Rendering ─────────────────────────────────────────────────────────
  function appendMessage(role, text, extra) {
    extra = extra || {};
    var container = document.getElementById("salla-chat-messages");

    // CSAT survey is rendered as a special bubble instead of plain text.
    if (extra.meta && extra.meta.kind === "csat") {
      renderCsat(extra.meta);
      return;
    }

    var msg = document.createElement("div");
    msg.className = "chat-msg " + role;

    // For admin messages, render a small caption above the bubble showing
    // which employee replied — matches the "Shurog" caption in the Kiabi
    // screenshot the user referenced.
    if (role === "admin" && extra.employee_name) {
      var cap = document.createElement("div");
      cap.className = "agent-caption";
      cap.textContent = extra.employee_name;
      msg.appendChild(cap);
    }

    var bubble = document.createElement("div");
    bubble.className = "bubble";
    // Basic markdown bold support + XSS protection
    bubble.innerHTML = String(text || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>");
    msg.appendChild(bubble);
    container.appendChild(msg);
    container.scrollTop = container.scrollHeight;
    return msg;
  }

  // ── CSAT survey (post-conversation rating prompt) ─────────────────────────────
  function renderCsat(meta) {
    var container = document.getElementById("salla-chat-messages");
    var wrap = document.createElement("div");
    wrap.className = "chat-msg bot";
    var card = document.createElement("div");
    card.className = "csat-card";

    var title = document.createElement("div");
    title.className = "csat-title";
    title.textContent = meta.question || "كيف كانت تجربتك معنا؟";
    card.appendChild(title);

    var opts = (meta.options && meta.options.length) ? meta.options : [
      { value: 5, label: "راضٍ تماماً" },
      { value: 4, label: "راضٍ" },
      { value: 3, label: "محايد" },
      { value: 2, label: "غير راضٍ" },
      { value: 1, label: "غير راضٍ تماماً" },
    ];

    var grid = document.createElement("div");
    grid.className = "csat-options" + (opts.length === 3 ? " cols-3" : "");
    opts.forEach(function (opt) {
      var b = document.createElement("button");
      b.className = "csat-btn";
      b.type = "button";
      b.setAttribute("data-v", String(opt.value));
      b.textContent = opt.label;
      b.addEventListener("click", function () {
        // Disable all buttons + highlight the picked one
        grid.querySelectorAll("button").forEach(function (el) {
          el.disabled = true;
          if (el === b) el.classList.add("picked");
        });
        submitCsat(opt.value, meta);
        setTimeout(function () {
          card.innerHTML = '<div class="csat-thanks">شكراً لتقييمك 🌷</div>';
        }, 600);
      });
      grid.appendChild(b);
    });
    card.appendChild(grid);
    wrap.appendChild(card);
    container.appendChild(wrap);
    container.scrollTop = container.scrollHeight;
  }

  async function submitCsat(value, meta) {
    try {
      await fetch(CONFIG.apiUrl + "/chat/rate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sessionId,
          store_id:   CONFIG.storeId,
          rating:     value,
          comment:    meta && meta.target_agent_name
                       ? ("CSAT: " + meta.target_agent_name)
                       : "CSAT",
        }),
      });
    } catch (e) { /* non-critical */ }
  }

  function showTyping() {
    var container = document.getElementById("salla-chat-messages");
    var el = document.createElement("div");
    el.className = "chat-typing";
    el.id = "typing-indicator";
    el.innerHTML = "<span></span><span></span><span></span>";
    container.appendChild(el);
    container.scrollTop = container.scrollHeight;
  }

  function hideTyping() {
    var el = document.getElementById("typing-indicator");
    if (el) el.remove();
  }

  // ── Quick action buttons (shown after welcome message) ───────────────────────
  var QUICK_ACTIONS = [
    { msg: "أريد طلب منتج جديد، ساعدني في اختيار الأنسب لي", icon: "🛍️", label: "طلب جديد",       color: "blue"   },
    { msg: "أحتاج عرض سعر للطباعة",                          icon: "💰", label: "عرض سعر",        color: "green"  },
    { msg: "أريد تتبع طلبي السابق",                          icon: "📦", label: "تتبع طلب",       color: "purple" },
    { msg: "أحتاج التحدث مع موظف دعم بشري من فضلك",          icon: "👨‍💼", label: "التواصل مع الدعم", color: "amber"  },
  ];

  function appendQuickActions() {
    if (document.getElementById("quick-actions")) return;
    var container = document.getElementById("salla-chat-messages");
    var wrap = document.createElement("div");
    wrap.className = "chat-msg quick-actions-row";
    wrap.id = "quick-actions";

    var html = '<div class="quick-actions-title">كيف أقدر أساعدك؟</div>' +
               '<div class="quick-actions-grid">';
    for (var i = 0; i < QUICK_ACTIONS.length; i++) {
      var a = QUICK_ACTIONS[i];
      html += '<button class="qa-btn qa-' + a.color + '" data-idx="' + i + '">' +
                '<span class="qa-icon">' + a.icon + '</span>' +
                '<span>' + a.label + '</span>' +
              '</button>';
    }
    html += '</div>';
    wrap.innerHTML = html;
    container.appendChild(wrap);
    container.scrollTop = container.scrollHeight;

    wrap.querySelectorAll(".qa-btn").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var idx = parseInt(btn.getAttribute("data-idx"), 10);
        var action = QUICK_ACTIONS[idx];
        if (action) {
          removeQuickActions();
          sendMessage(action.msg);
        }
      });
    });
  }

  function removeQuickActions() {
    var el = document.getElementById("quick-actions");
    if (el) el.remove();
  }

  // ── Cart badge ────────────────────────────────────────────────────────────────
  function updateCartBadge(count) {
    var badge = document.getElementById("salla-cart-badge");
    var countEl = document.getElementById("salla-cart-count");
    if (!badge || !countEl) return;
    if (count > 0) {
      countEl.textContent = count;
      badge.classList.add("visible");
    } else {
      badge.classList.remove("visible");
    }
  }

  // ── Rich Component Renderer ───────────────────────────────────────────────────
  function renderComponent(component) {
    if (!component || !component.type) return;
    var container = document.getElementById("salla-chat-messages");
    var wrap = document.createElement("div");
    wrap.className = "chat-component";

    if (component.type === "product_cards") {
      var cardsHtml = '<div class="product-cards-wrap">';
      (component.products || []).forEach(function (p) {
        var imgTag = p.image
          ? '<img src="' + escapeAttr(p.image) + '" alt="' + escapeAttr(p.name) + '" onerror="this.style.display=\'none\'">'
          : '<div style="width:100%;height:100px;background:#f1f5f9;display:flex;align-items:center;justify-content:center;font-size:28px">🖨️</div>';
        var priceHtml = p.sale_price && p.sale_price !== p.price && p.sale_price !== ""
          ? '<del>' + esc(p.price) + '</del> ' + esc(p.sale_price) + ' ' + esc(p.currency)
          : esc(p.price) + ' ' + esc(p.currency);
        var availHtml = p.available ? '' : '<div class="card-unavail">⛔ نفد المخزون</div>';
        cardsHtml += (
          '<div class="product-card">' +
            imgTag +
            '<div class="card-body">' +
              '<div class="card-name">' + esc(p.name) + '</div>' +
              '<div class="card-price">' + priceHtml + '</div>' +
              availHtml +
              '<button class="card-add" data-id="' + escapeAttr(p.id) + '" data-name="' + escapeAttr(p.name) + '"' +
                (p.available ? '' : ' disabled') + '>أضف للسلة</button>' +
            '</div>' +
          '</div>'
        );
      });
      cardsHtml += '</div>';
      wrap.innerHTML = cardsHtml;

      // Wire "أضف للسلة" buttons
      wrap.querySelectorAll(".card-add").forEach(function (btn) {
        btn.addEventListener("click", function () {
          if (isLoading) return;
          // Keep ID as a string to avoid precision loss for large Salla IDs
          // (JS parseInt caps at Number.MAX_SAFE_INTEGER ≈ 9×10¹⁵, but still
          //  better to let Salla's SDK handle the type conversion itself).
          var pidStr = btn.getAttribute("data-id") || "";
          var pid    = parseInt(pidStr, 10);
          // If parsing failed or lost precision, fall back to the original string
          var safeId = (!isNaN(pid) && String(pid) === pidStr) ? pid : pidStr;
          var name = btn.getAttribute("data-name");
          var qty  = parseInt(btn.getAttribute("data-qty") || "1", 10);
          if (isNaN(qty) || qty < 1) qty = 1;

          if (sallaReady()) {
            // ── Use Salla native cart ──────────────────────────────────────────
            btn.disabled = true;
            btn.textContent = "جارٍ الإضافة…";
            window.salla.cart.addItem({ id: safeId, quantity: qty })
              .then(function (response) {
                btn.textContent = "✅ تمت الإضافة";
                // Sync cart badge from Salla response
                var count = (response && response.data && response.data.count) ||
                            (response && response.count) || 0;
                if (count) updateCartBadge(count);
                // Notify the AI so it can confirm and suggest more
                sendMessage("أضفت " + name + " للسلة ✅");
              })
              .catch(function (err) {
                btn.disabled = false;
                btn.textContent = "أضف للسلة";
                var errMsg = (err && (err.message || err.error || err)) || "خطأ غير معروف";
                sendMessage("حاولت أضيف " + name + " بس واجهت مشكلة: " + errMsg);
              });
          } else {
            // ── Fallback: let the AI agent handle cart via backend ─────────────
            sendMessage("أضف " + esc(name) + " للسلة");
          }
        });
      });

    } else if (component.type === "cart") {
      var items = component.items || [];
      var currency = component.currency || "SAR";
      var itemsHtml = items.map(function (item) {
        var sub = (parseFloat(item.price || 0) * parseInt(item.quantity || 1, 10)).toFixed(2);
        var imgTag = item.image
          ? '<img src="' + escapeAttr(item.image) + '" alt="" onerror="this.style.display=\'none\'">'
          : '<div style="width:36px;height:36px;background:#f1f5f9;border-radius:6px;display:flex;align-items:center;justify-content:center;font-size:16px;flex-shrink:0">📦</div>';
        return (
          '<div class="cart-item">' +
            imgTag +
            '<span class="ci-name">' + esc(item.name) + '</span>' +
            '<span class="ci-qty">×' + item.quantity + '</span>' +
            '<span class="ci-sub">' + sub + ' ' + esc(currency) + '</span>' +
          '</div>'
        );
      }).join("");
      wrap.innerHTML = (
        '<div class="cart-component">' +
          '<div class="cart-title">🛒 سلة التسوق (' + items.length + ' منتج)</div>' +
          itemsHtml +
          '<div class="cart-total"><span>الإجمالي</span><span>' + esc(component.total) + ' ' + esc(currency) + '</span></div>' +
          '<button class="cart-checkout-btn">إتمام الطلب ←</button>' +
        '</div>'
      );
      wrap.querySelector(".cart-checkout-btn").addEventListener("click", function () {
        if (sallaReady()) {
          // On Salla storefront — go straight to checkout
          try {
            if (typeof window.salla.cart.checkout === "function") {
              window.salla.cart.checkout();
            } else {
              window.location.href = "/checkout";
            }
          } catch (e) {
            window.location.href = "/checkout";
          }
        } else {
          sendMessage("أريد إتمام الطلب");
        }
      });

    } else if (component.type === "checkout") {
      wrap.innerHTML = (
        '<div class="checkout-component">' +
          '<div class="co-title">✅ تم إنشاء طلبك بنجاح!</div>' +
          (component.order_ref ? '<div class="co-ref">رقم الطلب: #' + esc(component.order_ref) + '</div>' : '') +
          '<div class="co-total">الإجمالي: ' + esc(component.total) + ' ' + esc(component.currency || "SAR") + '</div>' +
          '<a href="' + escapeAttr(component.url) + '" target="_blank" rel="noopener" class="checkout-pay-btn">💳 ادفع الآن</a>' +
        '</div>'
      );

    } else if (component.type === "checkout_fallback") {
      var linksHtml = (component.items || [])
        .filter(function (i) { return i.url; })
        .map(function (i) {
          return '<a href="' + escapeAttr(i.url) + '" target="_blank" rel="noopener">• ' + esc(i.name) + '</a>';
        }).join("<br>");
      wrap.innerHTML = (
        '<div class="checkout-fallback">' +
          '<div class="cf-title">🛒 أتمم طلبك عبر الروابط التالية:</div>' +
          '<div style="display:flex;flex-direction:column;gap:4px">' + linksHtml + '</div>' +
        '</div>'
      );
    } else if (component.type === "order_status") {
      var os = component;
      var trackBtn = os.tracking_url
        ? '<a href="' + escapeAttr(os.tracking_url) + '" target="_blank" class="os-track">🚚 تتبع الشحنة</a>'
        : '';
      var itemsHtml2 = (os.items || []).slice(0, 3).map(function(it) {
        return '<div class="os-row">• ' + esc(it.name) + ' × ' + (it.qty||1) + '</div>';
      }).join('');
      wrap.innerHTML = (
        '<div class="order-status-card">' +
          '<div class="os-header">' +
            '<div class="os-ref">طلب #' + esc(os.order_ref || os.order_id) + '</div>' +
            '<div class="os-badge">' + esc(os.status_emoji||'📦') + ' ' + esc(os.status) + '</div>' +
          '</div>' +
          '<div class="os-row">📅 <strong>' + esc(os.date||'') + '</strong></div>' +
          '<div class="os-row">💰 <strong>' + esc(os.total||'') + ' ' + esc(os.currency||'SAR') + '</strong></div>' +
          (os.shipping_company ? '<div class="os-row">🚚 <strong>' + esc(os.shipping_company) + '</strong></div>' : '') +
          (os.tracking_number  ? '<div class="os-row">🔢 رقم التتبع: <strong style="direction:ltr;display:inline-block">' + esc(os.tracking_number) + '</strong></div>' : '') +
          itemsHtml2 +
          trackBtn +
        '</div>'
      );

    } else {
      return; // unknown component — skip
    }

    container.appendChild(wrap);
    container.scrollTop = container.scrollHeight;
  }

  // XSS helpers
  function esc(str) {
    return String(str || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }
  function escapeAttr(str) {
    return String(str || "").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  // ── Rating ───────────────────────────────────────────────────────────────────
  function showRatingBar() {
    if (_ratingShown) return;
    _ratingShown = true;
    var bar = document.getElementById("salla-rating-bar");
    if (!bar) return;
    bar.style.display = "block";
    bar.innerHTML =
      '<div class="r-label">كيف كانت تجربتك مع المساعد؟</div>' +
      '<div class="r-stars" id="r-stars-wrap">' +
        [1,2,3,4,5].map(function(v){
          return '<button data-v="'+v+'" title="'+v+' نجوم" aria-label="'+v+' نجوم">⭐</button>';
        }).join('') +
      '</div>';

    // Light-up hover effect: highlight all stars up to hovered one
    var starsWrap = document.getElementById("r-stars-wrap");
    var btns = starsWrap.querySelectorAll("button");
    btns.forEach(function(btn, idx) {
      btn.addEventListener("mouseenter", function() {
        btns.forEach(function(b, i) { b.style.opacity = i <= idx ? "1" : "0.25"; });
      });
      btn.addEventListener("mouseleave", function() {
        btns.forEach(function(b) { b.style.opacity = ""; });
      });
      btn.addEventListener("click", function() {
        submitRating(parseInt(btn.getAttribute("data-v"), 10));
      });
    });
  }

  async function submitRating(value) {
    var bar = document.getElementById("salla-rating-bar");
    if (bar) {
      bar.innerHTML = '<div class="r-thanks">شكراً لتقييمك ' + "⭐".repeat(value) + ' 😊</div>';
      setTimeout(function() { bar.style.display = "none"; }, 3000);
    }
    try {
      await fetch(CONFIG.apiUrl + "/chat/rate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, store_id: CONFIG.storeId, rating: value }),
      });
    } catch(e) { /* non-critical */ }
  }

  // ── Human Takeover UI ─────────────────────────────────────────────────────────
  function setHumanMode(enabled) {
    var banner = document.getElementById("salla-human-banner");
    var statusEl = document.getElementById("salla-status-text");

    if (enabled) {
      // Bot disabled — human took over
      if (!humanBannerShown) {
        humanBannerShown = true;
        appendMessage("system-note", "👨‍💼 تم تحويل المحادثة إلى فريق الدعم");
      }
      if (banner) banner.classList.add("visible");
      if (statusEl) {
        statusEl.textContent = "فريق الدعم";
        statusEl.className = "status human";
      }
      // Realtime stays open across bot/human transitions — keep this
      // for backwards-compat (a stale poll loop is harmless if SSE is
      // also running; both feed appendAdminLike).
      startRealtime();
    } else {
      // Bot re-enabled — SSE still useful (CSAT survey, future bot msgs).
      humanBannerShown = false;
      if (banner) banner.classList.remove("visible");
      if (statusEl) {
        statusEl.textContent = "متاح الآن";
        statusEl.className = "status";
      }
      // Don't close the SSE — we still want to receive bot follow-ups
      // (CSAT survey, end-of-chat farewell) that the server pushes.
    }
  }

  function applyBotState(newBotEnabled) {
    if (botEnabled === newBotEnabled) return; // no change
    botEnabled = newBotEnabled;
    setHumanMode(!botEnabled);
  }

  // ── Realtime stream (replaces polling in Phase 3) ────────────────────────────
  // Uses SSE (EventSource) so admin replies + bot-toggle updates land in
  // < 100ms instead of waiting for the next 3-second poll tick. Polling
  // is kept as a fallback: if the browser blocks SSE (corporate proxy
  // stripping text/event-stream, ancient runtime), we silently revert.
  var streamConn = null;
  var streamReconnectTimer = null;
  var streamBackoff = 1000;            // ms — doubles up to 30s on each failure
  var STREAM_BACKOFF_MAX = 30000;

  function startRealtime() {
    if (!sessionId) return;
    // Already connected — no-op.
    if (streamConn && streamConn.readyState !== 2 /*CLOSED*/) return;
    // No EventSource support → fall back to polling.
    if (typeof EventSource === "undefined") {
      startPolling();
      return;
    }
    try {
      var url = CONFIG.apiUrl + "/chat/stream?session_id="
              + encodeURIComponent(sessionId);
      streamConn = new EventSource(url);

      // 'connected' fires immediately on a successful handshake — reset
      // the backoff so a clean reconnect doesn't burn budget.
      streamConn.addEventListener("connected", function () {
        streamBackoff = 1000;
        // Successful SSE means polling is redundant. Stop it in case a
        // previous fallback was running.
        stopPolling();
      });

      // admin_message — admin replied. role 'admin' includes employee replies.
      streamConn.addEventListener("admin_message", function (e) {
        try {
          var payload = JSON.parse(e.data);
          // Server sends a 'preview' (≤200 chars) in the NOTIFY payload to
          // stay under the 8KB Postgres limit. For the widget the preview IS
          // the full message in 99% of cases — but if it was truncated, we
          // re-fetch the full thread on next user send.
          appendAdminLike(payload);
        } catch (err) { /* malformed event — ignore */ }
      });

      // bot_toggle — admin took over (or handed back) this session.
      streamConn.addEventListener("bot_toggle", function (e) {
        try {
          var payload = JSON.parse(e.data);
          if (payload.bot_enabled && !botEnabled) {
            botEnabled = true;
            setHumanMode(false);
            appendMessage("system-note", "✅ تم إعادة توصيلك بالمساعد الذكي");
          } else if (!payload.bot_enabled && botEnabled) {
            botEnabled = false;
            setHumanMode(true);
          }
        } catch (err) { /* ignore */ }
      });

      // shutdown — server is restarting. The browser EventSource will
      // auto-reconnect; we just acknowledge to avoid confusion.
      streamConn.addEventListener("shutdown", function () {
        try { streamConn.close(); } catch (e) {}
      });

      // onerror fires both when the connection drops AND on permanent
      // failures. EventSource auto-reconnects on transient errors with
      // its own ~3s default; we layer our own exponential backoff for
      // the bad-network case where the browser keeps retrying instantly.
      //
      // Critical fallback: also kick off polling. If the server returns
      // 503 because realtime is unavailable (DATABASE_URL unset, listener
      // failed to start, etc.), every reconnect attempt also returns 503
      // — without polling as a safety net, admin replies + CSAT never
      // reach the customer. stopPolling() in the 'connected' handler
      // automatically tears it down if SSE later succeeds.
      streamConn.onerror = function () {
        if (streamConn && streamConn.readyState === 2 /*CLOSED*/) {
          startPolling();
          scheduleStreamReconnect();
        }
      };
    } catch (err) {
      // SSE constructor threw (very rare) → fall back to polling.
      startPolling();
    }
  }

  function scheduleStreamReconnect() {
    if (streamReconnectTimer) return;
    streamReconnectTimer = setTimeout(function () {
      streamReconnectTimer = null;
      streamBackoff = Math.min(streamBackoff * 2, STREAM_BACKOFF_MAX);
      startRealtime();
    }, streamBackoff);
  }

  function stopRealtime() {
    if (streamConn) {
      try { streamConn.close(); } catch (e) {}
      streamConn = null;
    }
    if (streamReconnectTimer) {
      clearTimeout(streamReconnectTimer);
      streamReconnectTimer = null;
    }
  }

  // Render an admin/bot follow-up message (extracted so both the SSE
  // handler and the legacy poll handler share one rendering path).
  function appendAdminLike(m) {
    var content = m.content || m.preview || "";
    if (!content) return;
    var role = m.role === "bot" ? "bot" : "admin";
    appendMessage(role, content, {
      employee_name: m.employee_name,
      meta:          m.meta,
    });
    if (!isOpen) {
      var badge = document.getElementById("salla-chat-badge");
      if (badge) badge.classList.add("show");
    }
  }

  // ── Polling (FALLBACK — kept for clients that can't open SSE) ───────────────
  function startPolling() {
    if (pollTimer) return; // already running
    pollTimer = setInterval(pollAdmin, 3000);
  }

  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  // ── Restore previous conversation on load ─────────────────────────────────────
  // When a returning visitor has a persisted session_id, fetch the server-side
  // transcript and re-render it so they continue exactly where they left off
  // after a page refresh or leaving and coming back. Returns count rendered.
  async function loadHistory() {
    if (historyLoaded || !sessionId) return 0;
    historyLoaded = true;
    try {
      var res = await fetch(
        CONFIG.apiUrl + "/chat/history?session_id=" + encodeURIComponent(sessionId)
      );
      if (!res.ok) return 0;
      var data = await res.json();
      var msgs = (data && data.messages) || [];
      if (!msgs.length) return 0;

      var container = document.getElementById("salla-chat-messages");
      if (container) container.innerHTML = "";   // clear stray welcome/quick-actions
      msgs.forEach(function (m) {
        var role = m.role === "user" ? "user"
                 : m.role === "admin" || m.employee_name ? "admin"
                 : "bot";
        appendMessage(role, m.content || "", {
          employee_name: m.employee_name,
          meta:          m.meta,
        });
      });

      // Sync bot/human mode so the input + banner match the live state.
      if (typeof data.bot_enabled !== "undefined" && !data.bot_enabled) {
        botEnabled = false;
        setHumanMode(true);
      }
      // Returning visitor with an active thread → open the live channel.
      startRealtime();
      return msgs.length;
    } catch (e) {
      return 0;
    }
  }

  async function pollAdmin() {
    if (!sessionId) return;
    try {
      var res = await fetch(CONFIG.apiUrl + "/chat/poll?session_id=" + encodeURIComponent(sessionId) + "&store_id=" + encodeURIComponent(CONFIG.storeId));
      if (!res.ok) return;
      var data = await res.json();

      // Render any admin / bot follow-up messages queued for the widget.
      // After the agent ends the conversation, the server also queues the
      // bot's thank-you line and the CSAT survey here so the widget shows
      // the full farewell flow without needing a page refresh.
      if (data.messages && data.messages.length > 0) {
        data.messages.forEach(function (m) {
          var role = m.role === "bot" ? "bot" : "admin";
          appendMessage(role, m.content || "", {
            employee_name: m.employee_name,
            meta:          m.meta,
          });
        });
        // Flash badge on chat button if panel is closed
        if (!isOpen) {
          var badge = document.getElementById("salla-chat-badge");
          if (badge) badge.classList.add("show");
        }
      }

      // Check if bot was re-enabled by admin
      if (data.bot_enabled && !botEnabled) {
        botEnabled = true;
        setHumanMode(false);
        appendMessage("system-note", "✅ تم إعادة توصيلك بالمساعد الذكي");
      }
    } catch (e) {
      // Silently ignore polling errors — non-critical
    }
  }

  // ── API ───────────────────────────────────────────────────────────────────────
  async function sendMessage(message) {
    if (isLoading) return;
    isLoading = true;
    document.getElementById("salla-chat-send").disabled = true;

    // Hide quick-action buttons once the user starts chatting
    removeQuickActions();

    appendMessage("user", message);

    // Only show typing animation when bot is handling the conversation
    if (botEnabled) showTyping();

    // Re-detect the logged-in Salla customer — the storefront SDK may have
    // finished loading after init(). Sending the customer_id lets the backend
    // fetch their profile (name, phone, order history) so the bot greets them
    // by name and personalises the conversation.
    detectSallaCustomer();

    try {
      var res = await fetch(CONFIG.apiUrl + "/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message:       message,
          session_id:    sessionId,
          store_id:      CONFIG.storeId,
          customer_id:   sallaCustomerId   || "",
          customer_name: sallaCustomerName || "",
        }),
      });
      var data = await res.json();
      hideTyping();

      if (!res.ok) {
        // Try to show server's Arabic message if available, otherwise generic
        var errMsg = "عذراً، حدث خطأ مؤقت. حاول مرة أخرى.";
        try {
          var errData = await res.clone().json();
          if (errData && errData.detail) errMsg = errData.detail;
        } catch(ignored) {}
        appendMessage("bot", errMsg);
      } else {
        if (data.session_id) { sessionId = data.session_id; savePersistedSession(); }

        // Check bot_enabled flag from response
        if (typeof data.bot_enabled !== "undefined") {
          if (!data.bot_enabled && botEnabled) {
            // Bot just got disabled — human takeover
            botEnabled = false;
            setHumanMode(true);
          } else if (data.bot_enabled && !botEnabled) {
            botEnabled = true;
            setHumanMode(false);
          }
        }

        // Always show the reply (either bot reply or "support team notified" message)
        appendMessage(botEnabled ? "bot" : "system-note", data.reply || "عذراً، لم أفهم طلبك. حاول مرة أخرى.");

        // Count bot replies and maybe show rating bar (after 2nd reply, bot-only)
        if (botEnabled) {
          _botReplyCount++;
          if (_botReplyCount >= 2 && !_ratingShown) {
            setTimeout(showRatingBar, 800);
          }
        }

        // Render rich components (product cards, cart, checkout…)
        if (data.components && data.components.length > 0) {
          data.components.forEach(function (comp) { renderComponent(comp); });
        }

        // Update cart badge in header
        if (typeof data.cart_count !== "undefined") {
          updateCartBadge(data.cart_count);
        }
      }
    } catch (e) {
      hideTyping();
      appendMessage("bot", "⚠️ تعذر الاتصال بالخادم. تأكد من اتصالك بالإنترنت وحاول مرة أخرى.");
    }

    isLoading = false;
    var sendBtn = document.getElementById("salla-chat-send");
    var inputEl = document.getElementById("salla-chat-input");
    sendBtn.disabled = inputEl.value.trim() === "";
  }

  async function uploadFile(file) {
    if (!file) return;
    if (file.size > CONFIG.maxFileSizeMB * 1024 * 1024) {
      appendMessage("bot", `⚠️ حجم الملف كبير جداً. الحد الأقصى ${CONFIG.maxFileSizeMB} MB`);
      return;
    }

    appendMessage("user", `📎 إرفاق ملف: ${file.name}`);
    showTyping();

    var formData = new FormData();
    formData.append("file", file);
    formData.append("session_id", sessionId || "");
    formData.append("store_id", CONFIG.storeId);

    try {
      var res = await fetch(CONFIG.apiUrl + "/upload", {
        method: "POST",
        body: formData,
      });
      var data = await res.json();
      hideTyping();
      appendMessage("bot", data.message || "تم رفع الملف.");
    } catch (e) {
      hideTyping();
      appendMessage("bot", "⚠️ فشل رفع الملف. حاول مرة أخرى.");
    }

    // Clear preview
    document.getElementById("salla-file-preview").style.display = "none";
    document.getElementById("salla-file-input").value = "";
  }

  // ── Init ──────────────────────────────────────────────────────────────────────
  function init() {
    buildWidget();

    // Identify the visitor (Salla customer if logged in) and resume their
    // persisted session_id from localStorage so a refresh / return continues
    // the same conversation instead of starting a fresh empty thread.
    detectSallaCustomer();
    loadPersistedSession();

    var btn = document.getElementById("salla-chat-btn");
    var panel = document.getElementById("salla-chat-panel");
    var closeBtn = document.getElementById("salla-chat-close");
    var input = document.getElementById("salla-chat-input");
    var sendBtn = document.getElementById("salla-chat-send");
    var attachBtn = document.getElementById("salla-attach-btn");
    var fileInput = document.getElementById("salla-file-input");
    var filePreview = document.getElementById("salla-file-preview");
    var badge = document.getElementById("salla-chat-badge");
    var cartBadge = document.getElementById("salla-cart-badge");

    // Show badge on load
    badge.classList.add("show");

    // Toggle panel
    btn.addEventListener("click", async function () {
      isOpen = !isOpen;
      panel.classList.toggle("open", isOpen);
      badge.classList.remove("show");
      if (isOpen) {
        var msgsEl = document.getElementById("salla-chat-messages");
        // Resume a returning visitor's previous conversation first.
        if (!historyLoaded && sessionId) {
          await loadHistory();
        }
        // Only greet when there's no prior conversation to restore.
        if (msgsEl.children.length === 0) {
          appendMessage("bot", CONFIG.welcomeMessage);
          appendQuickActions();
        }
        input.focus();
      }
    });

    closeBtn.addEventListener("click", function () {
      isOpen = false;
      panel.classList.remove("open");
    });

    // Input handling
    input.addEventListener("input", function () {
      sendBtn.disabled = input.value.trim() === "";
      // Auto resize
      input.style.height = "auto";
      input.style.height = Math.min(input.scrollHeight, 100) + "px";
    });

    input.addEventListener("keydown", function (e) {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        var text = input.value.trim();
        if (text) {
          input.value = "";
          input.style.height = "auto";
          sendBtn.disabled = true;
          sendMessage(text);
        }
      }
    });

    sendBtn.addEventListener("click", function () {
      var text = input.value.trim();
      if (text) {
        input.value = "";
        input.style.height = "auto";
        sendBtn.disabled = true;
        sendMessage(text);
      }
    });

    // Cart badge click → show cart
    if (cartBadge) {
      cartBadge.addEventListener("click", function () {
        sendMessage("اعرض سلة التسوق");
      });
    }

    // File upload
    attachBtn.addEventListener("click", function () {
      fileInput.click();
    });

    fileInput.addEventListener("change", function () {
      var file = fileInput.files[0];
      if (!file) return;
      // Show preview bar
      filePreview.style.display = "flex";
      filePreview.innerHTML =
        `<span>📎</span><span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${file.name}</span>` +
        `<span class="remove" id="remove-file">✕</span>`;
      document.getElementById("remove-file").addEventListener("click", function () {
        filePreview.style.display = "none";
        fileInput.value = "";
      });
      uploadFile(file);
    });

    // ── Salla Storefront cart event listeners ──────────────────────────────────
    // Keeps our cart badge in sync whenever items are added/removed from the
    // native Salla cart (even outside the chatbot, e.g. via the store's own UI).
    _bindSallaCartEvents();
  }

  function _bindSallaCartEvents() {
    if (!sallaReady()) return;
    var onAdd = function (response) {
      var count = (response && response.data && response.data.count) ||
                  (response && response.count) || 0;
      if (count) updateCartBadge(count);
    };
    var onRemove = function (response) {
      var count = (response && response.data && response.data.count) ||
                  (response && response.count) || 0;
      updateCartBadge(count); // may go to 0
    };

    // Pattern 1: salla.event.on — standard Salla Storefront SDK
    if (window.salla.event && typeof window.salla.event.on === "function") {
      try {
        window.salla.event.on("cart::add",    onAdd);
        window.salla.event.on("cart::remove", onRemove);
        window.salla.event.on("cart::update", onAdd);
      } catch (e) { /* ignore — non-critical */ }
    }
    // Pattern 2: salla.cart.event.onItemAdded — alternate SDK surface
    else if (window.salla.cart.event) {
      try {
        if (typeof window.salla.cart.event.onItemAdded  === "function") window.salla.cart.event.onItemAdded(onAdd);
        if (typeof window.salla.cart.event.onItemRemoved === "function") window.salla.cart.event.onItemRemoved(onRemove);
      } catch (e) { /* ignore */ }
    }
  }

  // Wait for DOM
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
