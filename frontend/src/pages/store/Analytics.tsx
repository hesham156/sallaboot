import { useEffect, useState } from 'react'
import {
  Card, CardBody, CardHeader, Spinner, Divider, Chip, Tooltip,
} from '@heroui/react'
import {
  api,
  Analytics as AnalyticsData,
  ConversationInsights,
  TopicItem,
  NonPurchaseItem,
  AtRiskCustomer,
} from '../../api'

interface Props { storeId: string }

// ── Small helpers ──────────────────────────────────────────────────────────────

function BarRow({ label, value, max, color, icon, examples }: {
  label: string; value: number; max: number
  color: string; icon: string; examples?: string[]
}) {
  const pct = max ? Math.round((value / max) * 100) : 0
  const bar = (
    <div className="flex items-center gap-2 flex-1">
      <div className="flex-1 h-2.5 bg-content2 rounded-full overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-700"
          style={{ width: `${pct}%`, background: color }}
        />
      </div>
      <span className="text-xs font-bold w-10 text-right" style={{ color }}>{value}</span>
    </div>
  )

  return (
    <div className="flex items-center gap-3 py-1.5">
      <span className="text-base w-6 text-center">{icon}</span>
      <span className="text-xs text-default-500 w-28 shrink-0 truncate">{label}</span>
      {examples && examples.length > 0 ? (
        <Tooltip
          content={
            <div className="max-w-xs p-2 space-y-1">
              {examples.map((e, i) => (
                <p key={i} className="text-xs text-default-400 leading-relaxed">«{e}»</p>
              ))}
            </div>
          }
          placement="top"
        >
          <div className="flex-1 flex items-center gap-2 cursor-help">{bar}</div>
        </Tooltip>
      ) : bar}
    </div>
  )
}

function SentimentDot({ mood, count, total }: { mood: string; count: number; total: number }) {
  const cfg: Record<string, { icon: string; label: string; color: string }> = {
    happy:   { icon: '😊', label: 'راضون',     color: '#22c55e' },
    neutral: { icon: '😐', label: 'محايدون',   color: '#a3a3a3' },
    angry:   { icon: '😠', label: 'غير راضين', color: '#ef4444' },
  }
  const { icon, label, color } = cfg[mood] ?? { icon: '❓', label: mood, color: '#777' }
  const pct = total ? Math.round((count / total) * 100) : 0
  return (
    <div className="flex flex-col items-center gap-1">
      <span className="text-2xl">{icon}</span>
      <span className="text-lg font-black" style={{ color }}>{pct}%</span>
      <span className="text-xs text-default-400">{label}</span>
      <span className="text-xs text-default-500">{count}</span>
    </div>
  )
}

// ── Main component ─────────────────────────────────────────────────────────────

