import { useState } from 'react'
import { Chip } from '@heroui/react'

interface Props { storeId: string }

/* ── Generic icon helper ── */
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

/* ── Platform logos ── */
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
      <path d="M26.5 11.5c-.1-.7-.7-1-1.2-1.1-.5 0-1.9-.1-2-.1-.1 0-1.1-3-2.3-3-1.3 0-2.1 1-2.1 1s-.8-.3-1.9-.1l-.8 5.6 9.3.7zM19 27.5l8.5-1.7-1.2-8.5L18 18l1 9.5z"
        fill="white" fillOpacity="0.9" />
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
type IntegrationStatus = 'connected' | 'disconnected' | 'coming_soon'

interface Integration {
  id: string
  name: string
  nameEn?: string
  description: string
  logo: React.ReactNode
  status: IntegrationStatus
  category: string
  docsUrl?: string
}

/* ── Integration card ── */
function IntegrationCard({
  integration,
  onConnect,
  onDisconnect,
}: {
  integration: Integration
  onConnect: (id: string) => void
  onDisconnect: (id: string) => void
}) {
  const isConnected   = integration.status === 'connected'
  const isComingSoon  = integration.status === 'coming_soon'

  return (
    <div className={`
      relative bg-content1 border rounded-2xl p-5 flex flex-col gap-4 transition-all
      ${isConnected
        ? 'border-emerald-500/30 shadow-[0_0_0_1px_rgba(16,185,129,0.1)]'
        : 'border-divider hover:border-default-300'
      }
    `}>
      {/* Connected glow top edge */}
      {isConnected && (
        <div className="absolute top-0 left-0 right-0 h-0.5 bg-gradient-to-r from-transparent via-emerald-500 to-transparent rounded-t-2xl" />
      )}

      {/* Header: logo + status */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex-shrink-0">
          {integration.logo}
        </div>
        {isConnected ? (
          <Chip size="sm" color="success" variant="flat"
            startContent={<span className="w-1.5 h-1.5 bg-emerald-500 rounded-full animate-pulse" />}
            className="text-[10px] font-bold">
            متصل
          </Chip>
        ) : isComingSoon ? (
          <Chip size="sm" color="default" variant="flat" className="text-[10px] font-bold text-slate-500">
            قريباً
          </Chip>
        ) : (
          <Chip size="sm" color="default" variant="flat" className="text-[10px]">
            غير متصل
          </Chip>
        )}
      </div>

      {/* Name + description */}
      <div className="flex-1">
        <p className="text-sm font-bold text-foreground mb-1">
          {integration.name}
          {integration.nameEn && (
            <span className="text-[10px] font-normal text-slate-500 mr-1.5">{integration.nameEn}</span>
          )}
        </p>
        <p className="text-xs text-default-500 leading-relaxed">{integration.description}</p>
      </div>

      {/* Action */}
      <div className="flex gap-2">
        {isComingSoon ? (
          <button disabled
            className="flex-1 py-2 text-xs font-semibold rounded-xl border border-divider text-slate-500 cursor-not-allowed opacity-60">
            قريباً
          </button>
        ) : isConnected ? (
          <button
            onClick={() => onDisconnect(integration.id)}
            className="flex-1 py-2 text-xs font-semibold rounded-xl border border-red-200 text-red-500 hover:bg-red-50 transition-colors">
            قطع الاتصال
          </button>
        ) : (
          <button
            onClick={() => onConnect(integration.id)}
            className="flex-1 py-2 text-xs font-bold rounded-xl bg-primary text-white hover:opacity-90 transition-opacity">
            ربط الآن
          </button>
        )}
        {integration.docsUrl && (
          <a href={integration.docsUrl} target="_blank" rel="noopener noreferrer"
            className="p-2 rounded-xl border border-divider text-slate-500 hover:text-slate-300 hover:border-slate-500 transition-colors">
            <Icon paths="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" size={14} />
          </a>
        )}
      </div>
    </div>
  )
}

/* ── Toast ── */
function Toast({ msg, type }: { msg: string; type: 'success' | 'error' | 'info' }) {
  const colors = {
    success: 'bg-emerald-500',
    error:   'bg-red-500',
    info:    'bg-blue-500',
  }
  return (
    <div className={`fixed bottom-6 left-1/2 -translate-x-1/2 z-50 ${colors[type]} text-white text-xs font-bold px-5 py-2.5 rounded-full shadow-xl flex items-center gap-2`}>
      {type === 'success' && <Icon paths="M5 13l4 4L19 7" size={13} />}
      {type === 'error'   && <Icon paths={['M18 6L6 18', 'M6 6l12 12']} size={13} />}
      {type === 'info'    && <Icon paths="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" size={13} />}
      {msg}
    </div>
  )
}

/* ══════════════════════════════════════════ MAIN PAGE ══════════════════════════════════════════ */
export default function Integrations({ storeId: _storeId }: Props) {
  const [toast, setToast] = useState<{ msg: string; type: 'success' | 'error' | 'info' } | null>(null)

  function showToast(msg: string, type: 'success' | 'error' | 'info' = 'info') {
    setToast({ msg, type })
    setTimeout(() => setToast(null), 3000)
  }

  const [integrations, setIntegrations] = useState<Integration[]>([
    /* ── المتاجر الإلكترونية ── */
    {
      id: 'salla',
      name: 'سلّة',
      nameEn: 'Salla',
      description: 'ربط متجرك على سلّة لعرض الطلبات والمنتجات والعملاء مباشرةً في المحادثات.',
      logo: <SallaLogo />,
      status: 'connected',
      category: 'ecommerce',
    },
    {
      id: 'shopify',
      name: 'شوبيفاي',
      nameEn: 'Shopify',
      description: 'اربط متجر شوبيفاي لإدارة الطلبات والمنتجات من لوحة تحكم واحدة.',
      logo: <ShopifyLogo />,
      status: 'coming_soon',
      category: 'ecommerce',
    },
    {
      id: 'zid',
      name: 'زد',
      nameEn: 'Zid',
      description: 'تكامل مع منصة زد للتجارة الإلكترونية لعرض بيانات متجرك تلقائياً.',
      logo: <ZidLogo />,
      status: 'coming_soon',
      category: 'ecommerce',
    },
    {
      id: 'woocommerce',
      name: 'ووكومرس',
      nameEn: 'WooCommerce',
      description: 'ربط موقع ووردبريس/ووكومرس لمتابعة الطلبات وخدمة العملاء.',
      logo: <WooLogo />,
      status: 'coming_soon',
      category: 'ecommerce',
    },

    /* ── بوابات الدفع ── */
    {
      id: 'myfatoorah',
      name: 'ماي فاتوره',
      nameEn: 'MyFatoorah',
      description: 'إرسال روابط دفع مباشرة للعميل داخل المحادثة وتتبع حالة الدفع فوراً.',
      logo: <MyFatoorahLogo />,
      status: 'disconnected',
      category: 'payment',
    },
    {
      id: 'tabby',
      name: 'تابي',
      nameEn: 'Tabby',
      description: 'عرض خيار الدفع بالتقسيط عبر تابي مع متابعة الطلبات مباشرةً.',
      logo: <TabbyLogo />,
      status: 'coming_soon',
      category: 'payment',
    },
    {
      id: 'tamara',
      name: 'تمارا',
      nameEn: 'Tamara',
      description: 'تكامل مع تمارا لتقديم خيارات الشراء الآن والدفع لاحقاً لعملائك.',
      logo: <TamaraLogo />,
      status: 'coming_soon',
      category: 'payment',
    },
    {
      id: 'payfort',
      name: 'بيفورت (Amazon Payment)',
      nameEn: 'Payfort',
      description: 'قبول مدفوعات البطاقات عبر بوابة بيفورت الآمنة مع تقارير مفصّلة.',
      logo: <PayfortLogo />,
      status: 'coming_soon',
      category: 'payment',
    },
  ])

  function handleConnect(id: string) {
    // سلّة متصلة دائماً كمثال — غيرها يعرض رسالة "قريباً"
    if (id === 'myfatoorah') {
      showToast('جاري فتح صفحة ربط ماي فاتوره...', 'info')
      setTimeout(() => {
        setIntegrations(prev =>
          prev.map(i => i.id === id ? { ...i, status: 'connected' } : i)
        )
        showToast('تم الربط مع ماي فاتوره بنجاح!', 'success')
      }, 1500)
    } else {
      showToast('هذا التكامل قيد التطوير وسيُتاح قريباً', 'info')
    }
  }

  function handleDisconnect(id: string) {
    if (id === 'salla') {
      showToast('لا يمكن فصل سلّة — هي القناة الرئيسية لمتجرك.', 'error')
      return
    }
    setIntegrations(prev =>
      prev.map(i => i.id === id ? { ...i, status: 'disconnected' } : i)
    )
    showToast('تم قطع الاتصال بنجاح', 'success')
  }

  const categories = [
    { id: 'ecommerce', label: 'المتاجر الإلكترونية',
      icon: 'M16 11V7a4 4 0 00-8 0v4M5 9h14l1 12H4L5 9z',
      color: 'text-violet-400', bg: 'bg-violet-500/10' },
    { id: 'payment',   label: 'بوابات الدفع',
      icon: 'M3 10h18M7 15h1m4 0h1m-7 4h12a3 3 0 003-3V8a3 3 0 00-3-3H6a3 3 0 00-3 3v8a3 3 0 003 3z',
      color: 'text-emerald-400', bg: 'bg-emerald-500/10' },
  ]

  const connectedCount = integrations.filter(i => i.status === 'connected').length

  return (
    <div className="min-h-screen bg-background p-6" dir="rtl">

      {/* ── Page header ── */}
      <div className="max-w-5xl mx-auto">
        <div className="flex items-start justify-between gap-4 mb-8">
          <div>
            <h1 className="text-2xl font-extrabold text-foreground mb-1">التكاملات</h1>
            <p className="text-sm text-default-500">
              اربط متجرك بالمنصات والأدوات الخارجية لتجربة خدمة عملاء أقوى
            </p>
          </div>
          <div className="flex items-center gap-2 px-4 py-2.5 bg-content1 border border-divider rounded-2xl flex-shrink-0">
            <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
            <span className="text-xs font-bold text-foreground">{connectedCount}</span>
            <span className="text-xs text-default-500">متصل</span>
          </div>
        </div>

        {/* ── Categories ── */}
        {categories.map(cat => {
          const items = integrations.filter(i => i.category === cat.id)
          return (
            <section key={cat.id} className="mb-10">
              {/* Category header */}
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

              {/* Cards grid */}
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

        {/* ── Request new integration ── */}
        <div className="mt-6 border-2 border-dashed border-divider rounded-2xl p-8 text-center">
          <div className="w-12 h-12 mx-auto rounded-2xl bg-content2 flex items-center justify-center mb-3">
            <Icon paths={['M12 5v14', 'M5 12h14']} size={20} className="text-slate-500" />
          </div>
          <p className="text-sm font-bold text-foreground mb-1">تريد تكاملاً آخر؟</p>
          <p className="text-xs text-default-500 mb-4">
            إذا كان لديك منصة أو أداة تريد ربطها، أخبرنا وسنضيفها في التحديثات القادمة
          </p>
          <a
            href="mailto:support@7ayak.app?subject=طلب تكامل جديد"
            className="inline-flex items-center gap-2 px-4 py-2 bg-content2 border border-divider rounded-xl text-xs font-semibold text-foreground hover:border-default-300 transition-colors"
          >
            <Icon paths="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" size={13} />
            اقتراح تكامل
          </a>
        </div>
      </div>

      {/* Toast */}
      {toast && <Toast msg={toast.msg} type={toast.type} />}
    </div>
  )
}
