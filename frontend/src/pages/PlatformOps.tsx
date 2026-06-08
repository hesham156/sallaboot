import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Button, Card, CardBody, CardHeader, Chip, Divider, Spinner, Table,
  TableBody, TableCell, TableColumn, TableHeader, TableRow,
} from '@heroui/react'
import { api, ApiError, PlatformOpsSnapshot, PlatformOpsStoreRow, getIsSuper } from '../api'

/* ─────────────────────────── Helpers ────────────────────────────────── */

function fmt(n: number): string {
  return n.toLocaleString('ar-EG')
}

function fmtDate(iso: string): string {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleDateString('ar-EG', { year: 'numeric', month: 'short', day: 'numeric' })
  } catch { return iso }
}

const TOKEN_STATUS_CHIP: Record<string, { label: string; color: 'success' | 'warning' | 'danger' | 'default' }> = {
  valid:    { label: 'صالح',         color: 'success' },
  expiring: { label: 'قريب الانتهاء', color: 'warning' },
  expired:  { label: 'منتهٍ',         color: 'danger'  },
  unknown:  { label: 'غير محدد',     color: 'default' },
}

// Big-number tile. Tone-coded so red counters draw the eye without
// requiring the user to read the labels first.
function StatCard({ label, value, hint, tone = 'neutral' }: {
  label: string; value: string | number; hint?: string
  tone?: 'neutral' | 'good' | 'warning' | 'danger'
}) {
  const toneClass = {
    neutral: 'border-slate-200 bg-white',
    good:    'border-emerald-200 bg-emerald-50/40',
    warning: 'border-amber-200  bg-amber-50/40',
    danger:  'border-rose-200   bg-rose-50/40',
  }[tone]
  const valueClass = {
    neutral: 'text-slate-900',
    good:    'text-emerald-700',
    warning: 'text-amber-700',
    danger:  'text-rose-700',
  }[tone]
  return (
    <div className={`rounded-2xl border p-4 ${toneClass}`}>
      <div className="text-xs text-default-500">{label}</div>
      <div className={`mt-2 text-2xl font-extrabold font-mono ${valueClass}`}>
        {typeof value === 'number' ? fmt(value) : value}
      </div>
      {hint && <div className="text-[11px] text-default-400 mt-1">{hint}</div>}
    </div>
  )
}

// Queue depths card — pending/processing/failed/dead per queue. Failed
// and dead get red colour because they need operator attention.
function QueueCard({ title, counts }: { title: string; counts: Record<string, number> }) {
  const rows = [
    { key: 'pending',    label: 'انتظار',     color: 'text-slate-700' },
    { key: 'processing', label: 'قيد المعالجة', color: 'text-sky-600'  },
    { key: 'done',       label: 'مكتمل',       color: 'text-emerald-600' },
    { key: 'failed',     label: 'فشل',        color: 'text-amber-600' },
    { key: 'dead',       label: 'ميت',         color: 'text-rose-600'  },
  ]
  const total = Object.values(counts).reduce((s, n) => s + n, 0)
  return (
    <Card>
      <CardHeader className="flex items-center justify-between">
        <h3 className="font-bold">{title}</h3>
        <span className="text-xs text-default-400">إجمالي: {fmt(total)}</span>
      </CardHeader>
      <Divider />
      <CardBody className="space-y-1">
        {rows.map((r) => {
          const n = counts[r.key] || 0
          if (!n && r.key !== 'pending') return null   // hide empty rows except pending baseline
          return (
            <div key={r.key} className="flex items-center justify-between text-sm">
              <span className="text-default-500">{r.label}</span>
              <span className={`font-mono font-bold ${r.color}`}>{fmt(n)}</span>
            </div>
          )
        })}
      </CardBody>
    </Card>
  )
}

/* ─────────────────────────── Page ───────────────────────────────────── */