export default function Analytics({ storeId }: Props) {
  const [data,     setData]     = useState<AnalyticsData | null>(null)
  const [insights, setInsights] = useState<ConversationInsights | null>(null)
  const [loading,  setLoading]  = useState(true)

  useEffect(() => {
    Promise.all([
      api.analytics(storeId),
      api.insights(storeId),
    ])
      .then(([a, ins]) => { setData(a); setInsights(ins) })
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

  const c  = data.conversations
  const m  = data.messages
  const ac = data.abandoned_carts
  const r  = data.ratings

  const HOURS  = Array.from({ length: 24 }, (_, i) => `${i}:00`)
  const maxHour = Math.max(...c.hourly_distribution, 1)
  const maxDay  = Math.max(...c.daily_counts.map(d => d.count), 1)

  // Topic bar max
  const maxTopic  = Math.max(...(insights?.top_questions.map(t => t.count) ?? [1]), 1)
  const maxReason = Math.max(...(insights?.non_purchase.map(n => n.count) ?? [1]), 1)

  const TOPIC_COLORS = [
    '#6366f1', '#8b5cf6', '#a855f7', '#ec4899',
    '#f59e0b', '#10b981', '#3b82f6', '#f43f5e', '#14b8a6',
  ]

  return (
    <div className="p-6 space-y-6" dir="rtl">
      <h1 className="text-xl font-bold text-foreground">التحليلات</h1>

      {/* ── KPI Cards ── */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {[
          { label: 'إجمالي المحادثات', value: c.total,          color: 'text-primary' },
          { label: 'هذا الأسبوع',      value: c.this_week,      color: 'text-success' },
          { label: 'معدل الرسائل',     value: c.avg_messages,   color: 'text-warning' },
          { label: 'تولي الإدارة',     value: c.admin_takeover, color: 'text-danger' },
        ].map(s => (
          <Card key={s.label} className="bg-content1 border border-divider">
            <CardBody className="py-4 px-5">
              <p className="text-xs text-default-400 font-medium">{s.label}</p>
              <p className={`text-3xl font-black mt-2 ${s.color}`}>{s.value}</p>
            </CardBody>
          </Card>
        ))}
      </div>

      {/* ── Conversion + Sentiment row ── */}
      {insights && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {/* Conversion funnel */}
          <Card className="bg-content1 border border-divider">
            <CardHeader className="px-5 py-4">
              <h2 className="font-bold text-sm">معدل التحويل إلى مبيعات</h2>
            </CardHeader>
            <Divider />
            <CardBody className="px-5 py-5 flex flex-col items-center gap-4">
              <div
                className="text-5xl font-black"
                style={{ color: insights.conversion.conversion_rate >= 20 ? '#22c55e' : '#f59e0b' }}
              >
                {insights.conversion.conversion_rate}%
              </div>
              <div className="w-full grid grid-cols-3 gap-2 text-center">
                {[
                  { label: 'إجمالي المحادثات', value: insights.conversion.total_convs,      color: 'text-foreground' },
                  { label: 'اكتملوا بشراء',    value: insights.conversion.with_checkout,    color: 'text-success' },
                  { label: 'بدون شراء',         value: insights.conversion.without_checkout, color: 'text-default-400' },
                ].map(s => (
                  <div key={s.label} className="bg-content2 rounded-xl p-3">
                    <p className="text-xs text-default-400">{s.label}</p>
                    <p className={`text-xl font-bold mt-1 ${s.color}`}>{s.value}</p>
                  </div>
                ))}
              </div>
            </CardBody>
          </Card>

          {/* Sentiment */}
          <Card className="bg-content1 border border-divider">
            <CardHeader className="px-5 py-4">
              <h2 className="font-bold text-sm">مزاج العملاء</h2>
            </CardHeader>
            <Divider />
            <CardBody className="px-5 py-5">
              <div className="flex justify-around items-center h-full">
                {(['happy', 'neutral', 'angry'] as const).map(mood => (
                  <SentimentDot
                    key={mood}
                    mood={mood}
                    count={insights.sentiment_summary[mood]}
                    total={insights.sentiment_summary.total}
                  />
                ))}
              </div>
            </CardBody>
          </Card>
        </div>
      )}

      {/* ── Hourly heatmap ── */}
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
                    style={{ height: `${h}px`, background: `rgba(99,102,241,${0.2 + (v / maxHour) * 0.8})` }}
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

      {/* ── Daily chart ── */}
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

      {/* ── TOP QUESTIONS ── */}
      {insights && insights.top_questions.length > 0 && (
        <Card className="bg-content1 border border-divider">
          <CardHeader className="px-5 py-4 flex items-center gap-3">
            <h2 className="font-bold text-sm">أكثر الأسئلة والمواضيع شيوعاً</h2>
            <Chip size="sm" variant="flat" color="primary">{insights.top_questions.length} موضوع</Chip>
          </CardHeader>
          <Divider />
          <CardBody className="px-5 py-4 space-y-1">
            {insights.top_questions.map((t: TopicItem, idx: number) => (
              <BarRow
                key={t.id}
                icon={t.icon}
                label={t.label}
                value={t.count}
                max={maxTopic}
                color={TOPIC_COLORS[idx % TOPIC_COLORS.length]}
                examples={t.examples}
              />
            ))}
            <p className="text-xs text-default-400 pt-2">
              💡 مرّر على الشريط لرؤية أمثلة من المحادثات الفعلية
            </p>
          </CardBody>
        </Card>
      )}

      {/* ── NON-PURCHASE REASONS ── */}
      {insights && insights.non_purchase.length > 0 && (
        <Card className="bg-content1 border border-divider">
          <CardHeader className="px-5 py-4 flex items-center gap-3">
            <h2 className="font-bold text-sm">أسباب عدم إتمام الشراء</h2>
            <Chip size="sm" variant="flat" color="warning">{insights.conversion.without_checkout} محادثة بدون شراء</Chip>
          </CardHeader>
          <Divider />
          <CardBody className="px-5 py-4 space-y-1">
            {insights.non_purchase.map((n: NonPurchaseItem, idx: number) => (
              <div key={n.id} className="flex items-center gap-3 py-1.5">
                <span className="text-base w-6 text-center">{n.icon}</span>
                <span className="text-xs text-default-500 w-40 shrink-0">{n.label}</span>
                <div className="flex-1 h-2.5 bg-content2 rounded-full overflow-hidden">
                  <div
                    className="h-full rounded-full transition-all duration-700"
                    style={{
                      width: `${Math.round((n.count / maxReason) * 100)}%`,
                      background: ['#f59e0b','#ef4444','#8b5cf6','#3b82f6','#10b981','#ec4899'][idx % 6],
                    }}
                  />
                </div>
                <span className="text-xs font-bold w-10 text-right text-default-500">{n.count}</span>
                <span className="text-xs text-default-400 w-10 text-right">{n.percent}%</span>
              </div>
            ))}
          </CardBody>
        </Card>
      )}

      {/* ── AT-RISK CUSTOMERS ── */}
      {insights && insights.at_risk_customers.length > 0 && (
        <Card className="bg-content1 border border-danger/30">
          <CardHeader className="px-5 py-4 flex items-center gap-3">
            <h2 className="font-bold text-sm text-danger">⚠️ عملاء في خطر</h2>
            <Chip size="sm" variant="flat" color="danger">{insights.at_risk_customers.length}</Chip>
            <span className="text-xs text-default-400">عملاء غاضبون أو محتمل خسارتهم</span>
          </CardHeader>
          <Divider />
          <CardBody className="px-5 py-4 space-y-3">
            {insights.at_risk_customers.slice(0, 10).map((cust: AtRiskCustomer) => (
              <div
                key={cust.session_id}
                className="p-3 rounded-xl bg-danger/5 border border-danger/20 space-y-1.5"
              >
                <div className="flex items-center justify-between gap-2 flex-wrap">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold text-foreground">
                      {cust.customer_name !== '—' ? cust.customer_name : 'عميل مجهول'}
                    </span>
                    {cust.customer_phone !== '—' && (
                      <span className="text-xs text-default-400">{cust.customer_phone}</span>
                    )}
                  </div>
                  <div className="flex items-center gap-2">
                    {cust.rating && (
                      <Chip size="sm" color="danger" variant="flat">★ {cust.rating}</Chip>
                    )}
                    <Chip size="sm" color="warning" variant="flat">{cust.signal}</Chip>
                  </div>
                </div>
                {cust.last_message && (
                  <p className="text-xs text-default-500 leading-relaxed line-clamp-2 bg-content2 px-2.5 py-1.5 rounded-lg">
                    «{cust.last_message}»
                  </p>
                )}
                <p className="text-xs text-default-400">
                  {new Date(cust.ts).toLocaleString('ar-SA', { dateStyle: 'short', timeStyle: 'short' })}
                </p>
              </div>
            ))}
            {insights.at_risk_customers.length > 10 && (
              <p className="text-xs text-default-400 text-center pt-1">
                + {insights.at_risk_customers.length - 10} عميل آخر — راجع المحادثات للتفاصيل الكاملة
              </p>
            )}
          </CardBody>
        </Card>
      )}

      {/* ── Message breakdown + Abandoned carts ── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card className="bg-content1 border border-divider">
          <CardHeader className="px-5 py-4"><h2 className="font-bold text-sm">الرسائل</h2></CardHeader>
          <Divider />
          <CardBody className="px-5 py-4 space-y-3">
            {[
              { label: 'العملاء', value: m.user,  color: '#6366f1' },
              { label: 'البوت',   value: m.bot,   color: '#22c55e' },
              { label: 'الإدارة', value: m.admin, color: '#f59e0b' },
            ].map(item => (
              <div key={item.label} className="flex items-center gap-3">
                <span className="text-xs text-default-400 w-16">{item.label}</span>
                <div className="flex-1 h-3 bg-content2 rounded-full overflow-hidden">
                  <div
                    className="h-full rounded-full transition-all"
                    style={{ width: m.total ? `${(item.value / m.total) * 100}%` : '0%', background: item.color }}
                  />
                </div>
                <span className="text-xs font-bold w-8 text-right" style={{ color: item.color }}>{item.value}</span>
              </div>
            ))}
          </CardBody>
        </Card>

        <Card className="bg-content1 border border-divider">
          <CardHeader className="px-5 py-4"><h2 className="font-bold text-sm">السلات المتروكة</h2></CardHeader>
          <Divider />
          <CardBody className="px-5 py-4 space-y-2">
            {[
              { label: 'الإجمالي',       value: ac.total,                    color: 'text-foreground' },
              { label: 'تم الاسترداد',   value: ac.recovered,                color: 'text-success' },
              { label: 'قيد الانتظار',   value: ac.pending,                  color: 'text-warning' },
              { label: 'معدل الاسترداد', value: `${ac.recovery_rate}%`,      color: 'text-primary' },
            ].map(s => (
              <div key={s.label} className="flex items-center justify-between py-1.5 border-b border-divider last:border-0">
                <span className="text-sm text-default-400">{s.label}</span>
                <span className={`font-bold text-sm ${s.color}`}>{s.value}</span>
              </div>
            ))}
          </CardBody>
        </Card>
      </div>

      {/* ── Ratings ── */}
      {r.count > 0 && (
        <Card className="bg-content1 border border-divider">
          <CardHeader className="px-5 py-4">
            <div className="flex items-center gap-3">
              <h2 className="font-bold text-sm">التقييمات</h2>
              <Chip size="sm" color="warning" variant="flat">★ {r.avg} ({r.count} تقييم)</Chip>
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
                    <div className="h-full bg-warning rounded-full transition-all" style={{ width: `${pct}%` }} />
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
