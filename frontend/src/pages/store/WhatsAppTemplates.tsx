import { useEffect, useState } from 'react'
import { Spinner } from '@heroui/react'
import { api, ApiError, WaTemplate, MetaTemplate } from '../../api'
import { PageHeader } from '../../components/ui'

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

const CATEGORY_LABELS: Record<string, string> = {
  MARKETING: 'تسويقي',
  UTILITY:   'خدمي',
  AUTHENTICATION: 'مصادقة',
}
const STATUS_COLORS: Record<string, string> = {
  approved: 'bg-green-100 text-green-700',
  pending:  'bg-yellow-100 text-yellow-700',
  rejected: 'bg-red-100 text-red-700',
}

/* ── Empty template form ── */
const EMPTY_FORM: Partial<WaTemplate> = {
  name: '', language: 'ar', category: 'MARKETING',
  header_type: '', header_text: '', body_text: '', footer_text: '',
  buttons: [], variables: [], status: 'approved', notes: '',
}

/* ── Send modal state ── */
interface SendState {
  tpl: WaTemplate
  phone: string
  vars: Record<string, string>
}

export default function WhatsAppTemplates({ storeId }: { storeId: string }) {
  const [templates, setTemplates]   = useState<WaTemplate[]>([])
  const [loading, setLoading]       = useState(true)
  const [error, setError]           = useState('')
  const [showForm, setShowForm]     = useState(false)
  const [form, setForm]             = useState<Partial<WaTemplate>>(EMPTY_FORM)
  const [saving, setSaving]         = useState(false)
  const [formError, setFormError]   = useState('')
  const [sendState, setSendState]   = useState<SendState | null>(null)
  const [sending, setSending]       = useState(false)
  const [sendMsg, setSendMsg]       = useState('')
  const [importing, setImporting]   = useState(false)
  const [importMsg, setImportMsg]   = useState('')
  const [metaTpls, setMetaTpls]     = useState<MetaTemplate[] | null>(null)
  const [metaLoading, setMetaLoading] = useState(false)
  const [metaError, setMetaError]   = useState('')

  const load = async () => {
    try {
      setLoading(true)
      const res = await api.listWaTemplates(storeId)
      setTemplates(res.templates)
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : 'فشل تحميل القوالب')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [storeId])

  const handleSave = async () => {
    setFormError('')
    if (!form.name?.trim()) { setFormError('اسم القالب مطلوب'); return }
    if (!form.body_text?.trim()) { setFormError('نص الرسالة مطلوب'); return }
    setSaving(true)
    try {
      await api.saveWaTemplate(storeId, form)
      setShowForm(false)
      setForm(EMPTY_FORM)
      await load()
    } catch (e) {
      setFormError(e instanceof ApiError ? e.detail : 'فشل الحفظ')
    } finally {
      setSaving(false)
    }
  }

  // Submit the template to Meta for approval (vs. handleSave which only stores
  // a local draft). Meta reviews it; it becomes sendable once approved.
  const handleCreateOnMeta = async () => {
    setFormError('')
    if (!form.name?.trim()) { setFormError('اسم القالب مطلوب'); return }
    if (!form.body_text?.trim()) { setFormError('نص الرسالة مطلوب'); return }
    setSaving(true)
    try {
      const res = await api.createTemplateOnMeta(storeId, {
        name:        form.name!.trim(),
        body_text:   form.body_text!.trim(),
        language:    form.language || 'ar',
        category:    form.category || 'MARKETING',
        header_text: form.header_text || '',
        footer_text: form.footer_text || '',
      })
      setShowForm(false)
      setForm(EMPTY_FORM)
      setImportMsg(res.message || '✅ تم الإرسال إلى Meta للمراجعة')
      await load()
    } catch (e) {
      setFormError(e instanceof ApiError ? e.detail : 'فشل الإنشاء على Meta')
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (name: string) => {
    if (!confirm(`حذف القالب "${name}"؟`)) return
    try {
      await api.deleteWaTemplate(storeId, name)
      setTemplates(t => t.filter(x => x.name !== name))
    } catch (e) {
      alert(e instanceof ApiError ? e.detail : 'فشل الحذف')
    }
  }

  const openSend = (tpl: WaTemplate) => {
    const vars: Record<string, string> = {}
    ;(tpl.variables || []).forEach(v => { vars[v] = '' })
    setSendState({ tpl, phone: '', vars })
    setSendMsg('')
  }

  const handleSend = async () => {
    if (!sendState) return
    if (!sendState.phone.trim()) { setSendMsg('أدخل رقم الهاتف'); return }
    setSending(true)
    setSendMsg('')
    try {
      const res = await api.sendWaTemplate(storeId, sendState.tpl.name, sendState.phone, sendState.vars)
      setSendMsg(res.message || '✅ تم الإرسال')
    } catch (e) {
      setSendMsg(e instanceof ApiError ? e.detail : 'فشل الإرسال')
    } finally {
      setSending(false)
    }
  }

  const handleImport = async () => {
    setImporting(true)
    setImportMsg('')
    try {
      const res = await api.importMetaTemplates(storeId)
      setImportMsg(res.message || `تم استيراد ${res.imported} قالب`)
      await load()
    } catch (e) {
      setImportMsg(e instanceof ApiError ? e.detail : 'فشل الاستيراد')
    } finally {
      setImporting(false)
    }
  }

  const loadMetaTemplates = async () => {
    setMetaLoading(true)
    setMetaError('')
    setMetaTpls(null)
    try {
      const res = await api.listMetaTemplates(storeId)
      setMetaTpls(res.templates)
    } catch (e) {
      setMetaError(e instanceof ApiError ? e.detail : 'فشل تحميل قوالب Meta')
    } finally {
      setMetaLoading(false)
    }
  }

  if (loading) return (
    <div className="flex justify-center items-center h-48">
      <Spinner size="lg" />
    </div>
  )

  return (
    <div className="max-w-4xl mx-auto p-6 space-y-6" dir="rtl">
      <PageHeader
        title="قوالب WhatsApp"
        subtitle="إدارة القوالب المعتمدة من Meta للرسائل التسويقية والخدمية"
        icon="M21 11.5a8.38 8.38 0 01-.9 3.8 8.5 8.5 0 01-7.6 4.7 8.38 8.38 0 01-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 01-.9-3.8 8.5 8.5 0 014.7-7.6 8.38 8.38 0 013.8-.9h.5a8.48 8.48 0 018 8v.5z"
        actions={
          <>
            <button
              onClick={loadMetaTemplates}
              disabled={metaLoading}
              className="flex items-center gap-2 px-4 py-2 text-sm border border-divider rounded-lg hover:bg-content2 transition-colors"
            >
              {metaLoading ? <Spinner size="sm" /> : <Icon d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />}
              قوالب Meta
            </button>
            <button
              onClick={handleImport}
              disabled={importing}
              className="flex items-center gap-2 px-4 py-2 text-sm border border-success/40 text-success rounded-lg hover:bg-success/10 transition-colors"
            >
              {importing ? <Spinner size="sm" /> : <Icon d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />}
              استيراد من Meta
            </button>
            <button
              onClick={() => { setShowForm(true); setForm(EMPTY_FORM); setFormError('') }}
              className="flex items-center gap-2 px-4 py-2 text-sm bg-primary text-white rounded-lg hover:bg-primary/90 transition-colors"
            >
              <Icon d="M12 5v14M5 12h14" />
              قالب جديد
            </button>
          </>
        }
      />

      {importMsg && (
        <div className={`p-3 rounded-lg text-sm ${importMsg.startsWith('✅') || importMsg.startsWith('تم') ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-700'}`}>
          {importMsg}
        </div>
      )}

      {error && <div className="p-3 bg-red-50 text-red-700 rounded-lg text-sm">{error}</div>}

      {/* Meta Templates Panel */}
      {(metaTpls !== null || metaLoading || metaError) && (
        <div className="border border-divider rounded-xl p-4 bg-content2">
          <div className="flex items-center justify-between mb-3">
            <h2 className="font-semibold text-default-700">قوالب Meta المعتمدة</h2>
            <button onClick={() => setMetaTpls(null)} className="text-default-400 hover:text-default-600">
              <Icon d="M6 18L18 6M6 6l12 12" size={16} />
            </button>
          </div>
          {metaLoading && <Spinner size="sm" />}
          {metaError && <p className="text-red-600 text-sm">{metaError}</p>}
          {metaTpls && metaTpls.length === 0 && <p className="text-default-500 text-sm">لا توجد قوالب معتمدة في Meta</p>}
          {metaTpls && metaTpls.map(t => (
            <div key={t.name} className="flex items-start justify-between bg-white border border-divider rounded-lg p-3 mb-2">
              <div>
                <p className="font-medium text-sm text-foreground">{t.name}</p>
                <p className="text-xs text-default-500 mt-0.5">{t.body?.slice(0, 80)}{t.body?.length > 80 ? '…' : ''}</p>
              </div>
              <span className={`text-xs px-2 py-0.5 rounded-full ${STATUS_COLORS[t.status?.toLowerCase()] || 'bg-content2 text-default-600'}`}>
                {t.status}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* Templates Grid */}
      {templates.length === 0 ? (
        <div className="text-center py-16 text-default-400">
          <Icon d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" size={48} className="mx-auto mb-3 opacity-40" />
          <p className="text-sm">لا توجد قوالب محفوظة بعد</p>
          <p className="text-xs mt-1">أنشئ قالباً جديداً أو استورد من Meta</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {templates.map(tpl => (
            <div key={tpl.name} className="bg-white border border-divider rounded-xl p-4 shadow-sm hover:shadow transition-shadow">
              <div className="flex items-start justify-between mb-2">
                <div>
                  <h3 className="font-semibold text-foreground text-sm">{tpl.name}</h3>
                  <div className="flex gap-2 mt-1">
                    <span className="text-xs bg-blue-50 text-blue-600 px-2 py-0.5 rounded-full">
                      {CATEGORY_LABELS[tpl.category] || tpl.category}
                    </span>
                    <span className={`text-xs px-2 py-0.5 rounded-full ${STATUS_COLORS[tpl.status] || 'bg-content2 text-default-600'}`}>
                      {tpl.status === 'approved' ? 'معتمد' : tpl.status === 'pending' ? 'قيد المراجعة' : 'مرفوض'}
                    </span>
                    <span className="text-xs text-default-400">{tpl.language}</span>
                  </div>
                </div>
                <div className="flex gap-1">
                  <button
                    onClick={() => openSend(tpl)}
                    title="إرسال تجريبي"
                    className="p-1.5 text-green-600 hover:bg-green-50 rounded-lg transition-colors"
                  >
                    <Icon d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" size={15} />
                  </button>
                  <button
                    onClick={() => { setForm({ ...tpl }); setShowForm(true); setFormError('') }}
                    title="تعديل"
                    className="p-1.5 text-blue-500 hover:bg-blue-50 rounded-lg transition-colors"
                  >
                    <Icon d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" size={15} />
                  </button>
                  <button
                    onClick={() => handleDelete(tpl.name)}
                    title="حذف"
                    className="p-1.5 text-red-400 hover:bg-red-50 rounded-lg transition-colors"
                  >
                    <Icon d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" size={15} />
                  </button>
                </div>
              </div>
              <p className="text-xs text-default-600 bg-content2 rounded-lg p-2 leading-relaxed whitespace-pre-wrap">
                {tpl.body_text?.slice(0, 120)}{(tpl.body_text?.length || 0) > 120 ? '…' : ''}
              </p>
              {(tpl.variables?.length || 0) > 0 && (
                <div className="flex flex-wrap gap-1 mt-2">
                  {tpl.variables?.map(v => (
                    <span key={v} className="text-xs bg-purple-50 text-purple-600 px-2 py-0.5 rounded-full">{'{{'}{v}{'}}'}</span>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Add/Edit Form Modal */}
      {showForm && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg max-h-[90vh] overflow-y-auto" dir="rtl">
            <div className="flex items-center justify-between p-5 border-b">
              <h2 className="text-lg font-bold text-foreground">{form.id ? 'تعديل القالب' : 'قالب جديد'}</h2>
              <button onClick={() => setShowForm(false)} className="text-default-400 hover:text-default-600">
                <Icon d="M6 18L18 6M6 6l12 12" />
              </button>
            </div>
            <div className="p-5 space-y-4">
              <div>
                <label className="block text-sm font-medium text-default-700 mb-1">اسم القالب <span className="text-red-500">*</span></label>
                <input
                  value={form.name || ''}
                  onChange={e => setForm(f => ({ ...f, name: e.target.value.toLowerCase().replace(/\s+/g, '_') }))}
                  placeholder="مثال: order_confirmation"
                  className="w-full border border-divider rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue-400"
                  dir="ltr"
                />
                <p className="text-xs text-default-400 mt-1">بالحروف اللاتينية الصغيرة والشرطة السفلية فقط</p>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-sm font-medium text-default-700 mb-1">اللغة</label>
                  <select value={form.language || 'ar'} onChange={e => setForm(f => ({ ...f, language: e.target.value }))}
                    className="w-full border border-divider rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue-400">
                    <option value="ar">عربي (ar)</option>
                    <option value="en_US">English (en_US)</option>
                    <option value="en">English (en)</option>
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium text-default-700 mb-1">الفئة</label>
                  <select value={form.category || 'MARKETING'} onChange={e => setForm(f => ({ ...f, category: e.target.value }))}
                    className="w-full border border-divider rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue-400">
                    <option value="MARKETING">تسويقي</option>
                    <option value="UTILITY">خدمي</option>
                    <option value="AUTHENTICATION">مصادقة</option>
                  </select>
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium text-default-700 mb-1">نص الرسالة <span className="text-red-500">*</span></label>
                <textarea
                  value={form.body_text || ''}
                  onChange={e => setForm(f => ({ ...f, body_text: e.target.value }))}
                  rows={4}
                  placeholder="مرحباً {{name}}، طلبك رقم {{order_id}} قيد التجهيز."
                  className="w-full border border-divider rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue-400 resize-none"
                />
                <p className="text-xs text-default-400 mt-1">استخدم {'{{'}<span>name</span>{'}}'} للمتغيرات</p>
              </div>

              <div>
                <label className="block text-sm font-medium text-default-700 mb-1">المتغيرات (اسم كل متغير في سطر)</label>
                <textarea
                  value={(form.variables || []).join('\n')}
                  onChange={e => setForm(f => ({ ...f, variables: e.target.value.split('\n').map(x => x.trim()).filter(Boolean) }))}
                  rows={2}
                  placeholder={"name\norder_id"}
                  className="w-full border border-divider rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue-400 resize-none font-mono"
                  dir="ltr"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-default-700 mb-1">تذييل الرسالة (اختياري)</label>
                <input
                  value={form.footer_text || ''}
                  onChange={e => setForm(f => ({ ...f, footer_text: e.target.value }))}
                  placeholder="مثال: لإلغاء الاشتراك أرسل إيقاف"
                  className="w-full border border-divider rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue-400"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-default-700 mb-1">ملاحظات (اختياري)</label>
                <input
                  value={form.notes || ''}
                  onChange={e => setForm(f => ({ ...f, notes: e.target.value }))}
                  className="w-full border border-divider rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue-400"
                />
              </div>

              {formError && <p className="text-sm text-red-600">{formError}</p>}

              {formError && <p className="text-xs text-amber-600">💡 «إنشاء على Meta» يرسل القالب للمراجعة (يحتاج ربط واتساب). «حفظ كمسودة» يخزّنه محلياً فقط.</p>}
              <div className="flex gap-2 pt-2">
                <button
                  onClick={handleCreateOnMeta}
                  disabled={saving}
                  className="flex-1 bg-blue-600 text-white py-2 rounded-lg text-sm font-medium hover:bg-blue-700 transition-colors disabled:opacity-60"
                >
                  {saving ? <Spinner size="sm" color="white" /> : 'إنشاء على Meta'}
                </button>
                <button
                  onClick={handleSave}
                  disabled={saving}
                  className="flex-1 border border-blue-200 text-blue-700 py-2 rounded-lg text-sm font-medium hover:bg-blue-50 transition-colors disabled:opacity-60"
                >
                  حفظ كمسودة
                </button>
                <button
                  onClick={() => setShowForm(false)}
                  className="px-4 border border-divider py-2 rounded-lg text-sm text-default-600 hover:bg-content2 transition-colors"
                >
                  إلغاء
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Send Modal */}
      {sendState && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md" dir="rtl">
            <div className="flex items-center justify-between p-5 border-b">
              <h2 className="text-lg font-bold text-foreground">إرسال قالب: <span className="text-blue-600">{sendState.tpl.name}</span></h2>
              <button onClick={() => setSendState(null)} className="text-default-400 hover:text-default-600">
                <Icon d="M6 18L18 6M6 6l12 12" />
              </button>
            </div>
            <div className="p-5 space-y-4">
              <div>
                <label className="block text-sm font-medium text-default-700 mb-1">رقم الهاتف <span className="text-red-500">*</span></label>
                <input
                  value={sendState.phone}
                  onChange={e => setSendState(s => s ? { ...s, phone: e.target.value } : s)}
                  placeholder="966501234567"
                  className="w-full border border-divider rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue-400"
                  dir="ltr"
                />
              </div>

              {sendState.tpl.variables?.map(v => (
                <div key={v}>
                  <label className="block text-sm font-medium text-default-700 mb-1">{'{{'}{v}{'}}'}</label>
                  <input
                    value={sendState.vars[v] || ''}
                    onChange={e => setSendState(s => s ? { ...s, vars: { ...s.vars, [v]: e.target.value } } : s)}
                    className="w-full border border-divider rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue-400"
                  />
                </div>
              ))}

              {sendMsg && (
                <p className={`text-sm ${sendMsg.startsWith('✅') ? 'text-green-600' : 'text-red-600'}`}>{sendMsg}</p>
              )}

              <div className="flex gap-2 pt-1">
                <button
                  onClick={handleSend}
                  disabled={sending}
                  className="flex-1 bg-green-600 text-white py-2 rounded-lg text-sm font-medium hover:bg-green-700 transition-colors disabled:opacity-60"
                >
                  {sending ? <Spinner size="sm" color="white" /> : 'إرسال'}
                </button>
                <button
                  onClick={() => setSendState(null)}
                  className="flex-1 border border-divider py-2 rounded-lg text-sm text-default-600 hover:bg-content2 transition-colors"
                >
                  إغلاق
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