export default function PlatformOps() {
  const navigate = useNavigate()
  const [data, setData]       = useState<PlatformOpsSnapshot | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState<string>('')
  const [refreshing, setRefreshing] = useState(false)

  async function load(initial = false) {
    if (!initial) setRefreshing(true)
    else setLoading(true)
    setError('')
    try {
      setData(await api.platformOps())
    } catch (e) {
      const msg = e instanceof ApiError ? e.detail : (e instanceof Error ? e.message : '—')
      setError(msg)
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }

  useEffect(() => {
    if (!getIsSuper()) { navigate('/login', { replace: true }); return }
    load(true)
    // Light-touch auto-refresh — every 60s the dashboard re-pulls so it
    // doesn't get stale during a long admin session.
    const t = setInterval(() => load(false), 60_000)
    return () => clearInterval(t)
  }, [])

  if (loading && !data) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <Spinner size="lg" color="primary" label="جاري التحميل..." />
      </div>
    )
  }
  if (error || !data) {
    return (
      <div className="min-h-screen flex items-center justify-center p-6" dir="rtl">
        <div className="max-w-md text-center bg-white rounded-2xl p-8 shadow-sm border border-rose-100">
          <p className="text-rose-600 mb-3 font-bold">تعذّر تحميل لوحة العمليات</p>
          <p className="text-xs text-default-500 mb-4 break-words">{error || '—'}</p>
          <Button color="primary" variant="flat" onPress={() => load(true)}>إعادة المحاولة</Button>
        </div>
      </div>
    )
  }

  const t = data.totals
  const e = data.errors
  const hasErrors = e.webhook_errors_24h > 0 || e.login_failures_24h > 0

  return (
    <div className="min-h-screen bg-slate-50 p-4 md:p-6" dir="rtl">
      {/* ── Header ───────────────────────────────────────────────── */}
      <div className="max-w-7xl mx-auto space-y-4">
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div>
            <h1 className="text-2xl md:text-3xl font-extrabold text-slate-900">عمليات المنصة</h1>
            <p className="text-sm text-default-500 mt-1">
              لقطة تشغيلية لكل المتاجر، الطوابير، والأخطاء — يُحدّث كل دقيقة تلقائياً.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="flat" onPress={() => navigate('/admin')}>
              قائمة المتاجر
            </Button>
            <Button variant="flat" color="warning" onPress={() => navigate('/admin/audit-log')}>
              سجل المراجعة
            </Button>
            <Button color="primary" onPress={() => load(false)} isLoading={refreshing}>
              تحديث
            </Button>
          </div>
        </div>

        {/* ── Top totals ────────────────────────────────────────── */}
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
          <StatCard label="إجمالي المتاجر"      value={t.stores_registered} />
          <StatCard label="متاجر نشطة اليوم"    value={t.stores_active_today} tone="good" />
          <StatCard label="رسائل اليوم"          value={t.messages_today} />
          <StatCard label="توكنز LLM اليوم"      value={t.tokens_today}
                    hint={`${fmt(t.llm_requests_today)} طلب`} />
          <StatCard label="متاجر اقتربت من الحد" value={data.near_budget.length}
                    tone={data.near_budget.length ? 'warning' : 'good'} />
        </div>

        {/* ── Errors + security ─────────────────────────────────── */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <StatCard label="أخطاء webhooks (24س)"          value={e.webhook_errors_24h}
                    tone={e.webhook_errors_24h ? 'danger' : 'good'} />
          <StatCard label="فشل تواقيع webhooks (24س)"     value={e.webhook_sig_failures_24h}
                    hint="رفض بسبب توقيع غير صالح"
                    tone={e.webhook_sig_failures_24h ? 'warning' : 'good'} />
          <StatCard label="محاولات دخول فاشلة (24س)"     value={e.login_failures_24h}
                    tone={e.login_failures_24h > 10 ? 'danger' : e.login_failures_24h > 0 ? 'warning' : 'good'} />
        </div>

        {/* ── Queues ────────────────────────────────────────────── */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <QueueCard title="Inbox (webhook ingest)" counts={data.queues.inbox} />
          <QueueCard title="Outbox (outbound side-effects)" counts={data.queues.outbox} />
        </div>

        {/* ── Stores near budget + top error stores ─────────────── */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <Card>
            <CardHeader>
              <div>
                <h3 className="font-bold">متاجر اقتربت من الحد اليومي</h3>
                <p className="text-xs text-default-400">≥ 80% من ميزانية اليوم</p>
              </div>
            </CardHeader>
            <Divider />
            <CardBody>
              {data.near_budget.length === 0 ? (
                <p className="text-sm text-default-400 text-center py-3">
                  لا توجد متاجر اقتربت من حدها اليوم ✅
                </p>
              ) : (
                <ul className="space-y-2">
                  {data.near_budget.map((r) => (
                    <li key={r.store_id} className="flex items-center justify-between text-sm">
                      <button
                        onClick={() => navigate(`/store/${r.store_id}/llm-usage`)}
                        className="text-sky-600 hover:underline truncate text-right"
                      >
                        {r.store_name || r.store_id}
                      </button>
                      <span className="font-mono">
                        <span className={r.percent_used >= 100 ? 'text-rose-600 font-bold' : r.percent_used >= 90 ? 'text-orange-600' : 'text-amber-600'}>
                          {r.percent_used}%
                        </span>
                        <span className="text-default-400 mr-2 text-xs">
                          ({fmt(r.tokens_today)}/{fmt(r.budget)})
                        </span>
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </CardBody>
          </Card>

          <Card>
            <CardHeader>
              <div>
                <h3 className="font-bold">أعلى متاجر بأخطاء (24س)</h3>
                <p className="text-xs text-default-400">webhooks + outbox dead</p>
              </div>
            </CardHeader>
            <Divider />
            <CardBody className="space-y-3">
              <div>
                <div className="text-xs text-default-500 mb-1">أخطاء webhooks</div>
                {data.top_error_stores.length === 0 ? (
                  <p className="text-xs text-default-400">لا أخطاء ✅</p>
                ) : (
                  <ul className="space-y-1">
                    {data.top_error_stores.map((r) => (
                      <li key={r.store_id} className="flex items-center justify-between text-sm">
                        <span className="truncate">{r.store_id}</span>
                        <span className="font-mono text-rose-600">{r.errors}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
              <Divider />
              <div>
                <div className="text-xs text-default-500 mb-1">رسائل ميتة في outbox</div>
                {data.outbox_dead_top.length === 0 ? (
                  <p className="text-xs text-default-400">لا توجد ✅</p>
                ) : (
                  <ul className="space-y-1">
                    {data.outbox_dead_top.map((r) => (
                      <li key={r.store_id} className="flex items-center justify-between text-sm">
                        <span className="truncate">{r.store_id}</span>
                        <span className="font-mono text-rose-600">{r.dead}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </CardBody>
          </Card>
        </div>

        {/* ── Stores table ──────────────────────────────────────── */}
        <Card>
          <CardHeader>
            <div>
              <h3 className="font-bold">المتاجر ({data.stores.length})</h3>
              <p className="text-xs text-default-400">
                لا تظهر هنا أي أسرار — مفاتيح OpenAI/Anthropic/WhatsApp وtokens محفوظة مشفّرة في DB ولا تُعرض في الواجهة.
              </p>
            </div>
          </CardHeader>
          <Divider />
          <CardBody className="overflow-x-auto">
            <Table aria-label="المتاجر" removeWrapper>
              <TableHeader>
                <TableColumn>المتجر</TableColumn>
                <TableColumn>الحالة</TableColumn>
                <TableColumn>القنوات</TableColumn>
                <TableColumn>توكن سلة</TableColumn>
                <TableColumn>مزوّد AI</TableColumn>
                <TableColumn className="text-right">توكنز اليوم</TableColumn>
                <TableColumn>الحد</TableColumn>
                <TableColumn>تاريخ الربط</TableColumn>
              </TableHeader>
              <TableBody>
                {data.stores.map((s: PlatformOpsStoreRow) => {
                  const usageColor =
                    s.percent_used === null   ? 'text-default-400' :
                    s.percent_used >= 100     ? 'text-rose-600 font-bold' :
                    s.percent_used >= 90      ? 'text-orange-600' :
                    s.percent_used >= 80      ? 'text-amber-600' :
                    'text-default-700'
                  const chip = TOKEN_STATUS_CHIP[s.token_status] || TOKEN_STATUS_CHIP.unknown
                  return (
                    <TableRow key={s.store_id}>
                      <TableCell>
                        <button
                          onClick={() => navigate(`/store/${s.store_id}`)}
                          className="text-sky-600 hover:underline text-right truncate max-w-[180px]"
                        >
                          {s.store_name || s.store_id}
                        </button>
                        <div className="text-[10px] text-default-400 font-mono">{s.store_id}</div>
                      </TableCell>
                      <TableCell>
                        <Chip size="sm" color={s.bot_enabled ? 'success' : 'default'} variant="flat">
                          {s.bot_enabled ? 'مُفعل' : 'موقوف'}
                        </Chip>
                      </TableCell>
                      <TableCell>
                        <div className="flex gap-1">
                          {s.channels.widget   && <Chip size="sm" variant="flat" color="primary">Widget</Chip>}
                          {s.channels.whatsapp && <Chip size="sm" variant="flat" color="success">WhatsApp</Chip>}
                        </div>
                      </TableCell>
                      <TableCell>
                        <Chip size="sm" color={chip.color} variant="flat">{chip.label}</Chip>
                      </TableCell>
                      <TableCell><span className="text-xs">{s.provider}</span></TableCell>
                      <TableCell className={`text-right font-mono text-sm ${usageColor}`}>
                        {fmt(s.tokens_today)}
                        {s.percent_used !== null && (
                          <span className="text-default-400 text-xs mr-1">({s.percent_used}%)</span>
                        )}
                      </TableCell>
                      <TableCell className="font-mono text-xs">
                        {s.budget > 0 ? fmt(s.budget) : 'بدون حد'}
                      </TableCell>
                      <TableCell className="text-xs">{fmtDate(s.connected_at)}</TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          </CardBody>
        </Card>

        {/* ── Privacy note ─────────────────────────────────────── */}
        <Card className="bg-slate-50 border-slate-200">
          <CardBody className="text-xs text-default-500 leading-relaxed">
            🔒 هذه اللوحة تعرض مؤشرات تشغيلية فقط. المفاتيح والـ tokens مشفّرة على القرص ولا تُكشف هنا.
            للوصول لمحادثات عميل بعينه، استخدم الصلاحية المخصصة (في الإصدار القادم — مع تسجيل سبب الوصول).
          </CardBody>
        </Card>
      </div>
    </div>
  )
}
