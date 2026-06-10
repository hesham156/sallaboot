import { useEffect, useState, lazy, Suspense } from 'react'
import { useNavigate, useParams, Routes, Route, useLocation } from 'react-router-dom'
import { Avatar, Spinner } from '@heroui/react'
import { api, ApiError, StoreInfo, clearAuth, getIsSuper, getEmployee } from '../api'
import ErrorPage from './ErrorPage'

// Lazy-load each page so the initial bundle stays small. Heavy deps like
// recharts (Analytics/Overview) only download when that page is opened.
const Overview       = lazy(() => import('./store/Overview'))
const Conversations  = lazy(() => import('./store/Conversations'))
const Products       = lazy(() => import('./store/Products'))
const Analytics      = lazy(() => import('./store/Analytics'))
const Settings       = lazy(() => import('./store/Settings'))
const Orders         = lazy(() => import('./store/Orders'))
const AbandonedCarts = lazy(() => import('./store/AbandonedCarts'))
const Pricing        = lazy(() => import('./store/Pricing'))
const Brain          = lazy(() => import('./store/Brain'))
const Training       = lazy(() => import('./store/Training'))
const Employees      = lazy(() => import('./store/Employees'))
const LlmUsage       = lazy(() => import('./store/LlmUsage'))
const SupportAccess    = lazy(() => import('./store/SupportAccess'))
const WhatsAppEvents   = lazy(() => import('./store/WhatsAppEvents'))

/* ── Icon helper ── */
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

// Role-based access:
//   owner   = store owner (no employee in token)
//   manager = employee with role='manager'
//   agent   = employee with role='agent'  → customer-service only
// `roles` lists who can see/access the item. Omit → everyone.
type Role = 'owner' | 'manager' | 'agent'

const NAV_ITEMS: Array<{
  key: string
  label: string
  icon: string[]
  activeColor: string
  activeBg: string
  activeBorder: string
  printingOnly?: boolean
  roles?: Role[]
}> = [
  {
    key: '',
    label: 'نظرة عامة',
    icon: ['M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6'],
    activeColor: 'text-blue-400',
    activeBg: 'bg-blue-500/10',
    activeBorder: 'border-r-blue-500',
  },
  {
    key: 'conversations',
    label: 'المحادثات',
    icon: ['M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z'],
    activeColor: 'text-violet-400',
    activeBg: 'bg-violet-500/10',
    activeBorder: 'border-r-violet-500',
  },
  {
    key: 'products',
    label: 'المنتجات',
    icon: ['M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4'],
    activeColor: 'text-emerald-400',
    activeBg: 'bg-emerald-500/10',
    activeBorder: 'border-r-emerald-500',
    roles: ['owner', 'manager'],
  },
  {
    key: 'orders',
    label: 'الطلبات',
    icon: ['M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2'],
    activeColor: 'text-sky-400',
    activeBg: 'bg-sky-500/10',
    activeBorder: 'border-r-sky-500',
  },
  {
    key: 'carts',
    label: 'سلات متروكة',
    icon: ['M3 3h2l.4 2M7 13h10l4-8H5.4M7 13L5.4 5M7 13l-2.293 2.293c-.63.63-.184 1.707.707 1.707H17m0 0a2 2 0 100 4 2 2 0 000-4zm-8 2a2 2 0 11-4 0 2 2 0 014 0z'],
    activeColor: 'text-orange-400',
    activeBg: 'bg-orange-500/10',
    activeBorder: 'border-r-orange-500',
  },
  {
    key: 'analytics',
    label: 'التحليلات',
    icon: ['M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z'],
    activeColor: 'text-pink-400',
    activeBg: 'bg-pink-500/10',
    activeBorder: 'border-r-pink-500',
    roles: ['owner', 'manager'],
  },
  {
    key: 'pricing',
    label: 'حاسبة الأسعار',
    icon: ['M9 7h6m0 10v-3m-3 3h.01M9 17h.01M9 14h.01M12 14h.01M15 11h.01M12 11h.01M9 11h.01M7 21h10a2 2 0 002-2V5a2 2 0 00-2-2H7a2 2 0 00-2 2v14a2 2 0 002 2z'],
    activeColor: 'text-cyan-400',
    activeBg: 'bg-cyan-500/10',
    activeBorder: 'border-r-cyan-500',
    printingOnly: true,
    roles: ['owner', 'manager'],
  },
  {
    key: 'brain',
    label: 'ذاكرة الـ AI',
    icon: ['M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z'],
    activeColor: 'text-purple-400',
    activeBg: 'bg-purple-500/10',
    activeBorder: 'border-r-purple-500',
    roles: ['owner', 'manager'],
  },
  {
    key: 'employees',
    label: 'الموظفون',
    icon: ['M16 7a4 4 0 11-8 0 4 4 0 018 0z', 'M12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z'],
    activeColor: 'text-amber-400',
    activeBg: 'bg-amber-500/10',
    activeBorder: 'border-r-amber-500',
    roles: ['owner'],
  },
  {
    key: 'llm-usage',
    label: 'استهلاك الذكاء',
    icon: ['M13 10V3L4 14h7v7l9-11h-7z'],
    activeColor: 'text-rose-400',
    activeBg: 'bg-rose-500/10',
    activeBorder: 'border-r-rose-500',
    roles: ['owner', 'manager'],
  },
  {
    key: 'training',
    label: 'تدريب البوت',
    icon: ['M12 14l9-5-9-5-9 5 9 5z', 'M12 14l6.16-3.422a12.083 12.083 0 01.665 6.479A11.952 11.952 0 0012 20.055a11.952 11.952 0 00-6.824-2.998 12.078 12.078 0 01.665-6.479L12 14z'],
    activeColor: 'text-fuchsia-400',
    activeBg: 'bg-fuchsia-500/10',
    activeBorder: 'border-r-fuchsia-500',
    roles: ['owner', 'manager'],
  },
  {
    key: 'whatsapp-events',
    label: 'أحداث WhatsApp',
    icon: ['M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347z', 'M11.5 2C6.253 2 2 6.253 2 11.5c0 1.82.487 3.53 1.338 5.003L2 22l5.588-1.326A9.45 9.45 0 0 0 11.5 21c5.247 0 9.5-4.253 9.5-9.5S16.747 2 11.5 2z'],
    activeColor: 'text-green-500',
    activeBg: 'bg-green-500/10',
    activeBorder: 'border-r-green-500',
    roles: ['owner', 'manager'],
  },
  {
    key: 'support-access',
    label: 'وصول الدعم',
    icon: ['M16 11V7a4 4 0 1 0-8 0v4', 'M5 11h14v10H5z'],
    activeColor: 'text-orange-400',
    activeBg: 'bg-orange-500/10',
    activeBorder: 'border-r-orange-500',
    roles: ['owner'],
  },
  {
    key: 'settings',
    label: 'الإعدادات',
    icon: ['M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z', 'M15 12a3 3 0 11-6 0 3 3 0 016 0z'],
    activeColor: 'text-slate-600',
    activeBg: 'bg-slate-500/10',
    activeBorder: 'border-r-slate-400',
    roles: ['owner'],
  },
]

