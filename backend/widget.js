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
    #salla-chat-widget * { box-sizing: border-box; font-family: 'Segoe UI', Tahoma, Arial, sans-serif; }
    #salla-chat-btn {
      position: fixed; bottom: 24px; ${_side}: 24px; z-index: 9999;
      width: 60px; height: 60px; border-radius: 50%;
      background: ${CONFIG.primaryColor}; border: none; cursor: pointer;
      box-shadow: 0 4px 20px rgba(26,86,219,0.4);
      display: flex; align-items: center; justify-content: center;
      transition: transform 0.2s, box-shadow 0.2s;
    }
    #salla-chat-btn:hover { transform: scale(1.1); box-shadow: 0 6px 28px rgba(26,86,219,0.5); }
    #salla-chat-btn svg { width: 28px; height: 28px; fill: white; }
    #salla-chat-badge {
      position: absolute; top: -4px; right: -4px;
      background: #ef4444; color: white; border-radius: 50%;
      width: 20px; height: 20px; font-size: 11px; font-weight: 700;
      display: flex; align-items: center; justify-content: center;
      display: none;
    }
    #salla-chat-panel {
      position: fixed; bottom: 96px; ${_side}: 24px; z-index: 9998;
      width: 370px; height: 560px; border-radius: 16px;
      background: #fff; box-shadow: 0 10px 50px rgba(0,0,0,0.18);
      display: flex; flex-direction: column; overflow: hidden;
      transform: scale(0.9) translateY(20px); opacity: 0;
      transition: transform 0.25s, opacity 0.25s; pointer-events: none;
      direction: rtl;
    }
    #salla-chat-panel.open {
      transform: scale(1) translateY(0); opacity: 1; pointer-events: all;
    }
    #salla-chat-header {
      background: ${CONFIG.primaryColor}; color: white; padding: 14px 16px;
      display: flex; align-items: center; gap: 10px; flex-shrink: 0;
    }
    #salla-chat-header .avatar {
      width: 38px; height: 38px; border-radius: 50%; background: rgba(255,255,255,0.25);
      display: flex; align-items: center; justify-content: center; font-size: 18px;
    }
    #salla-chat-header .info { flex: 1; }
    #salla-chat-header .info .name { font-weight: 700; font-size: 15px; }
    #salla-chat-header .info .status {
      font-size: 12px; opacity: 0.85; display: flex; align-items: center; gap: 4px;
    }
    #salla-chat-header .info .status::before {
      content: ''; width: 7px; height: 7px; border-radius: 50%; display: inline-block;
      background: #4ade80;
    }
    #salla-chat-header .info .status.human::before { background: #fb923c; }
    #salla-chat-close { background: none; border: none; color: white; cursor: pointer; opacity: 0.8; font-size: 22px; line-height: 1; padding: 2px; }
    #salla-chat-close:hover { opacity: 1; }
    #salla-chat-messages {
      flex: 1; overflow-y: auto; padding: 16px; display: flex; flex-direction: column; gap: 10px;
      background: #f8fafc;
    }
    #salla-chat-messages::-webkit-scrollbar { width: 4px; }
    #salla-chat-messages::-webkit-scrollbar-track { background: transparent; }
    #salla-chat-messages::-webkit-scrollbar-thumb { background: #cbd5e1; border-radius: 4px; }
    .chat-msg { display: flex; gap: 8px; max-width: 88%; }
    .chat-msg.user { align-self: flex-start; flex-direction: row-reverse; }
    .chat-msg.bot  { align-self: flex-end; }
    .chat-msg.admin { align-self: flex-end; }
    .chat-msg .bubble {
      padding: 10px 13px; border-radius: 14px; font-size: 14px; line-height: 1.55;
      white-space: pre-wrap; word-break: break-word;
    }
    .chat-msg.user  .bubble { background: ${CONFIG.primaryColor}; color: white; border-bottom-right-radius: 4px; }
    .chat-msg.bot   .bubble { background: white; color: #1e293b; border-bottom-left-radius: 4px; box-shadow: 0 1px 4px rgba(0,0,0,0.08); }
    .chat-msg.admin .bubble { background: #fff7ed; color: #92400e; border: 1px solid #fed7aa; border-bottom-left-radius: 4px; box-shadow: 0 1px 4px rgba(0,0,0,0.06); }
    .chat-msg.admin .bubble::before { content: '👨‍💼 '; }
    .chat-msg.system-note { align-self: center; }
    .chat-msg.system-note .bubble {
      background: #f0fdf4; color: #166534; border: 1px solid #bbf7d0;
      border-radius: 20px; font-size: 12px; padding: 6px 14px; text-align: center;
    }
    .chat-typing { display: flex; gap: 4px; padding: 10px 14px; background: white; border-radius: 14px; border-bottom-left-radius: 4px; box-shadow: 0 1px 4px rgba(0,0,0,0.08); align-self: flex-end; }
    .chat-typing span { width: 7px; height: 7px; background: #94a3b8; border-radius: 50%; animation: bounce 1.2s infinite; }
    .chat-typing span:nth-child(2) { animation-delay: 0.2s; }
    .chat-typing span:nth-child(3) { animation-delay: 0.4s; }
    @keyframes bounce { 0%,60%,100% { transform: translateY(0); } 30% { transform: translateY(-6px); } }
    /* Human support banner */
    #salla-human-banner {
      background: #fff7ed; border-top: 2px solid #fb923c;
      padding: 8px 14px; font-size: 12px; color: #92400e;
      display: flex; align-items: center; gap: 6px; flex-shrink: 0;
      display: none;
    }
    #salla-human-banner.visible { display: flex; }
    #salla-human-banner .dot { width: 8px; height: 8px; border-radius: 50%; background: #fb923c; flex-shrink: 0; animation: pulse-dot 1.5s infinite; }
    @keyframes pulse-dot { 0%,100% { opacity:1; } 50% { opacity:0.4; } }
    #salla-chat-footer {
      padding: 10px 12px; border-top: 1px solid #e2e8f0; background: white; flex-shrink: 0;
    }
    #salla-chat-upload-bar {
      display: flex; gap: 6px; margin-bottom: 8px; display: none;
    }
    #salla-chat-upload-bar.visible { display: flex; }
    .upload-btn {
      flex: 1; padding: 7px 10px; border: 1.5px dashed #cbd5e1; border-radius: 8px;
      background: #f8fafc; color: #64748b; font-size: 13px; cursor: pointer;
      text-align: center; transition: border-color 0.15s, color 0.15s;
      display: flex; align-items: center; justify-content: center; gap: 6px;
    }
    .upload-btn:hover { border-color: ${CONFIG.primaryColor}; color: ${CONFIG.primaryColor}; }
    #salla-file-input { display: none; }
    #salla-chat-input-row { display: flex; gap: 8px; align-items: flex-end; }
    #salla-chat-input {
      flex: 1; resize: none; border: 1.5px solid #e2e8f0; border-radius: 10px;
      padding: 9px 13px; font-size: 14px; color: #1e293b; outline: none;
      font-family: inherit; line-height: 1.4; max-height: 100px; overflow-y: auto;
      direction: rtl;
      transition: border-color 0.15s;
    }
    #salla-chat-input:focus { border-color: ${CONFIG.primaryColor}; }
    #salla-chat-input::placeholder { color: #94a3b8; }
    #salla-chat-send {
      width: 40px; height: 40px; border-radius: 10px; background: ${CONFIG.primaryColor};
      border: none; cursor: pointer; display: flex; align-items: center; justify-content: center;
      flex-shrink: 0; transition: opacity 0.15s;
    }
    #salla-chat-send:hover { opacity: 0.9; }
    #salla-chat-send:disabled { opacity: 0.5; cursor: not-allowed; }
    #salla-chat-send svg { width: 18px; height: 18px; fill: white; transform: rotate(180deg); }
    .chat-attach-btn {
      width: 40px; height: 40px; border-radius: 10px; background: #f1f5f9;
      border: none; cursor: pointer; display: flex; align-items: center; justify-content: center;
      flex-shrink: 0; transition: background 0.15s;
    }
    .chat-attach-btn:hover { background: #e2e8f0; }
    .chat-attach-btn svg { width: 20px; height: 20px; fill: #64748b; }
    .file-preview {
      background: #f0f9ff; border: 1px solid #bae6fd; border-radius: 8px;
      padding: 8px 12px; display: flex; align-items: center; gap: 8px;
      font-size: 13px; color: #0369a1; margin-bottom: 8px;
    }
    .file-preview .remove { margin-right: auto; cursor: pointer; color: #94a3b8; font-size: 16px; }
    .file-preview .remove:hover { color: #ef4444; }
    @media (max-width: 420px) {
      #salla-chat-panel { width: calc(100vw - 16px); ${_side}: 8px; bottom: 80px; height: 70vh; }
    }
    /* ── Quick action buttons ────────────────────────────────── */
    .quick-actions-row { align-self: stretch; max-width: 100%; }
    .quick-actions-title {
      font-size: 11px; color: #94a3b8; text-align: center; margin: 4px 0 6px;
      font-weight: 600;
    }
    .quick-actions-grid {
      display: grid; grid-template-columns: 1fr 1fr; gap: 8px;
    }
    .qa-btn {
      display: flex; flex-direction: column; align-items: center; gap: 4px; justify-content: center;
      padding: 12px 6px; border-radius: 12px; cursor: pointer;
      font-size: 12px; font-weight: 700; font-family: inherit;
      border: 1.5px solid; transition: transform 0.15s, box-shadow 0.15s, border-color 0.15s;
      text-align: center; line-height: 1.2;
    }
    .qa-btn:hover { transform: translateY(-2px); box-shadow: 0 4px 14px rgba(0,0,0,0.10); }
    .qa-btn:active { transform: translateY(0); }
    .qa-btn .qa-icon { font-size: 20px; line-height: 1; }
    .qa-blue   { color: #1e40af; border-color: #bfdbfe; background: #eff6ff; }
    .qa-blue:hover   { border-color: #3b82f6; background: #dbeafe; }
    .qa-green  { color: #166534; border-color: #bbf7d0; background: #f0fdf4; }
    .qa-green:hover  { border-color: #22c55e; background: #dcfce7; }
    .qa-purple { color: #6b21a8; border-color: #e9d5ff; background: #faf5ff; }
    .qa-purple:hover { border-color: #a855f7; background: #f3e8ff; }
    .qa-amber  { color: #92400e; border-color: #fde68a; background: #fffbeb; }
    .qa-amber:hover  { border-color: #f59e0b; background: #fef3c7; }
    /* ── Cart badge on header ─────────────────────────────────── */
    #salla-cart-badge {
      background: #ef4444; color: white; border-radius: 20px;
      font-size: 11px; font-weight: 700; padding: 1px 7px; margin-right: auto;
      display: none;
    }
    #salla-cart-badge.visible { display: inline-block; }
    /* ── Product cards component ──────────────────────────────── */
    .chat-component { width: 100%; margin-top: 4px; }
    .product-cards-wrap {
      display: flex; gap: 8px; overflow-x: auto; padding-bottom: 4px;
      scrollbar-width: thin; scrollbar-color: #cbd5e1 transparent;
    }
    .product-cards-wrap::-webkit-scrollbar { height: 4px; }
    .product-cards-wrap::-webkit-scrollbar-thumb { background: #cbd5e1; border-radius: 4px; }
    .product-card {
      flex: 0 0 140px; background: white; border-radius: 12px;
      box-shadow: 0 2px 10px rgba(0,0,0,0.1); overflow: hidden;
      display: flex; flex-direction: column; transition: box-shadow 0.2s;
    }
    .product-card:hover { box-shadow: 0 4px 18px rgba(0,0,0,0.15); }
    .product-card img {
      width: 100%; height: 100px; object-fit: cover; background: #f1f5f9;
    }
    .product-card .card-body { padding: 8px 10px; flex: 1; display: flex; flex-direction: column; gap: 4px; }
    .product-card .card-name { font-size: 12px; font-weight: 600; color: #1e293b; line-height: 1.3; }
    .product-card .card-price { font-size: 12px; color: ${CONFIG.primaryColor}; font-weight: 700; }
    .product-card .card-price del { color: #94a3b8; font-weight: 400; margin-left: 4px; font-size: 11px; }
    .product-card .card-unavail { font-size: 11px; color: #ef4444; }
    .product-card .card-add {
      margin-top: auto; width: 100%; padding: 6px 0; background: ${CONFIG.primaryColor};
      color: white; border: none; border-radius: 8px; font-size: 12px; font-weight: 600;
      cursor: pointer; transition: opacity 0.15s;
    }
    .product-card .card-add:hover { opacity: 0.88; }
    .product-card .card-add:disabled { background: #cbd5e1; cursor: not-allowed; }
    /* ── Cart component ───────────────────────────────────────── */
    .cart-component {
      background: white; border-radius: 12px; box-shadow: 0 2px 10px rgba(0,0,0,0.09);
      padding: 12px 14px; display: flex; flex-direction: column; gap: 8px; width: 100%;
    }
    .cart-component .cart-title { font-size: 13px; font-weight: 700; color: #1e293b; }
    .cart-item {
      display: flex; align-items: center; gap: 8px; font-size: 12px; color: #475569;
    }
    .cart-item img { width: 36px; height: 36px; border-radius: 6px; object-fit: cover; background: #f1f5f9; flex-shrink: 0; }
    .cart-item .ci-name { flex: 1; font-weight: 500; color: #1e293b; }
    .cart-item .ci-qty { color: #64748b; }
    .cart-item .ci-sub { font-weight: 600; color: ${CONFIG.primaryColor}; }
    .cart-total {
      display: flex; justify-content: space-between; border-top: 1px solid #e2e8f0;
      padding-top: 8px; font-size: 13px; font-weight: 700; color: #1e293b;
    }
    .cart-checkout-btn {
      width: 100%; padding: 9px 0; background: #16a34a; color: white;
      border: none; border-radius: 10px; font-size: 13px; font-weight: 700;
      cursor: pointer; transition: opacity 0.15s;
    }
    .cart-checkout-btn:hover { opacity: 0.88; }
    /* ── Checkout component ───────────────────────────────────── */
    .checkout-component {
      background: linear-gradient(135deg, #f0fdf4, #dcfce7); border: 1px solid #86efac;
      border-radius: 12px; padding: 14px 16px; display: flex; flex-direction: column;
      gap: 8px; width: 100%;
    }
    .checkout-component .co-title { font-size: 13px; font-weight: 700; color: #166534; }
    .checkout-component .co-ref { font-size: 12px; color: #166534; }
    .checkout-component .co-total { font-size: 14px; font-weight: 700; color: #15803d; }
    .checkout-pay-btn {
      width: 100%; padding: 10px 0; background: #16a34a; color: white;
      border: none; border-radius: 10px; font-size: 14px; font-weight: 700;
      cursor: pointer; transition: opacity 0.15s; text-decoration: none;
      display: block; text-align: center;
    }
    .checkout-pay-btn:hover { opacity: 0.88; }
    /* ── Checkout fallback component ─────────────────────────── */
    .checkout-fallback {
      background: #fff7ed; border: 1px solid #fed7aa; border-radius: 12px;
      padding: 12px 14px; display: flex; flex-direction: column; gap: 6px; width: 100%;
    }
    .checkout-fallback .cf-title { font-size: 13px; font-weight: 700; color: #92400e; }
    .checkout-fallback a { color: ${CONFIG.primaryColor}; font-size: 12px; }
    /* ── Agent name caption (above admin bubble) ─────────────── */
    .chat-msg.admin { flex-direction: column; align-items: flex-end; }
    .chat-msg.admin .agent-caption {
      font-size: 10.5px; font-weight: 700; color: #92400e;
      margin: 0 4px 2px; opacity: 0.85; text-align: right;
    }
    /* ── CSAT survey card ────────────────────────────────────── */
    .csat-card {
      background: white; border: 1px solid #99f6e4; border-radius: 14px;
      padding: 12px 14px; display: flex; flex-direction: column; gap: 10px;
      width: 100%; box-shadow: 0 2px 10px rgba(13, 148, 136, 0.08);
    }
    .csat-card .csat-title {
      font-size: 12px; font-weight: 700; color: #0f766e; text-align: center;
    }
    .csat-options {
      display: grid; grid-template-columns: 1fr 1fr; gap: 6px;
    }
    .csat-options.cols-3 { grid-template-columns: 1fr 1fr 1fr; }
    .csat-btn {
      padding: 8px 6px; border-radius: 10px; cursor: pointer;
      font-size: 12px; font-weight: 700; font-family: inherit;
      border: 1.5px solid #99f6e4; background: #f0fdfa; color: #0f766e;
      transition: transform 0.12s, background 0.12s, border-color 0.12s;
    }
    .csat-btn:hover { background: #ccfbf1; border-color: #2dd4bf; transform: translateY(-1px); }
    .csat-btn.picked { background: #14b8a6; color: white; border-color: #14b8a6; }
    .csat-thanks {
      font-size: 12px; font-weight: 700; color: #0f766e; text-align: center;
      padding: 6px 0;
    }
    /* ── Rating bar ──────────────────────────────────────────── */
    #salla-rating-bar {
      padding: 10px 16px 8px; text-align: center; border-top: 1px solid #e8efff;
      background: #f5f8ff; flex-shrink: 0;
      animation: ratingSlide .3s ease;
    }
    @keyframes ratingSlide { from { opacity:0; transform:translateY(5px); } to { opacity:1; transform:translateY(0); } }
    #salla-rating-bar .r-label { font-size: 12px; color: #64748b; margin-bottom: 6px; }
    #salla-rating-bar .r-stars { display: flex; gap: 4px; justify-content: center; }
    #salla-rating-bar .r-stars button {
      background: none; border: none; font-size: 24px; cursor: pointer; padding: 2px 3px;
      opacity: .25; transition: opacity .12s, transform .1s; line-height: 1;
    }
    #salla-rating-bar .r-stars button:hover ~ button { opacity: .25; }
    #salla-rating-bar .r-stars:hover button { opacity: .25; }
    #salla-rating-bar .r-stars button:hover,
    #salla-rating-bar .r-stars button.lit { opacity: 1; transform: scale(1.18); }
    #salla-rating-bar .r-stars:hover button:hover,
    #salla-rating-bar .r-stars:hover button:hover ~ button + button { opacity: .25; }
    /* light up all stars up to hovered one */
    #salla-rating-bar .r-stars button:not(:hover) { transition: opacity .08s; }
    #salla-rating-bar .r-thanks {
      font-size: 13px; color: #16a34a; font-weight: 600; padding: 4px 0 2px;
      animation: ratingSlide .3s ease;
    }
    /* ── Order status component ───────────────────────────────── */
    .order-status-card {
      background: white; border-radius: 12px; box-shadow: 0 2px 10px rgba(0,0,0,0.09);
      padding: 12px 14px; display: flex; flex-direction: column; gap: 8px; width: 100%;
    }
    .order-status-card .os-header {
      display: flex; justify-content: space-between; align-items: center;
    }
    .order-status-card .os-ref { font-weight: 700; font-size: 13px; color: #1e293b; }
    .order-status-card .os-badge {
      background: #eff6ff; color: #1d4ed8; border-radius: 20px;
      font-size: 11px; font-weight: 700; padding: 3px 9px;
    }
    .order-status-card .os-row { font-size: 12px; color: #64748b; display: flex; gap: 6px; }
    .order-status-card .os-row strong { color: #1e293b; }
    .order-status-card .os-track {
      display: block; text-align: center; padding: 7px 0;
      background: ${CONFIG.primaryColor}; color: white; border-radius: 8px;
      font-size: 12px; font-weight: 700; text-decoration: none; margin-top: 4px;
    }
    .order-status-card .os-track:hover { opacity: .88; }
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
      startPolling();
    } else {
      // Bot re-enabled
      humanBannerShown = false;
      if (banner) banner.classList.remove("visible");
      if (statusEl) {
        statusEl.textContent = "متاح الآن";
        statusEl.className = "status";
      }
      stopPolling();
    }
  }

  function applyBotState(newBotEnabled) {
    if (botEnabled === newBotEnabled) return; // no change
    botEnabled = newBotEnabled;
    setHumanMode(!botEnabled);
  }

  // ── Polling (admin → widget messages) ────────────────────────────────────────
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
      // Returning visitor with an active thread → keep admin polling alive.
      startPolling();
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
          if (badge) badge.style.display = "flex";
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
    badge.style.display = "flex";

    // Toggle panel
    btn.addEventListener("click", async function () {
      isOpen = !isOpen;
      panel.classList.toggle("open", isOpen);
      badge.style.display = "none";
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
