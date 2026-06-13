import { useEffect, useState } from 'react'
import { Switch, Spinner } from '@heroui/react'
import { api } from '../../api'

/* ── Icon ── */
function Icon({ d, size = 18, className = '' }: { d: string | string[]; size?: number; className?: string }) {
  const paths = Array.isArray(d) ? d : [d]
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round"
      className={className}>
      {paths.map((p, i) => <path key={i} d={p} />)}
    </svg>
  )
}

/* ── Event definitions ── */
interface EventDef {
  key: string
  label: string
  description: string
  icon: string | string[]
  iconBg: string
  iconColor: string
  accent: string  // hex — used for the hover glow and accent stripe
  isNew?: boolean
  readOnly?: boolean
}

const EVENT_DEFS: EventDef[] = [
  {
    key: 'abandoned_cart',
    label: 'سلة متروكة',
    description: 'يُرسل رسالة للعميل عبر WhatsApp عندما يترك سلة التسوق دون إتمام الشراء.',
    icon: ['M6 2 3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z', 'M3 6h18', 'M16 10a4 4 0 0 1-8 0'],
    iconBg: 'bg-blue-50', iconColor: 'text-blue-600',
    accent: '#3b82f6',
  },
  {
    key: 'customer_welcome',
    label: 'ترحيب بعميل جديد',
    description: 'رسالة ترحيب تلقائية عبر WhatsApp عندما يسجّل عميل جديد في متجرك.',
    icon: ['M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z'],
    iconBg: 'bg-purple-50', iconColor: 'text-purple-600',
    accent: '#a855f7',
  },
  {
    key: 'new_order',
    label: 'طلب جديد',
    description: 'إشعار فوري للعميل عبر WhatsApp عند تقديم طلب جديد في المتجر.',
    icon: ['M9 5H7a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2h-2', 'M9 5a2 2 0 0 0 2 2h2a2 2 0 0 0 2-2', 'M9 5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2'],
    iconBg: 'bg-emerald-50', iconColor: 'text-emerald-600',
    accent: '#10b981',
    isNew: true,
  },
  {
    key: 'order_status',
    label: 'تحديث حالة الطلب',
    description: 'يُخطر العميل بتغييرات حالة طلبه (قيد التوصيل، مكتمل، إلخ) عبر WhatsApp.',
    icon: ['M9 3H5a2 2 0 0 0-2 2v4', 'M9 3h6', 'M9 3v4', 'M15 3h4a2 2 0 0 1 2 2v4', 'M21 9v6', 'M3 9v6', 'M3 15a2 2 0 0 0 2 2h4', 'M15 17h4a2 2 0 0 0 2-2'],
    iconBg: 'bg-orange-50', iconColor: 'text-orange-600',
    accent: '#f97316',
  },
  {
    key: 'invoice_created',
    label: 'إنشاء فاتورة',
    description: 'إشعار للعميل عبر WhatsApp عند إنشاء فاتورة لطلبه.',
    icon: ['M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z', 'M14 2v6h6', 'M16 13H8', 'M16 17H8', 'M10 9H8'],
    iconBg: 'bg-amber-50', iconColor: 'text-amber-600',
    accent: '#d97706',
  },
  {
    key: 'verification_code',
    label: 'رمز التحقق',
    description: 'إرسال رمز التحقق للعميل عبر WhatsApp عند محاولة تسجيل الدخول.',
    icon: ['M8 9h8', 'M8 13h6', 'M18 2H6a2 2 0 0 0-2 2v16l4-2 4 2 4-2 4 2V4a2 2 0 0 0-2-2z'],
    iconBg: 'bg-rose-50', iconColor: 'text-rose-500',
    accent: '#f43f5e',
    readOnly: true,
  },
  {
    key: 'shipment_created',
    label: 'إنشاء شحنة',
    description: 'إشعار للعميل عبر WhatsApp بمعلومات الشحن ورقم التتبع.',
    icon: ['M5 17H3a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v9a2 2 0 0 1-2 2h-3', 'M16 3.13V8H11', 'M16 17a2 2 0 1 1-4 0 2 2 0 0 1 4 0', 'M7 17a2 2 0 1 1-4 0 2 2 0 0 1 4 0'],
    iconBg: 'bg-cyan-50', iconColor: 'text-cyan-600',
    accent: '#06b6d4',
  },
  {
    key: 'review_added',
    label: 'إضافة تقييم',
    description: 'يُرسَل هذا الحدث عند إضافة تقييم لمنتج ويُشكر العميل تلقائياً.',
    icon: ['M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z'],
    iconBg: 'bg-yellow-50', iconColor: 'text-yellow-600',
    accent: '#eab308',
  },
]

