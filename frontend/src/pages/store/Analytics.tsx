import { useEffect, useState } from 'react'
import { Card, CardBody, CardHeader, Spinner, Divider, Chip } from '@heroui/react'
import { api, Analytics as AnalyticsData } from '../../api'

interface Props { storeId: string }

export default function Analytics({ storeId }: Props) {
  const [data, setData] = useState<AnalyticsData | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.analytics(storeId)
      .then(setData)
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [storeId])

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <Spinner size="lg" color="primary" />
      </div>
    )
  }

  if (!data) return null

  const c = data.conversations
  const m = data.messages
  const ac = data.abandoned_carts
  const r = data.ratings

  const HOURS = Array.from({ length: 24 }, (_, i) => `${i}:00`)
  const maxHour = Math.max(...c.hourly_distribution, 1)
  const maxDay  = Math.max(...c.daily_counts.map(d => d.count), 1)

  return (
    <div className="p-6 space-y-6">
      <h1 className="text-xl font-bold text-foreground">التحليلات</h1>

      {/* KPI Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {[
          { label: 'إجمالي المحادثات', value: c.total,       color: 'text-primary' },
          { label: 'هذا الأسبوع',      value: c.this_week,   color: 'text-success' },
          { label: 'معدل الرسائل',    value: c.avg_messages, color: 'text-warning' },
          { label: 'تولي الإدارة',    value: c.admin_takeover, color: 'text-danger' },
        ].map(s => (
          <Card key={s.label} className="bg-content1 border border-divider">
            <CardBody className="py-4 px-5">
              <p className="text-xs text-default-400 font-medium">{s.label}</p>
              <p className={`text-3xl font-black mt-2 ${s.color}`}>{s.value}</p>
            </CardBody>
          </Card>
        ))}
      </div>

      {/* Hourly heatmap */}
      <Card className="bg-content1 border border-divider">
        <CardHeader className="px-5 py-4"><h2 className="font-bold text-sm">توزيع الساعات</h2></CardHeader>
        <Divider />
        <CardBody className="px-5 py-4">
          <div className="flex items-end gap-0.5 h-24">
            {c.hourly_distribution.map((v, i) => {
              const h = v === 0 ? 3 : Math.max(3, (v / maxHour) * 96)
              return (
                <div key={i} className="flex-1 flex flex-col items-center">
                  <div
                    className="w-full rounded-sm hover:opacity-80 transition-opacity"
                    style={{
                      height: `${h}px`,
                      background: `rgba(59, 130, 246, ${0.2 + (v / maxHour) * 0.8})`,
                    }}
                    title={`${i}:00 — ${v} محادثة`}
                  />
                </div>
              )
            })}
          </div>
          <div className="flex justify-between text-xs text-default-500 mt-2">
            <span>12 ص</span><span>6 ص</span><span>12 م</span><span>6 م</span><span>12 ص</span>
          </div>
        </CardBody>
      </Card>

      {/* Daily chart */}
      <Card className="bg-content1 border border-divider">
        <CardHeader className="px-5 py-4"><h2 className="font-bold text-sm">المحادثات اليومية</h2></CardHeader>
        <Divider />
        <CardBody className="px-5 py-4">
          <div className="flex items-end gap-1 h-32">
            {c.daily_counts.map(d => {
              const h = d.count === 0 ? 3 : Math.max(3, (d.count / maxDay) * 128)
              return (
                <div key={d.date} className="flex-1 flex flex-col items-center gap-1">
                  <div
                    className="w-full bg-primary/70 rounded hover:bg-primary transition-colors"
                    style={{ height: `${h}px` }}
                    title={`${d.date}: ${d.count}`}
                  />
                  <span className="text-xs text-default-600 hidden sm:block"
                    style={{ writingMode: 'vertical-lr', fontSize: '9px' }}>
                    {d.date.slice(5)}
                  </span>
                </div>
              )
            })}
          </div>
        </CardBody>
      </Card>

      {/* Message breakdown + Abandoned carts */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card className="bg-content1 border border-divider">
          <CardHeader className="px-5 py-4"><h2 className="font-bold text-sm">الرسائل</h2></CardHeader>
          <Divider />
          <CardBody className="px-5 py-4 space-y-3">
            {[
              { label: 'العملاء', value: m.user, color: '#3b82f6' },
              { label: 'البوت',   value: m.bot,  color: '#22c55e' },
              { label: 'الإدارة', value: m.admin, color: '#f59e0b' },
            ].map(item => (
              <div key={item.label} className="flex items-center gap-3">
                <span className="text-xs text-default-400 w-16">{item.label}</span>
                <div className="flex-1 h-3 bg-content2 rounded-full overflow-hidden">
                  <div
                    className="h-full rounded-full transition-all"
                    style={{
                      width: m.total ? `${(item.value / m.total) * 100}%` : '0%',
                      background: item.color,
                    }}
                  />
                </div>
                <span className="text-xs font-bold w-8 text-right" style={{ color: item.color }}>
                  {item.value}
                </span>
              </div>
            ))}
          </CardBody>
        </Card>

        <Card className="bg-content1 border border-divider">
          <CardHeader className="px-5 py-4"><h2 className="font-bold text-sm">السلات المتروكة</h2></CardHeader>
          <Divider />
          <CardBody className="px-5 py-4 space-y-2">
            {[
              { label: 'الإجمالي',    value: ac.total,          color: 'text-foreground' },
              { label: 'تم الاسترداد', value: ac.recovered,     color: 'text-success' },
              { label: 'قيد الانتظار', value: ac.pending,       color: 'text-warning' },
              { label: 'معدل الاسترداد', value: `${ac.recovery_rate}%`, color: 'text-primary' },
            ].map(s => (
              <div key={s.label} className="flex items-center justify-between py-1.5 border-b border-divider last:border-0">
                <span className="text-sm text-default-400">{s.label}</span>
                <span className={`font-bold text-sm ${s.color}`}>{s.value}</span>
              </div>
            ))}
          </CardBody>
        </Card>
      </div>

      {/* Ratings */}
      {r.count > 0 && (
        <Card className="bg-content1 border border-divider">
          <CardHeader className="px-5 py-4">
            <div className="flex items-center gap-3">
              <h2 className="font-bold text-sm">التقييمات</h2>
              <Chip size="sm" color="warning" variant="flat">
                ★ {r.avg} ({r.count} تقييم)
              </Chip>
            </div>
          </CardHeader>
          <Divider />
          <CardBody className="px-5 py-4 space-y-2">
            {[5,4,3,2,1].map(star => {
              const count = r.distribution[star - 1] ?? 0
              const pct   = r.count ? (count / r.count) * 100 : 0
              return (
                <div key={star} className="flex items-center gap-3">
                  <span className="text-xs text-default-400 w-5">{star}★</span>
                  <div className="flex-1 h-2.5 bg-content2 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-warning rounded-full transition-all"
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                  <span className="text-xs text-default-400 w-6 text-right">{count}</span>
                </div>
              )
            })}
          </CardBody>
        </Card>
      )}
    </div>
  )
}
