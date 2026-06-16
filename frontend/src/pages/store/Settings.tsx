import { useEffect, useRef, useState } from 'react'
import { Button, Switch, Chip, Spinner } from '@heroui/react'
import { api, AIConfig, TokenStatus, NotificationSettings } from '../../api'
import { TextField } from '../../components/ui'

/* ── Icon helper ── */
function Icon({ d, size = 16, className = '' }: { d: string | string[]; size?: number; className?: string }) {
  const paths = Array.isArray(d) ? d : [d]
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round"
      className={className}>
      {paths.map((p, i) => <path key={i} d={p} />)}
    </svg>
  )
}

/* ── Copy row ── */
function CopyRow({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <div className="space-y-1">
      <p className="text-xs font-semibold text-default-400">{label}</p>
      <div className="flex items-center gap-2">
        <code className="flex-1 text-xs bg-content2 border border-divider rounded-lg px-3 py-2 text-foreground truncate font-mono" dir="ltr">{value}</code>
        <button onClick={() => { navigator.clipboard.writeText(value); setCopied(true); setTimeout(() => setCopied(false), 1500) }}
          className="text-xs font-bold text-teal-600 bg-teal-50 border border-teal-200 rounded-lg px-3 py-2 hover:bg-teal-100 whitespace-nowrap">
          {copied ? '✓ تم' : 'نسخ'}
        </button>
      </div>
    </div>
  )
}

/* ── Feedback banner ── */
function Msg({ text }: { text: string }) {
  if (!text) return null
  const ok = text.startsWith('✅')
  return (
    <div className={`rounded-xl px-4 py-2.5 text-sm border flex items-center gap-2 ${
      ok ? 'bg-success/8 border-success/20 text-success' : 'bg-danger/8 border-danger/20 text-danger'
    }`}>
      <span>{ok ? '✓' : '!'}</span>{text}
    </div>
  )
}

/* ─────── Data ─────── */
interface Props { storeId: string }
type ProviderKey = 'groq' | 'anthropic' | 'openai'
type TabKey = 'ai' | 'whatsapp' | 'notifications' | 'security'

const PROVIDERS: { key: ProviderKey; label: string; sub: string; ph: string; accent: string }[] = [
  { key: 'groq',      label: 'Groq',      sub: 'Llama 3.3', ph: 'gsk_...',          accent: 'orange'  },
  { key: 'anthropic', label: 'Anthropic', sub: 'Claude',    ph: 'sk-ant-api03-...', accent: 'violet'  },
  { key: 'openai',    label: 'OpenAI',    sub: 'GPT-4o',    ph: 'sk-proj-...',      accent: 'emerald' },
]
const MODELS: Record<ProviderKey, string[]> = {
  groq:      ['llama-3.3-70b-versatile', 'llama-3.1-70b-versatile', 'mixtral-8x7b-32768'],
  anthropic: ['claude-sonnet-4-6', 'claude-3-5-haiku-20241022', 'claude-opus-4-5'],
  openai:    ['gpt-4o-mini', 'gpt-4o', 'gpt-4-turbo'],
}
const ACCENT: Record<string, { btn: string; ring: string }> = {
  orange:  { btn: 'bg-orange-500/12 border-orange-500/40 text-orange-300',  ring: 'ring-orange-500/30'  },
  violet:  { btn: 'bg-violet-500/12 border-violet-500/40 text-violet-300',  ring: 'ring-violet-500/30'  },
  emerald: { btn: 'bg-emerald-500/12 border-emerald-500/40 text-emerald-300', ring: 'ring-emerald-500/30' },
}

const TABS: { key: TabKey; label: string; icon: string }[] = [
  { key: 'ai',            label: 'الذكاء الاصطناعي', icon: 'M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z' },
  { key: 'whatsapp',      label: 'واتساب',            icon: 'M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z' },
  { key: 'notifications', label: 'الإشعارات',         icon: 'M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9' },
  { key: 'security',      label: 'الأمان',             icon: 'M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z' },
]