/* ── Configure modal ── */
function ConfigureModal({
  def, enabled, template, saving, testMsg,
  onClose, onToggle, onSave, onTest,
}: {
  def: EventDef
  enabled: boolean
  template: string
  saving: boolean
  testMsg: string
  onClose: () => void
  onToggle: (v: boolean) => void
  onSave: (t: string) => void
  onTest: (phone: string) => void
}) {
  const [draft, setDraft] = useState(template)
  const [testPhone, setTestPhone] = useState('')

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
      <div className="bg-content1 rounded-2xl shadow-2xl w-full max-w-lg border border-divider" dir="rtl">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-divider">
          <h2 className="font-bold text-foreground text-base">{def.label}</h2>
          <button onClick={onClose} className="text-default-400 hover:text-foreground transition-colors">
            <Icon d="M18 6 6 18M6 6l12 12" size={20} />
          </button>
        </div>

        <div className="px-6 py-5 space-y-5">
          {/* Toggle */}
          <div className="flex items-center justify-between">
            <span className="text-sm text-default-600">تفعيل هذا الحدث</span>
            <Switch isSelected={enabled} onValueChange={onToggle} isDisabled={def.readOnly} size="sm" color="success" />
          </div>

          {/* Template */}
          {!def.readOnly && (
            <div className="space-y-2">
              <label className="text-sm font-medium text-default-700">نص الرسالة (اختياري)</label>
              <textarea
                value={draft}
                onChange={e => setDraft(e.target.value)}
                rows={5}
                placeholder={`اتركه فارغاً لاستخدام النص الافتراضي\n\nمتغيرات متاحة:\n{name} — اسم العميل\n{order_ref} — رقم الطلب\n{store_name} — اسم المتجر`}
                className="w-full text-sm bg-content2 border border-divider rounded-xl px-4 py-3 text-foreground placeholder:text-default-300 resize-none focus:outline-none focus:border-primary"
              />
              <p className="text-xs text-default-400">اتركه فارغاً لاستخدام النص الافتراضي</p>
            </div>
          )}

          {def.readOnly && (
            <div className="rounded-xl bg-default-100 border border-divider px-4 py-3 text-sm text-default-500">
              هذا الحدث يُدار بواسطة Salla مباشرة ولا يمكن تخصيصه.
            </div>
          )}

          {/* Test phone */}
          {!def.readOnly && (
            <div className="space-y-1.5">
              <label className="text-sm font-medium text-default-700">رقم الاختبار</label>
              <input
                type="tel"
                value={testPhone}
                onChange={e => setTestPhone(e.target.value)}
                placeholder="+966 5XX XXX XXX"
                dir="ltr"
                className="w-full text-sm bg-content2 border border-divider rounded-xl px-4 py-2.5 text-foreground placeholder:text-default-300 focus:outline-none focus:border-primary"
              />
              <p className="text-xs text-default-400">الرقم اللي هتتبعتله رسالة الاختبار</p>
            </div>
          )}

          {/* Test result */}
          {testMsg && (
            <div className={`rounded-xl px-4 py-2.5 text-sm border flex items-center gap-2 ${testMsg.startsWith('✅') ? 'bg-success-50 border-success-200 text-success-700' : 'bg-danger-50 border-danger-200 text-danger-700'}`}>
              {testMsg}
            </div>
          )}
        </div>

        {/* Actions */}
        <div className="flex items-center gap-3 px-6 py-4 border-t border-divider">
          {!def.readOnly && (
            <>
              <button
                onClick={() => onSave(draft)}
                disabled={saving}
                className="flex-1 bg-primary text-white rounded-xl py-2.5 text-sm font-semibold hover:bg-primary/90 disabled:opacity-50 transition-colors"
              >
                {saving ? 'جاري الحفظ...' : 'حفظ'}
              </button>
              <button
                onClick={() => onTest(testPhone)}
                disabled={saving || !testPhone.trim()}
                className="flex items-center gap-1.5 px-4 py-2.5 text-sm font-semibold border border-divider rounded-xl hover:bg-content2 text-default-600 disabled:opacity-40 transition-colors"
              >
                <Icon d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.127.96.361 1.903.7 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.907.339 1.85.573 2.81.7A2 2 0 0 1 22 16.92z" size={14} />
                اختبار
              </button>
            </>
          )}
          <button onClick={onClose} className="px-4 py-2.5 text-sm text-default-500 hover:text-foreground transition-colors">
            إغلاق
          </button>
        </div>
      </div>
    </div>
  )
}

