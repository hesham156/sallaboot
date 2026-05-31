import { useEffect, useState } from 'react'
import { useNavigate, useParams, Routes, Route, useLocation } from 'react-router-dom'
import { Avatar, Spinner } from '@heroui/react'
import { api, StoreInfo, clearAuth, getIsSuper } from '../api'
import Overview      from './store/Overview'
import Conversations from './store/Conversations'
import Products      from './store/Products'
import Analytics     from './store/Analytics'
import Settings      from './store/Settings'
import Orders        from './store/Orders'
import AbandonedCarts from './store/AbandonedCarts'
import Pricing       from './store/Pricing'

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

const NAV_ITEMS = [
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
  },
  {
    key: 'pricing',
    label: 'حاسبة الأسعار',
    icon: ['M9 7h6m0 10v-3m-3 3h.01M9 17h.01M9 14h.01M12 14h.01M15 11h.01M12 11h.01M9 11h.01M7 21h10a2 2 0 002-2V5a2 2 0 00-2-2H7a2 2 0 00-2 2v14a2 2 0 002 2z'],
    activeColor: 'text-cyan-400',
    activeBg: 'bg-cyan-500/10',
    activeBorder: 'border-r-cyan-500',
  },
  {
    key: 'settings',
    label: 'الإعدادات',
    icon: ['M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z', 'M15 12a3 3 0 11-6 0 3 3 0 016 0z'],
    activeColor: 'text-slate-300',
    activeBg: 'bg-slate-500/10',
    activeBorder: 'border-r-slate-400',
  },
]

export default function StoreDashboard() {
  const { storeId = '' } = useParams<{ storeId: string }>()
  const navigate  = useNavigate()
  const location  = useLocation()
  const [store, setStore]         = useState<StoreInfo | null>(null)
  const [botEnabled, setBotEnabled]   = useState(true)
  const [loadingBot, setLoadingBot]   = useState(false)

  const basePath     = `/store/${storeId}`
  const relativePath = location.pathname.replace(basePath, '').replace(/^\//, '')
  const activeKey    = NAV_ITEMS.find(n => n.key === relativePath)?.key ?? ''

  useEffect(() => { loadStore() }, [storeId])

  async function loadStore() {
    try {
      const [storeRes, botRes] = await Promise.all([
        api.listStores(),
        api.botStatus(storeId),
      ])
      const found = storeRes.stores.find(s => s.store_id === storeId)
      if (found) setStore(found)
      setBotEnabled(botRes.bot_globally_enabled)
    } catch (e) { console.error(e) }
  }

  async function toggleBot() {
    setLoadingBot(true)
    try {
      const res = await api.botToggle(storeId, !botEnabled)
      setBotEnabled(res.bot_globally_enabled)
    } finally { setLoadingBot(false) }
  }

  function logout()        { clearAuth(); navigate('/login', { replace: true }) }
  function goTab(key: string) { navigate(key ? `${basePath}/${key}` : basePath) }

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

      {/* ════════════ SIDEBAR ════════════ */}
      <aside className="w-60 bg-[#0c1627] border-l border-[#1c2d42] flex flex-col fixed right-0 h-screen z-40">

        {/* ── Store header ── */}
        <div className="p-4 border-b border-[#1c2d42]">
          <div className="flex items-center gap-3">
            <div className="relative flex-shrink-0">
              <Avatar
                src={store.store_avatar || undefined}
                name={store.store_name[0]}
                size="sm"
                className="bg-gradient-to-br from-blue-500 to-indigo-600 text-white font-bold"
              />
              {/* Bot status dot */}
              <span className={`absolute -bottom-0.5 -left-0.5 w-2.5 h-2.5 rounded-full border-2 border-[#0c1627] ${
                botEnabled ? 'bg-emerald-400' : 'bg-slate-500'
              }`} />
            </div>
            <div className="min-w-0">
              <p className="font-bold text-sm text-white truncate">{store.store_name}</p>
              <p className="text-xs text-slate-600 font-mono truncate">{store.store_id}</p>
            </div>
          </div>
        </div>

        {/* ── Navigation ── */}
        <nav className="flex-1 py-2 overflow-y-auto">
          {NAV_ITEMS.map(item => {
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
                    : 'border-r-transparent text-slate-500 hover:text-slate-300 hover:bg-[#111e32]'
                  }
                `}
              >
                <Icon
                  paths={item.icon}
                  size={16}
                  className={`flex-shrink-0 ${isActive ? item.activeColor : 'text-slate-600'}`}
                />
                <span>{item.label}</span>
              </button>
            )
          })}
        </nav>

        {/* ── Footer ── */}
        <div className="p-3 border-t border-[#1c2d42] space-y-2">
          {/* Bot toggle */}
          <button
            onClick={!loadingBot ? toggleBot : undefined}
            className={`
              w-full flex items-center gap-3 px-3 py-2.5 rounded-xl border text-sm
              transition-all duration-200
              ${botEnabled
                ? 'bg-emerald-500/10 border-emerald-500/25 text-emerald-400 hover:bg-emerald-500/15'
                : 'bg-[#111e32] border-[#1c2d42] text-slate-500 hover:text-slate-300 hover:border-slate-500'
              }
            `}
          >
            {loadingBot ? (
              <Spinner size="sm" color="success" />
            ) : (
              <span className={`w-2 h-2 rounded-full flex-shrink-0 ${
                botEnabled ? 'bg-emerald-400 animate-pulse-dot' : 'bg-slate-600'
              }`} />
            )}
            <span className="font-semibold flex-1 text-right">
              {botEnabled ? 'البوت شغّال' : 'البوت موقوف'}
            </span>
            <span className={`text-xs ${botEnabled ? 'text-emerald-600' : 'text-slate-600'}`}>
              {botEnabled ? 'إيقاف' : 'تشغيل'}
            </span>
          </button>

          {/* Action buttons */}
          <div className="flex gap-1.5">
            {getIsSuper() && (
              <button
                onClick={() => navigate('/')}
                className="flex-1 flex items-center justify-center gap-1.5 py-2 rounded-xl text-xs font-medium text-slate-400 bg-[#111e32] border border-[#1c2d42] hover:text-white hover:border-slate-500"
              >
                <Icon paths="M10 19l-7-7m0 0l7-7m-7 7h18" size={12} />
                كل المتاجر
              </button>
            )}
            <button
              onClick={logout}
              className="flex-1 flex items-center justify-center gap-1.5 py-2 rounded-xl text-xs font-medium text-red-400 bg-red-500/10 border border-red-500/20 hover:bg-red-500/15"
            >
              <Icon paths="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" size={12} />
              خروج
            </button>
          </div>

          {/* Active section label */}
          <p className="text-center text-xs text-slate-700 pt-1">
            {activeItem?.label}
          </p>
        </div>
      </aside>

      {/* ════════════ MAIN CONTENT ════════════ */}
      <main className="mr-60 flex-1 min-h-screen overflow-y-auto">
        <Routes>
          <Route index element={<Overview storeId={storeId} store={store} />} />
          <Route path="conversations/*" element={<Conversations storeId={storeId} />} />
          <Route path="products"        element={<Products storeId={storeId} />} />
          <Route path="orders"          element={<Orders storeId={storeId} />} />
          <Route path="carts"           element={<AbandonedCarts storeId={storeId} />} />
          <Route path="analytics"       element={<Analytics storeId={storeId} />} />
          <Route path="pricing"         element={<Pricing storeId={storeId} />} />
          <Route path="settings"        element={<Settings storeId={storeId} />} />
        </Routes>
      </main>
    </div>
  )
}
