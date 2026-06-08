import { useEffect, useMemo, useState } from 'react'
import {
  Button, Card, CardBody, CardHeader, Chip, Divider, Input, Modal,
  ModalBody, ModalContent, ModalFooter, ModalHeader, Spinner,
  useDisclosure,
} from '@heroui/react'
import { api, ApiError, LlmUsageResponse, getIsSuper } from '../../api'

interface Props { storeId: string }

// ─────────────────────────── Helpers ──────────────────────────────────────

function fmt(n: number): string {
  return n.toLocaleString('ar-EG')
}

// Color the progress ring + percentage chip based on usage band.
//   < 50 %  → green   (plenty of room)
//   50-79 % → blue    (normal)
//   80-89 % → amber   (heads-up)
//   90-99 % → orange  (warning — 90% threshold alert fired)
//   100 %   → red     (breaker tripped)
function bandFor(pct: number | null): { ring: string; text: string; bg: string; label: string } {
  if (pct === null) return { ring: 'stroke-slate-300',   text: 'text-slate-500',  bg: 'bg-slate-50',  label: 'غير محدد' }
  if (pct >= 100)   return { ring: 'stroke-rose-500',    text: 'text-rose-600',   bg: 'bg-rose-50',   label: 'تجاوز الحد' }
  if (pct >= 90)    return { ring: 'stroke-orange-500',  text: 'text-orange-600', bg: 'bg-orange-50', label: 'تحذير عالي' }
  if (pct >= 80)    return { ring: 'stroke-amber-500',   text: 'text-amber-600',  bg: 'bg-amber-50',  label: 'تنبيه' }
  if (pct >= 50)    return { ring: 'stroke-sky-500',     text: 'text-sky-600',    bg: 'bg-sky-50',    label: 'استخدام طبيعي' }
  return                  { ring: 'stroke-emerald-500',  text: 'text-emerald-600',bg: 'bg-emerald-50',label: 'مستوى منخفض' }
}

// SVG ring — single-purpose, no chart lib. Stroke clipped to the visible
// arc; the rest of the circle stays muted grey so 0% is still legible.
function ProgressRing({ pct, band }: { pct: number; band: ReturnType<typeof bandFor> }) {
  const size = 160
  const radius = 70
  const circ = 2 * Math.PI * radius
  const clamped = Math.max(0, Math.min(100, pct))
  const offset = circ * (1 - clamped / 100)
  return (
    <div className="relative" style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="rotate-[-90deg]">
        <circle cx={size / 2} cy={size / 2} r={radius}
          fill="none" strokeWidth={14} className="stroke-slate-100" />
        <circle cx={size / 2} cy={size / 2} r={radius}
          fill="none" strokeWidth={14}
          strokeDasharray={circ}
          strokeDashoffset={offset}
          strokeLinecap="round"
          className={`${band.ring} transition-all duration-700`} />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className={`text-3xl font-extrabold ${band.text}`}>{Math.round(pct)}%</span>
        <span className="text-[10px] text-slate-400 mt-0.5">من الحد اليومي</span>
      </div>
    </div>
  )
}

// 7-day mini bar chart — height proportional to that day's total tokens
// vs. the largest day in the window. Tooltip on hover shows raw value.
function HistoryChart({ history }: { history: LlmUsageResponse['history'] }) {
  const max = useMemo(
    () => Math.max(1, ...history.map(h => h.tokens_total)),
    [history],
  )
  if (history.length === 0) return null
  return (
    <div className="flex items-end justify-between gap-2 h-32 pt-2">
      {[...history].reverse().map((h, i) => {
        const pct = (h.tokens_total / max) * 100
        const date = new Date(h.date)
        const day  = date.toLocaleDateString('ar-EG', { weekday: 'short' })
        return (
          <div key={i} className="flex-1 flex flex-col items-center gap-1 min-w-0">
            <div className="text-[10px] font-mono text-slate-400">{fmt(h.tokens_total)}</div>
            <div className="w-full bg-slate-100 rounded-md h-24 flex items-end overflow-hidden">
              <div
                className="w-full bg-gradient-to-t from-sky-400 to-sky-300 rounded-md transition-all duration-500"
                style={{ height: `${Math.max(pct, 2)}%` }}
                title={`${fmt(h.tokens_total)} توكن في ${h.date}`}
              />
            </div>
            <div className="text-[10px] text-slate-500">{day}</div>
          </div>
        )
      })}
    </div>
  )
}

