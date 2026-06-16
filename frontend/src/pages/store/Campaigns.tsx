/**
 * WhatsApp Broadcast Campaigns
 *
 * List + create + launch WhatsApp template campaigns.
 * Multi-step create flow: (1) template & variables, (2) audience, (3) launch.
 */
import { useEffect, useState, useCallback } from 'react'
import {
  Button, Input, Select, SelectItem, Switch,
  Modal, ModalContent, ModalHeader, ModalBody, ModalFooter,
  useDisclosure, Textarea, Chip,
} from '@heroui/react'
import { api, ApiError, Campaign } from '../../api'

/* ── helpers ── */
function fmtDate(iso?: string) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('ar-SA', {
    dateStyle: 'short', timeStyle: 'short',
  })
}

type CampaignStatus = Campaign['status']

const STATUS_LABELS: Record<CampaignStatus, string> = {
  draft:     'مسودة',
  scheduled: 'مجدولة',
  sending:   'جارٍ الإرسال',
  sent:      'أُرسلت',
  failed:    'فشلت',
}
const STATUS_COLORS: Record<CampaignStatus, 'default' | 'primary' | 'success' | 'warning' | 'danger'> = {
  draft:     'default',
  scheduled: 'primary',
  sending:   'warning',
  sent:      'success',
  failed:    'danger',
}

const AUDIENCE_LABELS: Record<string, string> = {
  chat_users:      'مستخدمو الشات',
  salla_customers: 'عملاء سلة',
  abandoned_carts: 'سلات متروكة',
  manual:          'قائمة يدوية',
}

/* ── Icon helper ── */
function Icon({ d, size = 16, className = '' }: { d: string; size?: number; className?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round"
      className={className}>
      <path d={d} />
    </svg>
  )
}