/* ── Main page ── */
export default function WhatsAppEvents({ storeId }: { storeId: string }) {
  const [events, setEvents] = useState<Record<string, { enabled: boolean; template: string }>>({})
  const [loading, setLoading] = useState(true)
  const [configuring, setConfiguring] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [testMsg, setTestMsg] = useState('')

  useEffect(() => {
    api.getWaEvents(storeId)
      .then(r => setEvents(r.events))
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [storeId])

  const toggleEvent = async (key: string, val: boolean) => {
    // Optimistic flip — snapshot the previous value so we can roll back
    // if the API rejects (no point lying to the user about persisted state).
    const prev = events[key]?.enabled ?? false
    setEvents(p => ({ ...p, [key]: { ...p[key], enabled: val } }))
    try {
      await api.setWaEvent(storeId, key, { enabled: val })
    } catch (e) {
      console.error(e)
      setEvents(p => ({ ...p, [key]: { ...p[key], enabled: prev } }))
      setTestMsg(e instanceof Error ? `❌ ${e.message}` : '❌ تعذّر حفظ التغيير')
    }
  }

  const saveTemplate = async (key: string, template: string) => {
    setSaving(true)
    setTestMsg('')
    try {
      await api.setWaEvent(storeId, key, { template })
      setEvents(p => ({ ...p, [key]: { ...p[key], template } }))
      setConfiguring(null)
    } catch (e) {
      console.error(e)
      // Keep the modal open so the user can retry without retyping.
      setTestMsg(e instanceof Error ? `❌ ${e.message}` : '❌ تعذّر حفظ القالب')
    } finally {
      setSaving(false)
    }
  }

  const testEvent = async (key: string, phone: string) => {
    setTestMsg('')
    try {
      const r = await api.testWaEvent(storeId, key, phone)
      setTestMsg(r.message || '✅ تم الإرسال')
    } catch {
      setTestMsg('❌ فشل الإرسال — تحقق من إعدادات WhatsApp')
    }
  }

  if (loading) return (
    <div className="flex items-center justify-center h-48">
      <Spinner size="lg" color="primary" label="جاري التحميل..." />
    </div>
  )

  const activeDef = configuring ? EVENT_DEFS.find(d => d.key === configuring) : null
  const enabledCount = EVENT_DEFS.filter(d => events[d.key]?.enabled).length
  const configurableCount = EVENT_DEFS.filter(d => !d.readOnly).length

  return (
    <div className="relative px-4 sm:px-6 lg:px-8 py-6 sm:py-8 space-y-8 overflow-hidden" dir="rtl">
      {/* ─── Atmospheric background ─── */}
      <div className="absolute top-[-3rem] right-[-3rem] w-[26rem] h-[26rem] bg-emerald-400/15 rounded-full blur-[140px] pointer-events-none -z-10" />
      <div className="absolute top-32 left-[-4rem] w-[22rem] h-[22rem] bg-teal-400/10 rounded-full blur-[140px] pointer-events-none -z-10" />
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_1px_1px,_theme(colors.default.200)_1px,_transparent_0)] [background-size:24px_24px] opacity-40 pointer-events-none -z-10" />

      {/* ─── Header ─── */}
      <div className="relative flex flex-wrap items-start justify-between gap-6">
        <div className="flex-1 min-w-[260px]">
          <div className="inline-flex items-center gap-2 bg-emerald-50 border border-emerald-100 text-emerald-700 text-[11px] font-bold rounded-full px-3 py-1 mb-3">
            <svg width={12} height={12} viewBox="0 0 24 24" fill="currentColor">
              <path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347z" />
              <path d="M12 0C5.373 0 0 5.373 0 12c0 2.12.554 4.106 1.521 5.836L.057 23.887l6.217-1.432A11.946 11.946 0 0012 24c6.627 0 12-5.373 12-12S18.627 0 12 0z" />
            </svg>
            تكامل مباشر مع WhatsApp Business
          </div>
          <h1 className="text-3xl sm:text-4xl font-black text-foreground tracking-tight leading-tight">
            أحداث <span className="text-gradient">WhatsApp</span>
          </h1>
          <p className="text-sm text-default-500 mt-3 max-w-xl leading-relaxed">
            كل حدث في متجرك = رسالة في الوقت المناسب — من ترحيب العميل لحد متابعة الشحنة. خصّص الرسائل بنفسك أو خلّيهم على الافتراضي.
          </p>
        </div>

        {/* Stats card */}
        <div className="bg-content1 border border-divider rounded-2xl px-5 py-4 flex items-center gap-5 shadow-sm shrink-0 mt-1">
          <div className="text-center">
            <div className="flex items-baseline justify-center gap-1" dir="ltr">
              <span className="text-3xl font-black text-emerald-600 leading-none">{enabledCount}</span>
              <span className="text-sm font-bold text-default-400">/{EVENT_DEFS.length}</span>
            </div>
            <p className="text-[10px] font-bold text-default-500 mt-1.5 uppercase tracking-wider">مفعّل</p>
          </div>
          <div className="h-10 w-px bg-divider" />
          <div className="text-center">
            <p className="text-3xl font-black text-foreground leading-none">{configurableCount}</p>
            <p className="text-[10px] font-bold text-default-500 mt-1.5 uppercase tracking-wider">قابل للتخصيص</p>
          </div>
        </div>
      </div>

      {/* ─── Cards grid ─── */}
      <div className="relative grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
        {EVENT_DEFS.map(def => {
          const ev = events[def.key] ?? { enabled: false, template: '' }
          const isHero = def.isNew

          return (
            <div
              key={def.key}
              onClick={() => { setTestMsg(''); setConfiguring(def.key) }}
              className={`group relative overflow-hidden rounded-2xl border bg-content1 p-5 flex flex-col gap-4 cursor-pointer transition-all duration-300 hover:-translate-y-1 ${
                isHero
                  ? 'border-emerald-200/70'
                  : 'border-divider hover:border-default-200'
              }`}
              style={{
                ['--accent' as string]: def.accent,
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.boxShadow = `0 18px 40px -12px ${def.accent}30, 0 0 0 1px ${def.accent}20`
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.boxShadow = ''
              }}
            >
              {/* Accent stripe — top edge, gradient fading from the accent color */}
              <div
                className="absolute top-0 inset-x-0 h-[3px] opacity-0 group-hover:opacity-100 transition-opacity duration-300"
                style={{ background: `linear-gradient(90deg, transparent, ${def.accent}, transparent)` }}
              />

              {/* Featured background tint for the "new" hero card */}
              {isHero && (
                <div
                  className="absolute inset-0 pointer-events-none opacity-60"
                  style={{ background: `radial-gradient(circle at top right, ${def.accent}15, transparent 70%)` }}
                />
              )}

              {def.isNew && (
                <span
                  className="absolute top-3 left-3 text-white text-[10px] font-black px-2.5 py-1 rounded-full uppercase tracking-wider shadow-md flex items-center gap-1 z-10"
                  style={{ background: `linear-gradient(135deg, ${def.accent}, #0d9488)` }}
                >
                  <span className="w-1.5 h-1.5 rounded-full bg-white animate-pulse" />
                  جديد
                </span>
              )}

              {def.readOnly && (
                <span className="absolute top-3 left-3 text-default-500 bg-default-100 border border-divider text-[10px] font-bold px-2 py-0.5 rounded-full uppercase tracking-wide z-10 flex items-center gap-1">
                  <svg width={10} height={10} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round">
                    <rect x="3" y="11" width="18" height="11" rx="2" />
                    <path d="M7 11V7a5 5 0 0110 0v4" />
                  </svg>
                  Salla
                </span>
              )}

              {/* Icon + title */}
              <div className="relative flex items-start gap-3.5">
                <div
                  className={`w-12 h-12 rounded-2xl flex items-center justify-center flex-shrink-0 ${def.iconBg} transition-transform duration-300 group-hover:scale-110 group-hover:rotate-[-4deg]`}
                >
                  <Icon d={def.icon} size={24} className={def.iconColor} />
                </div>
                <div className="flex-1 min-w-0 pt-0.5">
                  <p className="font-black text-sm text-foreground leading-tight">
                    {def.label}
                  </p>
                  <p className="text-xs text-default-500 mt-1.5 leading-relaxed line-clamp-2">
                    {def.description}
                  </p>
                </div>
              </div>

              {/* Footer */}
              <div className="relative flex items-center justify-between border-t border-divider/70 pt-3 mt-auto">
                <div className="flex items-center gap-1.5">
                  <span className="relative flex items-center justify-center w-2 h-2">
                    <span
                      className={`absolute inset-0 rounded-full ${ev.enabled ? 'animate-ping opacity-60' : 'opacity-0'}`}
                      style={{ background: def.accent }}
                    />
                    <span
                      className="relative w-2 h-2 rounded-full transition-colors"
                      style={{ background: ev.enabled ? def.accent : '#cbd5e1' }}
                    />
                  </span>
                  <span
                    className="text-xs font-bold transition-colors"
                    style={{ color: ev.enabled ? def.accent : '#94a3b8' }}
                  >
                    {ev.enabled ? 'مفعّل' : 'معطّل'}
                  </span>
                </div>
                <span
                  className="text-xs font-bold flex items-center gap-1 transition-all"
                  style={{ color: def.accent }}
                >
                  ضبط
                  <Icon d="M9 18l6-6-6-6" size={13} className="group-hover:-translate-x-1 transition-transform duration-300" />
                </span>
              </div>
            </div>
          )
        })}
      </div>

      {/* Configure modal */}
      {activeDef && (
        <ConfigureModal
          def={activeDef}
          enabled={events[activeDef.key]?.enabled ?? false}
          template={events[activeDef.key]?.template ?? ''}
          saving={saving}
          testMsg={testMsg}
          onClose={() => setConfiguring(null)}
          onToggle={v => toggleEvent(activeDef.key, v)}
          onSave={t => saveTemplate(activeDef.key, t)}
          onTest={(phone) => testEvent(activeDef.key, phone)}
        />
      )}
    </div>
  )
}
