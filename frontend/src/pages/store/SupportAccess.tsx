import { useEffect, useMemo, useState } from 'react'
import {
  Button, Card, CardBody, CardHeader, Chip, Divider, Input, Modal,
  ModalBody, ModalContent, ModalFooter, ModalHeader, Select, SelectItem,
  Spinner, Textarea, useDisclosure,
} from '@heroui/react'
import { api, ApiError, SupportAccessGrant } from '../../api'
import { PageHeader } from '../../components/ui'

interface Props { storeId: string }

/* ─────────────────────────── Helpers ────────────────────────────────── */

const DURATION_PRESETS: Array<{ key: string; minutes: number; label: string }> = [
  { key: '15m',  minutes: 15,        label: '15 دقيقة' },
  { key: '1h',   minutes: 60,        label: 'ساعة'      },
  { key: '4h',   minutes: 60 * 4,    label: '4 ساعات'   },
  { key: '24h',  minutes: 60 * 24,   label: '24 ساعة'   },
]

function fmtRel(iso: string, now: number = Date.now()): string {
  const t = new Date(iso).getTime()
  const diff = t - now
  const abs = Math.abs(diff)
  const mins = Math.round(abs / 60_000)
  if (mins < 1)    return diff > 0 ? 'الآن' : 'انتهى'
  if (mins < 60)   return diff > 0 ? `بعد ${mins} د` : `منذ ${mins} د`
  const hrs  = Math.floor(mins / 60)
  const rest = mins % 60
  if (hrs < 24)    return diff > 0 ? `بعد ${hrs}س ${rest}د` : `منذ ${hrs}س`
  const days = Math.floor(hrs / 24)
  return diff > 0 ? `بعد ${days} يوم` : `منذ ${days} يوم`
}

function fmtAbs(iso: string): string {
  try {
    return new Date(iso).toLocaleString('ar-EG', {
      year: 'numeric', month: 'short', day: 'numeric',
      hour: '2-digit', minute: '2-digit',
    })
  } catch { return iso }
}

/* ─────────────────────────── Page ───────────────────────────────────── */