// ─────────────────────────── Page ─────────────────────────────────────────

export default function LlmUsage({ storeId }: Props) {
  const [data, setData]       = useState<LlmUsageResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState<string>('')
  const isSuper = getIsSuper()

  const edit = useDisclosure()
  const [budgetInput, setBudgetInput] = useState<string>('')
  const [saving, setSaving]   = useState(false)
  const [saveErr, setSaveErr] = useState<string>('')

  async function load() {
    setLoading(true)
    setError('')
    try {
      const res = await api.getLlmUsage(storeId, 7)
      setData(res)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'تعذّر تحميل بيانات الاستهلاك')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [storeId])

  function openEdit() {
    // Pre-fill with the current effective budget; user edits then saves.
    setBudgetInput(String(data?.budget.value ?? ''))
    setSaveErr('')
    edit.onOpen()
  }

  async function saveBudget(value: number | null) {
    setSaving(true)
    setSaveErr('')
    try {
      await api.setLlmBudget(storeId, value)
      edit.onClose()
      await load()
    } catch (e) {
      const msg = e instanceof ApiError ? e.detail : (e instanceof Error ? e.message : 'تعذّر الحفظ')
      setSaveErr(msg)
    } finally {
      setSaving(false)
    }
  }

  if (loading && !data) {
    return (
      <div className="flex items-center justify-center min-h-[50vh]">
        <Spinner size="lg" color="primary" label="جاري التحميل..." />
      </div>
    )
  }

  if (error || !data) {
    return (
      <div className="p-6 text-center" dir="rtl">
        <p className="text-rose-600 mb-3">{error || 'لا توجد بيانات'}</p>
        <Button color="primary" variant="flat" onPress={load}>إعادة المحاولة</Button>
      </div>
    )
  }

  const t = data.today
  const band = bandFor(t.percent_used)
  const breakerOff = !data.budget.breaker_active
  const sourceChip = data.budget.source === 'store_override'
    ? { label: 'مخصّص لهذا المتجر', color: 'success' as const }
    : { label: 'الحد الافتراضي للمنصة', color: 'default' as const }

  return (
    <div className="p-4 md:p-6 max-w-5xl mx-auto space-y-4" dir="rtl">
      {/* ── Header ───────────────────────────────────────────────────── */}
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-2xl font-extrabold text-foreground">استهلاك الذكاء الاصطناعي</h1>
          <p className="text-sm text-default-500 mt-1">
            متابعة عدد التوكنز المستهلكة اليوم وضبط الحد اليومي للمتجر.
            يُعاد التعيين كل يوم في الساعة 00:00 بتوقيت UTC.
          </p>
        </div>
        <Button color="primary" radius="lg" onPress={openEdit}>
          تعديل الحد اليومي
        </Button>
      </div>

      {/* ── Today's usage ─────────────────────────────────────────────── */}
      <Card>
        <CardHeader className="flex items-center justify-between">
          <div>
            <h2 className="font-bold text-foreground">استهلاك اليوم</h2>
            <p className="text-xs text-default-400">
              منذ آخر إعادة تعيين (UTC).
            </p>
          </div>
          <Chip size="sm" variant="flat" color={t.exhausted ? 'danger' : 'default'}>
            {band.label}
          </Chip>
        </CardHeader>
        <Divider />
        <CardBody>
          <div className="flex items-center justify-between gap-6 flex-wrap">
            {/* Progress ring */}
            <div className="flex items-center gap-6">
              {breakerOff ? (
                <div className={`${band.bg} ${band.text} rounded-2xl px-6 py-8 text-center min-w-[160px]`}>
                  <div className="text-2xl font-extrabold">∞</div>
                  <div className="text-xs mt-1">بدون حد</div>
                </div>
              ) : (
                <ProgressRing pct={t.percent_used ?? 0} band={band} />
              )}

              <div className="space-y-2">
                <Stat label="إجمالي توكنز اليوم" value={fmt(t.tokens_total)} />
                <Stat label="توكنز الإدخال"    value={fmt(t.tokens_in)} />
                <Stat label="توكنز الإخراج"    value={fmt(t.tokens_out)} />
                <Stat label="عدد الطلبات"      value={fmt(t.requests)} />
              </div>
            </div>

            {/* Budget summary */}
            <div className="bg-content2 rounded-2xl p-5 min-w-[220px] space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-sm text-default-500">الحد اليومي</span>
                <Chip size="sm" variant="flat" color={sourceChip.color}>
                  {sourceChip.label}
                </Chip>
              </div>
              <div className="text-2xl font-extrabold text-foreground">
                {breakerOff ? 'بدون حد' : `${fmt(data.budget.value)} توكن`}
              </div>
              {!breakerOff && (
                <div className="text-xs text-default-500">
                  المتبقي اليوم:{' '}
                  <span className="font-bold text-foreground">
                    {t.remaining !== null ? fmt(t.remaining) : '—'} توكن
                  </span>
                </div>
              )}
              {t.exhausted && (
                <div className="text-xs text-rose-600 leading-relaxed">
                  ⛔ تجاوز الحد — البوت يعرض رسالة بديلة للعملاء حتى منتصف
                  الليل بتوقيت UTC أو حتى ترفع الحد.
                </div>
              )}
            </div>
          </div>
        </CardBody>
      </Card>

      {/* ── 7-day history ─────────────────────────────────────────────── */}
      <Card>
        <CardHeader>
          <div>
            <h2 className="font-bold text-foreground">آخر 7 أيام</h2>
            <p className="text-xs text-default-400">
              إجمالي التوكنز المستهلكة لكل يوم — الأحدث على اليمين.
            </p>
          </div>
        </CardHeader>
        <Divider />
        <CardBody>
          <HistoryChart history={data.history} />
        </CardBody>
      </Card>

      {/* ── Edit modal ───────────────────────────────────────────────── */}
      <Modal isOpen={edit.isOpen} onOpenChange={edit.onOpenChange} placement="center" backdrop="blur" size="md">
        <ModalContent>
          {(close) => (
            <>
              <ModalHeader className="flex flex-col gap-1" dir="rtl">
                <h3 className="font-bold">تعديل الحد اليومي</h3>
                <p className="text-xs text-default-400 font-normal">
                  استهلاك المتجر يومياً من توكنز الذكاء الاصطناعي. الحد الأدنى
                  المقترح 100,000 توكن للمتاجر النشطة.
                </p>
              </ModalHeader>
              <ModalBody className="space-y-3" dir="rtl">
                <Input
                  type="number"
                  label="الحد اليومي (توكن)"
                  placeholder="مثلاً: 500000"
                  min={isSuper ? 0 : 1000}
                  step={10000}
                  value={budgetInput}
                  onValueChange={setBudgetInput}
                  description={
                    isSuper
                      ? 'كمدير عام يمكنك إدخال 0 لإلغاء الحد تماماً (للعملاء المدفوعين فقط).'
                      : 'لإلغاء الحد تماماً اتواصل مع المدير العام — هذه الصلاحية محصورة لمنع الاستهلاك غير المحدود.'
                  }
                />
                {saveErr && (
                  <div className="text-sm text-rose-600 bg-rose-50 border border-rose-200 rounded-lg px-3 py-2">
                    {saveErr}
                  </div>
                )}
              </ModalBody>
              <ModalFooter>
                <Button
                  variant="flat"
                  onPress={() => saveBudget(null)}
                  isDisabled={saving}
                >
                  استخدام الافتراضي
                </Button>
                <Button variant="light" onPress={close} isDisabled={saving}>
                  إلغاء
                </Button>
                <Button
                  color="primary"
                  onPress={() => {
                    const n = parseInt(budgetInput, 10)
                    if (isNaN(n) || n < 0) {
                      setSaveErr('أدخل رقماً صحيحاً (≥ 0)')
                      return
                    }
                    saveBudget(n)
                  }}
                  isLoading={saving}
                >
                  حفظ
                </Button>
              </ModalFooter>
            </>
          )}
        </ModalContent>
      </Modal>
    </div>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center gap-3 min-w-[180px]">
      <span className="text-xs text-default-500 w-24 shrink-0">{label}</span>
      <span className="text-sm font-bold font-mono text-foreground">{value}</span>
    </div>
  )
}
