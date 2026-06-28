import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Chip, Modal, ModalBody, ModalContent, ModalFooter, ModalHeader, Input, Spinner } from '@heroui/react'
import { api, IntegrationData, CustomIntegrationStatus } from '../../api'
import { BrandLogo, PageHeader, StatusPill } from '../../components/ui'

interface Props { storeId: string }

function Icon({ paths, size = 16, className = '' }: {
  paths: string | string[]
  size?: number
  className?: string
}) {
  const arr = Array.isArray(paths) ? paths : [paths]
  return (
    <svg width={size} height={size} viewBox="0 0 24 24"
      fill="none" stroke="currentColor" strokeWidth={2}
      strokeLinecap="round" strokeLinejoin="round" className={className}>
      {arr.map((d, i) => <path key={i} d={d} />)}
    </svg>
  )
}


/* ── Types ── */
type Status = 'connected' | 'disconnected' | 'coming_soon'

interface IntegrationDef {
  id:          string
  name:        string
  nameEn?:     string
  description: string
  logo:        React.ReactNode
  category:    string
  comingSoon?: boolean
  // filled from API at runtime:
  status:      Status
  data?:       IntegrationData
}

const INTEGRATIONS_DEF: Omit<IntegrationDef, 'status' | 'data'>[] = [
  { id: 'salla',       name: 'سلّة',       nameEn: 'Salla',       category: 'ecommerce', logo: <BrandLogo domain="salla.sa"        fallbackColor="#6B3FA0" fallbackLabel="س"   />, description: 'متجرك على سلّة — الطلبات والمنتجات والعملاء تظهر مباشرةً في المحادثات.' },
  { id: 'shopify',     name: 'شوبيفاي',    nameEn: 'Shopify',     category: 'ecommerce', logo: <BrandLogo domain="shopify.com"     fallbackColor="#96BF48" fallbackLabel="S"   />, description: 'اربط متجر شوبيفاي لإدارة الطلبات والمنتجات من لوحة تحكم واحدة.' },
  { id: 'zid',         name: 'زد',         nameEn: 'Zid',         category: 'ecommerce', logo: <BrandLogo domain="zid.sa"          fallbackColor="#1C3553" fallbackLabel="ز"   />, description: 'اربط متجرك على منصة زد — الطلبات والمنتجات والعملاء تظهر في المحادثات.' },
  { id: 'custom',      name: 'متجر مبرمَج خاص', nameEn: 'Custom',  category: 'ecommerce', logo: <BrandLogo domain="" fallbackColor="#475569" fallbackLabel="API" />, description: 'متجرك مبني ببرمجة خاصة؟ اربطه بحياك عبر API موقّع — ادفع المنتجات والطلبات والسلات المتروكة مباشرةً.' },
  { id: 'woocommerce', name: 'ووكومرس',    nameEn: 'WooCommerce', category: 'ecommerce', logo: <BrandLogo domain="woocommerce.com" fallbackColor="#7F54B3" fallbackLabel="Woo" />, description: 'ربط موقع ووردبريس/ووكومرس لمتابعة الطلبات.', comingSoon: true },
  { id: 'tiktok',      name: 'تيك توك',     nameEn: 'TikTok',      category: 'social',    logo: <BrandLogo domain="tiktok.com"     fallbackColor="#000000" fallbackLabel="TT"  />, description: 'اربط حساب تيك توك (الأساس: تسجيل الدخول وعرض الحساب). الرد على الرسائل والتعليقات غير متاح بعد عبر واجهة تيك توك الرسمية.' },
  { id: 'myfatoorah',  name: 'ماي فاتوره', nameEn: 'MyFatoorah',  category: 'payment',   logo: <BrandLogo domain="myfatoorah.com" fallbackColor="#00B0A6" fallbackLabel="MF"  />, description: 'إرسال روابط دفع مباشرة للعميل داخل المحادثة.', comingSoon: true },
  { id: 'tabby',       name: 'تابي',        nameEn: 'Tabby',       category: 'payment',   logo: <BrandLogo domain="tabby.ai"       fallbackColor="#3DBFA3" fallbackLabel="tab" />, description: 'عرض خيار الدفع بالتقسيط عبر تابي.', comingSoon: true },
  { id: 'tamara',      name: 'تمارا',       nameEn: 'Tamara',      category: 'payment',   logo: <BrandLogo domain="tamara.co"      fallbackColor="#EB4C60" fallbackLabel="تم"  />, description: 'الشراء الآن والدفع لاحقاً عبر تمارا.', comingSoon: true },
  { id: 'payfort',     name: 'بيفورت',      nameEn: 'Payfort',     category: 'payment',   logo: <BrandLogo domain="payfort.com"    fallbackColor="#003087" fallbackLabel="APS" />, description: 'قبول مدفوعات البطاقات عبر بوابة Amazon Payment Services.', comingSoon: true },
]