export default function SupportAccess({ storeId }: Props) {
  const [active,  setActive]   = useState<SupportAccessGrant | null>(null)
  const [pending, setPending]  = useState<SupportAccessGrant[]>([])
  const [history, setHistory]  = useState<SupportAccessGrant[]>([])
  const [loading, setLoading]  = useState(true)
  const [error,   setError]    = useState<string>('')

  const grant = useDisclosure()
  const [duration,  setDuration]  = useState<string>('1h')
  const [note,      setNote]      = useState<string>('')
  const [submitting, setSubmitting] = useState(false)
  const [grantErr,  setGrantErr]  = useState<string>('')

  // Approve-request modal (owner picks the duration when approving).
  const approve = useDisclosure()
  const [approveReq,      setApproveReq]      = useState<SupportAccessGrant | null>(null)
  const [approveDuration, setApproveDuration] = useState<string>('1h')
  const [deciding,        setDeciding]        = useState(false)
  const [decideErr,       setDecideErr]       = useState<string>('')

  // Tick once a minute so the relative countdown stays fresh without
  // hitting the API. Cheap — just rebinds the rendered string.
  const [now, setNow] = useState(Date.now())
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 60_000)
    return () => clearInterval(t)
  }, [])

  async function load() {
    setLoading(true)
    setError('')
    try {
      const res = await api.supportAccessStatus(storeId)
      setActive(res.active)
      setPending(res.pending || [])
      setHistory(res.history)
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : (e instanceof Error ? e.message : '—'))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [storeId])

  async function submitGrant() {
    setGrantErr('')
    setSubmitting(true)
    try {
      const minutes = DURATION_PRESETS.find(d => d.key === duration)?.minutes ?? 60
      await api.supportAccessGrant(storeId, { duration_minutes: minutes, note })
      setNote('')
      setDuration('1h')
      grant.onClose()
      await load()
    } catch (e) {
      setGrantErr(e instanceof ApiError ? e.detail : (e instanceof Error ? e.message : '—'))
    } finally {
      setSubmitting(false)
    }
  }

  async function revoke(grantId: number) {
    try {
      await api.supportAccessRevoke(storeId, grantId)
      await load()
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : (e instanceof Error ? e.message : '—'))
    }
  }

  function openApprove(reqRow: SupportAccessGrant) {
    setApproveReq(reqRow)
    setApproveDuration('1h')
    setDecideErr('')
    approve.onOpen()
  }

  async function submitApprove() {
    if (!approveReq) return
    setDecideErr('')
    setDeciding(true)
    try {
      const minutes = DURATION_PRESETS.find(d => d.key === approveDuration)?.minutes ?? 60
      await api.supportAccessApprove(storeId, approveReq.id, { duration_minutes: minutes })
      approve.onClose()
      await load()
    } catch (e) {
      setDecideErr(e instanceof ApiError ? e.detail : (e instanceof Error ? e.message : '—'))
    } finally {
      setDeciding(false)
    }
  }

  async function reject(grantId: number) {
    try {
      await api.supportAccessReject(storeId, grantId)
      await load()
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : (e instanceof Error ? e.message : '—'))
    }
  }

  const expiresInLabel = useMemo(
    () => (active ? fmtRel(active.expires_at, now) : ''),
    [active, now],
  )

  if (loading && !active && history.length === 0) {
    return (
      <div className="flex items-center justify-center min-h-[50vh]">
        <Spinner size="lg" color="primary" label="جاري التحميل..." />
      </div>
    )
  }

  return (
    <div className="p-4 md:p-6 max-w-4xl mx-auto space-y-4" dir="rtl">
      {/* ── Intro ─────────────────────────────────────────────────────── */}
      <PageHeader
        title="وصول الدعم الفني"
        icon="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z"
      />
      <p className="text-sm text-default-500 -mt-2 leading-relaxed">
        الفريق الفني للمنصة <b>لا يستطيع</b> الدخول على لوحة متجرك بدون إذن منك.
        عند الحاجة، افتح نافذة وصول محدودة بوقت، وألغها متى شئت.
        كل دخول مسجّل في سجل المراجعة.
      </p>

      {error && (
        <div className="bg-rose-50 border border-rose-200 text-rose-700 rounded-xl px-4 py-3 text-sm">
          {error}
        </div>
      )}

      {/* ── Pending requests (admin asked, owner decides) ─────────────── */}
      {pending.length > 0 && (
        <Card className="border border-warning/40">
          <CardHeader className="flex items-center gap-2">
            <span className="relative flex h-2 w-2">
              <span className="absolute inline-flex h-full w-full rounded-full bg-warning opacity-75 animate-ping" />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-warning" />
            </span>
            <h3 className="font-bold">طلبات وصول بانتظار موافقتك ({pending.length})</h3>
          </CardHeader>
          <Divider />
          <CardBody className="space-y-3">
            <p className="text-xs text-default-500">
              طلب فريق المنصة الدخول لمساعدتك. لن يتمكّن أحد من الدخول قبل موافقتك،
              وأنت تحدّد المدة.
            </p>
            {pending.map((r) => (
              <div key={r.id} className="border border-divider rounded-xl px-4 py-3 space-y-2">
                <div className="flex items-center justify-between gap-2 flex-wrap">
                  <div className="text-sm">
                    <span className="font-semibold text-foreground">
                      {r.requested_by || 'فريق الدعم'}
                    </span>
                    <span className="text-xs text-default-400 mr-2">{fmtAbs(r.granted_at)}</span>
                  </div>
                  <Chip size="sm" color="warning" variant="flat">بانتظار القرار</Chip>
                </div>
                {r.note && (
                  <p className="text-xs text-default-500 bg-content2 rounded-lg px-3 py-2">
                    <span className="text-default-400">السبب: </span>{r.note}
                  </p>
                )}
                <div className="flex items-center gap-2 pt-1">
                  <Button size="sm" color="success" className="font-bold text-white"
                    onPress={() => openApprove(r)}>
                    موافقة وتحديد المدة
                  </Button>
                  <Button size="sm" color="danger" variant="flat" onPress={() => reject(r.id)}>
                    رفض
                  </Button>
                </div>
              </div>
            ))}
          </CardBody>
        </Card>
      )}

      {/* ── Active grant card ─────────────────────────────────────────── */}
      <Card>
        <CardHeader className="flex items-center justify-between">
          <h3 className="font-bold">حالة الوصول</h3>
          {active && (
            <Chip size="sm" color="warning" variant="flat">مفعّل الآن</Chip>
          )}
        </CardHeader>
        <Divider />
        <CardBody>
          {active ? (
            <div className="space-y-3">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-sm">
                <Stat label="ينتهي خلال" value={expiresInLabel} highlight />
                <Stat label="ينتهي في"   value={fmtAbs(active.expires_at)} />
                <Stat label="منذ"        value={fmtAbs(active.granted_at)} />
                <Stat label="أصدره"      value={active.granted_by === 'owner' ? 'المالك' : active.granted_by} />
              </div>
              {active.note && (
                <div className="bg-amber-50 border border-amber-200 rounded-xl px-3 py-2 text-sm text-amber-800">
                  <span className="text-xs text-amber-600 mb-1 block">ملاحظة:</span>
                  {active.note}
                </div>
              )}
              <Button
                color="danger"
                variant="flat"
                onPress={() => revoke(active.id)}
                radius="lg"
              >
                إلغاء الوصول الآن
              </Button>
            </div>
          ) : (
            <div className="text-center py-6">
              <p className="text-default-500 mb-4 text-sm">
                لا يوجد وصول مفتوح حالياً. الفريق الفني لا يستطيع الدخول الآن.
              </p>
              <Button color="primary" onPress={grant.onOpen} radius="lg">
                منح وصول للدعم الفني
              </Button>
            </div>
          )}
        </CardBody>
      </Card>

      {/* ── History ───────────────────────────────────────────────────── */}
      <Card>
        <CardHeader>
          <div>
            <h3 className="font-bold">السجل ({history.length})</h3>
            <p className="text-xs text-default-400">
              كل الأذونات السابقة — حتى الملغية والمنتهية.
            </p>
          </div>
        </CardHeader>
        <Divider />
        <CardBody>
          {history.length === 0 ? (
            <p className="text-center text-default-400 py-6 text-sm">
              لم تمنح أي إذن سابق.
            </p>
          ) : (
            <ul className="space-y-2">
              {history.map((g) => {
                const status = g.active
                  ? { label: 'مفعّل', color: 'warning' as const }
                  : g.revoked_at
                    ? { label: 'ملغى',   color: 'danger'  as const }
                    : { label: 'منتهٍ',  color: 'default' as const }
                return (
                  <li key={g.id} className="flex items-center justify-between border border-divider rounded-xl px-3 py-2.5">
                    <div className="text-sm">
                      <div className="flex items-center gap-2">
                        <Chip size="sm" color={status.color} variant="flat">{status.label}</Chip>
                        <span className="text-xs text-default-500">{fmtAbs(g.granted_at)}</span>
                      </div>
                      {g.note && (
                        <p className="text-xs text-default-400 mt-1 truncate max-w-md">{g.note}</p>
                      )}
                    </div>
                    <div className="text-xs text-default-500">
                      ← ينتهي {fmtRel(g.expires_at, now)}
                    </div>
                  </li>
                )
              })}
            </ul>
          )}
        </CardBody>
      </Card>

      {/* ── Grant modal ───────────────────────────────────────────────── */}
      <Modal isOpen={grant.isOpen} onOpenChange={grant.onOpenChange} placement="center" backdrop="blur" size="md">
        <ModalContent>
          {(close) => (
            <>
              <ModalHeader dir="rtl" className="flex flex-col gap-1">
                <h3 className="font-bold">منح وصول الدعم</h3>
                <p className="text-xs text-default-500 font-normal">
                  ينتهي الوصول تلقائياً بعد المدة. الحد الأقصى 24 ساعة.
                </p>
              </ModalHeader>
              <ModalBody dir="rtl" className="space-y-3">
                <Select
                  label="مدة الوصول"
                  selectedKeys={[duration]}
                  onSelectionChange={(keys) => setDuration(Array.from(keys)[0] as string)}
                >
                  {DURATION_PRESETS.map((d) => (
                    <SelectItem key={d.key}>{d.label}</SelectItem>
                  ))}
                </Select>
                <Textarea
                  label="ملاحظة (اختياري)"
                  placeholder="مثلاً: لمتابعة بلاغ #4221"
                  value={note}
                  onValueChange={setNote}
                  minRows={2}
                  maxRows={4}
                />
                {grantErr && (
                  <div className="text-sm text-rose-600 bg-rose-50 border border-rose-200 rounded-lg px-3 py-2">
                    {grantErr}
                  </div>
                )}
              </ModalBody>
              <ModalFooter>
                <Button variant="light" onPress={close} isDisabled={submitting}>إلغاء</Button>
                <Button color="primary" onPress={submitGrant} isLoading={submitting}>
                  منح
                </Button>
              </ModalFooter>
            </>
          )}
        </ModalContent>
      </Modal>

      {/* ── Approve-request modal (owner picks duration) ──────────────── */}
      <Modal isOpen={approve.isOpen} onOpenChange={approve.onOpenChange} placement="center" backdrop="blur" size="md">
        <ModalContent>
          {(close) => (
            <>
              <ModalHeader dir="rtl" className="flex flex-col gap-1">
                <h3 className="font-bold">الموافقة على طلب الوصول</h3>
                <p className="text-xs text-default-500 font-normal">
                  اختر المدة المسموح بها. ينتهي الوصول تلقائياً بعدها — ويمكنك إلغاؤه في أي وقت.
                </p>
              </ModalHeader>
              <ModalBody dir="rtl" className="space-y-3">
                {approveReq?.note && (
                  <p className="text-xs text-default-500 bg-content2 rounded-lg px-3 py-2">
                    <span className="text-default-400">سبب الطلب: </span>{approveReq.note}
                  </p>
                )}
                <Select
                  label="مدة الوصول"
                  selectedKeys={[approveDuration]}
                  onSelectionChange={(keys) => setApproveDuration(Array.from(keys)[0] as string)}
                >
                  {DURATION_PRESETS.map((d) => (
                    <SelectItem key={d.key}>{d.label}</SelectItem>
                  ))}
                </Select>
                {decideErr && (
                  <div className="text-sm text-rose-600 bg-rose-50 border border-rose-200 rounded-lg px-3 py-2">
                    {decideErr}
                  </div>
                )}
              </ModalBody>
              <ModalFooter>
                <Button variant="light" onPress={close} isDisabled={deciding}>إلغاء</Button>
                <Button color="success" className="text-white" onPress={submitApprove} isLoading={deciding}>
                  موافقة
                </Button>
              </ModalFooter>
            </>
          )}
        </ModalContent>
      </Modal>
    </div>
  )
}

function Stat({ label, value, highlight = false }: { label: string; value: string; highlight?: boolean }) {
  return (
    <div className="bg-content2 rounded-xl px-3 py-2">
      <div className="text-xs text-default-500">{label}</div>
      <div className={`mt-1 font-bold ${highlight ? 'text-amber-700' : 'text-foreground'}`}>{value}</div>
    </div>
  )
}
