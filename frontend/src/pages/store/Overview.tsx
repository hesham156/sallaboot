import { useEffect, useState } from 'react'
import { Spinner, Progress, Avatar, Chip } from '@heroui/react'
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
    <div className={`group relative overflow-hidden rounded-3xl bg-[#0c1627]/60 backdrop-blur-xl border ${color.border} p-6 ${color.glow} hover:-translate-y-1 transition-all duration-300 shadow-xl`}>
      <div className={`absolute inset-0 bg-gradient-to-br ${color.gradient} opacity-40 group-hover:opacity-65 transition-opacity duration-300 pointer-events-none`} />
      
      {/* Glowing card border overlay */}
      <div className="absolute inset-0 border border-white/5 rounded-3xl pointer-events-none" />
      
      <div className="relative flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <p className="text-xs text-slate-400 font-bold mb-3 uppercase tracking-wider">{label}</p>
          <p className={`text-4xl font-black tracking-tight leading-none ${color.numColor} transition-transform duration-300 group-hover:scale-[1.03] origin-right`}>{value}</p>
          {sub && <p className="text-xs text-slate-500 font-semibold mt-3.5 flex items-center gap-1.5"><span className="inline-block w-1.5 h-1.5 rounded-full bg-slate-600 group-hover:bg-blue-400 transition-colors" />{sub}</p>}
        </div>
        <div className={`w-12 h-12 ${color.iconBg} rounded-2xl flex items-center justify-center flex-shrink-0 ${color.iconColor} shadow-inner group-hover:scale-110 transition-transform duration-300`}>
          <Icon paths={icon} size={20} />
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
      setSyncMsg(`تمت المزامنة بنجاح — ${r.products_count} منتج`)
    } catch (e: unknown) {
      setSyncMsg(e instanceof Error ? e.message : 'حدث خطأ أثناء مزامنة المنتجات')
    } finally { setSyncing(false) }
  }

  const c = analytics?.conversations
  const m = analytics?.messages
  const r = analytics?.ratings

  return (
    <div className="p-6 space-y-6" dir="rtl">

      {/* ── Premium Greeting Banner ── */}
      <div className="relative overflow-hidden rounded-3xl border border-blue-500/20 bg-gradient-to-r from-blue-950/40 via-indigo-950/20 to-transparent p-6 sm:p-8 shadow-2xl">
        <div className="absolute top-0 right-0 w-96 h-96 bg-blue-500/10 rounded-full blur-3xl pointer-events-none -mr-20 -mt-20" />
        <div className="absolute bottom-0 left-0 w-80 h-80 bg-purple-500/5 rounded-full blur-3xl pointer-events-none -ml-20 -mb-20" />
        
        <div className="relative flex flex-col sm:flex-row items-center gap-6 justify-between">
          <div className="flex items-center gap-4 text-center sm:text-right flex-col sm:flex-row">
            <div className="relative p-1 bg-gradient-to-br from-blue-500 to-indigo-600 rounded-2xl shadow-xl shadow-blue-500/20">
              <Avatar
                src={store.store_avatar || undefined}
                name={store.store_name[0]}
                size="lg"
                className="bg-[#020917] text-white font-black text-xl border-2 border-transparent w-16 h-16"
              />
            </div>
            <div>
              <div className="flex items-center justify-center sm:justify-start gap-2.5 flex-wrap">
                <h1 className="text-2xl font-black text-white tracking-tight">{store.store_name}</h1>
                <Chip size="sm" color={store.has_ai_config ? "success" : "warning"} variant="flat" className="font-bold">
                  {store.has_ai_config ? "✓ المساعد الذكي نشط" : "⚠️ وضع البيئة الافتراضية"}
                </Chip>
              </div>
              <p className="text-sm text-slate-400 mt-1.5 flex items-center gap-2 justify-center sm:justify-start">
                <span className="opacity-60">🔗</span>
                <span className="font-mono">{store.store_domain || store.store_id}</span>
              </p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={handleSync}
              disabled={syncing}
              className="flex items-center gap-2.5 px-5 py-3 rounded-2xl text-xs font-bold border border-blue-500/30 bg-blue-500/10 text-blue-400 hover:bg-blue-500/20 active:scale-95 transition-all shadow-lg shadow-blue-500/5 disabled:opacity-60"
            >
              {syncing
                ? <Spinner size="sm" color="primary" />
                : <Icon paths="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" size={14} />
              }
              مزامنة مستودع المنتجات
            </button>
          </div>
        </div>
      </div>

      {/* ── Sync message ── */}
      {syncMsg && (
        <div className={`flex items-center gap-3 rounded-2xl px-4 py-3.5 text-sm border ${
          !syncMsg.includes('خطأ')
            ? 'bg-emerald-500/10 border-emerald-500/25 text-emerald-400'
            : 'bg-red-500/10 border-red-500/25 text-red-400'
        }`}>
          <Icon
            paths={!syncMsg.includes('خطأ') ? 'M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z' : 'M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z'}
            size={16}
            className="flex-shrink-0"
          />
          <span className="font-semibold">{syncMsg}</span>
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center py-24">
          <Spinner size="lg" color="primary" label="جاري تحميل البيانات..." />
        </div>
      ) : (
        <>
          {/* ── Stats grid ── */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
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
              sub={`آخر مزامنة: ${store.last_sync === 'never' ? 'لم تتم بعد' : 'نشطة'}`}
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

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* ── Messages breakdown ── */}
            {m && m.total > 0 && (
              <div className="rounded-3xl bg-[#0c1627]/60 backdrop-blur-xl border border-divider overflow-hidden shadow-xl relative group">
                <div className="absolute top-0 right-0 w-64 h-64 bg-violet-500/5 rounded-full blur-3xl pointer-events-none -mr-20 -mt-20" />
                <div className="flex items-center gap-2.5 px-6 py-5 border-b border-divider">
                  <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-violet-500 to-pink-500 flex items-center justify-center text-white shadow-lg shadow-violet-500/20">
                    <Icon paths="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" size={14} />
                  </div>
                  <h2 className="font-bold text-white text-base">توزيع وتحليل الرسائل</h2>
                  <Chip size="sm" variant="flat" color="secondary" className="mr-auto font-bold">
                    {m.total} رسالة نشطة
                  </Chip>
                </div>
                <div className="p-6 space-y-6">
                  {[
                    { label: 'رسائل العملاء 👤', value: m.user,  color: 'primary'  as const, hex: '#3b82f6', bg: 'bg-blue-500/10' },
                    { label: 'ردود البوت الذكي 🤖',    value: m.bot,   color: 'success'  as const, hex: '#22c55e', bg: 'bg-emerald-500/10' },
                    { label: 'تدخل وتوجيه الإدارة 👨‍💼',  value: m.admin, color: 'warning'  as const, hex: '#f59e0b', bg: 'bg-amber-500/10' },
                  ].map(item => (
                    <div key={item.label} className="space-y-2">
                      <div className="flex justify-between items-center">
                        <span className="text-sm text-slate-300 font-semibold">{item.label}</span>
                        <div className="flex items-center gap-3">
                          <span className="text-xs text-slate-400 font-medium">{item.value} رسالة</span>
                          <span className="text-sm font-black px-2 py-0.5 rounded-lg text-white" style={{ background: `${item.hex}15`, color: item.hex }}>
                            {m.total ? Math.round(item.value / m.total * 100) : 0}%
                          </span>
                        </div>
                      </div>
                      <Progress
                        value={m.total ? (item.value / m.total) * 100 : 0}
                        color={item.color}
                        size="md"
                        className="max-w-full"
                        classNames={{
                          track: 'bg-[#111e32]/60 border border-white/5',
                          indicator: 'rounded-full bg-gradient-to-r',
                        }}
                      />
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* ── Ratings ── */}
            {r && r.count > 0 && (
              <div className="rounded-3xl bg-[#0c1627]/60 backdrop-blur-xl border border-divider overflow-hidden shadow-xl relative group">
                <div className="absolute top-0 right-0 w-64 h-64 bg-amber-500/5 rounded-full blur-3xl pointer-events-none -mr-20 -mt-20" />
                <div className="flex items-center gap-2.5 px-6 py-5 border-b border-divider">
                  <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-amber-400 to-orange-500 flex items-center justify-center text-white shadow-lg shadow-amber-500/20">
                    <Icon paths="M11.049 2.927c.3-.921 1.603-.921 1.902 0l1.519 4.674a1 1 0 00.95.69h4.915c.969 0 1.371 1.24.588 1.81l-3.976 2.888a1 1 0 00-.363 1.118l1.518 4.674c.3.922-.755 1.688-1.538 1.118l-3.976-2.888a1 1 0 00-1.176 0l-3.976 2.888c-.783.57-1.838-.197-1.538-1.118l1.518-4.674a1 1 0 00-.363-1.118l-3.976-2.888c-.784-.57-.38-1.81.588-1.81h4.914a1 1 0 00.951-.69l1.519-4.674z" size={14} />
                  </div>
                  <h2 className="font-bold text-white text-base">تقييمات ومراجعات العملاء</h2>
                  <Chip size="sm" variant="flat" color="warning" className="mr-auto font-black">
                    ★ {r.avg} متوسط التقييم
                  </Chip>
                </div>
                <div className="p-6 space-y-4">
                  {[5, 4, 3, 2, 1].map(star => {
                    const count = r.distribution[star - 1] ?? 0
                    const pct   = r.count ? (count / r.count) * 100 : 0
                    return (
                      <div key={star} className="flex items-center gap-4 group/row">
                        <span className="text-xs text-amber-400 font-black w-8 shrink-0 flex items-center gap-0.5">
                          {star}★
                        </span>
                        <div className="flex-1">
                          <Progress
                            value={pct}
                            size="md"
                            color="warning"
                            classNames={{
                              track: 'bg-[#111e32]/60 border border-white/5',
                              indicator: 'bg-gradient-to-r from-amber-500 to-orange-400 rounded-full',
                            }}
                          />
                        </div>
                        <span className="text-xs text-slate-500 font-bold w-12 text-right shrink-0 group-hover/row:text-slate-300 transition-colors">
                          {count} تقييم
                        </span>
                      </div>
                    )
                  })}
                </div>
              </div>
            )}
          </div>

          {/* ── Daily chart ── */}
          {c?.daily_counts && c.daily_counts.length > 0 && (
            <div className="rounded-3xl bg-[#0c1627]/60 backdrop-blur-xl border border-divider overflow-hidden shadow-xl relative group">
              <div className="absolute top-0 right-0 w-64 h-64 bg-blue-500/5 rounded-full blur-3xl pointer-events-none -mr-20 -mt-20" />
              <div className="flex items-center gap-2.5 px-6 py-5 border-b border-divider">
                <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-blue-500 to-cyan-500 flex items-center justify-center text-white shadow-lg shadow-blue-500/20">
                  <Icon paths="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" size={14} />
                </div>
                <h2 className="font-bold text-white text-base">نشاط المحادثات اليومي (آخر 14 يوم)</h2>
              </div>
              <div className="p-6">
                {/* Bar chart */}
                <div className="flex items-end gap-2.5 h-36 px-2">
                  {c.daily_counts.slice(-14).map(d => {
                    const max = Math.max(...c.daily_counts.map(x => x.count), 1)
                    const h   = d.count === 0 ? 4 : Math.max(8, (d.count / max) * 120)
                    return (
                      <div key={d.date} className="flex-1 flex flex-col items-center gap-2 group">
                        <div
                          className="w-full bg-gradient-to-t from-blue-600/20 to-blue-500/40 hover:from-blue-500 hover:to-cyan-400 rounded-lg transition-all duration-300 cursor-default relative shadow-lg group-hover:shadow-blue-500/20"
                          style={{ height: `${h}px` }}
                        >
                          {/* Tooltip */}
                          <div className="absolute bottom-full mb-2 left-1/2 -translate-x-1/2 bg-[#111e32] border border-[#1c2d42] text-white text-[11px] font-bold px-2.5 py-1 rounded-xl opacity-0 group-hover:opacity-100 pointer-events-none whitespace-nowrap transition-all duration-200 transform translate-y-1 group-hover:translate-y-0 shadow-2xl z-10">
                            {d.count} محادثة
                          </div>
                        </div>
                        <span className="text-[10px] text-slate-500 font-bold opacity-60 group-hover:opacity-100 transition-opacity">
                          {d.date?.slice(8)}
                        </span>
                      </div>
                    )
                  })}
                </div>
                <div className="flex justify-between text-xs text-slate-600 mt-4 px-2 border-t border-white/5 pt-3">
                  <span className="font-semibold">{c.daily_counts.at(-14)?.date}</span>
                  <span className="font-semibold">{c.daily_counts.at(-1)?.date}</span>
                </div>
              </div>
            </div>
          )}

          {/* Empty state */}
          {!m?.total && !c?.total && (
            <div className="rounded-3xl bg-[#0c1627]/60 backdrop-blur-xl border border-divider py-20 text-center shadow-xl">
              <div className="w-16 h-16 bg-[#111e32] rounded-2xl flex items-center justify-center mx-auto mb-4 border border-white/5">
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
