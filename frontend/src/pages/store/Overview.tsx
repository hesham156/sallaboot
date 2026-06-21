import { useEffect, useState } from 'react'
import { Progress, Avatar, Chip } from '@heroui/react'
import { api, Analytics, ROIData, WeeklyReport, StoreInfo } from '../../api'
import {
  Icon, StatCard, DataCard, EmptyState, StatSkeleton, DeltaBadge, StatusPill,
} from '../../components/ui'
import Setup from './Setup'

interface Props { storeId: string; store: StoreInfo }

export default function Overview({ storeId, store }: Props) {
  const [analytics, setAnalytics] = useState<Analytics | null>(null)
  const [roi, setRoi]             = useState<ROIData | null>(null)
  const [weekly, setWeekly]       = useState<WeeklyReport | null>(null)
  const [copied, setCopied]       = useState(false)
  const [syncing, setSyncing]     = useState(false)
  const [syncMsg, setSyncMsg]     = useState('')
  const [loading, setLoading]     = useState(true)

  useEffect(() => { loadAnalytics() }, [storeId])

  async function loadAnalytics() {
    setLoading(true)
    try {
      const [a, r, w] = await Promise.all([
        api.analytics(storeId),
        api.roi(storeId, 30).catch(() => null),
        api.weekly(storeId).catch(() => null),
      ])
      setAnalytics(a)
      setRoi(r)
      setWeekly(w)
    }
    catch (e) { console.error(e) }
    finally { setLoading(false) }
  }

  function copyWeekly() {
    if (!weekly) return
    const cur = weekly.currency === 'SAR' ? 'ريال' : weekly.currency
    const d = (n: number) => (n > 0 ? `▲${n}%` : n < 0 ? `▼${Math.abs(n)}%` : '—')
    const report =
      `📊 تقرير حياك الأسبوعي — ${store.store_name}\n` +
      `━━━━━━━━━━━━━━━━━━\n` +
      `💰 المبيعات: ${weekly.revenue.toLocaleString('en-US', { maximumFractionDigits: 0 })} ${cur} (${d(weekly.revenue_delta)})\n` +
      `📦 الطلبات: ${weekly.orders} (${d(weekly.orders_delta)})\n` +
      `💬 المحادثات: ${weekly.conversations} (${d(weekly.conv_delta)})\n` +
      (weekly.avg_rating ? `⭐ رضا العملاء: ${weekly.avg_rating}/5\n` : '') +
      (weekly.top_topic ? `🔎 أكثر موضوع: ${weekly.top_topic}\n` : '') +
      `━━━━━━━━━━━━━━━━━━\nبواسطة حياك 🤖`
    navigator.clipboard.writeText(report)
    setCopied(true); setTimeout(() => setCopied(false), 1800)
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
  const cur = (n: number) => n.toLocaleString('en-US', { maximumFractionDigits: 0 })

  return (
    <div className="p-6 space-y-6" dir="rtl">

      {/* ── Onboarding setup wizard (hides when dismissed or complete) ── */}
      <Setup storeId={storeId} store={store} />

      {/* ── Greeting banner (brand teal — white text passes contrast on teal) ── */}
      <div className="relative overflow-hidden rounded-2xl bg-gradient-to-r from-teal-500 to-cyan-500 p-6 sm:p-7 shadow-sm">
        <div className="absolute top-0 right-0 w-80 h-80 bg-white/10 rounded-full blur-3xl pointer-events-none -mr-20 -mt-20" />
        <div className="relative flex flex-col sm:flex-row items-center gap-5 justify-between">
          <div className="flex items-center gap-4 text-center sm:text-right flex-col sm:flex-row">
            <Avatar
              src={store.store_avatar || undefined}
              name={store.store_name[0]}
              size="lg"
              className="bg-white/20 text-white font-black text-xl w-16 h-16 ring-2 ring-white/30"
            />
            <div>
              <div className="flex items-center justify-center sm:justify-start gap-2.5 flex-wrap">
                <h1 className="text-2xl font-black text-white tracking-tight">{store.store_name}</h1>
                <Chip size="sm" color={store.has_ai_config ? 'success' : 'warning'} variant="solid" className="font-bold">
                  {store.has_ai_config ? '✓ المساعد الذكي نشط' : '⚠️ الوضع الافتراضي'}
                </Chip>
              </div>
              <p className="text-sm text-white/85 mt-1.5 flex items-center gap-2 justify-center sm:justify-start font-mono">
                <Icon paths={['M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101', 'M10.172 13.828a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1']} size={14} />
                {store.store_domain || store.store_id}
              </p>
            </div>
          </div>
          <button
            onClick={handleSync}
            disabled={syncing}
            className="flex items-center gap-2.5 px-5 py-3 rounded-xl text-xs font-bold bg-white/15 text-white hover:bg-white/25 active:scale-95 transition-all disabled:opacity-60 focus:outline-none focus-visible:ring-2 focus-visible:ring-white/60"
          >
            <Icon paths="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
              size={14} className={syncing ? 'animate-spin' : ''} />
            {syncing ? 'جاري المزامنة…' : 'مزامنة المنتجات'}
          </button>
        </div>
      </div>

      {/* ── Sync message ── */}
      {syncMsg && (
        <div className={`flex items-center gap-3 rounded-xl px-4 py-3 text-sm border ${
          !syncMsg.includes('خطأ')
            ? 'bg-success-50 border-success-200 text-success-700'
            : 'bg-danger-50 border-danger-200 text-danger-700'
        }`}>
          <Icon
            paths={!syncMsg.includes('خطأ') ? 'M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z' : 'M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z'}
            size={16} className="flex-shrink-0"
          />
          <span className="font-semibold">{syncMsg}</span>
        </div>
      )}

      {loading ? (
        <div className="space-y-6">
          <div className="h-32 rounded-2xl bg-content1 border border-divider animate-pulse" />
          <StatSkeleton count={4} />
        </div>
      ) : (
        <>
          {/* ── ROI hero: "how much did the bot make you" ── */}
          {roi && (
            <div className="relative overflow-hidden rounded-2xl bg-gradient-to-br from-teal-500 to-cyan-500 text-white p-6 sm:p-8 shadow-sm">
              <div className="absolute top-[-5rem] left-[-3rem] w-72 h-72 bg-white/10 rounded-full blur-3xl pointer-events-none" />
              <div className="relative flex flex-col lg:flex-row lg:items-center gap-6 justify-between">
                <div>
                  <div className="inline-flex items-center gap-2 bg-white/15 rounded-full px-3 py-1 text-xs font-bold mb-3">
                    <Icon paths="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" size={13} /> آخر 30 يوم
                  </div>
                  <p className="text-sm font-semibold text-teal-50">حياك جابلك</p>
                  <p className="text-4xl sm:text-5xl font-black tracking-tight mt-1 tabular-nums">
                    {cur(roi.revenue)}
                    <span className="text-2xl font-bold mr-2">{roi.currency === 'SAR' ? 'ريال' : roi.currency}</span>
                  </p>
                  <p className="text-sm text-teal-50/90 mt-2">
                    من <b>{roi.orders}</b> طلب أتمّه البوت
                    {roi.revenue_all > roi.revenue && (
                      <span className="opacity-80"> — وإجمالي <b>{cur(roi.revenue_all)}</b> منذ البداية</span>
                    )}
                  </p>
                </div>
                <div className="grid grid-cols-3 gap-3 lg:gap-4">
                  {[
                    { v: roi.conversations, l: 'محادثة', icon: 'M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z' },
                    { v: `${roi.hours_saved}س`, l: 'وقت موفّر', icon: 'M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z' },
                    { v: roi.carts_recovered, l: 'سلة مسترجعة', icon: 'M3 3h2l.4 2M7 13h10l4-8H5.4M7 13L5.4 5M7 13l-2.293 2.293c-.63.63-.184 1.707.707 1.707H17m0 0a2 2 0 100 4 2 2 0 000-4zm-8 2a2 2 0 11-4 0 2 2 0 014 0z' },
                  ].map((s) => (
                    <div key={s.l} className="bg-white/15 rounded-xl px-4 py-3.5 text-center min-w-[5.5rem]">
                      <Icon paths={s.icon} size={18} className="mx-auto mb-1.5 opacity-90" />
                      <p className="text-xl font-black leading-none tabular-nums">{s.v}</p>
                      <p className="text-[11px] font-semibold text-teal-50/90 mt-1">{s.l}</p>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* ── Weekly report (week-over-week) ── */}
          {weekly && (
            <DataCard
              title="تقرير الأسبوع"
              icon="M9 17V7m4 10V11m4 6V9M5 21h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v14a2 2 0 002 2z"
              action={
                <button onClick={copyWeekly}
                  className="inline-flex items-center gap-1.5 text-xs font-bold text-primary bg-primary/10 rounded-full px-4 py-1.5 hover:bg-primary/20 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/30">
                  <Icon paths={['M8 5H6a2 2 0 00-2 2v12a2 2 0 002 2h8a2 2 0 002-2v-2', 'M8 5a2 2 0 002 2h2a2 2 0 002-2M8 5a2 2 0 012-2h2a2 2 0 012 2m0 0h2a2 2 0 012 2v3']} size={14} />
                  {copied ? 'تم النسخ ✓' : 'نسخ للمشاركة'}
                </button>
              }
            >
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                {[
                  { l: 'المبيعات', v: cur(weekly.revenue), sub: weekly.currency === 'SAR' ? 'ريال' : weekly.currency, d: weekly.revenue_delta },
                  { l: 'الطلبات', v: weekly.orders, sub: 'طلب', d: weekly.orders_delta },
                  { l: 'المحادثات', v: weekly.conversations, sub: 'محادثة', d: weekly.conv_delta },
                  { l: 'رضا العملاء', v: weekly.avg_rating || '—', sub: weekly.avg_rating ? 'من 5 ⭐' : 'لا تقييمات', d: null as number | null },
                ].map((s) => (
                  <div key={s.l} className="bg-content2 rounded-xl p-4 border border-divider">
                    <p className="text-xs font-semibold text-default-500 mb-1.5">{s.l}</p>
                    <p className="text-2xl font-black text-foreground leading-none tabular-nums">
                      {s.v}<span className="text-xs font-semibold text-default-400 mr-1">{s.sub}</span>
                    </p>
                    {s.d !== null && <div className="mt-2"><DeltaBadge value={s.d} /></div>}
                  </div>
                ))}
              </div>
              {weekly.top_topic && (
                <p className="text-xs text-default-500 mt-4 flex items-center gap-1.5">
                  <Icon paths={['M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z']} size={13} className="text-default-400" />
                  أكثر موضوع سأل عنه العملاء هذا الأسبوع: <b className="text-foreground">{weekly.top_topic}</b>
                </p>
              )}
            </DataCard>
          )}

          {/* ── Stats grid (shared StatCard — theme-aware) ── */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <StatCard
              tone="primary" accent
              label="إجمالي المحادثات"
              value={c?.total ?? 0}
              sub={`${c?.today ?? 0} محادثة اليوم`}
              icon="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"
            />
            <StatCard
              tone="success" accent
              label="هذا الأسبوع"
              value={c?.this_week ?? 0}
              sub={`معدل ${c?.avg_messages ?? 0} رسالة/جلسة`}
              icon="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6"
            />
            <StatCard
              tone="secondary" accent
              label="المنتجات"
              value={store.products_count}
              sub={`آخر مزامنة: ${store.last_sync === 'never' ? 'لم تتم بعد' : 'نشطة'}`}
              icon="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4"
            />
            <StatCard
              tone="warning" accent
              label="متوسط التقييم"
              value={r?.avg ? `${r.avg} ★` : '—'}
              sub={`${r?.count ?? 0} تقييم إجمالاً`}
              icon="M11.049 2.927c.3-.921 1.603-.921 1.902 0l1.519 4.674a1 1 0 00.95.69h4.915c.969 0 1.371 1.24.588 1.81l-3.976 2.888a1 1 0 00-.363 1.118l1.518 4.674c.3.922-.755 1.688-1.538 1.118l-3.976-2.888a1 1 0 00-1.176 0l-3.976 2.888c-.783.57-1.838-.197-1.538-1.118l1.518-4.674a1 1 0 00-.363-1.118l-3.976-2.888c-.784-.57-.38-1.81.588-1.81h4.914a1 1 0 00.951-.69l1.519-4.674z"
            />
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* ── Messages breakdown ── */}
            {m && m.total > 0 && (
              <DataCard
                title="توزيع الرسائل"
                icon="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"
                iconTone="secondary"
                chip={<Chip size="sm" variant="flat" color="secondary" className="font-bold">{m.total} رسالة</Chip>}
              >
                <div className="space-y-5">
                  {[
                    { label: 'رسائل العملاء', value: m.user,  color: 'primary' as const, pctClass: 'text-primary' },
                    { label: 'ردود البوت',    value: m.bot,   color: 'success' as const, pctClass: 'text-success' },
                    { label: 'تدخّل الإدارة',  value: m.admin, color: 'warning' as const, pctClass: 'text-warning' },
                  ].map(item => (
                    <div key={item.label} className="space-y-2">
                      <div className="flex justify-between items-center">
                        <span className="text-sm text-default-600 font-semibold">{item.label}</span>
                        <div className="flex items-center gap-2.5">
                          <span className="text-xs text-default-400 font-medium tabular-nums">{item.value} رسالة</span>
                          <span className={`text-sm font-black tabular-nums ${item.pctClass}`}>
                            {m.total ? Math.round(item.value / m.total * 100) : 0}%
                          </span>
                        </div>
                      </div>
                      <Progress
                        value={m.total ? (item.value / m.total) * 100 : 0}
                        color={item.color}
                        size="sm"
                        aria-label={item.label}
                        classNames={{ track: 'bg-content2', indicator: 'rounded-full' }}
                      />
                    </div>
                  ))}
                </div>
              </DataCard>
            )}

            {/* ── Ratings ── */}
            {r && r.count > 0 && (
              <DataCard
                title="تقييمات العملاء"
                icon="M11.049 2.927c.3-.921 1.603-.921 1.902 0l1.519 4.674a1 1 0 00.95.69h4.915c.969 0 1.371 1.24.588 1.81l-3.976 2.888a1 1 0 00-.363 1.118l1.518 4.674c.3.922-.755 1.688-1.538 1.118l-3.976-2.888a1 1 0 00-1.176 0l-3.976 2.888c-.783.57-1.838-.197-1.538-1.118l1.518-4.674a1 1 0 00-.363-1.118l-3.976-2.888c-.784-.57-.38-1.81.588-1.81h4.914a1 1 0 00.951-.69l1.519-4.674z"
                iconTone="warning"
                chip={<Chip size="sm" variant="flat" color="warning" className="font-black">★ {r.avg} متوسط</Chip>}
              >
                <div className="space-y-3">
                  {[5, 4, 3, 2, 1].map(star => {
                    const count = r.distribution[star - 1] ?? 0
                    const pct   = r.count ? (count / r.count) * 100 : 0
                    return (
                      <div key={star} className="flex items-center gap-3">
                        <span className="text-xs text-warning font-black w-8 shrink-0">{star}★</span>
                        <Progress
                          value={pct} size="sm" color="warning" aria-label={`${star} نجوم`}
                          classNames={{ track: 'bg-content2', indicator: 'rounded-full' }}
                          className="flex-1"
                        />
                        <span className="text-xs text-default-500 font-bold w-14 text-right shrink-0 tabular-nums">
                          {count} تقييم
                        </span>
                      </div>
                    )
                  })}
                </div>
              </DataCard>
            )}
          </div>

          {/* ── Daily chart ── */}
          {c?.daily_counts && c.daily_counts.length > 0 && (
            <DataCard
              title="نشاط المحادثات اليومي (آخر 14 يوم)"
              icon="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6"
              iconTone="primary"
              chip={
                (c.peak_hour ?? -1) >= 0
                  ? <StatusPill tone="primary" label={`الذروة ${c.peak_hour}:00`} />
                  : undefined
              }
            >
              <div className="flex items-end gap-2 h-36 px-1">
                {c.daily_counts.slice(-14).map(d => {
                  const max = Math.max(...c.daily_counts.map(x => x.count), 1)
                  const h   = d.count === 0 ? 4 : Math.max(8, (d.count / max) * 120)
                  return (
                    <div key={d.date} className="flex-1 flex flex-col items-center gap-2 group">
                      <div className="relative w-full bg-primary/30 hover:bg-primary rounded-md transition-colors duration-200"
                        style={{ height: `${h}px` }}>
                        <div className="absolute bottom-full mb-2 left-1/2 -translate-x-1/2 bg-foreground text-background text-[11px] font-bold px-2 py-1 rounded-lg opacity-0 group-hover:opacity-100 pointer-events-none whitespace-nowrap transition-opacity duration-200 z-10">
                          {d.count} محادثة
                        </div>
                      </div>
                      <span className="text-[10px] text-default-400 font-bold tabular-nums">{d.date?.slice(8)}</span>
                    </div>
                  )
                })}
              </div>
              <div className="flex justify-between text-xs text-default-400 mt-3 px-1 border-t border-divider pt-3 tabular-nums">
                <span className="font-semibold">{c.daily_counts.at(-14)?.date}</span>
                <span className="font-semibold">{c.daily_counts.at(-1)?.date}</span>
              </div>
            </DataCard>
          )}

          {/* Empty state */}
          {!m?.total && !c?.total && (
            <DataCard>
              <EmptyState
                icon="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"
                title="لا توجد بيانات بعد"
                hint="ابدأ باستخدام البوت لترى التحليلات والإحصائيات تظهر هنا."
              />
            </DataCard>
          )}
        </>
      )}
    </div>
  )
}
