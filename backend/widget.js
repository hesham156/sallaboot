(function () {
  "use strict";

  // ── Configuration ────────────────────────────────────────────────────────────
  var _defaults = {
    apiUrl: "https://sallaboot-t.up.railway.app",
    primaryColor: "#1a56db",
    storeName: "متجر الطباعة",
    welcomeMessage: "مرحباً! 👋 أنا مساعد متجرنا للطباعة. كيف أقدر أساعدك اليوم؟",
    placeholder: "اكتب سؤالك هنا...",
    maxFileSizeMB: 20,
  };
  // Allow overriding via window.SallaChatConfig
  var CONFIG = Object.assign({}, _defaults, window.SallaChatConfig || {});

  // ── State ─────────────────────────────────────────────────────────────────────
  var sessionId = null;
  var isOpen = false;
  var isLoading = false;
  var botEnabled = true;          // tracks whether AI bot is handling this session
  var pollTimer = null;           // setInterval handle for admin message polling
  var humanBannerShown = false;   // prevent duplicate "human took over" banners

  // ── Styles ────────────────────────────────────────────────────────────────────
  var styles = `
    #salla-chat-widget * { box-sizing: border-box; font-family: 'Segoe UI', Tahoma, Arial, sans-serif; }
    #salla-chat-btn {
      position: fixed; bottom: 24px; left: 24px; z-index: 9999;
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
      position: fixed; bottom: 96px; left: 24px; z-index: 9998;
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
      #salla-chat-panel { width: calc(100vw - 16px); left: 8px; bottom: 80px; height: 70vh; }
    }
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
          <button id="salla-chat-close" aria-label="إغلاق">✕</button>
        </div>
        <div id="salla-human-banner">
          <div class="dot"></div>
          <span>جارٍ التواصل مع فريق الدعم... سيرد عليك أحد المتخصصين قريباً</span>
        </div>
        <div id="salla-chat-messages"></div>
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
  function appendMessage(role, text) {
    var container = document.getElementById("salla-chat-messages");
    var msg = document.createElement("div");
    msg.className = "chat-msg " + role;
    var bubble = document.createElement("div");
    bubble.className = "bubble";
    // Basic markdown bold support + XSS protection
    bubble.innerHTML = text
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>");
    msg.appendChild(bubble);
    container.appendChild(msg);
    container.scrollTop = container.scrollHeight;
    return msg;
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

  async function pollAdmin() {
    if (!sessionId) return;
    try {
      var res = await fetch(CONFIG.apiUrl + "/chat/poll?session_id=" + encodeURIComponent(sessionId));
      if (!res.ok) return;
      var data = await res.json();

      // Render any admin messages
      if (data.messages && data.messages.length > 0) {
        data.messages.forEach(function (m) {
          appendMessage("admin", m.content);
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

    appendMessage("user", message);

    // Only show typing animation when bot is handling the conversation
    if (botEnabled) showTyping();

    try {
      var res = await fetch(CONFIG.apiUrl + "/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: message, session_id: sessionId }),
      });
      var data = await res.json();
      hideTyping();

      if (!res.ok) {
        appendMessage("bot", "عذراً، حدث خطأ مؤقت. حاول مرة أخرى.");
      } else {
        if (data.session_id) sessionId = data.session_id;

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

    var btn = document.getElementById("salla-chat-btn");
    var panel = document.getElementById("salla-chat-panel");
    var closeBtn = document.getElementById("salla-chat-close");
    var input = document.getElementById("salla-chat-input");
    var sendBtn = document.getElementById("salla-chat-send");
    var attachBtn = document.getElementById("salla-attach-btn");
    var fileInput = document.getElementById("salla-file-input");
    var filePreview = document.getElementById("salla-file-preview");
    var badge = document.getElementById("salla-chat-badge");

    // Show badge on load
    badge.style.display = "flex";

    // Toggle panel
    btn.addEventListener("click", function () {
      isOpen = !isOpen;
      panel.classList.toggle("open", isOpen);
      badge.style.display = "none";
      if (isOpen && document.getElementById("salla-chat-messages").children.length === 0) {
        appendMessage("bot", CONFIG.welcomeMessage);
      }
      if (isOpen) input.focus();
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
  }

  // Wait for DOM
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