/** Resolve the current user's role from the persisted session token. */
function getCurrentRole(): Role {
  const emp = getEmployee()
  if (!emp) return 'owner'
  return emp.role === 'manager' ? 'manager' : 'agent'
}

/** Shown when a user opens a route their role can't access. */
function Forbidden() {
  return (
    <div className="flex flex-col items-center justify-center min-h-[60vh] text-center px-6" dir="rtl">
      <div className="w-16 h-16 rounded-3xl bg-red-500/10 text-red-500 flex items-center justify-center mb-4">
        <svg width={28} height={28} viewBox="0 0 24 24" fill="none" stroke="currentColor"
             strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
          <path d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2z" />
          <path d="M12 7V7a4 4 0 018 0v4H4V7a4 4 0 018 0z" />
        </svg>
      </div>
      <p className="text-base font-semibold text-foreground">صلاحيتك لا تسمح بفتح هذه الصفحة</p>
      <p className="text-xs text-slate-500 mt-1">تواصل مع مالك المتجر لو احتجت وصولاً إضافياً.</p>
    </div>
  )
}

export default function StoreDashboard() {
  const { storeId = '' } = useParams<{ storeId: string }>()
  const navigate  = useNavigate()
  const location  = useLocation()
  const [store, setStore]         = useState<StoreInfo | null>(null)
  const [botEnabled, setBotEnabled]   = useState(true)
  const [loadingBot, setLoadingBot]   = useState(false)
  const [storeType, setStoreType]     = useState<'printing' | 'general'>('printing')
  const [sidebarOpen, setSidebarOpen] = useState(false)   // mobile drawer
  // Initial-load error status so we can render a real error page instead
  // of an infinite spinner. Holds the HTTP status (403, 500, …) or null.
  const [loadErrorStatus, setLoadErrorStatus] = useState<number | null>(null)
  // Special-case: super admin tried to enter a store that didn't grant
  // access. Distinguished from a generic 403 so we can render an
  // actionable "ask the merchant" page instead of the styled error page.
  const [needsSupportAccess, setNeedsSupportAccess] = useState(false)

  const basePath     = `/store/${storeId}`
  // First path segment after /store/:storeId/ — strip sub-routes so the
  // sidebar still highlights "المحادثات" when you're inside one specific
  // conversation (/conversations/:sessionId).
  const relativePath = location.pathname.replace(basePath, '').replace(/^\//, '')
  const topSegment   = relativePath.split('/')[0]
  const activeKey    = NAV_ITEMS.find(n => n.key === topSegment)?.key ?? ''
  const employee     = getEmployee()
  const role         = getCurrentRole()
  const canSee = (item: { roles?: Role[] }) =>
    !item.roles || item.roles.includes(role)

  useEffect(() => { loadStore() }, [storeId])

  async function loadStore() {
    setLoadErrorStatus(null)  // clear stale error so a retry on the same mount can recover
    setNeedsSupportAccess(false)
    try {
      const [storeInfo, botRes, aiRes] = await Promise.all([
        api.getStoreInfo(storeId),
        api.botStatus(storeId),
        api.getAI(storeId).catch(() => null),
      ])
      setStore(storeInfo)
      setBotEnabled(botRes.bot_globally_enabled)
      if (aiRes?.store_type) setStoreType(aiRes.store_type === 'printing' ? 'printing' : 'general')
    } catch (e) {
      console.error(e)
      // Surface the failure as a real error page rather than letting the
      // loading spinner spin forever. 401 = token invalid/expired — kick
      // the user back to /login so they re-authenticate; 403/404/etc.
      // get the matching styled error page.
      if (e instanceof ApiError) {
        if (e.status === 401) {
          clearAuth()
          navigate('/login', { replace: true })
          return
        }
        // The specific "super needs grant" 403 gets its own UX — the
        // generic ErrorPage(403) doesn't tell the super what to do.
        if (e.status === 403 && e.detail === 'support_access_required') {
          setNeedsSupportAccess(true)
          return
        }
        setLoadErrorStatus(e.status)
      } else {
        setLoadErrorStatus(500)
      }
    }
  }

  async function toggleBot() {
    setLoadingBot(true)
    try {
      const res = await api.botToggle(storeId, !botEnabled)
      setBotEnabled(res.bot_globally_enabled)
    } finally { setLoadingBot(false) }
  }

  function logout()        { clearAuth(); navigate('/login', { replace: true }) }
  function goTab(key: string) {
    navigate(key ? `${basePath}/${key}` : basePath)
    setSidebarOpen(false)   // close the mobile drawer after navigating
  }

  if (needsSupportAccess) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-50 px-4" dir="rtl">
        <div className="max-w-lg w-full bg-white rounded-3xl shadow-xl border border-amber-100 p-10 text-center">
          <div className="w-16 h-16 mx-auto rounded-2xl bg-amber-50 text-amber-600 flex items-center justify-center mb-5">
            <svg width={30} height={30} viewBox="0 0 24 24" fill="none" stroke="currentColor"
                 strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round">
              <path d="M16 11V7a4 4 0 1 0-8 0v4" />
              <path d="M5 11h14v10H5z" />
            </svg>
          </div>
          <h1 className="text-2xl font-extrabold text-slate-900">يلزم إذن من مالك المتجر</h1>
          <p className="mt-3 text-sm text-slate-600 leading-relaxed">
            لا يمكنك الدخول على لوحة هذا المتجر إلا بعد أن يفتح المالك نافذة وصول محدودة بالوقت.
            تواصل معه ليفتح <span className="font-bold">"وصول الدعم"</span> من إعدادات متجره.
          </p>
          <p className="mt-2 text-xs text-slate-400">
            القرار في يد المالك. كل وصول مسجَّل ومحدّد بوقت.
          </p>
          <div className="mt-7 flex flex-wrap justify-center gap-3">
            <button
              onClick={() => loadStore()}
              className="px-4 py-2 rounded-xl bg-content2 border border-divider text-sm font-semibold hover:bg-content3"
            >
              إعادة المحاولة
            </button>
            <button
              onClick={() => navigate('/admin/platform-ops')}
              className="px-4 py-2 rounded-xl bg-primary text-white text-sm font-semibold hover:opacity-90"
            >
              عودة إلى لوحة العمليات
            </button>
          </div>
        </div>
      </div>
    )
  }

  if (loadErrorStatus !== null) {
    return <ErrorPage code={loadErrorStatus} />
  }

  if (!store) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-background">
        <Spinner size="lg" color="primary" label="جاري التحميل..." />
      </div>
    )
  }

  const activeItem = NAV_ITEMS.find(n => n.key === activeKey)!

  return (
    <div className="flex min-h-screen bg-background" dir="rtl">

      {/* ── Mobile top bar (hamburger) — hidden on md+ ── */}
      <div className="md:hidden fixed top-0 inset-x-0 h-14 bg-content1 border-b border-divider z-30 flex items-center justify-between px-4">
        <button
          onClick={() => setSidebarOpen(true)}
          aria-label="فتح القائمة"
          className="w-9 h-9 rounded-lg flex items-center justify-center text-default-600 hover:bg-content2"
        >
          <Icon paths={['M4 6h16', 'M4 12h16', 'M4 18h16']} size={20} />
        </button>
        <span className="font-bold text-sm text-foreground truncate">{store.store_name}</span>
      </div>

      {/* ── Mobile backdrop ── */}
      {sidebarOpen && (
        <div
          className="md:hidden fixed inset-0 bg-black/40 z-40"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* ════════════ SIDEBAR ════════════ */}
      <aside className={`w-60 bg-content1 border-l border-divider shadow-soft flex flex-col fixed right-0 h-screen z-50 transition-transform duration-300 ${
        sidebarOpen ? 'translate-x-0' : 'translate-x-full'
      } md:translate-x-0`}>

        {/* ── Store header ── */}
        <div className="p-4 border-b border-divider">
          <div className="flex items-center gap-3">
            <div className="relative flex-shrink-0">
              <Avatar
                src={store.store_avatar || undefined}
                name={store.store_name[0]}
                size="sm"
                className="bg-gradient-to-br from-teal-500 to-cyan-600 text-white font-bold"
              />
              {/* Bot status dot */}
              <span className={`absolute -bottom-0.5 -left-0.5 w-2.5 h-2.5 rounded-full border-2 border-content1 ${
                botEnabled ? 'bg-emerald-500' : 'bg-default-300'
              }`} />
            </div>
            <div className="min-w-0">
              <p className="font-bold text-sm text-foreground truncate">{store.store_name}</p>
              <p className="text-xs text-default-400 font-mono truncate">{store.store_id}</p>
            </div>
          </div>
          {/* Employee identity badge — only shown when logged in as an employee */}
          {employee && (
            <div className="mt-3 flex items-center gap-2 px-3 py-2 rounded-xl bg-amber-500/10 border border-amber-500/20">
              <div className="w-6 h-6 rounded-full bg-gradient-to-br from-amber-500 to-orange-600 text-white text-[10px] font-bold flex items-center justify-center flex-shrink-0">
                {employee.name.trim().charAt(0) || '?'}
              </div>
              <div className="min-w-0 flex-1">
                <p className="text-xs font-bold text-amber-700 truncate leading-tight">{employee.name}</p>
                <p className="text-[10px] text-amber-600/80">
                  {role === 'manager' ? 'مدير' : 'موظف خدمة عملاء'}
                </p>
              </div>
            </div>
          )}
        </div>

        {/* ── Navigation ── */}
        <nav className="flex-1 py-2 overflow-y-auto">
          {NAV_ITEMS
            .filter(item => !item.printingOnly || storeType === 'printing')
            .filter(canSee)
            .map(item => {
            const isActive = activeKey === item.key
            return (
              <button
                key={item.key}
                onClick={() => goTab(item.key)}
                className={`
                  w-full flex items-center gap-3 px-4 py-2.5 text-sm font-medium text-right
                  border-r-2 transition-all duration-150
                  ${isActive
                    ? `${item.activeBg} ${item.activeColor} ${item.activeBorder}`
                    : 'border-r-transparent text-default-500 hover:text-foreground hover:bg-content2'
                  }
                `}
              >
                <Icon
                  paths={item.icon}
                  size={16}
                  className={`flex-shrink-0 ${isActive ? item.activeColor : 'text-default-400'}`}
                />
                <span>{item.label}</span>
              </button>
            )
          })}
        </nav>

        {/* ── Footer ── */}
        <div className="p-3 border-t border-divider space-y-2">
          {/* Bot toggle */}
          <button
            onClick={!loadingBot ? toggleBot : undefined}
            className={`
              w-full flex items-center gap-3 px-3 py-2.5 rounded-xl border text-sm
              transition-all duration-200
              ${botEnabled
                ? 'bg-emerald-50 border-emerald-200 text-emerald-700 hover:bg-emerald-100'
                : 'bg-content2 border-divider text-default-500 hover:text-foreground hover:border-default-300'
              }
            `}
          >
            {loadingBot ? (
              <Spinner size="sm" color="success" />
            ) : (
              <span className={`w-2 h-2 rounded-full flex-shrink-0 ${
                botEnabled ? 'bg-emerald-500 animate-pulse-dot' : 'bg-default-400'
              }`} />
            )}
            <span className="font-semibold flex-1 text-right">
              {botEnabled ? 'البوت شغّال' : 'البوت موقوف'}
            </span>
            <span className={`text-xs ${botEnabled ? 'text-emerald-600' : 'text-default-400'}`}>
              {botEnabled ? 'إيقاف' : 'تشغيل'}
            </span>
          </button>

          {/* Action buttons */}
          <div className="flex gap-1.5">
            {getIsSuper() && (
              <button
                onClick={() => navigate('/admin')}
                className="flex-1 flex items-center justify-center gap-1.5 py-2 rounded-xl text-xs font-medium text-default-500 bg-content2 border border-divider hover:text-foreground hover:border-default-300"
              >
                <Icon paths="M10 19l-7-7m0 0l7-7m-7 7h18" size={12} />
                كل المتاجر
              </button>
            )}
            <button
              onClick={logout}
              className="flex-1 flex items-center justify-center gap-1.5 py-2 rounded-xl text-xs font-medium text-red-600 bg-red-50 border border-red-200 hover:bg-red-100"
            >
              <Icon paths="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" size={12} />
              خروج
            </button>
          </div>

          {/* Active section label */}
          <p className="text-center text-xs text-default-400 pt-1">
            {activeItem?.label}
          </p>
        </div>
      </aside>

      {/* ════════════ MAIN CONTENT ════════════ */}
      <main className="mr-0 md:mr-60 pt-14 md:pt-0 flex-1 min-h-screen overflow-y-auto">
        {/* Impersonation banner — sticks above the page content so the
            super admin never forgets they're operating in someone else's
            store. Customer-conversation reads still require a written
            reason on top of this. */}
        {getIsSuper() && (
          <div
            className="sticky top-0 z-20 bg-amber-50 border-b border-amber-200 px-4 py-2.5 flex items-center justify-between gap-3"
            dir="rtl"
          >
            <div className="flex items-center gap-2 text-amber-800 text-xs">
              <Icon paths={['M12 9v4', 'M12 17h.01', 'M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z']} size={14} className="flex-shrink-0" />
              <span>
                تتصفّح <b>{store.store_name}</b> كمدير عام —
                التغييرات الحساسة وقراءة المحادثات تُسجَّل في
                <button
                  onClick={() => navigate('/admin/audit-log')}
                  className="underline mx-1 hover:text-amber-900"
                >
                  سجل المراجعة
                </button>
              </span>
            </div>
            <button
              onClick={() => navigate('/admin/platform-ops')}
              className="text-xs font-bold text-amber-700 hover:text-amber-900 whitespace-nowrap"
            >
              ← عودة إلى لوحة العمليات
            </button>
          </div>
        )}
        <Suspense fallback={
          <div className="flex items-center justify-center min-h-screen">
            <Spinner size="lg" color="primary" label="جاري التحميل..." />
          </div>
        }>
          <Routes>
            <Route index element={<Overview storeId={storeId} store={store} />} />
            <Route path="conversations/*" element={<Conversations storeId={storeId} />} />
            <Route path="orders"          element={<Orders storeId={storeId} />} />
            <Route path="carts"           element={<AbandonedCarts storeId={storeId} />} />

            {/* Manager + owner only */}
            {(role === 'owner' || role === 'manager') && <>
              <Route path="products"        element={<Products        storeId={storeId} />} />
              <Route path="analytics"       element={<Analytics       storeId={storeId} />} />
              <Route path="pricing"         element={<Pricing         storeId={storeId} />} />
              <Route path="brain"           element={<Brain           storeId={storeId} />} />
              <Route path="training"        element={<Training        storeId={storeId} />} />
              <Route path="llm-usage"       element={<LlmUsage        storeId={storeId} />} />
              <Route path="whatsapp-events" element={<WhatsAppEvents  storeId={storeId} />} />
            </>}

            {/* Owner only */}
            {role === 'owner' && <>
              <Route path="employees"       element={<Employees       storeId={storeId} />} />
              <Route path="support-access"  element={<SupportAccess   storeId={storeId} />} />
              <Route path="settings"        element={<Settings        storeId={storeId} />} />
            </>}

            {/* Catch-all: redirect forbidden paths back to the dashboard root */}
            <Route path="*" element={<Forbidden />} />
          </Routes>
        </Suspense>
      </main>
    </div>
  )
}
