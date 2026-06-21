import { useEffect, useState, useCallback } from 'react'
import { Switch, Spinner } from '@heroui/react'
import { api, ApiError } from '../../api'
import { PageHeader } from '../../components/ui'

/* ── Types ── */
interface Customer {
  id: number
  store_id: string
  customer_id: string
  customer_name: string
  phone: string
  email: string
  segment: string
  segment_reason: string
  last_order_id: string | null
  last_order_at: string | null
  last_conv_at: string | null
  followup_count: number
  last_followup_at: string | null
  next_followup_at: string | null
  followup_paused: boolean
  notes: string
  updated_at: string
}

interface SegStats { counts: Record<string, number>; total: number }

interface SegConfig {
  delay_hours: number
  max_followups: number
  template: string
  message: string
  enabled: boolean
}

interface FollowupConfig {
  enabled: boolean
  segments: Record<string, SegConfig>
}

/* ── Segment meta ── */
const SEGMENTS: Record<string, { label: string; color: string; bg: string; icon: string; description: string }> = {
  new:      { label: 'جديد',          color: 'text-default-600',  bg: 'bg-content2',   icon: '👤', description: 'تواصل جديد بدون نية شراء' },
  inquiry:  { label: 'مستفسر',        color: 'text-blue-600',  bg: 'bg-blue-50',    icon: '💬', description: 'سأل عن المنتجات دون نية شراء واضحة' },
  hesitant: { label: 'متردد',         color: 'text-yellow-600',bg: 'bg-yellow-50',  icon: '🤔', description: 'أبدى اهتماماً بالشراء ولم يُكمل' },
  buyer:    { label: 'مشترٍ',         color: 'text-green-600', bg: 'bg-green-50',   icon: '🛍️', description: 'أتم طلباً واحداً' },
  loyal:    { label: 'عميل وفي',      color: 'text-purple-600',bg: 'bg-purple-50',  icon: '⭐', description: 'طلبين أو أكثر' },
  inactive: { label: 'غير نشط',       color: 'text-red-500',   bg: 'bg-red-50',     icon: '💤', description: 'لا نشاط منذ 30+ يوم' },
}

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

function Badge({ seg }: { seg: string }) {
  const m = SEGMENTS[seg] || { label: seg, color: 'text-default-500', bg: 'bg-content2', icon: '?' }
  return (
    <span className={`inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full font-medium ${m.bg} ${m.color}`}>
      {m.icon} {m.label}
    </span>
  )
}

function fmtDate(iso: string | null) {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleDateString('ar-SA', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
  } catch { return iso }
}

const DEFAULT_CONFIG: FollowupConfig = {
  enabled: false,
  segments: {
    hesitant: { enabled: true,  delay_hours: 48,  max_followups: 2, template: '', message: 'مرحباً {name} 👋\nلاحظنا اهتمامك بمنتجاتنا ولم تكمل طلبك.\nهل تحتاج مساعدة أو معلومات إضافية؟' },
    inquiry:  { enabled: true,  delay_hours: 24,  max_followups: 1, template: '', message: 'مرحباً {name} 👋\nشكراً لتواصلك معنا! هل لديك أي استفسار إضافي؟' },
    buyer:    { enabled: true,  delay_hours: 168, max_followups: 1, template: '', message: 'مرحباً {name} ❤️\nشكراً لثقتك بنا! كيف وجدت طلبك؟ يسعدنا خدمتك مجدداً.' },
    inactive: { enabled: false, delay_hours: 720, max_followups: 1, template: '', message: 'مرحباً {name} 🌟\nاشتقنا إليك! عندنا عروض جديدة تستحق اهتمامك.' },
  },
}

interface EditState {
  customer: Customer
  segment: string
  notes: string
  saving: boolean
  error: string
}