/* ── Step indicator ── */
function Steps({ step }: { step: number }) {
  const labels = ['القالب والمتغيرات', 'الجمهور', 'الإطلاق']
  return (
    <div className="flex items-center justify-center gap-0 mb-6" dir="rtl">
      {labels.map((label, i) => {
        const num = i + 1
        const active = num === step
        const done   = num < step
        return (
          <div key={i} className="flex items-center">
            <div className="flex flex-col items-center">
              <div className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold border-2 transition-all
                ${done   ? 'bg-green-500 border-green-500 text-white' :
                  active ? 'bg-primary border-primary text-white' :
                           'bg-content2 border-divider text-default-400'}`}>
                {done ? '✓' : num}
              </div>
              <span className={`text-[11px] mt-1 ${active ? 'text-primary font-semibold' : 'text-default-400'}`}>
                {label}
              </span>
            </div>
            {i < labels.length - 1 && (
              <div className={`w-12 h-0.5 mx-1 mb-5 transition-all ${done ? 'bg-green-500' : 'bg-divider'}`} />
            )}
          </div>
        )
      })}
    </div>
  )
}

/* ══════════════════════════════════════════════════════════════════════
   Main page
══════════════════════════════════════════════════════════════════════ */
export default function Campaigns({ storeId }: { storeId: string }) {
  const [campaigns, setCampaigns]     = useState<Campaign[]>([])
  const [loading, setLoading]         = useState(true)
  const [error, setError]             = useState('')
  const [deletingId, setDeletingId]   = useState<number | null>(null)
  const [launchingId, setLaunchingId] = useState<number | null>(null)

  /* create modal */
  const { isOpen, onOpen, onClose } = useDisclosure()
  const [step, setStep]           = useState(1)
  const [saving, setSaving]       = useState(false)
  const [saveErr, setSaveErr]     = useState('')

  /* step 1 — template */
  const [cName, setCName]             = useState('')
  const [tplName, setTplName]         = useState('')
  const [tplLang, setTplLang]         = useState('ar')
  const [headerParams, setHeaderParams] = useState<string[]>([''])
  const [bodyParams, setBodyParams]     = useState<string[]>([''])

  /* step 2 — audience */
  const [audienceType, setAudienceType] = useState<Campaign['audience_type']>('chat_users')
  const [manualPhones, setManualPhones] = useState('')   // newline-separated

  /* step 3 — launch */
  const [isScheduled, setIsScheduled] = useState(false)
  const [scheduledAt, setScheduledAt] = useState('')   // datetime-local value
  const [previewCount, setPreviewCount] = useState<number | null>(null)
  const [draftId, setDraftId]           = useState<number | null>(null)

  /* ── Fetch list ── */
  const reload = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = await api.listCampaigns(storeId)
      setCampaigns(res.campaigns || [])
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'فشل تحميل الحملات')
    } finally {
      setLoading(false)
    }
  }, [storeId])

  useEffect(() => { reload() }, [reload])

  /* ── Reset modal state ── */
  function resetModal() {
    setStep(1); setSaveErr('')
    setCName(''); setTplName(''); setTplLang('ar')
    setHeaderParams(['']); setBodyParams([''])
    setAudienceType('chat_users'); setManualPhones('')
    setIsScheduled(false); setScheduledAt('')
    setPreviewCount(null); setDraftId(null)
  }

  function openCreate() { resetModal(); onOpen() }

  /* ── Param list helpers ── */
  function updateParam(list: string[], setList: (v: string[]) => void, i: number, val: string) {
    const next = [...list]; next[i] = val; setList(next)
  }
  function addParam(list: string[], setList: (v: string[]) => void) {
    setList([...list, ''])
  }
  function removeParam(list: string[], setList: (v: string[]) => void, i: number) {
    setList(list.filter((_, j) => j !== i))
  }

  /* ── Step 1 → 2: create draft ── */
  async function goStep2() {
    if (!cName.trim()) { setSaveErr('أدخل اسم الحملة'); return }
    if (!tplName.trim()) { setSaveErr('أدخل اسم القالب'); return }
    setSaveErr(''); setSaving(true)
    try {
      const res = await api.createCampaign(storeId, {
        name:          cName.trim(),
        template_name: tplName.trim(),
        template_lang: tplLang,
        header_params: headerParams.filter(p => p.trim()),
        body_params:   bodyParams.filter(p => p.trim()),
        audience_type: audienceType,
        phone_list:    [],
      })
      setDraftId(res.id)
      setStep(2)
    } catch (e) {
      setSaveErr(e instanceof ApiError ? e.message : 'فشل إنشاء الحملة')
    } finally {
      setSaving(false)
    }
  }

  /* ── Step 2 → 3: update audience on draft ── */
  async function goStep3() {
    if (audienceType === 'manual' && !manualPhones.trim()) {
      setSaveErr('أدخل أرقام الهاتف'); return
    }
    if (!draftId) return
    setSaveErr(''); setSaving(true)
    try {
      const phone_list = audienceType === 'manual'
        ? manualPhones.split('\n').map(l => l.trim()).filter(Boolean)
        : []
      // Update campaign audience via create (we'll use a PATCH-style re-create as POST is idempotent in backend)
      // The backend doesn't have PATCH, so we delete & re-create OR we just preview the existing draft.
      // Actually: the draft was created with audience_type already. We need to update it.
      // Since the backend has no PATCH, we use: delete + create. But that's clunky.
      // Instead: the audience_type was already set in step 1. If different, re-create.
      // For simplicity: re-create always (delete old draft, create new one with final data).
      await api.deleteCampaign(storeId, draftId)
      const res2 = await api.createCampaign(storeId, {
        name:          cName.trim(),
        template_name: tplName.trim(),
        template_lang: tplLang,
        header_params: headerParams.filter(p => p.trim()),
        body_params:   bodyParams.filter(p => p.trim()),
        audience_type: audienceType,
        phone_list:    phone_list,
      })
      setDraftId(res2.id)
      // Get preview count
      try {
        const prev = await api.previewCampaign(storeId, res2.id)
        setPreviewCount(prev.count)
      } catch { setPreviewCount(null) }
      setStep(3)
    } catch (e) {
      setSaveErr(e instanceof ApiError ? e.message : 'فشل تحديث الجمهور')
    } finally {
      setSaving(false)
    }
  }

  /* ── Step 3: Launch ── */
  async function doLaunch() {
    if (!draftId) return
    if (isScheduled && !scheduledAt) { setSaveErr('حدد وقت الجدولة'); return }
    setSaveErr(''); setSaving(true)
    try {
      const sAt = isScheduled ? new Date(scheduledAt).toISOString() : undefined
      await api.launchCampaign(storeId, draftId, sAt)
      onClose(); resetModal(); await reload()
    } catch (e) {
      setSaveErr(e instanceof ApiError ? e.message : 'فشل الإطلاق')
    } finally {
      setSaving(false)
    }
  }

  /* ── Delete ── */
  async function handleDelete(id: number) {
    if (!confirm('هل تريد حذف هذه الحملة؟')) return
    setDeletingId(id)
    try {
      await api.deleteCampaign(storeId, id)
      await reload()
    } catch (e) {
      alert(e instanceof ApiError ? e.message : 'فشل الحذف')
    } finally {
      setDeletingId(null)
    }
  }

  /* ── Launch existing draft ── */
  async function handleLaunch(id: number) {
    if (!confirm('هل تريد إرسال الحملة الآن؟')) return
    setLaunchingId(id)
    try {
      await api.launchCampaign(storeId, id)
      await reload()
    } catch (e) {
      alert(e instanceof ApiError ? e.message : 'فشل الإطلاق')
    } finally {
      setLaunchingId(null)
    }
  }

  /* ══════════ Render ══════════ */
  return (
    <div className="p-4 md:p-6 max-w-5xl mx-auto" dir="rtl">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-bold text-foreground">حملات WhatsApp</h1>
          <p className="text-sm text-default-500 mt-0.5">أرسل رسائل قوالب واتساب لجمهور محدد</p>
        </div>
        <Button color="primary" size="sm" onPress={openCreate}
          startContent={<Icon d="M12 5v14M5 12h14" size={14} />}>
          حملة جديدة
        </Button>
      </div>

      {/* Error */}
      {error && (
        <div className="mb-4 p-3 rounded-xl bg-danger-50 border border-danger-200 text-danger text-sm">{error}</div>
      )}

      {/* Loading */}
      {loading ? (
        <div className="text-center text-default-400 py-12">جاري التحميل...</div>
      ) : campaigns.length === 0 ? (
        <div className="text-center py-16">
          <div className="w-16 h-16 rounded-2xl bg-content2 flex items-center justify-center mx-auto mb-4">
            <Icon d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347z"
              size={28} className="text-default-300" />
          </div>
          <p className="text-default-500 font-medium">لا توجد حملات بعد</p>
          <p className="text-default-400 text-sm mt-1">أنشئ حملتك الأولى لإرسال رسائل واتساب بالجملة</p>
          <Button color="primary" size="sm" className="mt-4" onPress={openCreate}>إنشاء حملة</Button>
        </div>
      ) : (
        /* Campaign list */
        <div className="space-y-3">
          {campaigns.map(c => (
            <div key={c.id}
              className="bg-content1 border border-divider rounded-2xl p-4 flex flex-col sm:flex-row sm:items-center gap-3">
              {/* Info */}
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="font-semibold text-foreground truncate">{c.name}</span>
                  <Chip size="sm" color={STATUS_COLORS[c.status]} variant="flat">
                    {STATUS_LABELS[c.status]}
                  </Chip>
                </div>
                <div className="flex flex-wrap gap-x-4 gap-y-1 mt-1.5 text-xs text-default-500">
                  <span>القالب: <b className="text-foreground">{c.template_name}</b></span>
                  <span>الجمهور: <b className="text-foreground">{AUDIENCE_LABELS[c.audience_type] || c.audience_type}</b></span>
                  {c.status === 'sent' && (
                    <span>أُرسل: <b className="text-success">{c.sent_count}</b> / <b>{c.total_count}</b>
                      {c.failed_count > 0 && <span className="text-danger"> (فشل {c.failed_count})</span>}
                    </span>
                  )}
                  {c.scheduled_at && c.status === 'scheduled' && (
                    <span>موعد الإرسال: <b>{fmtDate(c.scheduled_at)}</b></span>
                  )}
                  <span className="text-default-400">{fmtDate(c.created_at)}</span>
                </div>
              </div>

              {/* Actions */}
              <div className="flex items-center gap-2 flex-shrink-0">
                {(c.status === 'draft' || c.status === 'failed') && (
                  <Button size="sm" color="success" variant="flat"
                    isLoading={launchingId === c.id}
                    onPress={() => handleLaunch(c.id)}>
                    إطلاق
                  </Button>
                )}
                {(c.status !== 'sending') && (
                  <Button size="sm" color="danger" variant="flat" isIconOnly
                    isLoading={deletingId === c.id}
                    onPress={() => handleDelete(c.id)}>
                    <Icon d="M3 6h18M19 6l-1 14H6L5 6M9 6V4h6v2" size={14} />
                  </Button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* ════════════ Create Modal ════════════ */}
      <Modal isOpen={isOpen} onClose={() => { onClose(); resetModal() }}
        size="2xl" scrollBehavior="inside" dir="rtl">
        <ModalContent>
          {() => (
            <>
              <ModalHeader className="flex flex-col gap-1">
                <span>إنشاء حملة واتساب</span>
                <p className="text-xs text-default-400 font-normal">أرسل قالب واتساب لقائمة جهات اتصال</p>
              </ModalHeader>
              <ModalBody>
                <Steps step={step} />

                {/* ── Step 1: Template ── */}
                {step === 1 && (
                  <div className="space-y-4">
                    <Input
                      label="اسم الحملة"
                      placeholder="مثال: عروض رمضان 2025"
                      value={cName} onValueChange={setCName}
                      isRequired
                    />
                    <div className="grid grid-cols-2 gap-3">
                      <Input
                        label="اسم القالب (Meta)"
                        placeholder="مثال: order_confirmation"
                        value={tplName} onValueChange={setTplName}
                        isRequired
                        description="اسم القالب المعتمد من Meta"
                      />
                      <Select
                        label="لغة القالب"
                        selectedKeys={[tplLang]}
                        onSelectionChange={keys => setTplLang([...keys][0] as string)}
                      >
                        <SelectItem key="ar">العربية (ar)</SelectItem>
                        <SelectItem key="en">الإنجليزية (en)</SelectItem>
                        <SelectItem key="en_US">الإنجليزية US (en_US)</SelectItem>
                      </Select>
                    </div>

                    {/* Header params */}
                    <div>
                      <div className="flex items-center justify-between mb-2">
                        <label className="text-sm font-medium text-foreground">متغيرات الـ Header (اختياري)</label>
                        <Button size="sm" variant="light" onPress={() => addParam(headerParams, setHeaderParams)}>
                          + إضافة
                        </Button>
                      </div>
                      {headerParams.map((p, i) => (
                        <div key={i} className="flex gap-2 mb-2">
                          <Input
                            size="sm" value={p}
                            placeholder={`مثال: {{name}}`}
                            onValueChange={v => updateParam(headerParams, setHeaderParams, i, v)}
                          />
                          {headerParams.length > 1 && (
                            <Button size="sm" isIconOnly color="danger" variant="light"
                              onPress={() => removeParam(headerParams, setHeaderParams, i)}>
                              ×
                            </Button>
                          )}
                        </div>
                      ))}
                      <p className="text-[11px] text-default-400">استخدم {'{{name}}'} أو {'{{phone}}'} كمتغيرات ديناميكية</p>
                    </div>

                    {/* Body params */}
                    <div>
                      <div className="flex items-center justify-between mb-2">
                        <label className="text-sm font-medium text-foreground">متغيرات الـ Body</label>
                        <Button size="sm" variant="light" onPress={() => addParam(bodyParams, setBodyParams)}>
                          + إضافة
                        </Button>
                      </div>
                      {bodyParams.map((p, i) => (
                        <div key={i} className="flex gap-2 mb-2">
                          <Input
                            size="sm" value={p}
                            placeholder={`المتغير رقم ${i + 1}، مثال: {{name}}`}
                            onValueChange={v => updateParam(bodyParams, setBodyParams, i, v)}
                          />
                          {bodyParams.length > 1 && (
                            <Button size="sm" isIconOnly color="danger" variant="light"
                              onPress={() => removeParam(bodyParams, setBodyParams, i)}>
                              ×
                            </Button>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* ── Step 2: Audience ── */}
                {step === 2 && (
                  <div className="space-y-4">
                    <p className="text-sm text-default-500">اختر من ستصل إليهم هذه الحملة:</p>
                    <div className="grid grid-cols-2 gap-3">
                      {(Object.entries(AUDIENCE_LABELS) as [Campaign['audience_type'], string][]).map(([key, label]) => (
                        <button key={key}
                          onClick={() => setAudienceType(key)}
                          className={`p-3 rounded-xl border-2 text-right transition-all
                            ${audienceType === key
                              ? 'border-primary bg-primary/5 text-primary'
                              : 'border-divider text-default-600 hover:border-default-300'}`}>
                          <p className="font-semibold text-sm">{label}</p>
                          <p className="text-[11px] text-default-400 mt-0.5">
                            {key === 'chat_users'      && 'من تحدث معك عبر الشات'}
                            {key === 'salla_customers' && 'كل عملاء متجرك في سلة'}
                            {key === 'abandoned_carts' && 'من تركوا سلتهم دون إتمام'}
                            {key === 'manual'          && 'قائمة أرقام تدخلها يدوياً'}
                          </p>
                        </button>
                      ))}
                    </div>

                    {audienceType === 'manual' && (
                      <Textarea
                        label="أرقام الهاتف (رقم في كل سطر)"
                        placeholder={'966512345678\n966598765432'}
                        value={manualPhones}
                        onValueChange={setManualPhones}
                        minRows={4}
                        description="أدخل كل رقم في سطر مستقل بصيغة دولية"
                      />
                    )}
                  </div>
                )}

                {/* ── Step 3: Launch ── */}
                {step === 3 && (
                  <div className="space-y-5">
                    {/* Preview */}
                    <div className="p-4 rounded-xl bg-content2 border border-divider">
                      <p className="text-sm text-default-500 mb-3">ملخص الحملة</p>
                      <div className="space-y-2 text-sm">
                        <div className="flex justify-between">
                          <span className="text-default-500">الحملة</span>
                          <span className="font-semibold">{cName}</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-default-500">القالب</span>
                          <span className="font-mono">{tplName} ({tplLang})</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-default-500">الجمهور</span>
                          <span>{AUDIENCE_LABELS[audienceType]}</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-default-500">عدد المستقبلين المتوقع</span>
                          <span className={`font-bold ${previewCount !== null ? 'text-primary' : 'text-default-400'}`}>
                            {previewCount !== null ? `${previewCount} جهة اتصال` : 'جاري الحساب...'}
                          </span>
                        </div>
                      </div>
                    </div>

                    {/* Schedule toggle */}
                    <div className="flex items-center justify-between p-3 rounded-xl bg-content2 border border-divider">
                      <div>
                        <p className="text-sm font-medium">جدولة الإرسال</p>
                        <p className="text-xs text-default-400">أرسل في وقت محدد بدلاً من الآن</p>
                      </div>
                      <Switch isSelected={isScheduled} onValueChange={setIsScheduled} size="sm" />
                    </div>

                    {isScheduled && (
                      <Input
                        type="datetime-local"
                        label="وقت الإرسال"
                        value={scheduledAt}
                        onValueChange={setScheduledAt}
                        min={new Date().toISOString().slice(0, 16)}
                        isRequired
                      />
                    )}

                    {!isScheduled && (
                      <div className="p-3 rounded-xl bg-warning-50 border border-warning-200 text-warning-700 text-sm flex gap-2 items-start">
                        <Icon d="M12 9v4M12 17h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"
                          size={16} className="flex-shrink-0 mt-0.5" />
                        <span>سيبدأ الإرسال فوراً بعد الضغط على "إطلاق الحملة"</span>
                      </div>
                    )}
                  </div>
                )}

                {/* Error banner */}
                {saveErr && (
                  <div className="mt-3 p-3 rounded-xl bg-danger-50 border border-danger-200 text-danger text-sm">
                    {saveErr}
                  </div>
                )}
              </ModalBody>

              <ModalFooter>
                {step > 1 && (
                  <Button variant="flat" onPress={() => { setSaveErr(''); setStep(s => s - 1) }}
                    isDisabled={saving}>
                    السابق
                  </Button>
                )}
                <Button variant="light" onPress={() => { onClose(); resetModal() }} isDisabled={saving}>
                  إلغاء
                </Button>
                {step === 1 && (
                  <Button color="primary" onPress={goStep2} isLoading={saving}>
                    التالي: الجمهور
                  </Button>
                )}
                {step === 2 && (
                  <Button color="primary" onPress={goStep3} isLoading={saving}>
                    التالي: الإطلاق
                  </Button>
                )}
                {step === 3 && (
                  <Button color={isScheduled ? 'primary' : 'success'} onPress={doLaunch} isLoading={saving}>
                    {isScheduled ? 'جدولة الحملة' : 'إطلاق الحملة'}
                  </Button>
                )}
              </ModalFooter>
            </>
          )}
        </ModalContent>
      </Modal>
    </div>
  )
}
