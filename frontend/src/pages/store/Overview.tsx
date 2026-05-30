import { useEffect, useState } from 'react'
import { Card, CardBody, CardHeader, Button, Chip, Progress, Divider, Spinner } from '@heroui/react'
import { api, Analytics, StoreInfo } from '../../api'

interface Props { storeId: string; store: StoreInfo }

function StatCard({ label, value, sub, color = 'text-primary' }: {
  label: string; value: string | number; sub?: string; color?: string
}) {
  return (
    <Card className="bg-content1 border border-divider">
      <CardBody className="py-4 px-5">
        <p className="text-xs text-default-400 font-semibold uppercase tracking-wide">{label}</p>
        <p className={`text-3xl font-black mt-2 ${color}`}>{value}</p>
        {sub && <p className="text-xs text-default-500 mt-1">{sub}</p>}
      </CardBody>
    </Card>
  )
}

export default function Overview({ storeId, store }: Props) {
  const [analytics, setAnalytics] = useState<Analytics | null>(null)
  const [syncing, setSyncing] = useState(false)
  const [syncMsg, setSyncMsg] = useState('')
  const [loading, setLoading] = useState(true)

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
      setSyncMsg(`✅ تمت المزامنة — ${r.products_count} منتج`)
    } catch (e: unknown) {
      setSyncMsg(e instanceof Error ? e.message : 'خطأ في المزامنة')
    } finally { setSyncing(false) }
  }

  const c = analytics?.conversations
  const m = analytics?.messages
  const r = analytics?.ratings

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-foreground">{store.store_name}</h1>
          <p className="text-sm text-default-400 mt-1">
            {store.store_domain || store.store_id}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <Chip size="sm" color={store.has_ai_config ? 'success' : 'warning'} variant="flat">
            {store.has_ai_config ? 'AI مُعدّ' : 'يستخدم env vars'}
          </Chip>
          <Button
            size="sm"
            color="primary"
            variant="flat"
            isLoading={syncing}
            onPress={handleSync}
          >
            مزامنة المنتجات
          </Button>
        </div>
      </div>

      {syncMsg && (
        <div className={`rounded-lg p-3 text-sm border ${
          syncMsg.startsWith('✅')
            ? 'bg-success/10 border-success/20 text-success'
            : 'bg-danger/10 border-danger/20 text-danger'
        }`}>
          {syncMsg}
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center py-16">
          <Spinner size="lg" color="primary" />
        </div>
      ) : (
        <>
          {/* Stats grid */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <StatCard label="إجمالي المحادثات" value={c?.total ?? 0} sub={`${c?.today ?? 0} اليوم`} color="text-primary" />
            <StatCard label="هذا الأسبوع" value={c?.this_week ?? 0} sub={`معدل ${c?.avg_messages ?? 0} رسالة/جلسة`} color="text-success" />
            <StatCard label="المنتجات" value={store.products_count} sub={`آخر مزامنة: ${store.last_sync === 'never' ? 'لم تتم' : 'تمت'}`} color="text-warning" />
            <StatCard label="متوسط التقييم" value={r?.avg ? `${r.avg} ★` : '—'} sub={`${r?.count ?? 0} تقييم`} color="text-secondary" />
          </div>

          {/* Messages breakdown */}
          {m && m.total > 0 && (
            <Card className="bg-content1 border border-divider">
              <CardHeader className="px-5 py-4">
                <h2 className="font-bold text-sm">توزيع الرسائل</h2>
              </CardHeader>
              <Divider />
              <CardBody className="px-5 py-4 space-y-3">
                {[
                  { label: 'رسائل العملاء', value: m.user, color: 'primary' as const },
                  { label: 'ردود البوت', value: m.bot, color: 'success' as const },
                  { label: 'ردود الإدارة', value: m.admin, color: 'warning' as const },
                ].map(item => (
                  <div key={item.label}>
                    <div className="flex justify-between text-xs mb-1">
                      <span className="text-default-300">{item.label}</span>
                      <span className="text-default-400">{item.value} ({m.total ? Math.round(item.value / m.total * 100) : 0}%)</span>
                    </div>
                    <Progress
                      value={m.total ? (item.value / m.total) * 100 : 0}
                      color={item.color}
                      size="sm"
                      classNames={{ base: 'max-w-full' }}
                    />
                  </div>
                ))}
              </CardBody>
            </Card>
          )}

          {/* Daily chart — last 7 days */}
          {c?.daily_counts && c.daily_counts.length > 0 && (
            <Card className="bg-content1 border border-divider">
              <CardHeader className="px-5 py-4">
                <h2 className="font-bold text-sm">المحادثات (آخر 14 يوم)</h2>
              </CardHeader>
              <Divider />
              <CardBody className="px-5 py-4">
                <div className="flex items-end gap-1 h-20">
                  {c.daily_counts.slice(-14).map(d => {
                    const max = Math.max(...c.daily_counts.map(x => x.count), 1)
                    const h = d.count === 0 ? 4 : Math.max(4, (d.count / max) * 80)
                    return (
                      <div key={d.date} className="flex-1 flex flex-col items-center gap-1">
                        <div
                          className="w-full bg-primary/60 rounded-sm hover:bg-primary transition-colors"
                          style={{ height: `${h}px` }}
                          title={`${d.date}: ${d.count} محادثة`}
                        />
                      </div>
                    )
                  })}
                </div>
                <div className="flex justify-between text-xs text-default-500 mt-2">
                  <span>{c.daily_counts.at(-14)?.date?.slice(5)}</span>
                  <span>{c.daily_counts.at(-1)?.date?.slice(5)}</span>
                </div>
              </CardBody>
            </Card>
          )}

          {/* Ratings distribution */}
          {r && r.count > 0 && (
            <Card className="bg-content1 border border-divider">
              <CardHeader className="px-5 py-4">
                <h2 className="font-bold text-sm">توزيع التقييمات</h2>
              </CardHeader>
              <Divider />
              <CardBody className="px-5 py-4 space-y-2">
                {[5,4,3,2,1].map(star => {
                  const count = r.distribution[star - 1] ?? 0
                  const pct = r.count ? (count / r.count) * 100 : 0
                  return (
                    <div key={star} className="flex items-center gap-3">
                      <span className="text-xs text-default-400 w-6 text-left">{star}★</span>
                      <Progress value={pct} size="sm" color="warning" className="flex-1" />
                      <span className="text-xs text-default-400 w-6 text-right">{count}</span>
                    </div>
                  )
                })}
              </CardBody>
            </Card>
          )}
        </>
      )}
    </div>
  )
}