/* ═══════════════════════════════════════════════ */
export default function Settings({ storeId }: Props) {
  const [tab, setTab] = useState<TabKey>('ai')

  /* AI */
  const [cfg, setCfg]           = useState<Partial<AIConfig>>({})
  const [provider, setProvider] = useState<ProviderKey>('groq')
  const [apiKey, setApiKey]     = useState('')
  const [model, setModel]       = useState('')
  const [botName, setBotName]   = useState('')
  const [storeType, setStoreType] = useState<'printing' | 'general'>('general')
  const [aiLoading, setAiLoading] = useState(false)
  const [aiSaving, setAiSaving]   = useState(false)
  const [aiMsg, setAiMsg]         = useState('')

  /* coupons (AI-issued discounts) */
  const [couponsEnabled, setCouponsEnabled] = useState(false)
  const [couponMaxPct, setCouponMaxPct]     = useState(15)
  const [couponMaxVal, setCouponMaxVal]     = useState(200)
  const [couponMinOrder, setCouponMinOrder] = useState(0)
  const [couponSaving, setCouponSaving]     = useState(false)
  const [couponMsg, setCouponMsg]           = useState('')

  /* WhatsApp */
  const [waEnabled, setWaEnabled]   = useState(false)
  const [waPhoneId, setWaPhoneId]   = useState('')
  const [waWabaId, setWaWabaId]     = useState('')
  const [waToken, setWaToken]       = useState('')
  const [waSaving, setWaSaving]     = useState(false)
  const [waMsg, setWaMsg]           = useState('')
  const [waConnecting, setWaConnecting] = useState(false)
  const [waStep, setWaStep]         = useState<'idle'|'choose_waba'|'choose_phone'>('idle')
  const [waOptions, setWaOptions]   = useState<{id:string;name?:string;number?:string}[]>([])
  const [waPendingToken, setWaPendingToken] = useState('')
  const [waPendingWaba, setWaPendingWaba]   = useState('')
  // FB SDK status — `loading` (initial probe in flight), `ready` (SDK
  // loaded + FB.init ran), or `unavailable` (META_APP_ID env var missing
  // on backend, or the SDK script failed to load). Three states instead
  // of a single boolean so the UI can tell the user *why* the Connect
  // button is disabled instead of spinning "جاري تحميل…" forever.
  const [fbStatus, setFbStatus] = useState<'loading' | 'ready' | 'unavailable'>('loading')
  const fbLoaded = fbStatus === 'ready'
  const [waManual, setWaManual] = useState(false)

  /* Messenger + Instagram (Facebook Page) — connection status read from `cfg` */
  const [metaConnecting, setMetaConnecting] = useState(false)
  const [metaMsg, setMetaMsg]               = useState('')
  const [metaPendingToken, setMetaPendingToken] = useState('')
  const [metaPageOptions, setMetaPageOptions]   = useState<{id:string;name?:string;ig_username?:string}[]>([])
  const fbRef = useRef(false)

  /* Notifications */
  const DEF_NOTIF: NotificationSettings = {
    email_enabled: false, email_address: '', webhook_url: '',
    on_new_conversation: true, on_abandoned_cart: true, on_low_rating: true,
    quiet_hours_enabled: false, quiet_hours_start: 22, quiet_hours_end: 8,
  }
  const [notif, setNotif]           = useState<NotificationSettings>(DEF_NOTIF)
  const [notifSaving, setNotifSaving] = useState(false)
  const [notifTesting, setNotifTesting] = useState(false)
  const [notifMsg, setNotifMsg]     = useState('')

  /* Security */
  const [curPass, setCurPass]       = useState('')
  const [newPass, setNewPass]       = useState('')
  const [confirmPass, setConfirmPass] = useState('')
  const [passLoading, setPassLoading] = useState(false)
  const [passMsg, setPassMsg]       = useState('')
  const [tokenStatus, setTokenStatus] = useState<TokenStatus | null>(null)
  const [refreshing, setRefreshing]   = useState(false)
  const [tokenMsg, setTokenMsg]       = useState('')

  /* ── load ── */
  useEffect(() => { load() }, [storeId])

  async function load() {
    setAiLoading(true)
    try {
      const [ai, tok, n] = await Promise.all([
        api.getAI(storeId),
        api.tokenStatus(storeId),
        api.getNotifications(storeId).catch(() => DEF_NOTIF),
      ])
      setCfg(ai)
      setProvider((ai.provider !== 'env' ? ai.provider : 'groq') as ProviderKey)
      setBotName(ai.bot_name || '')
      setModel(ai.ai_model || '')
      setStoreType(ai.store_type === 'printing' ? 'printing' : 'general')
      setCouponsEnabled(!!ai.coupons_enabled)
      setCouponMaxPct(ai.coupon_max_percent ?? 15)
      setCouponMaxVal(ai.coupon_max_discount_value ?? 200)
      setCouponMinOrder(ai.coupon_min_order ?? 0)
      setWaEnabled(!!ai.whatsapp_enabled)
      setWaPhoneId(ai.whatsapp_phone_id || '')
      setWaWabaId((ai as AIConfig & { whatsapp_waba_id?: string }).whatsapp_waba_id || '')
      setTokenStatus(tok)
      setNotif(n)
    } catch { /* ignore */ }
    finally { setAiLoading(false) }
  }

  /* ── Load Facebook JS SDK once ──
     If META_APP_ID isn't set on the backend, /admin/{store}/whatsapp/meta-app-id
     throws and we mark `unavailable` so the UI can fall back to the manual
     entry path (or hide the Messenger/Instagram section entirely). Likewise
     if the SDK script fails to load — onerror flips us to `unavailable` so
     the Connect button never sits in a permanent loading state. */
  useEffect(() => {
    if (fbRef.current) return
    fbRef.current = true
    api.waGetMetaAppId(storeId).then(({ app_id, graph_version }) => {
      if (!app_id) { setFbStatus('unavailable'); return }
      if (document.getElementById('fb-sdk')) { setFbStatus('ready'); return }
      window.fbAsyncInit = () => {
        try {
          window.FB.init({ appId: app_id, version: graph_version, cookie: true, xfbml: false })
          setFbStatus('ready')
        } catch {
          setFbStatus('unavailable')
        }
      }
      const s = document.createElement('script')
      s.id  = 'fb-sdk'
      s.src = 'https://connect.facebook.net/en_US/sdk.js'
      s.onerror = () => setFbStatus('unavailable')
      document.body.appendChild(s)
    }).catch(() => { setFbStatus('unavailable') })
  }, [storeId])

  /* ── actions ── */
  async function saveAI() {
    setAiSaving(true); setAiMsg('')
    try {
      const payload: Record<string, string> = {
        groq_api_key: '', anthropic_api_key: '', openai_api_key: '',
        ai_model: model, bot_name: botName, store_type: storeType,
      }
      if (apiKey.trim()) {
        if (provider === 'groq')      payload.groq_api_key      = apiKey.trim()
        if (provider === 'anthropic') payload.anthropic_api_key = apiKey.trim()
        if (provider === 'openai')    payload.openai_api_key    = apiKey.trim()
      }
      await api.setAI(storeId, payload)
      setAiMsg('✅ تم حفظ إعدادات الذكاء الاصطناعي')
      setApiKey(''); load()
    } catch (e: unknown) { setAiMsg(e instanceof Error ? e.message : 'خطأ') }
    finally { setAiSaving(false) }
  }

  async function saveCoupons() {
    setCouponSaving(true); setCouponMsg('')
    try {
      await api.setAI(storeId, {
        coupons_enabled:           couponsEnabled,
        coupon_max_percent:        Math.max(1, Math.min(couponMaxPct || 15, 90)),
        coupon_max_discount_value: Math.max(0, couponMaxVal || 0),
        coupon_min_order:          Math.max(0, couponMinOrder || 0),
      })
      setCouponMsg('✅ تم حفظ إعدادات الكوبونات'); load()
    } catch (e: unknown) { setCouponMsg(e instanceof Error ? e.message : 'خطأ') }
    finally { setCouponSaving(false) }
  }

  async function saveWhatsApp() {
    setWaSaving(true); setWaMsg('')
    try {
      await api.setAI(storeId, {
        whatsapp_enabled: waEnabled, whatsapp_phone_id: waPhoneId.trim(),
        ...(waToken.trim() ? { whatsapp_token: waToken.trim() } : {}),
      })
      setWaMsg('✅ تم حفظ إعدادات واتساب'); setWaToken(''); load()
    } catch (e: unknown) { setWaMsg(e instanceof Error ? e.message : 'خطأ') }
    finally { setWaSaving(false) }
  }

  async function startEmbeddedSignup() {
    if (!window.FB) { setWaMsg('❌ لم يتم تحميل Facebook SDK بعد — انتظر لحظة أو استخدم الإدخال اليدوي'); return }
    setWaConnecting(true); setWaMsg('')
    window.FB.login(async (res: { authResponse?: { accessToken: string } }) => {
      if (!res.authResponse) { setWaConnecting(false); setWaMsg('❌ تم إلغاء ربط واتساب'); return }
      try {
        const data = await api.waConnect(storeId, { user_token: res.authResponse.accessToken })
        await handleConnectResponse(data)
      } catch (e: unknown) {
        setWaMsg(e instanceof Error ? e.message : '❌ فشل الاتصال')
      } finally { setWaConnecting(false) }
    }, {
      scope: 'whatsapp_business_management,business_management',
      extras: { feature: 'whatsapp_embedded_signup', setup: {} },
    })
  }

  async function handleConnectResponse(data: Awaited<ReturnType<typeof api.waConnect>>) {
    if (data.step === 'choose_waba') {
      setWaPendingToken(data.user_token || '')
      setWaOptions(data.options || [])
      setWaStep('choose_waba')
    } else if (data.step === 'choose_phone') {
      setWaPendingToken(data.user_token || '')
      setWaPendingWaba(data.waba_id || '')
      setWaOptions(data.options || [])
      setWaStep('choose_phone')
    } else {
      setWaStep('idle'); setWaOptions([]); setWaPendingToken(''); setWaPendingWaba('')
      setWaMsg(data.message || '✅ تم الربط')
      load()
    }
  }

  async function pickWaba(wabaId: string) {
    setWaConnecting(true); setWaStep('idle')
    try {
      const data = await api.waConnect(storeId, { user_token: waPendingToken, waba_id: wabaId })
      await handleConnectResponse(data)
    } catch (e: unknown) { setWaMsg(e instanceof Error ? e.message : '❌ خطأ') }
    finally { setWaConnecting(false) }
  }

  async function pickPhone(phoneId: string) {
    setWaConnecting(true); setWaStep('idle')
    try {
      const data = await api.waConnect(storeId, { user_token: waPendingToken, waba_id: waPendingWaba, phone_number_id: phoneId })
      await handleConnectResponse(data)
    } catch (e: unknown) { setWaMsg(e instanceof Error ? e.message : '❌ خطأ') }
    finally { setWaConnecting(false) }
  }

  async function disconnectWa() {
    if (!confirm('هل تريد إلغاء ربط واتساب؟')) return
    try {
      await api.waDisconnect(storeId)
      setWaMsg('✅ تم إلغاء الربط')
      load()
    } catch (e: unknown) { setWaMsg(e instanceof Error ? e.message : '❌ خطأ') }
  }

  // ── Messenger + Instagram connect (Facebook Page) ──
  async function startPagesConnect() {
    if (!window.FB) { setMetaMsg('❌ لم يتم تحميل Facebook SDK بعد — انتظر لحظة وحاول'); return }
    setMetaConnecting(true); setMetaMsg('')

    // Watchdog: FB.login normally fires its callback even when the user
    // cancels (with `authResponse: null`). But if the popup is blocked, if
    // the FB App is in Development mode and the visitor isn't a tester,
    // or if the popup gets stuck on an error page, the callback never
    // fires and the spinner spins forever. After 60s assume the flow is
    // wedged and surface a clear hint pointing at the usual culprits.
    let settled = false
    const watchdog = setTimeout(() => {
      if (settled) return
      settled = true
      setMetaConnecting(false)
      setMetaMsg(
        '❌ تعذّر إكمال تسجيل دخول Facebook (انتهى الوقت). الأسباب الشائعة: ' +
        'الـ popup مغلق من المتصفح • تطبيق Facebook لسه في Development Mode • ' +
        'الـ domain ‎7ayak.app‎ غير مضاف في App Settings • الصلاحيات المطلوبة ' +
        '(pages_messaging, instagram_basic, إلخ) محتاجة Facebook App Review.'
      )
    }, 60_000)

    window.FB.login(async (res: { authResponse?: { accessToken: string } }) => {
      if (settled) return
      settled = true
      clearTimeout(watchdog)
      if (!res.authResponse) { setMetaConnecting(false); setMetaMsg('❌ تم إلغاء الربط'); return }
      try {
        const data = await api.metaConnectPages(storeId, { user_token: res.authResponse.accessToken })
        await handlePagesResponse(data)
      } catch (e: unknown) {
        setMetaMsg(e instanceof Error ? e.message : '❌ فشل الاتصال')
      } finally { setMetaConnecting(false) }
    }, {
      scope: 'pages_messaging,pages_show_list,pages_manage_metadata,instagram_basic,instagram_manage_messages,business_management',
    })
  }

  async function handlePagesResponse(data: Awaited<ReturnType<typeof api.metaConnectPages>>) {
    if (data.step === 'choose_page') {
      setMetaPendingToken(data.user_token || '')
      setMetaPageOptions(data.options || [])
    } else {
      setMetaPageOptions([]); setMetaPendingToken('')
      setMetaMsg(data.message || '✅ تم الربط')
      load()
    }
  }

  async function pickPage(pageId: string) {
    setMetaConnecting(true); setMetaPageOptions([])
    try {
      const data = await api.metaConnectPages(storeId, { user_token: metaPendingToken, page_id: pageId })
      await handlePagesResponse(data)
    } catch (e: unknown) { setMetaMsg(e instanceof Error ? e.message : '❌ خطأ') }
    finally { setMetaConnecting(false) }
  }

  async function disconnectPages() {
    if (!confirm('هل تريد فصل ماسنجر وإنستقرام؟')) return
    try {
      await api.metaDisconnectPages(storeId)
      setMetaMsg('✅ تم الفصل'); load()
    } catch (e: unknown) { setMetaMsg(e instanceof Error ? e.message : '❌ خطأ') }
  }

  async function saveNotif() {
    setNotifSaving(true); setNotifMsg('')
    try { const r = await api.setNotifications(storeId, notif); setNotifMsg(r.message || '✅ تم') }
    catch (e: unknown) { setNotifMsg(e instanceof Error ? e.message : 'خطأ') }
    finally { setNotifSaving(false) }
  }

  async function testNotif() {
    setNotifTesting(true); setNotifMsg('')
    try { const r = await api.testNotification(storeId); setNotifMsg(r.message || '✅ تم الإرسال') }
    catch (e: unknown) { setNotifMsg(e instanceof Error ? e.message : 'خطأ') }
    finally { setNotifTesting(false) }
  }

  async function changePass() {
    if (newPass !== confirmPass) { setPassMsg('كلمتا المرور لا تتطابقان'); return }
    if (newPass.length < 6)      { setPassMsg('كلمة المرور 6 أحرف على الأقل'); return }
    setPassLoading(true); setPassMsg('')
    try { await api.changePassword(storeId, curPass, newPass); setPassMsg('✅ تم التغيير'); setCurPass(''); setNewPass(''); setConfirmPass('') }
    catch (e: unknown) { setPassMsg(e instanceof Error ? e.message : 'خطأ') }
    finally { setPassLoading(false) }
  }

  async function refreshTok() {
    setRefreshing(true); setTokenMsg('')
    try { const r = await api.refreshToken(storeId); setTokenStatus(r); setTokenMsg('✅ تم التجديد') }
    catch (e: unknown) { setTokenMsg(e instanceof Error ? e.message : 'فشل التجديد') }
    finally { setRefreshing(false) }
  }

  /* ── derived ── */
  const cur       = PROVIDERS.find(p => p.key === provider)!
  const models    = MODELS[provider]
  const keySaved  = !!(provider === 'groq' && cfg.groq_api_key) ||
                    !!(provider === 'anthropic' && cfg.anthropic_api_key) ||
                    !!(provider === 'openai' && cfg.openai_api_key)

  const tokInfo = (() => {
    if (!tokenStatus) return null
    const m: Record<string, { color: 'success'|'warning'|'danger'|'default'; label: string }> = {
      ok:       { color: 'success', label: 'صالح'          },
      warning:  { color: 'warning', label: 'ينتهي قريباً'  },
      critical: { color: 'danger',  label: 'حرج'           },
      expired:  { color: 'danger',  label: 'منتهي'         },
      unknown:  { color: 'default', label: 'غير معروف'     },
    }
    return m[tokenStatus.status] || m.unknown
  })()

  /* ══════════════ RENDER ══════════════ */
  return (
    <div className="h-full flex flex-col" dir="rtl">

      {/* ── Header ── */}
      <div className="px-6 pt-6 pb-0">
        <h1 className="text-lg font-black text-foreground">الإعدادات</h1>
        <p className="text-xs text-default-500 mt-0.5">إدارة الذكاء الاصطناعي والأمان والتكاملات</p>
      </div>

      {/* ── Tab bar ── */}
      <div className="px-6 pt-4 pb-0 flex gap-1 border-b border-divider overflow-x-auto">
        {TABS.map(t => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`flex items-center gap-1.5 px-3.5 py-2.5 text-xs font-bold rounded-t-xl whitespace-nowrap transition-all border-b-2 ${
              tab === t.key
                ? 'text-primary border-primary bg-primary/6'
                : 'text-default-400 border-transparent hover:text-foreground hover:bg-content2'
            }`}
          >
            <Icon d={t.icon} size={13} />
            {t.label}
          </button>
        ))}
      </div>

      {/* ── Tab content ── */}
      <div className="flex-1 overflow-y-auto px-6 py-5">

        {/* ══ AI ══ */}
        {tab === 'ai' && (
          aiLoading ? (
            <div className="flex justify-center py-16"><Spinner color="primary" /></div>
          ) : (
            <div className="max-w-xl space-y-5">

              {/* Provider */}
              <section>
                <label className="text-xs font-bold text-default-400 uppercase tracking-wider block mb-2">المزوّد</label>
                <div className="grid grid-cols-3 gap-2">
                  {PROVIDERS.map(p => {
                    const active = provider === p.key
                    const a = ACCENT[p.accent]
                    return (
                      <button key={p.key}
                        onClick={() => { setProvider(p.key); setApiKey('') }}
                        className={`relative flex flex-col items-center gap-0.5 py-3 px-2 rounded-xl border text-center transition-all ${
                          active ? `${a.btn} ring-1 ${a.ring}` : 'bg-content2 border-divider text-default-400 hover:border-slate-500'
                        }`}>
                        {active && <span className="absolute top-1.5 left-1.5 w-1.5 h-1.5 rounded-full bg-current opacity-70" />}
                        <span className="font-bold text-sm">{p.label}</span>
                        <span className="text-[10px] opacity-60">{p.sub}</span>
                      </button>
                    )
                  })}
                </div>
              </section>

              {/* API Key */}
              <section>
                <label className="text-xs font-bold text-default-400 uppercase tracking-wider block mb-2">مفتاح API</label>
                <TextField
                  label="" type="password" value={apiKey} onChange={setApiKey}
                  placeholder={keySaved ? '•••••••• (محفوظ — اتركه فارغاً للإبقاء)' : cur.ph}
                  dir="ltr"
                />
                {keySaved && (
                  <p className="text-xs text-success mt-1.5 flex items-center gap-1">
                    <Icon d="M5 13l4 4L19 7" size={11} className="text-success" />
                    مفتاح {cur.label} محفوظ بالفعل
                  </p>
                )}
              </section>

              {/* Model */}
              <section>
                <label className="text-xs font-bold text-default-400 uppercase tracking-wider block mb-2">الموديل</label>
                <TextField label="" value={model} onChange={setModel}
                  placeholder={models[0]} dir="ltr" />
                <div className="flex flex-wrap gap-1.5 mt-2">
                  {models.map(m => (
                    <button key={m} onClick={() => setModel(m)}
                      className={`text-[11px] px-2.5 py-1 rounded-lg border font-mono transition-colors ${
                        model === m
                          ? 'bg-primary/15 border-primary/40 text-primary'
                          : 'bg-content2 border-divider text-default-400 hover:text-foreground'
                      }`}>
                      {m}
                    </button>
                  ))}
                </div>
              </section>

              {/* Bot name + Store type in a row */}
              <section>
                <label className="text-xs font-bold text-default-400 uppercase tracking-wider block mb-2">اسم البوت</label>
                <TextField label="" value={botName} onChange={setBotName} placeholder="مساعد المتجر" />
              </section>

              <section>
                <label className="text-xs font-bold text-default-400 uppercase tracking-wider block mb-2">نوع المتجر</label>
                <div className="grid grid-cols-2 gap-2">
                  {([
                    { key: 'general',  label: '🛍️ متجر عام',    sub: 'منتجات عامة' },
                    { key: 'printing', label: '🖨️ متجر طباعة',  sub: 'حاسبات أسعار الطباعة' },
                  ] as const).map(opt => (
                    <button key={opt.key} onClick={() => setStoreType(opt.key)}
                      className={`text-right rounded-xl border p-3 transition-all ${
                        storeType === opt.key
                          ? 'border-primary bg-primary/8 ring-1 ring-primary/30'
                          : 'border-divider bg-content2 hover:border-primary/40'
                      }`}>
                      <p className="font-bold text-sm text-foreground">{opt.label}</p>
                      <p className="text-[11px] text-default-400 mt-0.5">{opt.sub}</p>
                    </button>
                  ))}
                </div>
              </section>

              <Msg text={aiMsg} />
              <Button color="primary" isLoading={aiSaving} onPress={saveAI}
                className="w-full font-bold h-10 bg-gradient-to-r from-blue-600 to-indigo-600">
                {aiSaving ? '' : 'حفظ إعدادات AI'}
              </Button>

              {/* ── AI discount coupons ── */}
              <section className="rounded-xl border border-divider bg-content2 p-4 space-y-3 mt-2">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <p className="font-bold text-sm text-foreground">🎁 كوبونات الخصم الذكية</p>
                    <p className="text-[11px] text-default-400 mt-0.5">
                      يسمح للبوت بإصدار كوبون خصم شخصي لإقناع العميل بالشراء أو استرجاع سلة متروكة.
                    </p>
                  </div>
                  <Switch isSelected={couponsEnabled} onValueChange={setCouponsEnabled} />
                </div>

                {couponsEnabled && (
                  <>
                    <div className="grid grid-cols-3 gap-2">
                      <TextField label="أقصى نسبة خصم ٪" type="number" value={String(couponMaxPct)}
                        onChange={(v) => setCouponMaxPct(parseInt(v) || 0)} placeholder="15" />
                      <TextField label="أقصى قيمة (ريال)" type="number" value={String(couponMaxVal)}
                        onChange={(v) => setCouponMaxVal(parseFloat(v) || 0)} placeholder="200" />
                      <TextField label="حد أدنى للطلب" type="number" value={String(couponMinOrder)}
                        onChange={(v) => setCouponMinOrder(parseFloat(v) || 0)} placeholder="0" />
                    </div>
                    <p className="text-[11px] text-amber-500">
                      ⚠️ يتطلب صلاحية <code>coupons.read_write</code> في تطبيق سلة. كل كوبون لاستخدام واحد وصالح ٢٤ ساعة.
                    </p>
                    <Msg text={couponMsg} />
                    <Button size="sm" color="primary" variant="flat" isLoading={couponSaving}
                      onPress={saveCoupons} className="font-bold">
                      {couponSaving ? '' : 'حفظ إعدادات الكوبونات'}
                    </Button>
                  </>
                )}
              </section>
            </div>
          )
        )}

        {/* ══ WhatsApp ══ */}
        {tab === 'whatsapp' && (
          <div className="max-w-xl space-y-5">

            {/* ── Connected state ── */}
            {waPhoneId && !waManual ? (
              <div className="space-y-4">
                {/* Status card */}
                <div className="rounded-2xl border border-emerald-500/30 bg-emerald-500/5 p-5">
                  <div className="flex items-start gap-4">
                    <div className="w-12 h-12 rounded-2xl bg-[#25D366]/15 flex items-center justify-center flex-shrink-0">
                      <svg viewBox="0 0 24 24" fill="#25D366" width={26} height={26}>
                        <path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347z"/>
                        <path d="M12 0C5.373 0 0 5.373 0 12c0 2.123.555 4.117 1.528 5.845L.057 23.886l6.184-1.622A11.945 11.945 0 0012 24c6.627 0 12-5.373 12-12S18.627 0 12 0zm0 22c-1.833 0-3.552-.497-5.027-1.362l-.36-.213-3.726.977.995-3.634-.234-.374A9.96 9.96 0 012 12C2 6.477 6.477 2 12 2s10 4.477 10 10-4.477 10-10 10z"/>
                      </svg>
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="font-black text-emerald-400 text-sm flex items-center gap-1.5">
                        <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
                        واتساب مربوط ونشط
                      </p>
                      <p className="text-xs text-default-500 mt-1">Phone ID: <span className="font-mono text-foreground">{waPhoneId}</span></p>
                      {waWabaId && <p className="text-xs text-default-500">WABA ID: <span className="font-mono text-foreground">{waWabaId}</span></p>}
                    </div>
                  </div>

                  {/* Enable/Disable toggle */}
                  <div className="mt-4 flex items-center justify-between border-t border-emerald-500/20 pt-3">
                    <p className="text-xs text-default-400">الرد التلقائي على رسائل واتساب</p>
                    <Switch isSelected={waEnabled} onValueChange={async (v) => {
                      setWaEnabled(v)
                      await api.setAI(storeId, { whatsapp_enabled: v })
                    }} color="success" size="sm" />
                  </div>
                </div>

                {/* Webhook info */}
                <section className="space-y-3 bg-content2 rounded-xl p-4 border border-divider">
                  <p className="text-xs font-bold text-default-500 flex items-center gap-1.5">
                    <Icon d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" size={12} />
                    Webhook Settings — أضفها في Meta Developer Console
                  </p>
                  <CopyRow label="Callback URL"  value={cfg.whatsapp_webhook || ''} />
                  <CopyRow label="Verify Token"  value={cfg.whatsapp_verify_token || ''} />
                </section>

                <Msg text={waMsg} />

                <div className="flex gap-2">
                  <Button variant="flat" color="danger" onPress={disconnectWa} className="flex-1 font-bold h-10">
                    إلغاء الربط
                  </Button>
                  <Button variant="flat" onPress={() => setWaManual(true)} className="font-bold h-10 text-default-400">
                    إعدادات يدوية
                  </Button>
                </div>
              </div>

            ) : waStep !== 'idle' ? (
              /* ── Picker step (WABA or Phone) ── */
              <div className="space-y-4">
                <p className="text-sm font-bold text-foreground">
                  {waStep === 'choose_waba' ? 'اختر حساب WhatsApp Business' : 'اختر رقم الهاتف'}
                </p>
                {waOptions.map(opt => (
                  <button key={opt.id}
                    onClick={() => waStep === 'choose_waba' ? pickWaba(opt.id) : pickPhone(opt.id)}
                    disabled={waConnecting}
                    className="w-full text-right flex items-center gap-3 p-4 rounded-xl border border-divider bg-content2 hover:border-primary/50 hover:bg-content1 transition-all disabled:opacity-50">
                    <div className="w-9 h-9 rounded-xl bg-primary/10 flex items-center justify-center text-primary text-xs font-black flex-shrink-0">
                      {(opt.name || opt.number || '?')[0]}
                    </div>
                    <div>
                      <p className="font-bold text-sm text-foreground">{opt.name || opt.number}</p>
                      <p className="text-xs text-default-500 font-mono">{opt.id}</p>
                    </div>
                  </button>
                ))}
                <Msg text={waMsg} />
                <Button variant="flat" onPress={() => { setWaStep('idle'); setWaOptions([]) }} className="w-full font-bold h-10">
                  إلغاء
                </Button>
              </div>

            ) : (
              /* ── Not connected / connect button ── */
              <div className="space-y-5">
                {/* Hero card */}
                <div className="rounded-2xl border border-divider bg-gradient-to-br from-[#25D366]/5 to-transparent p-6 text-center space-y-4">
                  <div className="w-16 h-16 rounded-3xl bg-[#25D366]/10 flex items-center justify-center mx-auto">
                    <svg viewBox="0 0 24 24" fill="#25D366" width={34} height={34}>
                      <path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347z"/>
                      <path d="M12 0C5.373 0 0 5.373 0 12c0 2.123.555 4.117 1.528 5.845L.057 23.886l6.184-1.622A11.945 11.945 0 0012 24c6.627 0 12-5.373 12-12S18.627 0 12 0zm0 22c-1.833 0-3.552-.497-5.027-1.362l-.36-.213-3.726.977.995-3.634-.234-.374A9.96 9.96 0 012 12C2 6.477 6.477 2 12 2s10 4.477 10 10-4.477 10-10 10z"/>
                    </svg>
                  </div>
                  <div>
                    <h3 className="font-black text-foreground text-base">ربط واتساب بالمتجر</h3>
                    <p className="text-xs text-default-500 mt-1 leading-relaxed">
                      سجّل دخولك بفيسبوك واختر رقم WhatsApp Business — الربط يكتمل في ثوانٍ
                    </p>
                  </div>

                  <Button
                    onPress={startEmbeddedSignup}
                    isLoading={waConnecting}
                    isDisabled={!fbLoaded && !waManual}
                    className="w-full font-black h-11 text-white"
                    style={{ background: '#25D366' }}
                  >
                    {waConnecting ? '' : (
                      <span className="flex items-center gap-2">
                        <svg viewBox="0 0 24 24" fill="currentColor" width={16} height={16}>
                          <path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347z"/>
                          <path d="M12 0C5.373 0 0 5.373 0 12c0 2.123.555 4.117 1.528 5.845L.057 23.886l6.184-1.622A11.945 11.945 0 0012 24c6.627 0 12-5.373 12-12S18.627 0 12 0zm0 22c-1.833 0-3.552-.497-5.027-1.362l-.36-.213-3.726.977.995-3.634-.234-.374A9.96 9.96 0 012 12C2 6.477 6.477 2 12 2s10 4.477 10 10-4.477 10-10 10z"/>
                        </svg>
                        ربط واتساب
                      </span>
                    )}
                  </Button>

                  {fbStatus === 'loading' && (
                    <p className="text-[11px] text-default-400">جاري تحميل Facebook SDK…</p>
                  )}
                  {fbStatus === 'unavailable' && !waManual && (
                    <p className="text-[11px] text-amber-600">
                      الربط التلقائي غير متاح حالياً — استخدم الإدخال اليدوي بالأسفل.
                    </p>
                  )}
                </div>

                {/* Manual fallback toggle */}
                <button onClick={() => setWaManual(v => !v)}
                  className="w-full text-xs text-default-400 hover:text-default-600 transition-colors flex items-center justify-center gap-1.5">
                  <Icon d={waManual ? "M5 15l7-7 7 7" : "M19 9l-7 7-7-7"} size={11} />
                  {waManual ? 'إخفاء' : 'إدخال يدوي (للمطورين)'}
                </button>

                {waManual && (
                  <div className="space-y-3 border border-divider rounded-xl p-4 bg-content2">
                    <TextField label="Phone Number ID" value={waPhoneId} onChange={setWaPhoneId}
                      placeholder="123456789012345" dir="ltr" hint="من لوحة Meta Business" />
                    <TextField label="Access Token" type="password" value={waToken} onChange={setWaToken}
                      placeholder={cfg.whatsapp_token ? '•••••••• (محفوظ)' : 'EAAG...'} dir="ltr"
                      hint={cfg.whatsapp_token ? 'محفوظ — اتركه فارغاً للإبقاء' : 'من Meta'} />
                    <Msg text={waMsg} />
                    <Button color="success" isLoading={waSaving} onPress={saveWhatsApp}
                      className="w-full font-bold h-10 bg-gradient-to-r from-emerald-500 to-teal-600 text-white">
                      {waSaving ? '' : 'حفظ'}
                    </Button>
                  </div>
                )}

                {!waManual && <Msg text={waMsg} />}

                {/* Webhook info */}
                {cfg.whatsapp_webhook && (
                  <section className="space-y-3 bg-content2 rounded-xl p-4 border border-divider">
                    <p className="text-xs font-bold text-default-500 flex items-center gap-1.5">
                      <Icon d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" size={12} />
                      Webhook — أضفها في Meta Developer Console
                    </p>
                    <CopyRow label="Callback URL"  value={cfg.whatsapp_webhook} />
                    <CopyRow label="Verify Token"  value={cfg.whatsapp_verify_token || ''} />
                  </section>
                )}
              </div>
            )}

            {/* ── Messenger + Instagram (Facebook Page) ── */}
            <section className="space-y-3 border-t border-divider pt-5">
              <div className="flex items-center gap-2">
                <span className="text-base">💬</span>
                <h3 className="text-sm font-bold text-foreground">ماسنجر + إنستقرام</h3>
              </div>
              <p className="text-xs text-default-500 leading-relaxed">
                اربط صفحة فيسبوك (وحساب إنستقرام المرتبط بها) ليرد البوت تلقائياً على رسائل
                ماسنجر وإنستقرام دايركت — بنفس ذكاء بوت المتجر.
              </p>

              {cfg.page_id ? (
                <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/5 p-4 space-y-2">
                  <p className="text-sm font-bold text-emerald-600">✅ متصل: {cfg.page_name || cfg.page_id}</p>
                  <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-default-600">
                    <span>ماسنجر: {cfg.messenger_enabled ? 'مفعّل ✓' : 'متوقف'}</span>
                    <span className="text-default-300">•</span>
                    <span>إنستقرام: {cfg.instagram_enabled ? `مفعّل ✓ ${cfg.ig_username ? '(@' + cfg.ig_username + ')' : ''}` : 'غير مرتبط'}</span>
                  </div>
                  <Button size="sm" color="danger" variant="flat" onPress={disconnectPages} className="mt-1">
                    فصل ماسنجر وإنستقرام
                  </Button>
                </div>
              ) : metaPageOptions.length > 0 ? (
                <div className="space-y-2">
                  <p className="text-xs font-bold text-default-500">اختر الصفحة:</p>
                  {metaPageOptions.map(p => (
                    <button key={p.id} onClick={() => pickPage(p.id)}
                      className="w-full text-right rounded-xl border border-divider bg-content2 p-3 hover:border-primary/40 transition-all">
                      <p className="text-sm font-bold text-foreground">{p.name || p.id}</p>
                      {p.ig_username && <p className="text-[11px] text-default-400 mt-0.5">إنستقرام: @{p.ig_username}</p>}
                    </button>
                  ))}
                </div>
              ) : fbStatus === 'unavailable' ? (
                /* Backend hasn't configured META_APP_ID, so the Facebook
                   Login popup can't be opened. Be explicit about the
                   reason — endless "loading" silently is worse than a
                   clear unavailable state with a path to resolution. */
                <div className="rounded-xl border border-amber-500/30 bg-amber-500/5 p-3 text-xs text-amber-700 leading-relaxed">
                  <p className="font-bold mb-1">ربط ماسنجر/إنستقرام غير متاح حالياً</p>
                  <p>
                    يحتاج إعداد <code className="px-1 py-0.5 bg-amber-100 rounded">META_APP_ID</code> + <code className="px-1 py-0.5 bg-amber-100 rounded">META_APP_SECRET</code> على
                    الخادم، وتسجيل تطبيق Facebook في{' '}
                    <a href="https://developers.facebook.com/apps" target="_blank" rel="noopener noreferrer"
                       className="font-bold underline">Meta Developers</a>.
                    تواصل مع المدير العام لتفعيل التكامل.
                  </p>
                </div>
              ) : (
                <Button color="primary" isLoading={metaConnecting} isDisabled={!fbLoaded}
                  onPress={startPagesConnect}
                  className="font-bold h-10 bg-gradient-to-r from-blue-600 to-indigo-600">
                  {fbLoaded ? 'ربط ماسنجر + إنستقرام' : 'جارٍ تحميل Facebook…'}
                </Button>
              )}
              <Msg text={metaMsg} />
            </section>
          </div>
        )}

        {/* ══ Notifications ══ */}
        {tab === 'notifications' && (
          <div className="max-w-xl space-y-5">

            {/* Email toggle */}
            <div className="flex items-center justify-between bg-content2 rounded-xl px-4 py-3 border border-divider">
              <div>
                <p className="text-sm font-bold text-foreground">إشعارات البريد الإلكتروني</p>
                <p className="text-xs text-default-500 mt-0.5">استقبل بريداً عند كل حدث مهم</p>
              </div>
              <Switch isSelected={notif.email_enabled}
                onValueChange={v => setNotif(n => ({ ...n, email_enabled: v }))} color="primary" />
            </div>

            {notif.email_enabled && (
              <TextField label="البريد الإلكتروني" value={notif.email_address}
                onChange={v => setNotif(n => ({ ...n, email_address: v }))}
                placeholder="owner@mystore.com" type="email" />
            )}

            {/* Triggers */}
            <section>
              <label className="text-xs font-bold text-default-400 uppercase tracking-wider block mb-2">أرسل إشعاراً عند:</label>
              <div className="bg-content2 rounded-xl border border-divider divide-y divide-divider overflow-hidden">
                {[
                  { key: 'on_new_conversation' as const, label: 'محادثة جديدة من عميل', emoji: '💬' },
                  { key: 'on_abandoned_cart'   as const, label: 'سلة متروكة',            emoji: '🛒' },
                  { key: 'on_low_rating'       as const, label: 'تقييم منخفض (≤ 2 نجوم)', emoji: '⭐' },
                ].map(item => (
                  <div key={item.key} className="flex items-center justify-between px-4 py-3">
                    <span className="text-sm text-foreground">{item.emoji} {item.label}</span>
                    <Switch size="sm" isSelected={notif[item.key]}
                      onValueChange={v => setNotif(n => ({ ...n, [item.key]: v }))} color="success" />
                  </div>
                ))}
              </div>
            </section>

            {/* Webhook */}
            <section>
              <label className="text-xs font-bold text-default-400 uppercase tracking-wider block mb-2">Webhook URL (Slack / Zapier)</label>
              <TextField label="" value={notif.webhook_url}
                onChange={v => setNotif(n => ({ ...n, webhook_url: v }))}
                placeholder="https://hooks.slack.com/services/..." hint="اختياري" dir="ltr" />
            </section>

            {/* Quiet hours */}
            <div className="flex items-center justify-between bg-content2 rounded-xl px-4 py-3 border border-divider">
              <div>
                <p className="text-sm font-bold text-foreground">ساعات الهدوء</p>
                <p className="text-xs text-default-500 mt-0.5">
                  بدون إشعارات من {notif.quiet_hours_start}:00 حتى {notif.quiet_hours_end}:00
                </p>
              </div>
              <Switch isSelected={notif.quiet_hours_enabled}
                onValueChange={v => setNotif(n => ({ ...n, quiet_hours_enabled: v }))} />
            </div>

            <Msg text={notifMsg} />
            <div className="flex gap-2">
              <Button variant="flat" isLoading={notifTesting} onPress={testNotif}
                className="flex-1 font-semibold h-10">
                {notifTesting ? '' : '🧪 اختبار'}
              </Button>
              <Button color="primary" isLoading={notifSaving} onPress={saveNotif}
                className="flex-1 font-bold h-10 bg-gradient-to-r from-cyan-500 to-teal-600 text-white">
                {notifSaving ? '' : 'حفظ الإشعارات'}
              </Button>
            </div>
          </div>
        )}

        {/* ══ Security ══ */}
        {tab === 'security' && (
          <div className="max-w-xl space-y-6">

            {/* Token status */}
            {tokenStatus && (
              <section>
                <label className="text-xs font-bold text-default-400 uppercase tracking-wider block mb-2">توكن سلة</label>
                <div className="bg-content2 rounded-xl border border-divider overflow-hidden">
                  <div className="flex items-center justify-between px-4 py-3 border-b border-divider">
                    <span className="text-sm font-bold text-foreground">الحالة</span>
                    {tokInfo && <Chip size="sm" color={tokInfo.color} variant="flat">{tokInfo.label}</Chip>}
                  </div>
                  {tokenStatus.days_remaining != null && (
                    <div className="flex items-center justify-between px-4 py-2.5 border-b border-divider">
                      <span className="text-xs text-default-400">الأيام المتبقية</span>
                      <span className={`text-sm font-bold ${
                        tokenStatus.days_remaining > 7 ? 'text-success' :
                        tokenStatus.days_remaining > 0 ? 'text-warning' : 'text-danger'
                      }`}>{tokenStatus.days_remaining > 0 ? `${tokenStatus.days_remaining} يوم` : 'انتهى'}</span>
                    </div>
                  )}
                  {tokenStatus.expires_at && (
                    <div className="flex items-center justify-between px-4 py-2.5 border-b border-divider">
                      <span className="text-xs text-default-400">تاريخ الانتهاء</span>
                      <span className="text-xs font-mono text-default-300">{tokenStatus.expires_at.slice(0,10)}</span>
                    </div>
                  )}
                  <div className="flex items-center justify-between px-4 py-2.5">
                    <span className="text-xs text-default-400">Refresh Token</span>
                    <Chip size="sm" variant="flat" color={tokenStatus.has_refresh ? 'success' : 'danger'}>
                      {tokenStatus.has_refresh ? 'متوفر' : 'غير موجود'}
                    </Chip>
                  </div>
                </div>
                {tokenStatus.message && (
                  <p className="text-xs text-default-400 mt-1.5 px-1">{tokenStatus.message}</p>
                )}
                <Msg text={tokenMsg} />
                <Button variant="flat" color="primary" isLoading={refreshing}
                  isDisabled={!tokenStatus.has_refresh} onPress={refreshTok}
                  className="w-full font-semibold h-10 mt-2">
                  {refreshing ? '' : 'تجديد التوكن يدوياً'}
                </Button>
              </section>
            )}

            {/* Password */}
            <section>
              <label className="text-xs font-bold text-default-400 uppercase tracking-wider block mb-2">تغيير كلمة المرور</label>
              <div className="space-y-3">
                <TextField label="الحالية" type="password" value={curPass} onChange={setCurPass}
                  placeholder="كلمة المرور الحالية" />
                <div className="grid grid-cols-2 gap-2">
                  <TextField label="الجديدة" type="password" value={newPass} onChange={setNewPass}
                    placeholder="٦ أحرف على الأقل" />
                  <TextField label="تأكيد" type="password" value={confirmPass} onChange={setConfirmPass}
                    placeholder="أعد الإدخال" />
                </div>
              </div>
              <Msg text={passMsg} />
              <Button color="warning" variant="flat" isLoading={passLoading} onPress={changePass}
                isDisabled={!curPass || !newPass || !confirmPass}
                className="w-full font-semibold h-10 mt-3">
                {passLoading ? '' : 'تغيير كلمة المرور'}
              </Button>
            </section>
          </div>
        )}
      </div>
    </div>
  )
}