/* ── Card ── */
function IntegrationCard({
  integration,
  onConnect,
  onDisconnect,
  onSync,
  onManage,
  connecting,
}: {
  integration: IntegrationDef
  onConnect:    (id: string) => void
  onDisconnect: (id: string) => void
  onSync?:      (id: string) => void
  onManage?:    (id: string) => void
  connecting?:  boolean
}) {
  const connected  = integration.status === 'connected'
  const comingSoon = integration.comingSoon || integration.status === 'coming_soon'
  return (
    <div className={`relative bg-content1 border rounded-2xl p-5 flex flex-col gap-4 transition-all
      ${connected ? 'border-emerald-500/30 shadow-[0_0_0_1px_rgba(16,185,129,0.1)]' : 'border-divider hover:border-default-300'}`}>
      {connected && (
        <div className="absolute top-0 left-0 right-0 h-0.5 bg-gradient-to-r from-transparent via-emerald-500 to-transparent rounded-t-2xl" />
      )}
      <div className="flex items-start justify-between gap-3">
        <div className="flex-shrink-0">{integration.logo}</div>
        {connected ? (
          <Chip size="sm" color="success" variant="flat"
            startContent={<span className="w-1.5 h-1.5 bg-emerald-500 rounded-full animate-pulse" />}
            className="text-[10px] font-bold">متصل</Chip>
        ) : comingSoon ? (
          <Chip size="sm" color="default" variant="flat" className="text-[10px] font-bold text-default-500">قريباً</Chip>
        ) : (
          <Chip size="sm" color="default" variant="flat" className="text-[10px]">غير متصل</Chip>
        )}
      </div>
      <div className="flex-1">
        <p className="text-sm font-bold text-foreground mb-1">
          {integration.name}
          {integration.nameEn && <span className="text-[10px] font-normal text-default-500 mr-1.5">{integration.nameEn}</span>}
        </p>
        <p className="text-xs text-default-500 leading-relaxed">{integration.description}</p>
        {connected && integration.data?.shop_name && (
          <p className="text-[10px] text-emerald-500 mt-1.5 font-mono">{integration.data.shop_name}</p>
        )}
      </div>
      <div className="flex gap-2">
        {comingSoon ? (
          <button disabled className="flex-1 py-2 text-xs font-semibold rounded-xl border border-divider text-default-500 cursor-not-allowed opacity-60">
            قريباً
          </button>
        ) : connected ? (
          <div className="flex gap-1.5 w-full">
            {onSync && (
              <button onClick={() => onSync(integration.id)}
                className="flex-1 py-2 text-xs font-semibold rounded-xl border border-emerald-200 text-emerald-600 hover:bg-emerald-50 transition-colors">
                مزامنة
              </button>
            )}
            {onManage && (
              <button onClick={() => onManage(integration.id)}
                className="flex-1 py-2 text-xs font-semibold rounded-xl border border-divider text-foreground hover:bg-content2 transition-colors">
                إعدادات الربط
              </button>
            )}
            <button onClick={() => onDisconnect(integration.id)}
              className="flex-1 py-2 text-xs font-semibold rounded-xl border border-red-200 text-red-500 hover:bg-red-50 transition-colors">
              قطع الاتصال
            </button>
          </div>
        ) : (
          <button onClick={() => onConnect(integration.id)}
            disabled={connecting}
            className="flex-1 py-2 text-xs font-bold rounded-xl bg-primary text-white hover:opacity-90 disabled:opacity-60 transition-opacity flex items-center justify-center gap-2">
            {connecting ? <><Spinner size="sm" color="white" /> جاري التحويل...</> : 'ربط الآن'}
          </button>
        )}
      </div>
    </div>
  )
}

/* ── Toast ── */
function Toast({ msg, type }: { msg: string; type: 'success' | 'error' | 'info' }) {
  const colors = { success: 'bg-emerald-500', error: 'bg-red-500', info: 'bg-blue-500' }
  return (
    <div className={`fixed bottom-6 left-1/2 -translate-x-1/2 z-50 ${colors[type]} text-white text-xs font-bold px-5 py-2.5 rounded-full shadow-xl flex items-center gap-2`}>
      {type === 'success' && <Icon paths="M5 13l4 4L19 7" size={13} />}
      {type === 'error'   && <Icon paths={['M18 6L6 18', 'M6 6l12 12']} size={13} />}
      {type === 'info'    && <Icon paths="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" size={13} />}
      {msg}
    </div>
  )
}

