import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Chip, Modal, ModalBody, ModalContent, ModalFooter, ModalHeader, Input, Spinner } from '@heroui/react'
import { api, IntegrationData } from '../../api'

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

/* ── Logos ── */
function SallaLogo({ size = 36 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 40 40" fill="none">
      <rect width={40} height={40} rx={10} fill="#6B3FA0" />
      <text x="50%" y="54%" dominantBaseline="middle" textAnchor="middle"
        fill="white" fontWeight="bold" fontSize="14" fontFamily="system-ui">س</text>
    </svg>
  )
}
function ShopifyLogo({ size = 36 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 40 40" fill="none">
      <rect width={40} height={40} rx={10} fill="#96BF48" />
      <text x="50%" y="54%" dominantBaseline="middle" textAnchor="middle"
        fill="white" fontWeight="bold" fontSize="13" fontFamily="system-ui">S</text>
    </svg>
  )
}
function MyFatoorahLogo({ size = 36 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 40 40" fill="none">
      <rect width={40} height={40} rx={10} fill="#00B0A6" />
      <text x="50%" y="54%" dominantBaseline="middle" textAnchor="middle"
        fill="white" fontWeight="bold" fontSize="11" fontFamily="system-ui">MF</text>
    </svg>
  )
}
function TabbyLogo({ size = 36 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 40 40" fill="none">
      <rect width={40} height={40} rx={10} fill="#3DBFA3" />
      <text x="50%" y="54%" dominantBaseline="middle" textAnchor="middle"
        fill="white" fontWeight="bold" fontSize="11" fontFamily="system-ui">tab</text>
    </svg>
  )
}
function TamaraLogo({ size = 36 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 40 40" fill="none">
      <rect width={40} height={40} rx={10} fill="#EB4C60" />
      <text x="50%" y="54%" dominantBaseline="middle" textAnchor="middle"
        fill="white" fontWeight="bold" fontSize="11" fontFamily="system-ui">تم</text>
    </svg>
  )
}
function ZidLogo({ size = 36 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 40 40" fill="none">
      <rect width={40} height={40} rx={10} fill="#1C3553" />
      <text x="50%" y="54%" dominantBaseline="middle" textAnchor="middle"
        fill="white" fontWeight="bold" fontSize="14" fontFamily="system-ui">ز</text>
    </svg>
  )
}
function WooLogo({ size = 36 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 40 40" fill="none">
      <rect width={40} height={40} rx={10} fill="#7F54B3" />
      <text x="50%" y="54%" dominantBaseline="middle" textAnchor="middle"
        fill="white" fontWeight="bold" fontSize="10" fontFamily="system-ui">Woo</text>
    </svg>
  )
}
function PayfortLogo({ size = 36 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 40 40" fill="none">
      <rect width={40} height={40} rx={10} fill="#003087" />
      <text x="50%" y="54%" dominantBaseline="middle" textAnchor="middle"
        fill="white" fontWeight="bold" fontSize="9" fontFamily="system-ui">FORT</text>
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
  { id: 'salla',       name: 'سلّة',            nameEn: 'Salla',        category: 'ecommerce', logo: <SallaLogo />,        description: 'متجرك على سلّة — الطلبات والمنتجات والعملاء تظهر مباشرةً في المحادثات.' },
  { id: 'shopify',     name: 'شوبيفاي',          nameEn: 'Shopify',      category: 'ecommerce', logo: <ShopifyLogo />,      description: 'اربط متجر شوبيفاي لإدارة الطلبات والمنتجات من لوحة تحكم واحدة.' },
  { id: 'zid',         name: 'زد',               nameEn: 'Zid',          category: 'ecommerce', logo: <ZidLogo />,          description: 'تكامل مع منصة زد للتجارة الإلكترونية.', comingSoon: true },
  { id: 'woocommerce', name: 'ووكومرس',           nameEn: 'WooCommerce',  category: 'ecommerce', logo: <WooLogo />,          description: 'ربط موقع ووردبريس/ووكومرس لمتابعة الطلبات.', comingSoon: true },
  { id: 'myfatoorah',  name: 'ماي فاتوره',       nameEn: 'MyFatoorah',   category: 'payment',   logo: <MyFatoorahLogo />,   description: 'إرسال روابط دفع مباشرة للعميل داخل المحادثة.', comingSoon: true },
  { id: 'tabby',       name: 'تابي',              nameEn: 'Tabby',        category: 'payment',   logo: <TabbyLogo />,        description: 'عرض خيار الدفع بالتقسيط عبر تابي.', comingSoon: true },
  { id: 'tamara',      name: 'تمارا',             nameEn: 'Tamara',       category: 'payment',   logo: <TamaraLogo />,       description: 'الشراء الآن والدفع لاحقاً عبر تمارا.', comingSoon: true },
  { id: 'payfort',     name: 'بيفورت',            nameEn: 'Payfort',      category: 'payment',   logo: <PayfortLogo />,      description: 'قبول مدفوعات البطاقات عبر بوابة Amazon Payment Services.', comingSoon: true },
]

/* ── Card ── */
function IntegrationCard({
  integration,
  onConnect,
  onDisconnect,
}: {
  integration: IntegrationDef
  onConnect:   (id: string) => void
  onDisconnect: (id: string) => void
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
          <Chip size="sm" color="default" variant="flat" className="text-[10px] font-bold text-slate-500">قريباً</Chip>
        ) : (
          <Chip size="sm" color="default" variant="flat" className="text-[10px]">غير متصل</Chip>
        )}
      </div>
      <div className="flex-1">
        <p className="text-sm font-bold text-foreground mb-1">
          {integration.name}
          {integration.nameEn && <span className="text-[10px] font-normal text-slate-500 mr-1.5">{integration.nameEn}</span>}
        </p>
        <p className="text-xs text-default-500 leading-relaxed">{integration.description}</p>
        {connected && integration.data?.shop_name && (
          <p className="text-[10px] text-emerald-500 mt-1.5 font-mono">{integration.data.shop_name}</p>
        )}
      </div>
      <div className="flex gap-2">
        {comingSoon ? (
          <button disabled className="flex-1 py-2 text-xs font-semibold rounded-xl border border-divider text-slate-500 cursor-not-allowed opacity-60">
            قريباً
          </button>
        ) : connected ? (
          <button onClick={() => onDisconnect(integration.id)}
            className="flex-1 py-2 text-xs font-semibold rounded-xl border border-red-200 text-red-500 hover:bg-red-50 transition-colors">
            قطع الاتصال
          </button>
        ) : (
          <button onClick={() => onConnect(integration.id)}
            className="flex-1 py-2 text-xs font-bold rounded-xl bg-primary text-white hover:opacity-90 transition-opacity">
            ربط الآن
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

  // Disconnect confirmation modal
  const [disconnectTarget, setDisconnectTarget] = useState<string | null>(null)
  const [disconnecting, setDisconnecting]       = useState(false)

  function showToast(msg: string, type: 'success' | 'error' | 'info' = 'info') {
    setToast({ msg, type })
    setTimeout(() => setToast(null), 3500)
  }

  // Handle redirect back from Shopify OAuth
  useEffect(() => {
    const shopifyParam = searchParams.get('shopify')
    if (shopifyParam === 'connected') {
      showToast('تم الربط مع Shopify بنجاح! 🎉', 'success')
      const next = new URLSearchParams(searchParams)
      next.delete('shopify')
      setSearchParams(next, { replace: true })
      loadIntegrations()
    } else if (shopifyParam === 'error') {
      showToast('فشل الربط مع Shopify — حاول مرة أخرى', 'error')
      const next = new URLSearchParams(searchParams)
      next.delete('shopify')
      next.delete('reason')
      setSearchParams(next, { replace: true })
    }
  }, [])

  useEffect(() => { loadIntegrations() }, [storeId])

  async function loadIntegrations() {
    setLoading(true)
    try {
      const res = await api.listIntegrations(storeId)
      const apiData = res.integrations || {}
      setIntegrations(INTEGRATIONS_DEF.map(def => {
        // salla is always connected (it's the main platform)
        if (def.id === 'salla') return { ...def, status: 'connected' as Status }
        if (def.comingSoon)     return { ...def, status: 'coming_soon' as Status }
        const d = apiData[def.id]
        return {
          ...def,
          status: d ? 'connected' as Status : 'disconnected' as Status,
          data:   d || undefined,
        }
      }))
    } catch {
      // On error still show the static list
      setIntegrations(INTEGRATIONS_DEF.map(d => ({
        ...d,
        status: (d.id === 'salla' ? 'connected' : d.comingSoon ? 'coming_soon' : 'disconnected') as Status,
      })))
    } finally { setLoading(false) }
  }

  function handleConnect(id: string) {
    if (id === 'shopify') { setShopDomain(''); setInstallError(''); setShopifyModal(true) }
    else showToast('هذا التكامل قيد التطوير وسيُتاح قريباً', 'info')
  }

  async function startShopifyInstall() {
    const shop = shopDomain.trim()
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

  function handleDisconnect(id: string) {
    if (id === 'salla') { showToast('لا يمكن فصل سلّة — هي القناة الرئيسية للمتجر', 'error'); return }
    setDisconnectTarget(id)
  }

  async function confirmDisconnect() {
    if (!disconnectTarget) return
    setDisconnecting(true)
    try {
      if (disconnectTarget === 'shopify') await api.shopifyDisconnect(storeId)
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
  ]

  const connectedCount = integrations.filter(i => i.status === 'connected').length

  return (
    <div className="min-h-screen bg-background p-6" dir="rtl">
      <div className="max-w-5xl mx-auto">

        {/* Header */}
        <div className="flex items-start justify-between gap-4 mb-8">
          <div>
            <h1 className="text-2xl font-extrabold text-foreground mb-1">التكاملات</h1>
            <p className="text-sm text-default-500">اربط متجرك بالمنصات والأدوات الخارجية</p>
          </div>
          <div className="flex items-center gap-2 px-4 py-2.5 bg-content1 border border-divider rounded-2xl flex-shrink-0">
            <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
            <span className="text-xs font-bold text-foreground">{connectedCount}</span>
            <span className="text-xs text-default-500">متصل</span>
          </div>
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
                      />
                    ))}
                  </div>
                </section>
              )
            })}

            {/* Request new */}
            <div className="mt-4 border-2 border-dashed border-divider rounded-2xl p-8 text-center">
              <div className="w-12 h-12 mx-auto rounded-2xl bg-content2 flex items-center justify-center mb-3">
                <Icon paths={['M12 5v14', 'M5 12h14']} size={20} className="text-slate-500" />
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

      {/* ── Shopify install modal ── */}
      <Modal isOpen={shopifyModal} onOpenChange={setShopifyModal} placement="center" backdrop="blur" size="sm">
        <ModalContent>
          {(close) => (
            <>
              <ModalHeader dir="rtl">
                <div className="flex items-center gap-3">
                  <ShopifyLogo size={30} />
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
                  <p className="mt-2 text-[10px] text-slate-600">لن نكتب أي بيانات في متجرك.</p>
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
