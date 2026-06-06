import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Button, Card, CardBody, CardHeader, Spinner, Divider, Chip, Tooltip,
} from '@heroui/react'
import {
  api,
  Analytics as AnalyticsData,
  ChannelStats,
  ConversationInsights,
  TopicItem,
  NonPurchaseItem,
  AtRiskCustomer,
} from '../../api'

type Channel = 'total' | 'widget' | 'whatsapp'

const CHANNEL_LABELS: Record<Channel, { label: string; emoji: string; color: string }> = {
  total:    { label: 'الإجمالي',  emoji: '📊', color: 'text-foreground' },
  widget:   { label: 'متجر (ويدجت)', emoji: '🛍️', color: 'text-teal-500' },
  whatsapp: { label: 'واتساب',     emoji: '🟢', color: 'text-emerald-500' },
}

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

// Convert a phone number to the wa.me canonical form (no +, no leading 0,
// no spaces / dashes). Falls back to the cleaned digits when we can't
// detect a country code.
function whatsappUrl(rawPhone: string, prefilledMessage: string): string {
  const digits = (rawPhone || '').replace(/[^\d]/g, '')
  let normalized = digits
  if (normalized.startsWith('00')) normalized = normalized.slice(2)
  if (normalized.startsWith('0'))  normalized = '966' + normalized.slice(1) // assume Saudi by default
  const text = encodeURIComponent(prefilledMessage)
  return `https://wa.me/${normalized}?text=${text}`
}