/* ── Salla connect modal (API-key / App-Settings linking — the ONLY Salla method) ── */
function SallaConnectModal({ isOpen, onClose, storeId, onToast }: {
  isOpen: boolean
  onClose: () => void
  storeId: string
  onToast: (msg: string, type: 'success' | 'error' | 'info') => void
}) {
  const [apiKey, setApiKey]   = useState('')
  const [loading, setLoading] = useState(false)

  // Fetch the linking key the first time the modal opens.
  useEffect(() => {
    if (!isOpen || apiKey) return
    let cancelled = false
    setLoading(true)
    api.getApiKey(storeId)
      .then(res => { if (!cancelled) setApiKey(res.api_key) })
      .catch(() => onToast('تعذّر جلب مفتاح الربط', 'error'))
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen, storeId])

  function copyKey() {
    if (!apiKey) return
    navigator.clipboard?.writeText(apiKey).then(
      () => onToast('تم نسخ المفتاح', 'success'),
      () => onToast('تعذّر النسخ', 'error'),
    )
  }

  async function regen() {
    setLoading(true)
    try {
      const res = await api.regenerateApiKey(storeId)
      setApiKey(res.api_key)
      onToast('تم توليد مفتاح جديد', 'success')
    } catch {
      onToast('تعذّر توليد مفتاح جديد', 'error')
    } finally { setLoading(false) }
  }

  return (
    <Modal isOpen={isOpen} onOpenChange={(o) => { if (!o) onClose() }} placement="center" backdrop="blur" size="md">
      <ModalContent>
        {(close) => (
          <>
            <ModalHeader dir="rtl">
              <div className="flex items-center gap-3">
                <BrandLogo domain="salla.sa" fallbackColor="#6B3FA0" fallbackLabel="س" size={30} />
                <div>
                  <p className="text-sm font-bold">ربط متجر سلّة</p>
                  <p className="text-xs font-normal text-default-500">عبر سوق تطبيقات سلة باستخدام مفتاح الربط</p>
                </div>
              </div>
            </ModalHeader>
            <ModalBody dir="rtl">
              <ol className="text-xs text-default-600 leading-relaxed list-decimal mr-4 space-y-1.5">
                <li>ثبّت تطبيق حياك من <a href="https://apps.salla.sa" target="_blank" rel="noreferrer" className="text-violet-600 font-semibold hover:underline">متجر تطبيقات سلة</a>.</li>
                <li>افتح <span className="font-semibold text-foreground">إعدادات ربط التطبيق</span> داخل لوحة سلة.</li>
                <li>أدخل بريدك الإلكتروني في حياك، وانسخ <span className="font-semibold text-foreground">مفتاح الربط</span> أدناه في حقل API Key، ثم احفظ.</li>
              </ol>

              <div>
                <label className="block text-[11px] font-semibold text-default-500 mb-1.5">مفتاح الربط (API Key)</label>
                <div className="flex items-center gap-2">
                  <code className="flex-1 px-3 py-2.5 bg-content2 border border-divider rounded-xl text-xs font-mono text-foreground break-all select-all">
                    {loading && !apiKey ? '…' : (apiKey || '—')}
                  </code>
                  <button onClick={copyKey} disabled={!apiKey}
                    className="px-3 py-2.5 text-xs font-bold rounded-xl border border-divider text-foreground hover:bg-content2 transition-colors flex-shrink-0 disabled:opacity-50">
                    نسخ
                  </button>
                </div>
                <button onClick={regen} disabled={loading}
                  className="mt-2 text-[11px] font-semibold text-default-400 hover:text-red-500 transition-colors disabled:opacity-50">
                  توليد مفتاح جديد (يُلغي القديم)
                </button>
              </div>

              <div className="bg-content2 rounded-xl p-3 text-[11px] text-default-500 leading-relaxed">
                بعد حفظ المفتاح في لوحة سلة، ارجع إلى هذه الصفحة واضغط زر <span className="font-bold text-foreground">«تحديث الربط»</span> بالأعلى ليظهر متجرك «متصل».
              </div>
            </ModalBody>
            <ModalFooter>
              <button onClick={close} className="px-4 py-2 text-xs text-default-500 hover:text-foreground">إغلاق</button>
            </ModalFooter>
          </>
        )}
      </ModalContent>
    </Modal>
  )
}

/* ── Custom store connect modal (self-built stores push catalog + events) ── */
function CopyRow({ label, value, onToast }: {
  label: string
  value: string
  onToast: (msg: string, type: 'success' | 'error' | 'info') => void
}) {
  function copy() {
    if (!value) return
    navigator.clipboard?.writeText(value).then(
      () => onToast('تم النسخ', 'success'),
      () => onToast('تعذّر النسخ', 'error'),
    )
  }
  return (
    <div>
      <label className="block text-[11px] font-semibold text-default-500 mb-1.5">{label}</label>
      <div className="flex items-center gap-2">
        <code className="flex-1 px-3 py-2.5 bg-content2 border border-divider rounded-xl text-[11px] font-mono text-foreground break-all select-all" dir="ltr">
          {value || '—'}
        </code>
        <button onClick={copy} disabled={!value}
          className="px-3 py-2.5 text-xs font-bold rounded-xl border border-divider text-foreground hover:bg-content2 transition-colors flex-shrink-0 disabled:opacity-50">
          نسخ
        </button>
      </div>
    </div>
  )
}

