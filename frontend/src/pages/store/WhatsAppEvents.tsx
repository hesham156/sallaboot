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
  isNew?: boolean
  readOnly?: boolean
}

const EVENT_DEFS: EventDef[] = [
  {
    key: 'abandoned_cart',
    label: 'سلة متروكة',
    description: 'يُرسل رسالة للعميل عبر WhatsApp عندما يترك سلة التسوق دون إتمام الشراء.',
    icon: ['M6 2 3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z', 'M3 6h18', 'M16 10a4 4 0 0 1-8 0'],
    iconBg: 'bg-blue-50', iconColor: 'text-blue-500',
  },
  {
    key: 'customer_welcome',
    label: 'ترحيب بعميل جديد',
    description: 'رسالة ترحيب تلقائية عبر WhatsApp عندما يسجّل عميل جديد في متجرك.',
    icon: ['M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z'],
    iconBg: 'bg-purple-50', iconColor: 'text-purple-500',
  },
  {
    key: 'new_order',
    label: 'طلب جديد',
    description: 'إشعار فوري للعميل عبر WhatsApp عند تقديم طلب جديد في المتجر.',
    icon: ['M9 5H7a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2h-2', 'M9 5a2 2 0 0 0 2 2h2a2 2 0 0 0 2-2', 'M9 5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2'],
    iconBg: 'bg-green-50', iconColor: 'text-green-600',
    isNew: true,
  },
  {
    key: 'order_status',
    label: 'تحديث حالة الطلب',
    description: 'يُخطر العميل بتغييرات حالة طلبه (قيد التوصيل، مكتمل، إلخ) عبر WhatsApp.',
    icon: ['M9 3H5a2 2 0 0 0-2 2v4', 'M9 3h6', 'M9 3v4', 'M15 3h4a2 2 0 0 1 2 2v4', 'M21 9v6', 'M3 9v6', 'M3 15a2 2 0 0 0 2 2h4', 'M15 17h4a2 2 0 0 0 2-2'],
    iconBg: 'bg-orange-50', iconColor: 'text-orange-500',
  },
  {
    key: 'invoice_created',
    label: 'إنشاء فاتورة',
    description: 'إشعار للعميل عبر WhatsApp عند إنشاء فاتورة لطلبه.',
    icon: ['M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z', 'M14 2v6h6', 'M16 13H8', 'M16 17H8', 'M10 9H8'],
    iconBg: 'bg-slate-50', iconColor: 'text-slate-500',
  },
  {
    key: 'verification_code',
    label: 'رمز التحقق',
    description: 'إرسال رمز التحقق للعميل عبر WhatsApp عند محاولة تسجيل الدخول.',
    icon: ['M8 9h8', 'M8 13h6', 'M18 2H6a2 2 0 0 0-2 2v16l4-2 4 2 4-2 4 2V4a2 2 0 0 0-2-2z'],
    iconBg: 'bg-slate-50', iconColor: 'text-slate-400',
    readOnly: true,
  },
  {
    key: 'shipment_created',
    label: 'إنشاء شحنة',
    description: 'إشعار للعميل عبر WhatsApp بمعلومات الشحن ورقم التتبع.',
    icon: ['M5 17H3a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v9a2 2 0 0 1-2 2h-3', 'M16 3.13V8H11', 'M16 17a2 2 0 1 1-4 0 2 2 0 0 1 4 0', 'M7 17a2 2 0 1 1-4 0 2 2 0 0 1 4 0'],
    iconBg: 'bg-slate-50', iconColor: 'text-slate-500',
  },
  {
    key: 'review_added',
    label: 'إضافة تقييم',
    description: 'يُرسَل هذا الحدث عند إضافة تقييم لمنتج ويُشكر العميل تلقائياً.',
    icon: ['M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z'],
    iconBg: 'bg-slate-50', iconColor: 'text-slate-500',
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
    setEvents(prev => ({ ...prev, [key]: { ...prev[key], enabled: val } }))
    await api.setWaEvent(storeId, key, { enabled: val }).catch(console.error)
  }

  const saveTemplate = async (key: string, template: string) => {
    setSaving(true)
    await api.setWaEvent(storeId, key, { template }).catch(console.error)
    setSaving(false)
    setConfiguring(null)
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

  return (
    <div className="space-y-6" dir="rtl">
      {/* Header */}
      <div>
        <h1 className="text-xl font-bold text-foreground">أحداث WhatsApp</h1>
        <p className="text-sm text-default-500 mt-1">
          خصّص رسائل WhatsApp التلقائية التي تُرسَل لعملائك عند كل حدث في متجرك.
        </p>
      </div>

      {/* Cards grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
        {EVENT_DEFS.map(def => {
          const ev = events[def.key] ?? { enabled: false, template: '' }
          return (
            <div
              key={def.key}
              className="bg-content1 border border-divider rounded-2xl p-5 flex flex-col gap-4 hover:border-primary/40 transition-colors relative"
            >
              {def.isNew && (
                <span className="absolute top-4 left-4 bg-primary text-white text-[10px] font-bold px-2 py-0.5 rounded-full uppercase tracking-wide">
                  جديد
                </span>
              )}

              {/* Icon + title */}
              <div className="flex items-start gap-3">
                <div className={`w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0 ${def.iconBg}`}>
                  <Icon d={def.icon} size={20} className={def.iconColor} />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="font-bold text-sm text-foreground leading-tight">{def.label}</p>
                  <p className="text-xs text-default-500 mt-1 leading-relaxed line-clamp-3">{def.description}</p>
                </div>
              </div>

              {/* Footer */}
              <div className="flex items-center justify-between border-t border-divider pt-3">
                <div className="flex items-center gap-2">
                  <span className={`w-2 h-2 rounded-full ${ev.enabled ? 'bg-success' : 'bg-default-300'}`} />
                  <span className={`text-xs font-medium ${ev.enabled ? 'text-success-600' : 'text-default-400'}`}>
                    {ev.enabled ? 'مفعّل' : 'معطّل'}
                  </span>
                </div>
                <button
                  onClick={() => { setTestMsg(''); setConfiguring(def.key) }}
                  className="text-xs font-semibold text-primary hover:underline flex items-center gap-1"
                >
                  ضبط
                  <Icon d="M9 18l6-6-6-6" size={13} />
                </button>
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