export default function Analytics({ storeId }: Props) {
  const navigate = useNavigate()
  const [data,     setData]     = useState<AnalyticsData | null>(null)
  const [insights, setInsights] = useState<ConversationInsights | null>(null)
  const [loading,  setLoading]  = useState(true)
  const [channel,  setChannel]  = useState<Channel>('total')

  function openConv(sessionId: string) {
    navigate(`/store/${storeId}/conversations?session=${encodeURIComponent(sessionId)}`)
  }

  useEffect(() => {
    Promise.all([
      api.analytics(storeId),
      api.insights(storeId),
    ])
      .then(([a, ins]) => { setData(a); setInsights(ins) })
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [storeId])

  // Pick the slice for the chosen channel. Falls back to the top-level
  // legacy fields if the backend hasn't been redeployed yet.
  const slice: ChannelStats | null = useMemo(() => {
    if (!data) return null
    const bc = data.by_channel
    if (bc && bc[channel]) return bc[channel]
    return {
      conversations: data.conversations,
      messages:      data.messages,
      ratings:       data.ratings,
    }
  }, [data, channel])

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <Spinner size="lg" color="primary" />
      </div>
    )
  }

  if (!data || !slice) return null

  const c  = slice.conversations
  const m  = slice.messages
  const ac = data.abandoned_carts   // not split by channel
  const r  = slice.ratings
  const bc = data.by_channel

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
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-bold text-foreground">التحليلات</h1>

        {/* Channel switcher — shown only when the backend supports by_channel */}
        {bc && (
          <div className="flex items-center gap-1.5 bg-content2 p-1 rounded-2xl">
            {(['total', 'widget', 'whatsapp'] as Channel[]).map(ch => {
              const cfg    = CHANNEL_LABELS[ch]
              const slice2 = bc[ch]
              const count  = slice2?.conversations.total ?? 0
              const active = channel === ch
              return (
                <button
                  key={ch}
                  onClick={() => setChannel(ch)}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-bold transition-all ${
                    active
                      ? 'bg-content1 shadow-sm ' + cfg.color
                      : 'text-default-500 hover:text-foreground'
                  }`}
                >
                  <span>{cfg.emoji}</span>
                  <span>{cfg.label}</span>
                  <span className={`text-[10px] px-1.5 py-0.5 rounded-full ${
                    active ? 'bg-content2' : 'bg-content1'
                  }`}>{count}</span>
                </button>
              )
            })}
          </div>
        )}
      </div>

      {/* Channel split overview — at-a-glance per-channel summary */}
      {bc && channel === 'total' && (bc.whatsapp.conversations.total > 0 || bc.widget.conversations.total > 0) && (
        <Card className="bg-content1 border border-divider">
          <CardHeader className="px-5 py-4">
            <h2 className="font-bold text-sm">التوزيع حسب القناة</h2>
          </CardHeader>
          <Divider />
          <CardBody className="px-5 py-4">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {(['widget', 'whatsapp'] as const).map(ch => {
                const s    = bc[ch]
                const cfg  = CHANNEL_LABELS[ch]
                const all  = bc.total.conversations.total
                const pct  = all ? Math.round((s.conversations.total / all) * 100) : 0
                return (
                  <button
                    key={ch}
                    onClick={() => setChannel(ch)}
                    className="text-right p-4 rounded-2xl bg-content2 hover:bg-content2/70 border border-divider transition-all"
                  >
                    <div className="flex items-center justify-between mb-2">
                      <span className={`text-sm font-bold flex items-center gap-1.5 ${cfg.color}`}>
                        <span>{cfg.emoji}</span>{cfg.label}
                      </span>
                      <span className="text-[11px] text-default-500">{pct}%</span>
                    </div>
                    <div className="flex items-baseline gap-2 mb-2">
                      <span className="text-2xl font-black text-foreground">{s.conversations.total}</span>
                      <span className="text-xs text-default-500">محادثة</span>
                    </div>
                    <div className="h-2 bg-content1 rounded-full overflow-hidden mb-2">
                      <div
                        className={`h-full rounded-full ${
                          ch === 'whatsapp' ? 'bg-emerald-500' : 'bg-teal-500'
                        }`}
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                    <div className="flex items-center gap-3 text-[11px] text-default-500">
                      <span>👤 {s.messages.user}</span>
                      <span>🤖 {s.messages.bot}</span>
                      <span>👨‍💼 {s.messages.admin}</span>
                      {s.ratings.count > 0 && <span>★ {s.ratings.avg}</span>}
                    </div>
                  </button>
                )
              })}
            </div>
          </CardBody>
        </Card>
      )}

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
            {insights.at_risk_customers.slice(0, 10).map((cust: AtRiskCustomer) => {
              const hasPhone = cust.customer_phone && cust.customer_phone !== '—'
              const customerName = cust.customer_name && cust.customer_name !== '—'
                ? cust.customer_name : 'عزيزي العميل'
              const apology =
                `أهلاً ${customerName}،\n\n` +
                'لاحظنا أن تجربتك معنا لم تكن بالمستوى المتوقع ونعتذر بشدة عن ذلك. ' +
                'يسعدنا تعويضك ومتابعة طلبك شخصياً. هل يمكننا مساعدتك الآن؟'
              return (
                <div
                  key={cust.session_id}
                  className="p-3 rounded-xl bg-danger/5 border border-danger/20 space-y-2"
                >
                  <div className="flex items-center justify-between gap-2 flex-wrap">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-semibold text-foreground">
                        {cust.customer_name !== '—' ? cust.customer_name : 'عميل مجهول'}
                      </span>
                      {cust.customer_phone !== '—' && (
                        <span className="text-xs text-default-400" dir="ltr">{cust.customer_phone}</span>
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
                  <div className="flex items-center justify-between gap-2 flex-wrap pt-1">
                    <p className="text-xs text-default-400">
                      {new Date(cust.ts).toLocaleString('ar-SA', { dateStyle: 'short', timeStyle: 'short' })}
                    </p>
                    <div className="flex items-center gap-1.5">
                      <Button
                        size="sm" color="danger" variant="flat"
                        onPress={() => openConv(cust.session_id)}
                        startContent={
                          <svg width={13} height={13} viewBox="0 0 24 24" fill="none"
                               stroke="currentColor" strokeWidth={2}
                               strokeLinecap="round" strokeLinejoin="round">
                            <path d="M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                          </svg>
                        }
                        className="text-xs font-bold"
                      >
                        فتح المحادثة
                      </Button>
                      {hasPhone && (
                        <Button
                          size="sm" variant="flat"
                          as="a"
                          href={whatsappUrl(cust.customer_phone, apology)}
                          target="_blank"
                          rel="noopener noreferrer"
                          startContent={
                            <svg width={13} height={13} viewBox="0 0 24 24" fill="currentColor">
                              <path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51l-.57-.01c-.198 0-.52.074-.792.372s-1.04 1.016-1.04 2.479 1.065 2.876 1.213 3.074c.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 00-3.48-8.413"/>
                            </svg>
                          }
                          className="text-xs font-bold bg-emerald-500/15 text-emerald-600 hover:bg-emerald-500/25"
                        >
                          واتساب
                        </Button>
                      )}
                    </div>
                  </div>
                </div>
              )
            })}
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