function CustomConnectModal({ isOpen, onClose, storeId, onToast, onChanged }: {
  isOpen: boolean
  onClose: () => void
  storeId: string
  onToast: (msg: string, type: 'success' | 'error' | 'info') => void
  onChanged: () => void
}) {
  const [status, setStatus]   = useState<CustomIntegrationStatus | null>(null)
  const [secret, setSecret]   = useState('')   // revealed once after connect/regen
  const [loading, setLoading] = useState(false)
  const [busy, setBusy]       = useState(false)

  useEffect(() => {
    if (!isOpen) { setSecret(''); setStatus(null); return }
    let cancelled = false
    setLoading(true)
    api.customStatus(storeId)
      .then(res => { if (!cancelled) setStatus(res) })
      .catch(() => onToast('تعذّر جلب حالة الربط', 'error'))
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen, storeId])

  async function activate() {
    setBusy(true)
    try {
      const res = await api.customConnect(storeId)
      setSecret(res.signing_secret)
      setStatus({ connected: true, secret_set: true, endpoints: res.endpoints })
      onToast('تم تفعيل الربط مع متجرك', 'success')
      onChanged()
    } catch {
      onToast('تعذّر تفعيل الربط', 'error')
    } finally { setBusy(false) }
  }

  async function regen() {
    setBusy(true)
    try {
      const res = await api.customRegenerateSecret(storeId)
      setSecret(res.signing_secret)
      onToast('تم توليد مفتاح جديد — حدّث متجرك به', 'success')
    } catch {
      onToast('تعذّر توليد مفتاح جديد', 'error')
    } finally { setBusy(false) }
  }

  const connected = status?.connected

  return (
    <Modal isOpen={isOpen} onOpenChange={(o) => { if (!o) onClose() }} placement="center" backdrop="blur" size="lg">
      <ModalContent>
        {(close) => (
          <>
            <ModalHeader dir="rtl">
              <div className="flex items-center gap-3">
                <BrandLogo domain="" fallbackColor="#475569" fallbackLabel="API" size={30} />
                <div>
                  <p className="text-sm font-bold">ربط متجر مبرمَج خاص</p>
                  <p className="text-xs font-normal text-default-500">متجرك يدفع البيانات إلى حياك عبر API موقّع</p>
                </div>
              </div>
            </ModalHeader>
            <ModalBody dir="rtl">
              {loading ? (
                <div className="flex justify-center py-8"><Spinner color="primary" /></div>
              ) : !connected ? (
                <>
                  <p className="text-xs text-default-600 leading-relaxed">
                    فعّل الربط لتوليد <span className="font-semibold text-foreground">مفتاح توقيع</span> ونقاط الإرسال (endpoints).
                    بعدها يُرسل متجرك المنتجات والطلبات والسلات المتروكة إلى حياك ليعمل عليها المساعد الذكي.
                  </p>
                  <button onClick={activate} disabled={busy}
                    className="w-full py-2.5 text-xs font-bold rounded-xl bg-primary text-white hover:opacity-90 disabled:opacity-60 transition-opacity flex items-center justify-center gap-2">
                    {busy ? <><Spinner size="sm" color="white" /> جارٍ التفعيل...</> : 'تفعيل الربط'}
                  </button>
                </>
              ) : (
                <>
                  {secret ? (
                    <div className="bg-amber-50 dark:bg-amber-500/10 border border-amber-200 dark:border-amber-500/30 rounded-xl p-3">
                      <p className="text-[11px] font-bold text-amber-700 dark:text-amber-400 mb-2">
                        ⚠️ مفتاح التوقيع — يظهر مرة واحدة فقط. انسخه الآن واحفظه بأمان.
                      </p>
                      <CopyRow label="Signing Secret" value={secret} onToast={onToast} />
                    </div>
                  ) : (
                    <div className="bg-content2 rounded-xl p-3 text-[11px] text-default-500 leading-relaxed">
                      مفتاح التوقيع محفوظ ومخفي لأمانك. لو فقدته، ولّد مفتاحاً جديداً (يُلغي القديم فوراً).
                    </div>
                  )}

                  <CopyRow label="رفع الكتالوج (POST)" value={status?.endpoints.catalog || ''} onToast={onToast} />
                  <CopyRow label="إرسال الأحداث (POST)" value={status?.endpoints.events || ''} onToast={onToast} />

                  {typeof status?.products_count === 'number' && status.products_count > 0 && (
                    <p className="text-[11px] text-emerald-500 font-semibold">
                      آخر مزامنة: {status.products_count} منتج
                    </p>
                  )}

                  <div className="flex items-center justify-between pt-1">
                    <button onClick={regen} disabled={busy}
                      className="text-[11px] font-semibold text-default-400 hover:text-red-500 transition-colors disabled:opacity-50">
                      {busy ? 'جارٍ التوليد…' : 'توليد مفتاح توقيع جديد (يُلغي القديم)'}
                    </button>
                    <a href="/docs/custom-store" target="_blank" rel="noreferrer"
                      className="text-[11px] font-semibold text-violet-600 hover:underline">
                      دليل المطوّر ←
                    </a>
                  </div>
                </>
              )}
            </ModalBody>
            <ModalFooter>
              <button onClick={close} className="px-4 py-2 text-xs text-default-500 hover:text-foreground">إغلاق</button>
            </ModalFooter>
          </>
        )}
      </ModalContent>
    </Modal>
  )
}