export default function CustomerSegments({ storeId }: { storeId: string }) {
  const [tab, setTab]           = useState<'customers' | 'settings'>('customers')
  const [filter, setFilter]     = useState('')
  const [customers, setCustomers] = useState<Customer[]>([])
  const [stats, setStats]       = useState<SegStats | null>(null)
  const [loading, setLoading]   = useState(true)
  const [scanning, setScanning] = useState(false)
  const [scanMsg, setScanMsg]   = useState('')
  const [config, setConfig]     = useState<FollowupConfig>(DEFAULT_CONFIG)
  const [cfgLoading, setCfgLoading] = useState(false)
  const [cfgSaving, setCfgSaving]   = useState(false)
  const [cfgMsg, setCfgMsg]     = useState('')
  const [sendingId, setSendingId] = useState<string | null>(null)
  const [editState, setEditState] = useState<EditState | null>(null)

  const loadData = useCallback(async () => {
    setLoading(true)
    try {
      const [custRes, statsRes] = await Promise.all([
        api.get<{ customers: Customer[]; count: number }>(`/admin/${storeId}/segments${filter ? `?segment=${filter}` : ''}`),
        api.get<SegStats>(`/admin/${storeId}/segments/stats`),
      ])
      setCustomers(custRes.customers)
      setStats(statsRes)
    } catch { /* ignore */ }
    finally { setLoading(false) }
  }, [storeId, filter])

  const loadConfig = useCallback(async () => {
    setCfgLoading(true)
    try {
      const cfg = await api.get<FollowupConfig>(`/admin/${storeId}/settings/followup`)
      setConfig(cfg)
    } catch { /* use default */ }
    finally { setCfgLoading(false) }
  }, [storeId])

  useEffect(() => { loadData() }, [loadData])
  useEffect(() => { if (tab === 'settings') loadConfig() }, [tab, loadConfig])

  const handleScan = async () => {
    setScanning(true)
    setScanMsg('')
    try {
      const res = await api.post<{ classified: number; message: string }>(`/admin/${storeId}/segments/scan`)
      setScanMsg(res.message)
      await loadData()
    } catch (e) {
      setScanMsg(e instanceof ApiError ? e.detail : 'فشل المسح')
    } finally { setScanning(false) }
  }

  const handlePause = async (cid: string, paused: boolean) => {
    await api.put(`/admin/${storeId}/segments/${encodeURIComponent(cid)}/pause`, { paused })
    setCustomers(cs => cs.map(c => c.customer_id === cid ? { ...c, followup_paused: paused } : c))
  }

  const handleSendNow = async (cid: string) => {
    setSendingId(cid)
    try {
      const res = await api.post<{ message: string }>(`/admin/${storeId}/segments/${encodeURIComponent(cid)}/followup-now`)
      alert(res.message)
      await loadData()
    } catch (e) {
      alert(e instanceof ApiError ? e.detail : 'فشل الإرسال')
    } finally { setSendingId(null) }
  }

  const openEdit = (c: Customer) => {
    setEditState({ customer: c, segment: c.segment, notes: c.notes || '', saving: false, error: '' })
  }

  const handleSaveEdit = async () => {
    if (!editState) return
    setEditState(s => s ? { ...s, saving: true, error: '' } : s)
    try {
      const res = await api.put<{ customer: Customer }>(
        `/admin/${storeId}/segments/${encodeURIComponent(editState.customer.customer_id)}`,
        { segment: editState.segment, notes: editState.notes }
      )
      setCustomers(cs => cs.map(c =>
        c.customer_id === editState.customer.customer_id
          ? { ...c, ...res.customer }
          : c
      ))
      setEditState(null)
    } catch (e) {
      setEditState(s => s ? { ...s, saving: false, error: e instanceof ApiError ? e.detail : 'فشل الحفظ' } : s)
    }
  }

  const handleSaveConfig = async () => {
    setCfgSaving(true)
    setCfgMsg('')
    try {
      const res = await api.put<{ message: string }>(`/admin/${storeId}/settings/followup`, config)
      setCfgMsg(res.message)
    } catch (e) {
      setCfgMsg(e instanceof ApiError ? e.detail : 'فشل الحفظ')
    } finally { setCfgSaving(false) }
  }

  const setSegCfg = (seg: string, key: string, val: unknown) => {
    setConfig(c => ({
      ...c,
      segments: {
        ...c.segments,
        [seg]: { ...c.segments[seg], [key]: val },
      },
    }))
  }

  return (
    <div className="max-w-5xl mx-auto p-6 space-y-6" dir="rtl">
      <PageHeader
        title="تصنيف العملاء والمتابعة"
        subtitle="تصنيف تلقائي للعملاء وإرسال رسائل متابعة عبر WhatsApp"
        icon="M17 20h5v-2a4 4 0 00-3-3.87M9 20H4v-2a4 4 0 013-3.87m6-2.13a4 4 0 10-4-4 4 4 0 004 4zm6 0a4 4 0 10-1-7.87"
        actions={
          <button onClick={handleScan} disabled={scanning}
            className="flex items-center gap-2 px-4 py-2 text-sm border border-divider rounded-lg hover:bg-content2 transition-colors disabled:opacity-60">
            {scanning ? <Spinner size="sm" /> : <Icon d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />}
            مسح المحادثات وتصنيف
          </button>
        }
      />

      {scanMsg && (
        <div className={`p-3 rounded-lg text-sm ${scanMsg.startsWith('✅') ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-700'}`}>
          {scanMsg}
        </div>
      )}

      {/* Stats cards */}
      {stats && (
        <div className="grid grid-cols-3 md:grid-cols-6 gap-3">
          {Object.entries(SEGMENTS).map(([seg, meta]) => (
            <button key={seg}
              onClick={() => setFilter(filter === seg ? '' : seg)}
              className={`rounded-xl p-3 text-center transition-all border ${
                filter === seg ? 'border-blue-400 shadow-md' : 'border-divider hover:border-default-300'
              } ${meta.bg}`}>
              <div className="text-2xl">{meta.icon}</div>
              <div className={`text-xl font-bold ${meta.color}`}>{stats.counts[seg] || 0}</div>
              <div className="text-xs text-default-500 mt-0.5">{meta.label}</div>
            </button>
          ))}
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-1 border-b border-divider">
        {(['customers', 'settings'] as const).map(t => (
          <button key={t} onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm font-medium transition-colors border-b-2 ${
              tab === t ? 'border-blue-500 text-blue-600' : 'border-transparent text-default-500 hover:text-default-700'
            }`}>
            {t === 'customers' ? 'قائمة العملاء' : 'إعدادات المتابعة'}
          </button>
        ))}
      </div>

      {/* Customers Tab */}
      {tab === 'customers' && (
        loading ? <div className="flex justify-center py-12"><Spinner size="lg" /></div> : (
          customers.length === 0 ? (
            <div className="text-center py-16 text-default-400">
              <div className="text-5xl mb-3">👤</div>
              <p className="text-sm">لا يوجد عملاء مصنّفون بعد</p>
              <p className="text-xs mt-1">اضغط "مسح المحادثات وتصنيف" لبناء القائمة</p>
            </div>
          ) : (
            <div className="space-y-2">
              {customers.map(c => (
                <div key={c.id} className="bg-white border border-divider rounded-xl p-4 shadow-sm hover:shadow transition-shadow">
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="font-semibold text-foreground">{c.customer_name || 'بدون اسم'}</span>
                        <Badge seg={c.segment} />
                        {c.followup_paused && (
                          <span className="text-xs bg-content2 text-default-500 px-2 py-0.5 rounded-full">متوقف</span>
                        )}
                      </div>
                      <div className="flex flex-wrap gap-x-4 gap-y-1 mt-1.5 text-xs text-default-500">
                        {c.phone && <span>📱 {c.phone}</span>}
                        {c.email && <span>✉️ {c.email}</span>}
                        {c.segment_reason && <span className="italic">{c.segment_reason}</span>}
                      </div>
                      <div className="flex flex-wrap gap-x-4 gap-y-1 mt-1 text-xs text-default-400">
                        <span>آخر تواصل: {fmtDate(c.last_conv_at)}</span>
                        {c.last_order_id && <span>آخر طلب: #{c.last_order_id}</span>}
                        {c.followup_count > 0 && <span>رسائل متابعة: {c.followup_count}</span>}
                        {c.next_followup_at && !c.followup_paused && (
                          <span className="text-blue-400">المتابعة القادمة: {fmtDate(c.next_followup_at)}</span>
                        )}
                      </div>
                      {c.notes && (
                        <p className="mt-1.5 text-xs text-amber-700 bg-amber-50 rounded px-2 py-1 border border-amber-100">
                          📝 {c.notes}
                        </p>
                      )}
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      {/* Edit segment/notes */}
                      <button
                        onClick={() => openEdit(c)}
                        title="تعديل التصنيف أو الملاحظات"
                        className="p-1.5 text-blue-500 hover:bg-blue-50 rounded-lg transition-colors">
                        <Icon d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" size={16} />
                      </button>
                      {/* Send now */}
                      <button
                        onClick={() => handleSendNow(c.customer_id)}
                        disabled={sendingId === c.customer_id}
                        title="إرسال رسالة متابعة الآن"
                        className="p-1.5 text-green-600 hover:bg-green-50 rounded-lg transition-colors disabled:opacity-50">
                        {sendingId === c.customer_id
                          ? <Spinner size="sm" />
                          : <Icon d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" size={16} />}
                      </button>
                      {/* Pause toggle */}
                      <button
                        onClick={() => handlePause(c.customer_id, !c.followup_paused)}
                        title={c.followup_paused ? 'استئناف المتابعة' : 'إيقاف المتابعة'}
                        className={`p-1.5 rounded-lg transition-colors ${
                          c.followup_paused
                            ? 'text-green-500 hover:bg-green-50'
                            : 'text-default-400 hover:bg-content2'
                        }`}>
                        <Icon d={c.followup_paused
                          ? 'M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z'
                          : 'M10 9v6m4-6v6'} size={16} />
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )
        )
      )}

      {/* Settings Tab */}
      {tab === 'settings' && (
        cfgLoading ? <div className="flex justify-center py-12"><Spinner size="lg" /></div> : (
          <div className="space-y-5">
            {/* Master toggle */}
            <div className="bg-white border border-divider rounded-xl p-4 flex items-center justify-between">
              <div>
                <p className="font-semibold text-foreground">تفعيل المتابعة التلقائية</p>
                <p className="text-xs text-default-500 mt-0.5">يرسل رسائل WhatsApp تلقائياً كل 30 دقيقة للعملاء المستحقين</p>
              </div>
              <Switch isSelected={config.enabled} onValueChange={v => setConfig(c => ({ ...c, enabled: v }))} />
            </div>

            {/* Per-segment config */}
            {(['hesitant', 'inquiry', 'buyer', 'inactive'] as const).map(seg => {
              const meta = SEGMENTS[seg]
              const sc   = config.segments[seg] || DEFAULT_CONFIG.segments[seg]
              return (
                <div key={seg} className={`bg-white border rounded-xl p-5 space-y-4 ${sc.enabled ? 'border-divider' : 'border-divider opacity-70'}`}>
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="text-xl">{meta.icon}</span>
                      <div>
                        <p className="font-semibold text-foreground">{meta.label}</p>
                        <p className="text-xs text-default-500">{meta.description}</p>
                      </div>
                    </div>
                    <Switch isSelected={sc.enabled} onValueChange={v => setSegCfg(seg, 'enabled', v)} />
                  </div>

                  {sc.enabled && (
                    <div className="grid grid-cols-2 gap-4 pt-2 border-t border-divider">
                      <div>
                        <label className="block text-xs font-medium text-default-600 mb-1">الانتظار قبل الإرسال (ساعة)</label>
                        <input type="number" min={1} max={8760}
                          value={sc.delay_hours}
                          onChange={e => setSegCfg(seg, 'delay_hours', +e.target.value)}
                          className="w-full border border-divider rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:border-blue-400"
                          dir="ltr" />
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-default-600 mb-1">أقصى عدد رسائل للعميل</label>
                        <input type="number" min={1} max={10}
                          value={sc.max_followups}
                          onChange={e => setSegCfg(seg, 'max_followups', +e.target.value)}
                          className="w-full border border-divider rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:border-blue-400"
                          dir="ltr" />
                      </div>
                      <div className="col-span-2">
                        <label className="block text-xs font-medium text-default-600 mb-1">
                          اسم قالب WhatsApp <span className="text-default-400">(اختياري — يستخدم إذا كان فارغاً النص أدناه)</span>
                        </label>
                        <input
                          value={sc.template}
                          onChange={e => setSegCfg(seg, 'template', e.target.value)}
                          placeholder="مثال: hesitant_followup"
                          className="w-full border border-divider rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:border-blue-400"
                          dir="ltr" />
                      </div>
                      <div className="col-span-2">
                        <label className="block text-xs font-medium text-default-600 mb-1">
                          نص الرسالة <span className="text-default-400">({'{name}'} = اسم العميل)</span>
                        </label>
                        <textarea
                          value={sc.message}
                          onChange={e => setSegCfg(seg, 'message', e.target.value)}
                          rows={3}
                          className="w-full border border-divider rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue-400 resize-none"
                        />
                      </div>
                    </div>
                  )}
                </div>
              )
            })}

            {cfgMsg && (
              <div className={`p-3 rounded-lg text-sm ${cfgMsg.startsWith('✅') ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-700'}`}>
                {cfgMsg}
              </div>
            )}

            <button onClick={handleSaveConfig} disabled={cfgSaving}
              className="w-full bg-blue-600 text-white py-2.5 rounded-xl font-medium hover:bg-blue-700 transition-colors disabled:opacity-60 flex items-center justify-center gap-2">
              {cfgSaving ? <Spinner size="sm" color="white" /> : null}
              حفظ الإعدادات
            </button>
          </div>
        )
      )}

      {/* ── Edit Modal ── */}
      {editState && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" dir="rtl">
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-md p-6 space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-bold text-foreground">تعديل بيانات العميل</h2>
              <button onClick={() => setEditState(null)}
                className="text-default-400 hover:text-default-600 p-1">
                <Icon d="M6 18L18 6M6 6l12 12" size={20} />
              </button>
            </div>

            {/* Customer name */}
            <div className="text-sm text-default-500">
              {editState.customer.customer_name || 'بدون اسم'} —{' '}
              {editState.customer.phone || editState.customer.email || editState.customer.customer_id}
            </div>

            {/* Segment selector */}
            <div>
              <label className="block text-sm font-medium text-default-700 mb-2">التصنيف</label>
              <div className="grid grid-cols-3 gap-2">
                {Object.entries(SEGMENTS).map(([seg, meta]) => (
                  <button key={seg}
                    onClick={() => setEditState(s => s ? { ...s, segment: seg } : s)}
                    className={`flex flex-col items-center gap-1 p-2 rounded-xl border-2 text-xs transition-all ${
                      editState.segment === seg
                        ? `border-blue-400 ${meta.bg}`
                        : 'border-divider hover:border-default-300'
                    }`}>
                    <span className="text-lg">{meta.icon}</span>
                    <span className={`font-medium ${editState.segment === seg ? meta.color : 'text-default-600'}`}>
                      {meta.label}
                    </span>
                  </button>
                ))}
              </div>
            </div>

            {/* Notes */}
            <div>
              <label className="block text-sm font-medium text-default-700 mb-1">ملاحظات الموظف</label>
              <textarea
                value={editState.notes}
                onChange={e => setEditState(s => s ? { ...s, notes: e.target.value } : s)}
                rows={3}
                placeholder="مثال: العميل طلب عرض سعر للطباعة الكبيرة..."
                className="w-full border border-divider rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue-400 resize-none"
              />
            </div>

            {editState.error && (
              <p className="text-sm text-red-600 bg-red-50 rounded-lg px-3 py-2">{editState.error}</p>
            )}

            <div className="flex gap-2 pt-1">
              <button onClick={() => setEditState(null)}
                className="flex-1 border border-divider text-default-600 py-2 rounded-xl text-sm hover:bg-content2 transition-colors">
                إلغاء
              </button>
              <button onClick={handleSaveEdit} disabled={editState.saving}
                className="flex-1 bg-blue-600 text-white py-2 rounded-xl text-sm font-medium hover:bg-blue-700 transition-colors disabled:opacity-60 flex items-center justify-center gap-2">
                {editState.saving ? <Spinner size="sm" color="white" /> : null}
                حفظ التعديلات
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
