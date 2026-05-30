import { useEffect, useState } from 'react'
import { Spinner, Progress } from '@heroui/react'
import { api, Analytics, StoreInfo } from '../../api'

interface Props { storeId: string; store: StoreInfo }

function Icon({ paths, size = 16, className = '' }: {
  paths: string | string[]; size?: number; className?: string
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

/* ── Stat card ── */
function StatCard({ label, value, sub, icon, color }: {
  label: string
  value: string | number
  sub?: string
  icon: string | string[]
  color: { gradient: string; border: string; iconBg: string; iconColor: string; numColor: string; glow: string }
}) {
  return (
    <div className={`relative overflow-hidden rounded-2xl bg-[#0c1627] border ${color.border} p-5 ${color.glow} transition-all duration-300`}>
      <div className={`absolute inset-0 bg-gradient-to-br ${color.gradient} pointer-events-none`} />
      <div className="relative flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <p className="text-xs text-slate-500 font-medium mb-2 uppercase tracking-wide truncate">{label}</p>
          <p className={`text-3xl font-black tracking-tight leading-none ${color.numColor}`}>{value}</p>
          {sub && <p className="text-xs text-slate-500 mt-2">{sub}</p>}
        </div>
        <div className={`w-10 h-10 ${color.iconBg} rounded-xl flex items-center justify-center flex-shrink-0 ${color.iconColor}`}>
          <Icon paths={icon} size={18} />
        </div>
      </div>
    </div>
  )
}

export default function Overview({ storeId, store }: Props) {
  const [analytics, setAnalytics] = useState<Analytics | null>(null)
  const [syncing, setSyncing]     = useState(false)
  const [syncMsg, setSyncMsg]     = useState('')
  const [loading, setLoading]     = useState(true)

  useEffect(() => { loadAnalytics() }, [storeId])

  async function loadAnalytics() {
    setLoading(true)
    try { setAnalytics(await api.analytics(storeId)) }
    catch (e) { console.error(e) }
    finally { setLoading(false) }
  }

  async function handleSync() {
    setSyncing(true); setSyncMsg('')
    try {
      const r = await api.sync(storeId)
      setSyncMsg(`تمت المزامنة — ${r.products_count} منتج`)
    } catch (e: unknown) {
      setSyncMsg(e instanceof Error ? e.message : 'خطأ في المزامنة')
    } finally { setSyncing(false) }
  }

  const c = analytics?.conversations
  const m = analytics?.messages
  const r = analytics?.ratings

  return (
    <div className="p-6 space-y-6">

      {/* ── Page header ── */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-black text-white">{store.store_name}</h1>
          <p className="text-sm text-slate-500 mt-1">{store.store_domain || store.store_id}</p>
        </div>
        <div className="flex items-center gap-2">
          <div className={`flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold border ${
            store.has_ai_config
              ? 'bg-emerald-500/10 border-emerald-500/25 text-emerald-400'
              : 'bg-amber-500/10 border-amber-500/25 text-amber-400'
          }`}>
            <Icon
              paths={store.has_ai_config
                ? 'M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z'
                : 'M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z'
              }
              size={13}
            />
            {store.has_ai_config ? 'AI مُعدّ' : 'يستخدم env'}
          </div>

          <button
            onClick={handleSync}
            disabled={syncing}
            className="flex items-center gap-2 px-3 py-1.5 rounded-xl text-xs font-semibold border bg-blue-500/10 border-blue-500/25 text-blue-400 hover:bg-blue-500/15 disabled:opacity-60"
          >
            {syncing
              ? <Spinner size="sm" color="primary" className="scale-75" />
              : <Icon paths="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" size={13} />
            }
            مزامنة المنتجات
          </button>
        </div>
      </div>

      {/* ── Sync message ── */}
      {syncMsg && (
        <div className={`flex items-center gap-2 rounded-xl px-4 py-3 text-sm border ${
          !syncMsg.includes('خطأ')
            ? 'bg-emerald-500/10 border-emerald-500/25 text-emerald-400'
            : 'bg-red-500/10 border-red-500/25 text-red-400'
        }`}>
          <Icon
            paths={!syncMsg.includes('خطأ') ? 'M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z' : 'M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z'}
            size={15}
            className="flex-shrink-0"
          />
          {syncMsg}
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center py-24">
          <Spinner size="lg" color="primary" />
        </div>
      ) : (
        <>
          {/* ── Stats grid ── */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <StatCard
              label="إجمالي المحادثات"
              value={c?.total ?? 0}
              sub={`${c?.today ?? 0} محادثة اليوم`}
              icon="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"
              color={{ gradient: 'from-blue-500/10 via-blue-500/5 to-transparent', border: 'border-blue-500/20 hover:border-blue-500/35', iconBg: 'bg-blue-500/15', iconColor: 'text-blue-400', numColor: 'text-blue-400', glow: 'card-blue' }}
            />
            <StatCard
              label="هذا الأسبوع"
              value={c?.this_week ?? 0}
              sub={`معدل ${c?.avg_messages ?? 0} رسالة/جلسة`}
              icon="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6"
              color={{ gradient: 'from-emerald-500/10 via-emerald-500/5 to-transparent', border: 'border-emerald-500/20 hover:border-emerald-500/35', iconBg: 'bg-emerald-500/15', iconColor: 'text-emerald-400', numColor: 'text-emerald-400', glow: 'card-green' }}
            />
            <StatCard
              label="المنتجات"
              value={store.products_count}
              sub={`آخر مزامنة: ${store.last_sync === 'never' ? 'لم تتم' : 'تمت'}`}
              icon="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4"
              color={{ gradient: 'from-violet-500/10 via-violet-500/5 to-transparent', border: 'border-violet-500/20 hover:border-violet-500/35', iconBg: 'bg-violet-500/15', iconColor: 'text-violet-400', numColor: 'text-violet-400', glow: 'card-purple' }}
            />
            <StatCard
              label="متوسط التقييم"
              value={r?.avg ? `${r.avg} ★` : '—'}
              sub={`${r?.count ?? 0} تقييم إجمالاً`}
              icon="M11.049 2.927c.3-.921 1.603-.921 1.902 0l1.519 4.674a1 1 0 00.95.69h4.915c.969 0 1.371 1.24.588 1.81l-3.976 2.888a1 1 0 00-.363 1.118l1.518 4.674c.3.922-.755 1.688-1.538 1.118l-3.976-2.888a1 1 0 00-1.176 0l-3.976 2.888c-.783.57-1.838-.197-1.538-1.118l1.518-4.674a1 1 0 00-.363-1.118l-3.976-2.888c-.784-.57-.38-1.81.588-1.81h4.914a1 1 0 00.951-.69l1.519-4.674z"
              color={{ gradient: 'from-amber-500/10 via-amber-500/5 to-transparent', border: 'border-amber-500/20 hover:border-amber-500/35', iconBg: 'bg-amber-500/15', iconColor: 'text-amber-400', numColor: 'text-amber-400', glow: 'card-amber' }}
            />
          </div>

          {/* ── Messages breakdown ── */}
          {m && m.total > 0 && (
            <div className="rounded-2xl bg-[#0c1627] border border-[#1c2d42] overflow-hidden">
              <div className="flex items-center gap-2.5 px-6 py-4 border-b border-[#1c2d42]">
                <span className="w-1 h-5 bg-gradient-to-b from-violet-400 to-pink-500 rounded-full" />
                <h2 className="font-bold text-white text-sm">توزيع الرسائل</h2>
                <span className="text-xs text-slate-600 bg-[#111e32] px-2 py-0.5 rounded-md border border-[#1c2d42] mr-auto">
                  {m.total} رسالة
                </span>
              </div>
              <div className="px-6 py-5 space-y-4">
                {[
                  { label: 'رسائل العملاء', value: m.user,  color: 'primary'  as const, hex: '#3b82f6' },
                  { label: 'ردود البوت',    value: m.bot,   color: 'success'  as const, hex: '#22c55e' },
                  { label: 'ردود الإدارة',  value: m.admin, color: 'warning'  as const, hex: '#f59e0b' },
                ].map(item => (
                  <div key={item.label}>
                    <div className="flex justify-between items-center mb-2">
                      <span className="text-sm text-slate-300 font-medium">{item.label}</span>
                      <div className="flex items-center gap-2">
                        <span className="text-xs text-slate-500">{item.value} رسالة</span>
                        <span className="text-xs font-bold" style={{ color: item.hex }}>
                          {m.total ? Math.round(item.value / m.total * 100) : 0}%
                        </span>
                      </div>
                    </div>
                    <Progress
                      value={m.total ? (item.value / m.total) * 100 : 0}
                      color={item.color}
                      size="sm"
                      className="max-w-full"
                    />
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* ── Daily chart ── */}
          {c?.daily_counts && c.daily_counts.length > 0 && (
            <div className="rounded-2xl bg-[#0c1627] border border-[#1c2d42] overflow-hidden">
              <div className="flex items-center gap-2.5 px-6 py-4 border-b border-[#1c2d42]">
                <span className="w-1 h-5 bg-gradient-to-b from-blue-400 to-cyan-500 rounded-full" />
                <h2 className="font-bold text-white text-sm">المحادثات — آخر 14 يوم</h2>
              </div>
              <div className="px-6 py-5">
                {/* Bar chart */}
                <div className="flex items-end gap-1.5 h-24">
                  {c.daily_counts.slice(-14).map(d => {
                    const max = Math.max(...c.daily_counts.map(x => x.count), 1)
                    const h   = d.count === 0 ? 3 : Math.max(6, (d.count / max) * 88)
                    return (
                      <div key={d.date} className="flex-1 flex flex-col items-center gap-1 group">
                        <div
                          className="w-full bg-blue-500/30 hover:bg-blue-500/60 rounded-sm transition-colors cursor-default relative"
                          style={{ height: `${h}px` }}
                          title={`${d.date}: ${d.count} محادثة`}
                        >
                          {/* Tooltip */}
                          <div className="absolute bottom-full mb-1 left-1/2 -translate-x-1/2 bg-[#111e32] border border-[#1c2d42] text-white text-xs px-2 py-1 rounded-lg opacity-0 group-hover:opacity-100 pointer-events-none whitespace-nowrap transition-opacity z-10">
                            {d.count}
                          </div>
                        </div>
                      </div>
                    )
                  })}
                </div>
                <div className="flex justify-between text-xs text-slate-600 mt-2">
                  <span>{c.daily_counts.at(-14)?.date?.slice(5)}</span>
                  <span>{c.daily_counts.at(-1)?.date?.slice(5)}</span>
                </div>
              </div>
            </div>
          )}

          {/* ── Ratings ── */}
          {r && r.count > 0 && (
            <div className="rounded-2xl bg-[#0c1627] border border-[#1c2d42] overflow-hidden">
              <div className="flex items-center gap-2.5 px-6 py-4 border-b border-[#1c2d42]">
                <span className="w-1 h-5 bg-gradient-to-b from-amber-400 to-orange-500 rounded-full" />
                <h2 className="font-bold text-white text-sm">توزيع التقييمات</h2>
                <span className="text-xs text-amber-400 font-bold mr-auto">
                  {r.avg} ★ متوسط
                </span>
              </div>
              <div className="px-6 py-5 space-y-3">
                {[5, 4, 3, 2, 1].map(star => {
                  const count = r.distribution[star - 1] ?? 0
                  const pct   = r.count ? (count / r.count) * 100 : 0
                  return (
                    <div key={star} className="flex items-center gap-3">
                      <span className="text-xs text-amber-400 font-bold w-7 text-left shrink-0">
                        {star}★
                      </span>
                      <div className="flex-1">
                        <Progress value={pct} size="sm" color="warning" />
                      </div>
                      <span className="text-xs text-slate-500 w-6 text-right shrink-0">{count}</span>
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {/* Empty state */}
          {!m?.total && !c?.total && (
            <div className="rounded-2xl bg-[#0c1627] border border-[#1c2d42] py-20 text-center">
              <div className="w-16 h-16 bg-[#111e32] rounded-2xl flex items-center justify-center mx-auto mb-4">
                <Icon paths="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" size={26} className="text-slate-600" />
              </div>
              <p className="text-slate-400 text-sm font-semibold">لا توجد بيانات بعد</p>
              <p className="text-slate-600 text-xs mt-1">ابدأ باستخدام البوت لترى التحليلات هنا</p>
            </div>
          )}
        </>
      )}
    </div>
  )
}