/* ══════════════════════════════════ MAIN PAGE ══════════════════════════════════ */
export default function Integrations({ storeId }: Props) {
  const [searchParams, setSearchParams] = useSearchParams()
  const [integrations, setIntegrations] = useState<IntegrationDef[]>(
    INTEGRATIONS_DEF.map(d => ({ ...d, status: 'disconnected' as Status }))
  )
  const [loading, setLoading]   = useState(true)
  const [toast, setToast]       = useState<{ msg: string; type: 'success' | 'error' | 'info' } | null>(null)

  // Shopify install modal
  const [shopifyModal, setShopifyModal] = useState(false)
  const [shopDomain, setShopDomain]     = useState('')
  const [installing, setInstalling]     = useState(false)
  const [installError, setInstallError] = useState('')
  const [syncing, setSyncing]           = useState<string | null>(null)
  const [connectingZid, setConnectingZid] = useState(false)
  const [connectingTiktok, setConnectingTiktok] = useState(false)

  // Salla connect modal — Salla links ONLY via the App-Settings API key.
  const [sallaModal, setSallaModal]     = useState(false)
  // Custom-store connect modal (self-built stores push catalog + events).
  const [customModal, setCustomModal]   = useState(false)
  // "تحديث الربط" button busy state.
  const [refreshingLink, setRefreshingLink] = useState(false)

  // Disconnect confirmation modal
  const [disconnectTarget, setDisconnectTarget] = useState<string | null>(null)
  const [disconnecting, setDisconnecting]       = useState(false)

  function showToast(msg: string, type: 'success' | 'error' | 'info' = 'info') {
    setToast({ msg, type })
    setTimeout(() => setToast(null), 3500)
  }

  // Handle redirect back from Shopify OAuth + initial load (single effect to avoid race)
  useEffect(() => {
    const shopifyParam = searchParams.get('shopify')
    if (shopifyParam === 'connected') {
      showToast('تم الربط مع Shopify بنجاح! 🎉', 'success')
      const next = new URLSearchParams(searchParams)
      next.delete('shopify')
      setSearchParams(next, { replace: true })
    } else if (shopifyParam === 'error') {
      const reason = searchParams.get('reason')
      const msg = reason === 'shop_already_connected'
        ? 'هذا المتجر مربوط بحساب حياك آخر بالفعل'
        : 'فشل الربط مع Shopify — حاول مرة أخرى'
      showToast(msg, 'error')
      const next = new URLSearchParams(searchParams)
      next.delete('shopify')
      next.delete('reason')
      setSearchParams(next, { replace: true })
    }

    const zidParam = searchParams.get('zid')
    if (zidParam === 'connected') {
      showToast('تم الربط مع زد بنجاح! 🎉', 'success')
      const next = new URLSearchParams(searchParams)
      next.delete('zid')
      setSearchParams(next, { replace: true })
    } else if (zidParam === 'error') {
      showToast('فشل الربط مع زد — حاول مرة أخرى', 'error')
      const next = new URLSearchParams(searchParams)
      next.delete('zid')
      next.delete('reason')
      setSearchParams(next, { replace: true })
    }

    const tiktokParam = searchParams.get('tiktok')
    if (tiktokParam === 'connected') {
      showToast('تم الربط مع تيك توك بنجاح! 🎉', 'success')
      const next = new URLSearchParams(searchParams)
      next.delete('tiktok')
      setSearchParams(next, { replace: true })
    } else if (tiktokParam === 'error') {
      const reason = searchParams.get('reason')
      showToast(`فشل الربط مع تيك توك${reason ? ` (${reason})` : ''} — حاول مرة أخرى`, 'error')
      const next = new URLSearchParams(searchParams)
      next.delete('tiktok')
      next.delete('reason')
      setSearchParams(next, { replace: true })
    }
    loadIntegrations()
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [storeId])

  async function loadIntegrations() {
    setLoading(true)
    try {
      const res = await api.listIntegrations(storeId)
      const apiData = res.integrations || {}
      setIntegrations(INTEGRATIONS_DEF.map(def => {
        if (def.comingSoon) return { ...def, status: 'coming_soon' as Status }
        const d = apiData[def.id]
        return {
          ...def,
          status: d ? 'connected' as Status : 'disconnected' as Status,
          data:   d || undefined,
        }
      }))
    } catch {
      setIntegrations(INTEGRATIONS_DEF.map(d => ({
        ...d,
        status: (d.comingSoon ? 'coming_soon' : 'disconnected') as Status,
      })))
    } finally { setLoading(false) }
  }

  // ── "تحديث الربط" — explicit, merchant-initiated link refresh ─────────────
  // After the merchant pastes the API key in Salla and saves, they come back
  // here and press this button. No automatic polling, no surprise navigation.
  // Two outcomes:
  //   1. The signup placeholder was merged into the Salla store (its store_id
  //      changed server-side): swap to a fresh token for the canonical store and
  //      load its dashboard. The token is already in localStorage before we
  //      navigate, so it loads straight in — no login screen, same password.
  //   2. The store linked in place (already canonical): just re-read the
  //      integration status and update the cards.
  async function refreshLink() {
    setRefreshingLink(true)
    try {
      const newStore = await api.resolveLinkedSession()
      if (newStore) {
        showToast('تم تحديث الربط بنجاح ✅', 'success')
        window.location.assign(`/store/${newStore}/integrations`)
        return
      }
      // Repair the merchant→account binding so the storefront widget resolves
      // (asks Salla which store our token owns). Best-effort: harmless if Salla
      // isn't connected, or already bound.
      await api.repairSallaBinding(storeId).catch(() => null)
      await loadIntegrations()
      const connected = (await api.listIntegrations(storeId).catch(() => null))
        ?.integrations?.['salla']
      showToast(connected ? 'تم ربط متجر سلّة بنجاح! 🎉' : 'لم يكتمل الربط بعد — تأكد من حفظ المفتاح في سلة ثم أعد المحاولة', connected ? 'success' : 'info')
    } catch {
      showToast('تعذّر تحديث الربط — حاول مرة أخرى', 'error')
    } finally {
      setRefreshingLink(false)
    }
  }

  const ECOMMERCE_IDS = ['salla', 'shopify', 'zid', 'custom', 'woocommerce']

  function handleConnect(id: string) {
    // Enforce one ecommerce platform per account
    if (ECOMMERCE_IDS.includes(id)) {
      const conflict = integrations.find(
        i => ECOMMERCE_IDS.includes(i.id) && i.id !== id && i.status === 'connected'
      )
      if (conflict) {
        showToast(`أنت مربوط بـ ${conflict.name} بالفعل — لا يمكن ربط منصتَي تجارة إلكترونية في آنٍ واحد`, 'error')
        return
      }
    }
    if (id === 'shopify') { setShopDomain(''); setInstallError(''); setShopifyModal(true) }
    else if (id === 'salla') { setSallaModal(true) }   // API-key linking is the only Salla method
    else if (id === 'zid') { handleZidConnect() }
    else if (id === 'custom') { setCustomModal(true) }
    else if (id === 'tiktok') { handleTiktokConnect() }
    else showToast('هذا التكامل قيد التطوير وسيُتاح قريباً', 'info')
  }

  async function startShopifyInstall() {
    // Strip protocol prefix if user pasted a full URL
    let shop = shopDomain.trim().toLowerCase()
    shop = shop.replace(/^https?:\/\//, '').replace(/^https?\/\//, '')
    shop = shop.split('/')[0].split('?')[0]
    if (!shop) return
    setInstalling(true); setInstallError('')
    try {
      const { install_url } = await api.shopifyInstall(storeId, shop)
      // Open OAuth in the same window so the callback can redirect back cleanly
      window.location.href = install_url
    } catch (e) {
      setInstallError(e instanceof Error ? e.message : 'تعذّر بدء عملية الربط')
      setInstalling(false)
    }
  }

  async function handleZidConnect() {
    setConnectingZid(true)
    try {
      const { install_url } = await api.zidInstall(storeId)
      window.location.href = install_url
    } catch (e) {
      showToast(e instanceof Error ? e.message : 'تعذّر بدء عملية الربط مع زد', 'error')
      setConnectingZid(false)
    }
  }

  async function handleTiktokConnect() {
    setConnectingTiktok(true)
    try {
      const { install_url } = await api.tiktokInstall(storeId)
      window.location.href = install_url
    } catch (e) {
      showToast(e instanceof Error ? e.message : 'تعذّر بدء عملية الربط مع تيك توك', 'error')
      setConnectingTiktok(false)
    }
  }

  const SYNCABLE_IDS = ['shopify', 'zid']

  async function handleSync(id: string) {
    setSyncing(id)
    try {
      if (id === 'shopify') {
        const res = await api.shopifySync(storeId)
        showToast(`تمت المزامنة — ${res.products} منتج`, 'success')
      } else if (id === 'zid') {
        const res = await api.zidSync(storeId)
        showToast(`تمت المزامنة — ${res.products} منتج`, 'success')
      }
    } catch (e) {
      showToast(e instanceof Error ? e.message : 'فشلت المزامنة', 'error')
    } finally { setSyncing(null) }
  }

  function handleDisconnect(id: string) {
    setDisconnectTarget(id)
  }

  async function confirmDisconnect() {
    if (!disconnectTarget) return
    setDisconnecting(true)
    try {
      if (disconnectTarget === 'shopify') await api.shopifyDisconnect(storeId)
      else if (disconnectTarget === 'salla') await api.sallaDisconnect(storeId)
      else if (disconnectTarget === 'zid') await api.zidDisconnect(storeId)
      else if (disconnectTarget === 'custom') await api.customDisconnect(storeId)
      else if (disconnectTarget === 'tiktok') await api.tiktokDisconnect(storeId)
      await loadIntegrations()
      showToast('تم قطع الاتصال بنجاح', 'success')
    } catch (e) {
      showToast(e instanceof Error ? e.message : 'تعذّر قطع الاتصال', 'error')
    } finally { setDisconnecting(false); setDisconnectTarget(null) }
  }

  const categories = [
    { id: 'ecommerce', label: 'المتاجر الإلكترونية',
      icon: 'M16 11V7a4 4 0 00-8 0v4M5 9h14l1 12H4L5 9z',
      color: 'text-violet-400', bg: 'bg-violet-500/10' },
    { id: 'payment', label: 'بوابات الدفع',
      icon: 'M3 10h18M7 15h1m4 0h1m-7 4h12a3 3 0 003-3V8a3 3 0 00-3-3H6a3 3 0 00-3 3v8a3 3 0 003 3z',
      color: 'text-emerald-400', bg: 'bg-emerald-500/10' },
    { id: 'social', label: 'منصات التواصل',
      icon: 'M7 8h10M7 12h4m1 8l-4-4H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-4 4z',
      color: 'text-pink-400', bg: 'bg-pink-500/10' },
  ]

  const connectedCount = integrations.filter(i => i.status === 'connected').length

  return (
    <div className="min-h-screen bg-background p-6" dir="rtl">
      <div className="max-w-5xl mx-auto">

        {/* Header */}
        <div className="mb-8">
          <PageHeader
            title="التكاملات"
            subtitle="اربط متجرك بالمنصات والأدوات الخارجية"
            icon="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 10-5.656-5.656l-1.1 1.1"
            actions={
              <div className="flex items-center gap-2.5">
                <button
                  onClick={refreshLink}
                  disabled={refreshingLink}
                  title="بعد حفظ مفتاح الربط في سلة، اضغط هنا لتحديث حالة الربط"
                  className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-xs font-bold border border-divider text-foreground hover:bg-content2 transition-colors disabled:opacity-50"
                >
                  <Icon paths={['M23 4v6h-6', 'M1 20v-6h6', 'M3.51 9a9 9 0 0114.85-3.36L23 10', 'M1 14l4.64 4.36A9 9 0 0020.49 15']} size={13}
                    className={refreshingLink ? 'animate-spin' : ''} />
                  {refreshingLink ? 'جارٍ التحديث…' : 'تحديث الربط'}
                </button>
                <StatusPill tone="success" pulse label={`${connectedCount} متصل`} />
              </div>
            }
          />
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-24">
            <Spinner size="lg" color="primary" />
          </div>
        ) : (
          <>
            {categories.map(cat => {
              const items = integrations.filter(i => i.category === cat.id)
              return (
                <section key={cat.id} className="mb-10">
                  <div className="flex items-center gap-2.5 mb-4">
                    <div className={`w-7 h-7 rounded-xl ${cat.bg} flex items-center justify-center flex-shrink-0`}>
                      <Icon paths={cat.icon} size={14} className={cat.color} />
                    </div>
                    <h2 className="text-sm font-bold text-foreground">{cat.label}</h2>
                    <div className="flex-1 h-px bg-divider" />
                    <span className="text-[10px] text-default-400">
                      {items.filter(i => i.status === 'connected').length} / {items.length} متصل
                    </span>
                  </div>
                  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
                    {items.map(integration => (
                      <IntegrationCard
                        key={integration.id}
                        integration={integration}
                        onConnect={handleConnect}
                        onDisconnect={handleDisconnect}
                        onSync={SYNCABLE_IDS.includes(integration.id) ? handleSync : undefined}
                        onManage={integration.id === 'custom' ? () => setCustomModal(true) : undefined}
                        connecting={(integration.id === 'zid' && connectingZid) || (integration.id === 'tiktok' && connectingTiktok)}
                      />
                    ))}
                  </div>
                </section>
              )
            })}

            {/* Request new */}
            <div className="mt-4 border-2 border-dashed border-divider rounded-2xl p-8 text-center">
              <div className="w-12 h-12 mx-auto rounded-2xl bg-content2 flex items-center justify-center mb-3">
                <Icon paths={['M12 5v14', 'M5 12h14']} size={20} className="text-default-500" />
              </div>
              <p className="text-sm font-bold text-foreground mb-1">تريد تكاملاً آخر؟</p>
              <p className="text-xs text-default-500 mb-4">أخبرنا وسنضيفه في التحديثات القادمة</p>
              <a href="mailto:support@7ayak.app?subject=طلب تكامل جديد"
                className="inline-flex items-center gap-2 px-4 py-2 bg-content2 border border-divider rounded-xl text-xs font-semibold text-foreground hover:border-default-300 transition-colors">
                <Icon paths="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" size={13} />
                اقتراح تكامل
              </a>
            </div>
          </>
        )}
      </div>

      {/* ── Salla connect modal (API-key linking — the only Salla method) ── */}
      <SallaConnectModal
        isOpen={sallaModal}
        onClose={() => setSallaModal(false)}
        storeId={storeId}
        onToast={showToast}
      />

      {/* ── Custom store connect modal (push-based API integration) ── */}
      <CustomConnectModal
        isOpen={customModal}
        onClose={() => setCustomModal(false)}
        storeId={storeId}
        onToast={showToast}
        onChanged={loadIntegrations}
      />

      {/* ── Shopify install modal ── */}
      <Modal isOpen={shopifyModal} onOpenChange={setShopifyModal} placement="center" backdrop="blur" size="sm">
        <ModalContent>
          {(close) => (
            <>
              <ModalHeader dir="rtl">
                <div className="flex items-center gap-3">
                  <BrandLogo domain="shopify.com" fallbackColor="#96BF48" fallbackLabel="S" size={30} />
                  <div>
                    <p className="text-sm font-bold">ربط متجر Shopify</p>
                    <p className="text-xs font-normal text-default-500">أدخل رابط متجرك على شوبيفاي</p>
                  </div>
                </div>
              </ModalHeader>
              <ModalBody dir="rtl">
                <Input
                  autoFocus
                  label="رابط المتجر"
                  placeholder="my-store.myshopify.com"
                  value={shopDomain}
                  onValueChange={v => { setShopDomain(v); setInstallError('') }}
                  variant="bordered"
                  description="يمكنك كتابة الاسم فقط بدون .myshopify.com"
                  onKeyDown={e => { if (e.key === 'Enter') startShopifyInstall() }}
                  isInvalid={!!installError}
                  errorMessage={installError}
                  endContent={
                    !shopDomain.includes('.') && shopDomain
                      ? <span className="text-[10px] text-default-400 whitespace-nowrap">.myshopify.com</span>
                      : null
                  }
                />
                <div className="bg-content2 rounded-xl p-3 text-xs text-default-500 leading-relaxed">
                  <p className="font-semibold text-foreground mb-1">ما الذي سيُسمح لنا بقراءته؟</p>
                  <ul className="space-y-0.5 list-disc mr-4">
                    <li>الطلبات (قراءة فقط)</li>
                    <li>المنتجات والمخزون</li>
                    <li>بيانات العملاء</li>
                  </ul>
                  <p className="mt-2 text-[10px] text-default-600">لن نكتب أي بيانات في متجرك.</p>
                </div>
              </ModalBody>
              <ModalFooter>
                <button onClick={close} className="px-4 py-2 text-xs text-default-500 hover:text-foreground">
                  إلغاء
                </button>
                <button
                  onClick={startShopifyInstall}
                  disabled={!shopDomain.trim() || installing}
                  className="px-5 py-2 text-xs font-bold rounded-xl bg-[#96BF48] text-white hover:opacity-90 disabled:opacity-50 flex items-center gap-2">
                  {installing
                    ? <><Spinner size="sm" color="white" /> جاري التحويل...</>
                    : <>متابعة إلى Shopify <Icon paths="M15 19l-7-7 7-7" size={12} className="rotate-180" /></>
                  }
                </button>
              </ModalFooter>
            </>
          )}
        </ModalContent>
      </Modal>

      {/* ── Disconnect confirmation modal ── */}
      <Modal isOpen={!!disconnectTarget} onOpenChange={open => !open && setDisconnectTarget(null)} placement="center" backdrop="blur" size="sm">
        <ModalContent>
          {(close) => (
            <>
              <ModalHeader dir="rtl">
                <p className="text-sm font-bold text-red-500">قطع الاتصال</p>
              </ModalHeader>
              <ModalBody dir="rtl">
                <p className="text-sm text-foreground">
                  هل تريد فعلاً قطع الاتصال مع{' '}
                  <span className="font-bold">
                    {INTEGRATIONS_DEF.find(d => d.id === disconnectTarget)?.name}
                  </span>؟
                </p>
                <p className="text-xs text-default-500">
                  ستُحذف بيانات الربط من الخادم. يمكنك إعادة الربط في أي وقت.
                </p>
              </ModalBody>
              <ModalFooter>
                <button onClick={close} className="px-4 py-2 text-xs text-default-500 hover:text-foreground">إلغاء</button>
                <button
                  onClick={confirmDisconnect}
                  disabled={disconnecting}
                  className="px-5 py-2 text-xs font-bold rounded-xl bg-red-500 text-white hover:bg-red-600 disabled:opacity-50 flex items-center gap-2">
                  {disconnecting ? <Spinner size="sm" color="white" /> : null}
                  قطع الاتصال
                </button>
              </ModalFooter>
            </>
          )}
        </ModalContent>
      </Modal>

      {toast && <Toast msg={toast.msg} type={toast.type} />}
    </div>
  )
}
